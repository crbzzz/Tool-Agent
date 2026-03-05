"""Macro ("app_") agent tools.

These tools bundle multi-step workflows server-side to keep the agent loop fast.
All tools must:
- Validate args
- Respect filesystem access policy (safe/full_disk) via check_path_allowed
- Support dry_run when applicable
- Require user_confirmation for destructive or external side-effects
- Return { ok: bool, data: ..., error: str|None }

State persistence:
- Uses a small JSON file (env: APP_MACRO_STATE_PATH, default: .secrets/apps_state.json)
- Intended for deduplication (e.g., SHA256 hashes of uploaded content)

NOTE: This module avoids emitting secrets in errors/logs.
"""

from __future__ import annotations

import fnmatch
import base64
import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from rag.tools.fs import check_path_allowed
from rag.tools.drive import drive_ensure_folder, drive_upload_file, drive_upload_local_file
from rag.tools.system import system_get_paths
from rag.tools.gmail import (
    gmail_download_attachment,
    gmail_list_attachments,
    list_emails,
    gmail_apply_label,
)
from rag.tools.email_send import send_email


logger = logging.getLogger(__name__)


_DEFAULT_MAX_DEPTH = 8
_DEFAULT_MAX_SECONDS = 12.0
_DEFAULT_MAX_FILES = 200
_DEFAULT_MAX_FILE_BYTES = 30_000_000  # must match drive_upload_local_file safety limit


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _as_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"true", "1", "yes", "y"}:
            return True
        if s in {"false", "0", "no", "n"}:
            return False
    return default


def _as_int(v: Any, default: int) -> int:
    if v is None:
        return default
    if isinstance(v, bool):
        return default
    try:
        return int(v)
    except Exception:
        return default


def _as_float(v: Any, default: float) -> float:
    if v is None:
        return default
    if isinstance(v, bool):
        return default
    try:
        return float(v)
    except Exception:
        return default


def _lower_ext(ext: str) -> str:
    e = (ext or "").strip().lower()
    if not e:
        return ""
    if not e.startswith("."):
        e = f".{e}"
    return e


def _safe_str(s: Any) -> str:
    if s is None:
        return ""
    return str(s)


def _require_confirmation(dry_run: bool, user_confirmation: Any) -> Optional[str]:
    if dry_run:
        return None
    if user_confirmation is True:
        return None
    return "Confirmation required: set user_confirmation=true"


def _normalize_path_arg(raw: Any) -> Optional[str]:
    """Accept common shapes for path-like args.

    The model sometimes emits objects instead of strings.
    Supported:
    - "C:\\..."
    - {"path": "C:\\..."} / {"root": ...} / {"dir": ...}
    """

    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        for k in ("path", "root", "dir", "folder", "value"):
            v = raw.get(k)
            if isinstance(v, str) and v.strip():
                return v
    return None


def _resolve_root_alias(path_str: str) -> str:
    s = (path_str or "").strip()
    if not s:
        return s

    key = s.strip().lower().replace("/", "\\")
    # Common aliases (French + English)
    aliases = {
        "desktop": "desktop",
        "bureau": "desktop",
        "my desktop": "desktop",
        "documents": "documents",
        "docs": "documents",
        "mes documents": "documents",
        "downloads": "downloads",
        "download": "downloads",
        "téléchargements": "downloads",
        "telechargements": "downloads",
        "temp": "temp",
        "tmp": "temp",
    }
    if key in aliases:
        picked = aliases[key]
        try:
            res = system_get_paths({})
            if res.get("ok"):
                p = (res.get("data") or {}).get(picked)
                if isinstance(p, str) and p.strip():
                    return p.strip()
        except Exception:
            return s

    # Also accept just the leaf name (e.g., "Desktop" or "Bureau")
    if key in {"desktop", "documents", "downloads"}:
        try:
            res = system_get_paths({})
            if res.get("ok"):
                p = (res.get("data") or {}).get(key)
                if isinstance(p, str) and p.strip():
                    return p.strip()
        except Exception:
            return s

    return s


def _resolve_allowed_dir(raw: Any, field_name: str) -> Tuple[Optional[Path], Optional[str]]:
    s = _normalize_path_arg(raw)
    if not isinstance(s, str) or not s.strip():
        return None, f"Missing or invalid {field_name}"
    s = _resolve_root_alias(s)
    p, err = check_path_allowed(s)
    if err:
        return None, err
    if p is None:
        return None, "Invalid path"
    return p, None


def _default_search_roots() -> List[Path]:
    """Default roots when the caller doesn't provide a direct path.

    We intentionally prefer common user folders to avoid scanning an entire disk.
    All roots still go through check_path_allowed.
    """

    roots: List[Path] = []
    try:
        res = system_get_paths({})
        if res.get("ok"):
            data = res.get("data") or {}
            candidates: List[Any] = []
            for key in ("desktop", "documents", "downloads"):
                candidates.append(data.get(key))
            for key in ("desktop_candidates", "documents_candidates", "downloads_candidates"):
                candidates.extend(data.get(key) or [])

            for c in candidates:
                if not isinstance(c, str) or not c.strip():
                    continue
                p, err = check_path_allowed(c.strip())
                if err or p is None:
                    continue
                try:
                    if p.exists() and p.is_dir():
                        roots.append(p)
                except Exception:
                    continue
    except Exception:
        pass

    # Fallback to WORKSPACE_ROOT (helps in ACCESS_MODE=safe).
    if not roots:
        try:
            p, err = check_path_allowed(os.getenv("WORKSPACE_ROOT") or "./rag/data")
            if not err and p is not None and p.exists() and p.is_dir():
                roots.append(p)
        except Exception:
            pass

    # De-dup while preserving order.
    uniq: List[Path] = []
    seen = set()
    for r in roots:
        k = str(r).lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq


class _JsonStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    @staticmethod
    def default_path() -> Path:
        raw = os.getenv("APP_MACRO_STATE_PATH") or ".secrets/apps_state.json"
        return Path(raw).resolve()

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _save(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            data = self._load()
            return data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            data = self._load()
            data[key] = value
            self._save(data)

    def update_dict(self, key: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            data = self._load()
            cur = data.get(key)
            if not isinstance(cur, dict):
                cur = {}
            cur.update(updates)
            data[key] = cur
            self._save(data)
            return cur


_STATE = _JsonStateStore(_JsonStateStore.default_path())


def _sha256_file(path: Path, max_bytes: int = _DEFAULT_MAX_FILE_BYTES) -> Tuple[Optional[str], Optional[str]]:
    try:
        size = path.stat().st_size
        if size <= 0:
            return None, "Empty file"
        if size > max_bytes:
            return None, f"File too large for hashing/upload (> {max_bytes} bytes)"
    except Exception as exc:
        return None, f"Unable to stat file: {exc}"

    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest(), None
    except Exception as exc:
        return None, f"Hash failed: {exc}"


def _sha256_bytes(blob: bytes, max_bytes: int = _DEFAULT_MAX_FILE_BYTES) -> Tuple[Optional[str], Optional[str]]:
    if not isinstance(blob, (bytes, bytearray)):
        return None, "Invalid bytes"
    if len(blob) <= 0:
        return None, "Empty bytes"
    if len(blob) > max_bytes:
        return None, f"Blob too large (> {max_bytes} bytes)"
    return hashlib.sha256(bytes(blob)).hexdigest(), None


def _iter_files_rglob(
    root: Path,
    pattern: str = "*",
    *,
    max_depth: int,
    max_seconds: float,
    max_files: int,
    follow_symlinks: bool = False,
) -> Tuple[List[Path], bool, str]:
    started = time.monotonic()

    def timed_out() -> bool:
        return (time.monotonic() - started) >= max_seconds

    if max_seconds <= 0:
        return [], True, "max_seconds must be > 0"

    results: List[Path] = []
    truncated = False
    reason = ""

    try:
        it = root.rglob(pattern)
        consecutive_errors = 0
        while True:
            try:
                p = next(it)
                consecutive_errors = 0
            except StopIteration:
                break
            except Exception as exc:
                consecutive_errors += 1
                truncated = True
                reason = f"Search encountered an error: {exc}"
                if consecutive_errors >= 25:
                    break
                continue

            if timed_out():
                truncated = True
                reason = f"search timed out after {max_seconds} seconds"
                break

            try:
                rel = p.relative_to(root)
                depth = len(rel.parts)
                if depth > max_depth:
                    continue
            except Exception:
                pass

            try:
                if p.is_symlink() and not follow_symlinks:
                    continue
            except Exception:
                continue

            try:
                if not p.is_file():
                    continue
            except Exception:
                continue

            results.append(p)
            if len(results) >= max_files:
                truncated = True
                reason = f"files limited to {max_files}"
                break

    except Exception as exc:
        logger.warning("rglob failed: %s", exc)
        return [], True, f"Search failed: {exc}"

    return results, truncated, reason


def _drive_folder_id(
    folder_name: str,
    parent_folder_id: Optional[str] = None,
    *,
    user_confirmation: Optional[bool] = None,
) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    payload: Dict[str, Any] = {"folder_name": folder_name}
    if parent_folder_id:
        payload["parent_folder_id"] = parent_folder_id
    if user_confirmation is True:
        payload["user_confirmation"] = True

    res = drive_ensure_folder(payload)
    if not res.get("ok"):
        return None, res.get("data"), res.get("error") or "drive_ensure_folder failed"
    folder_id = _safe_str((res.get("data") or {}).get("folder_id")).strip()
    if not folder_id:
        return None, res.get("data"), "drive_ensure_folder returned no folder_id"
    return folder_id, res.get("data"), None


def _dedupe_key(folder_id: str) -> str:
    return f"drive_sha256_index:{folder_id.strip()}"


def _sha256_seen(folder_id: str, sha256_hex: str) -> Optional[Dict[str, Any]]:
    key = _dedupe_key(folder_id)
    idx = _STATE.get(key, {})
    if not isinstance(idx, dict):
        return None
    item = idx.get(sha256_hex)
    return item if isinstance(item, dict) else None


def _sha256_mark(folder_id: str, sha256_hex: str, item: Dict[str, Any]) -> None:
    key = _dedupe_key(folder_id)
    idx = _STATE.get(key, {})
    if not isinstance(idx, dict):
        idx = {}
    idx[sha256_hex] = dict(item)
    _STATE.set(key, idx)


def _guess_mime(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def app_upload_files_to_drive(args: Dict[str, Any]) -> Dict[str, Any]:
    search_root = args.get("search_root")
    drive_folder_name = args.get("drive_folder_name")
    extensions = args.get("extensions")
    name_contains = args.get("name_contains")

    dry_run = _as_bool(args.get("dry_run"), False)
    user_confirmation = args.get("user_confirmation")

    max_depth = _as_int(args.get("max_depth"), _DEFAULT_MAX_DEPTH)
    max_seconds = _as_float(args.get("max_seconds"), _DEFAULT_MAX_SECONDS)
    max_files = _as_int(args.get("max_files"), _DEFAULT_MAX_FILES)

    # search_root is optional; if missing we'll search common user roots.
    search_root_norm = _normalize_path_arg(search_root)
    if search_root is not None and (not isinstance(search_root_norm, str) or not search_root_norm.strip()):
        return {"ok": False, "data": None, "error": "Invalid search_root"}
    if not isinstance(drive_folder_name, str) or not drive_folder_name.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid drive_folder_name"}
    if not isinstance(extensions, list) or not extensions or not all(isinstance(x, str) and x.strip() for x in extensions):
        return {"ok": False, "data": None, "error": "Missing or invalid extensions"}
    if name_contains is not None and not isinstance(name_contains, str):
        return {"ok": False, "data": None, "error": "Invalid name_contains"}

    if max_depth < 1 or max_depth > 20:
        return {"ok": False, "data": None, "error": "Invalid max_depth (1..20)"}
    if max_seconds <= 0 or max_seconds > 120:
        return {"ok": False, "data": None, "error": "Invalid max_seconds (0..120]"}
    if max_files < 1 or max_files > 5000:
        return {"ok": False, "data": None, "error": "Invalid max_files (1..5000)"}

    err = _require_confirmation(dry_run, user_confirmation)
    if err:
        return {"ok": False, "data": None, "error": err}

    roots: List[Path] = []
    if isinstance(search_root_norm, str) and search_root_norm.strip():
        root_path, perr = _resolve_allowed_dir(search_root_norm, "search_root")
        if perr:
            return {"ok": False, "data": None, "error": perr}
        if root_path is None or not root_path.exists() or not root_path.is_dir():
            return {"ok": False, "data": None, "error": "search_root does not exist or is not a directory"}
        roots = [root_path]
    else:
        roots = _default_search_roots()
        if not roots:
            return {"ok": False, "data": None, "error": "No default roots available to search"}

    ext_set = {e for e in (_lower_ext(x) for x in (extensions or [])) if e}
    needle = (name_contains or "").strip().lower()

    # Search across multiple roots with a shared time/file budget.
    deadline = time.monotonic() + float(max_seconds)
    remaining_files = max_files
    all_paths: List[Path] = []
    truncated = False
    truncated_reason = ""

    for rp in roots:
        remaining_seconds = max(0.1, deadline - time.monotonic())
        if remaining_seconds <= 0.11:
            truncated = True
            truncated_reason = f"search timed out after {max_seconds} seconds"
            break
        if remaining_files <= 0:
            truncated = True
            truncated_reason = f"files limited to {max_files}"
            break

        paths, t, tr = _iter_files_rglob(
            rp,
            pattern="*",
            max_depth=max_depth,
            max_seconds=float(remaining_seconds),
            max_files=int(remaining_files),
        )
        all_paths.extend(paths)
        remaining_files = max_files - len(all_paths)
        if t:
            truncated = True
            truncated_reason = tr or truncated_reason
        if remaining_files <= 0:
            truncated = True
            truncated_reason = f"files limited to {max_files}"
            break

    filtered: List[Path] = []
    for p in all_paths:
        try:
            if ext_set and _lower_ext(p.suffix) not in ext_set:
                continue
            if needle and needle not in p.name.lower():
                continue
            filtered.append(p)
        except Exception:
            continue

    if not filtered:
        return {
            "ok": True,
            "data": {
                "search_root": str(roots[0]) if roots else None,
                "search_roots": [str(r) for r in roots],
                "drive_folder_name": drive_folder_name.strip(),
                "dry_run": dry_run,
                "files_found": 0,
                "files_uploaded": 0,
                "duplicates_skipped": 0,
                "errors": [],
                "truncated": truncated,
                "truncated_reason": truncated_reason,
            },
            "error": None,
        }

    folder_id, ensure_data, derr = _drive_folder_id(
        drive_folder_name.strip(),
        args.get("parent_folder_id"),
        user_confirmation=True if user_confirmation is True else None,
    )
    if derr:
        return {"ok": False, "data": {"step": "drive_ensure_folder", "details": ensure_data}, "error": derr}

    assert folder_id is not None

    planned: List[Dict[str, Any]] = []
    duplicates = 0
    uploaded = 0
    errors: List[Dict[str, Any]] = []

    for p in filtered:
        sha, herr = _sha256_file(p)
        if not sha:
            errors.append({"local_path": str(p), "error": herr or "sha256 failed"})
            continue

        seen = _sha256_seen(folder_id, sha)
        if seen is not None:
            duplicates += 1
            planned.append({"local_path": str(p), "filename": p.name, "sha256": sha, "action": "skip_duplicate", "duplicate_of": seen})
            continue

        planned.append({"local_path": str(p), "filename": p.name, "sha256": sha, "action": "upload"})

    if dry_run:
        return {
            "ok": True,
            "data": {
                "search_root": str(roots[0]) if roots else None,
                "search_roots": [str(r) for r in roots],
                "drive_folder_name": drive_folder_name.strip(),
                "drive_folder_id": folder_id,
                "dry_run": True,
                "files_found": len(filtered),
                "files_planned": len(planned),
                "files_uploaded": 0,
                "duplicates_skipped": duplicates,
                "errors": errors,
                "truncated": truncated,
                "truncated_reason": truncated_reason,
                "plan": planned[: min(len(planned), 500)],
                "plan_truncated": len(planned) > 500,
            },
            "error": None,
        }

    for item in planned:
        if item.get("action") != "upload":
            continue
        local_path = item.get("local_path")
        sha = item.get("sha256")
        if not isinstance(local_path, str) or not isinstance(sha, str):
            continue

        up_res = drive_upload_local_file(
            {
                "local_path": local_path,
                "folder_id": folder_id,
                "filename": Path(local_path).name,
                "mime_type": _guess_mime(Path(local_path)),
                "user_confirmation": True if user_confirmation is True else None,
            }
        )
        if not up_res.get("ok"):
            errors.append({"local_path": local_path, "error": up_res.get("error")})
            continue

        uploaded += 1
        created = (up_res.get("data") or {}).get("file")
        _sha256_mark(
            folder_id,
            sha,
            {
                "drive_file": created,
                "filename": Path(local_path).name,
                "local_path": local_path,
                "size_bytes": (up_res.get("data") or {}).get("size_bytes"),
                "ts_utc": _now_iso(),
            },
        )

    logger.info(
        "app_upload_files_to_drive: root=%s folder=%s uploaded=%s dup=%s errors=%s",
        str(root_path),
        drive_folder_name.strip(),
        uploaded,
        duplicates,
        len(errors),
    )

    return {
        "ok": True,
        "data": {
            "search_root": str(root_path),
            "drive_folder_name": drive_folder_name.strip(),
            "drive_folder_id": folder_id,
            "dry_run": False,
            "files_found": len(filtered),
            "files_uploaded": uploaded,
            "duplicates_skipped": duplicates,
            "errors": errors,
            "truncated": truncated,
            "truncated_reason": truncated_reason,
        },
        "error": None,
    }


def app_sync_local_folder_to_drive(args: Dict[str, Any]) -> Dict[str, Any]:
    """Upload new/changed local files to a Drive folder.

    Uses SHA256 state index to skip already-uploaded content.
    """

    local_folder = args.get("local_folder")
    drive_folder_name = args.get("drive_folder_name")
    pattern = args.get("pattern", "*")
    dry_run = _as_bool(args.get("dry_run"), False)
    user_confirmation = args.get("user_confirmation")

    max_depth = _as_int(args.get("max_depth"), _DEFAULT_MAX_DEPTH)
    max_seconds = _as_float(args.get("max_seconds"), _DEFAULT_MAX_SECONDS)
    max_files = _as_int(args.get("max_files"), _DEFAULT_MAX_FILES)

    if not isinstance(local_folder, str) or not local_folder.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid local_folder"}
    if not isinstance(drive_folder_name, str) or not drive_folder_name.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid drive_folder_name"}
    if not isinstance(pattern, str) or not pattern.strip():
        return {"ok": False, "data": None, "error": "Invalid pattern"}

    if max_depth < 1 or max_depth > 20:
        return {"ok": False, "data": None, "error": "Invalid max_depth (1..20)"}
    if max_seconds <= 0 or max_seconds > 300:
        return {"ok": False, "data": None, "error": "Invalid max_seconds (0..300]"}
    if max_files < 1 or max_files > 20000:
        return {"ok": False, "data": None, "error": "Invalid max_files (1..20000)"}

    err = _require_confirmation(dry_run, user_confirmation)
    if err:
        return {"ok": False, "data": None, "error": err}

    root_path, perr = _resolve_allowed_dir(local_folder, "local_folder")
    if perr:
        return {"ok": False, "data": None, "error": perr}
    if root_path is None or not root_path.exists() or not root_path.is_dir():
        return {"ok": False, "data": None, "error": "local_folder does not exist or is not a directory"}

    folder_id, ensure_data, derr = _drive_folder_id(
        drive_folder_name.strip(),
        args.get("parent_folder_id"),
        user_confirmation=True if user_confirmation is True else None,
    )
    if derr:
        return {"ok": False, "data": {"step": "drive_ensure_folder", "details": ensure_data}, "error": derr}
    assert folder_id is not None

    paths, truncated, truncated_reason = _iter_files_rglob(
        root_path,
        pattern=pattern,
        max_depth=max_depth,
        max_seconds=max_seconds,
        max_files=max_files,
    )

    planned: List[Dict[str, Any]] = []
    duplicates = 0
    uploaded = 0
    errors: List[Dict[str, Any]] = []

    for p in paths:
        sha, herr = _sha256_file(p)
        if not sha:
            errors.append({"local_path": str(p), "error": herr or "sha256 failed"})
            continue

        if _sha256_seen(folder_id, sha) is not None:
            duplicates += 1
            planned.append({"local_path": str(p), "filename": p.name, "sha256": sha, "action": "skip_duplicate"})
        else:
            planned.append({"local_path": str(p), "filename": p.name, "sha256": sha, "action": "upload"})

    if dry_run:
        return {
            "ok": True,
            "data": {
                "local_folder": str(root_path),
                "drive_folder_name": drive_folder_name.strip(),
                "drive_folder_id": folder_id,
                "pattern": pattern,
                "dry_run": True,
                "files_found": len(paths),
                "files_planned": len(planned),
                "files_uploaded": 0,
                "duplicates_skipped": duplicates,
                "errors": errors,
                "truncated": truncated,
                "truncated_reason": truncated_reason,
            },
            "error": None,
        }

    for item in planned:
        if item.get("action") != "upload":
            continue
        local_path = _safe_str(item.get("local_path"))
        sha = _safe_str(item.get("sha256"))
        if not local_path or not sha:
            continue

        up_res = drive_upload_local_file(
            {
                "local_path": local_path,
                "folder_id": folder_id,
                "filename": Path(local_path).name,
                "mime_type": _guess_mime(Path(local_path)),
                "user_confirmation": True if user_confirmation is True else None,
            }
        )
        if not up_res.get("ok"):
            errors.append({"local_path": local_path, "error": up_res.get("error")})
            continue

        uploaded += 1
        created = (up_res.get("data") or {}).get("file")
        _sha256_mark(
            folder_id,
            sha,
            {
                "drive_file": created,
                "filename": Path(local_path).name,
                "local_path": local_path,
                "size_bytes": (up_res.get("data") or {}).get("size_bytes"),
                "ts_utc": _now_iso(),
            },
        )

    logger.info(
        "app_sync_local_folder_to_drive: folder=%s -> drive=%s uploaded=%s dup=%s",
        str(root_path),
        drive_folder_name.strip(),
        uploaded,
        duplicates,
    )

    return {
        "ok": True,
        "data": {
            "local_folder": str(root_path),
            "drive_folder_name": drive_folder_name.strip(),
            "drive_folder_id": folder_id,
            "pattern": pattern,
            "dry_run": False,
            "files_found": len(paths),
            "files_uploaded": uploaded,
            "duplicates_skipped": duplicates,
            "errors": errors,
            "truncated": truncated,
            "truncated_reason": truncated_reason,
        },
        "error": None,
    }


def app_organize_directory_by_type(args: Dict[str, Any]) -> Dict[str, Any]:
    root_dir = args.get("root_dir")
    dry_run = _as_bool(args.get("dry_run"), False)
    user_confirmation = args.get("user_confirmation")

    max_depth = _as_int(args.get("max_depth"), 1)
    max_seconds = _as_float(args.get("max_seconds"), 10.0)
    max_files = _as_int(args.get("max_files"), 5000)

    if not isinstance(root_dir, str) or not root_dir.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid root_dir"}

    if max_depth < 0 or max_depth > 10:
        return {"ok": False, "data": None, "error": "Invalid max_depth (0..10)"}
    if max_seconds <= 0 or max_seconds > 120:
        return {"ok": False, "data": None, "error": "Invalid max_seconds (0..120]"}
    if max_files < 1 or max_files > 50000:
        return {"ok": False, "data": None, "error": "Invalid max_files (1..50000)"}

    err = _require_confirmation(dry_run, user_confirmation)
    if err:
        return {"ok": False, "data": None, "error": err}

    root_path, perr = _resolve_allowed_dir(root_dir, "root_dir")
    if perr:
        return {"ok": False, "data": None, "error": perr}
    if root_path is None or not root_path.exists() or not root_path.is_dir():
        return {"ok": False, "data": None, "error": "root_dir does not exist or is not a directory"}

    def category(p: Path) -> str:
        suf = p.suffix.lower().lstrip(".")
        if not suf:
            return "other"
        if suf in {"jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "heic"}:
            return "images"
        if suf in {"mp3", "wav", "m4a", "flac", "aac", "ogg"}:
            return "audio"
        if suf in {"mp4", "mov", "avi", "mkv", "webm"}:
            return "video"
        if suf in {"pdf", "doc", "docx", "txt", "md", "rtf", "odt", "xlsx", "xls", "ppt", "pptx"}:
            return "documents"
        if suf in {"zip", "7z", "rar", "tar", "gz"}:
            return "archives"
        if suf in {"py", "js", "ts", "tsx", "jsx", "json", "yaml", "yml", "toml", "ini", "css", "html"}:
            return "code"
        return "other"

    paths, truncated, truncated_reason = _iter_files_rglob(
        root_path,
        pattern="*",
        max_depth=max_depth,
        max_seconds=max_seconds,
        max_files=max_files,
    )

    moves: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for p in paths:
        try:
            cat = category(p)
            dst_dir = root_path / cat
            dst = dst_dir / p.name

            # Skip if already in category folder
            try:
                if dst_dir in p.parents:
                    continue
            except Exception:
                pass

            # Avoid collisions
            if dst.exists():
                stem = dst.stem
                suf = dst.suffix
                i = 1
                while True:
                    candidate = dst_dir / f"{stem} ({i}){suf}"
                    if not candidate.exists():
                        dst = candidate
                        break
                    i += 1
                    if i > 2000:
                        raise RuntimeError("Too many name collisions")

            moves.append({"src": str(p), "dst": str(dst)})
        except Exception as exc:
            errors.append({"path": str(p), "error": str(exc)})

    if dry_run:
        return {
            "ok": True,
            "data": {
                "root_dir": str(root_path),
                "dry_run": True,
                "moves": moves[: min(len(moves), 2000)],
                "moves_truncated": len(moves) > 2000,
                "errors": errors,
                "truncated": truncated,
                "truncated_reason": truncated_reason,
            },
            "error": None,
        }

    moved = 0
    for m in moves:
        src = _safe_str(m.get("src"))
        dst = _safe_str(m.get("dst"))
        if not src or not dst:
            continue
        try:
            s_path, se = check_path_allowed(src)
            d_path, de = check_path_allowed(dst)
            if se or de or s_path is None or d_path is None:
                raise RuntimeError(se or de or "path not allowed")
            d_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(s_path), str(d_path))
            moved += 1
        except Exception as exc:
            errors.append({"src": src, "dst": dst, "error": str(exc)})

    logger.info("app_organize_directory_by_type: root=%s moved=%s errors=%s", str(root_path), moved, len(errors))

    return {
        "ok": True,
        "data": {
            "root_dir": str(root_path),
            "dry_run": False,
            "moved": moved,
            "planned": len(moves),
            "errors": errors,
            "truncated": truncated,
            "truncated_reason": truncated_reason,
        },
        "error": None,
    }


def app_email_pdf_pipeline(args: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch PDF attachments from Gmail and upload them to Drive."""

    gmail_query = args.get("gmail_query")
    max_messages = _as_int(args.get("max_messages"), 10)
    drive_folder_name = args.get("drive_folder_name")
    label_name = args.get("label_name")

    dry_run = _as_bool(args.get("dry_run"), False)
    user_confirmation = args.get("user_confirmation")

    if gmail_query is not None and not isinstance(gmail_query, str):
        return {"ok": False, "data": None, "error": "Invalid gmail_query"}
    if not isinstance(drive_folder_name, str) or not drive_folder_name.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid drive_folder_name"}
    if max_messages < 1 or max_messages > 50:
        return {"ok": False, "data": None, "error": "Invalid max_messages (1..50)"}
    if label_name is not None and (not isinstance(label_name, str) or not label_name.strip()):
        return {"ok": False, "data": None, "error": "Invalid label_name"}

    err = _require_confirmation(dry_run, user_confirmation)
    if err:
        return {"ok": False, "data": None, "error": err}

    folder_id, ensure_data, derr = _drive_folder_id(
        drive_folder_name.strip(),
        args.get("parent_folder_id"),
        user_confirmation=True if user_confirmation is True else None,
    )
    if derr:
        return {"ok": False, "data": {"step": "drive_ensure_folder", "details": ensure_data}, "error": derr}
    assert folder_id is not None

    mails = list_emails({"max_results": int(max_messages), "query": gmail_query or "has:attachment"})
    if not mails.get("ok"):
        return {"ok": False, "data": {"step": "list_emails", "details": mails.get("data")}, "error": mails.get("error")}

    emails = (mails.get("data") or {}).get("emails") or []
    uploaded = 0
    duplicates = 0
    errors: List[Dict[str, Any]] = []
    plan: List[Dict[str, Any]] = []

    for e in emails:
        mid = _safe_str((e or {}).get("id")).strip()
        if not mid:
            continue

        att = gmail_list_attachments({"message_id": mid})
        if not att.get("ok"):
            errors.append({"message_id": mid, "error": att.get("error")})
            continue

        atts = (att.get("data") or {}).get("attachments") or []
        for a in atts:
            fn = (_safe_str((a or {}).get("filename")) or "").strip()
            mime = (_safe_str((a or {}).get("mime_type")) or "").strip().lower()
            aid = _safe_str((a or {}).get("attachment_id")).strip()

            if not aid:
                continue
            is_pdf = (fn.lower().endswith(".pdf") if fn else False) or (mime == "application/pdf")
            if not is_pdf:
                continue

            dl = gmail_download_attachment({"message_id": mid, "attachment_id": aid, "max_bytes": 30_000_000})
            if not dl.get("ok"):
                errors.append({"message_id": mid, "attachment_id": aid, "error": dl.get("error")})
                continue

            data = dl.get("data") or {}
            content_b64 = data.get("content_base64")
            if not isinstance(content_b64, str) or not content_b64.strip():
                errors.append({"message_id": mid, "attachment_id": aid, "error": "Missing attachment content"})
                continue

            # Decode without logging
            try:
                blob = base64.b64decode(content_b64.encode("utf-8"), validate=False)
            except Exception:
                errors.append({"message_id": mid, "attachment_id": aid, "error": "Invalid base64"})
                continue

            sha, herr = _sha256_bytes(blob)
            if not sha:
                errors.append({"message_id": mid, "attachment_id": aid, "error": herr or "sha256 failed"})
                continue

            if _sha256_seen(folder_id, sha) is not None:
                duplicates += 1
                plan.append({"message_id": mid, "attachment_id": aid, "filename": fn or None, "sha256": sha, "action": "skip_duplicate"})
                continue

            resolved_name = (fn or f"attachment_{aid}.pdf").strip()
            plan.append({"message_id": mid, "attachment_id": aid, "filename": resolved_name, "sha256": sha, "action": "upload"})

            if dry_run:
                continue

            up = drive_upload_file(
                {
                    "folder_id": folder_id,
                    "filename": resolved_name,
                    "mime_type": "application/pdf",
                    "content_base64": content_b64,
                }
            )
            if not up.get("ok"):
                errors.append({"message_id": mid, "attachment_id": aid, "filename": resolved_name, "error": up.get("error")})
                continue

            uploaded += 1
            created = (up.get("data") or {}).get("file")
            _sha256_mark(
                folder_id,
                sha,
                {
                    "drive_file": created,
                    "filename": resolved_name,
                    "message_id": mid,
                    "attachment_id": aid,
                    "size_bytes": len(blob),
                    "ts_utc": _now_iso(),
                },
            )

        if isinstance(label_name, str) and label_name.strip() and not dry_run:
            _ = gmail_apply_label(
                {
                    "message_id": mid,
                    "label_name": label_name.strip(),
                    "user_confirmation": True if user_confirmation is True else None,
                }
            )

    logger.info("app_email_pdf_pipeline: uploaded=%s dup=%s errors=%s", uploaded, duplicates, len(errors))

    return {
        "ok": True,
        "data": {
            "gmail_query": gmail_query or "has:attachment",
            "max_messages": int(max_messages),
            "drive_folder_name": drive_folder_name.strip(),
            "drive_folder_id": folder_id,
            "label_name": (label_name.strip() if isinstance(label_name, str) and label_name.strip() else None),
            "dry_run": dry_run,
            "files_uploaded": uploaded,
            "duplicates_skipped": duplicates,
            "errors": errors,
            "plan": plan[: min(len(plan), 500)],
            "plan_truncated": len(plan) > 500,
        },
        "error": None,
    }


def app_weekly_mail_digest(args: Dict[str, Any]) -> Dict[str, Any]:
    query = args.get("gmail_query")
    max_messages = _as_int(args.get("max_messages"), 50)
    to = args.get("to")
    subject = args.get("subject")
    send_it = _as_bool(args.get("send_email"), False)

    dry_run = _as_bool(args.get("dry_run"), False)
    user_confirmation = args.get("user_confirmation")

    if query is not None and not isinstance(query, str):
        return {"ok": False, "data": None, "error": "Invalid gmail_query"}
    if max_messages < 1 or max_messages > 100:
        return {"ok": False, "data": None, "error": "Invalid max_messages (1..100)"}

    if send_it:
        if not isinstance(to, list) or not to or not all(isinstance(x, str) and x.strip() for x in to):
            return {"ok": False, "data": None, "error": "Invalid to (must be non-empty list of emails)"}
        if subject is not None and not isinstance(subject, str):
            return {"ok": False, "data": None, "error": "Invalid subject"}

        err = _require_confirmation(dry_run, user_confirmation)
        if err:
            return {"ok": False, "data": None, "error": err}

    mails = list_emails({"max_results": int(max_messages), "query": query or "newer_than:7d"})
    if not mails.get("ok"):
        return {"ok": False, "data": {"step": "list_emails", "details": mails.get("data")}, "error": mails.get("error")}

    emails = (mails.get("data") or {}).get("emails") or []

    lines: List[str] = []
    lines.append(f"Weekly digest generated at {_now_iso()}")
    lines.append(f"Query: {query or 'newer_than:7d'}")
    lines.append(f"Count: {len(emails)}")
    lines.append("")

    for e in emails:
        try:
            lines.append(f"- {(_safe_str(e.get('date')) or '').strip()} | {(_safe_str(e.get('from')) or '').strip()} | {(_safe_str(e.get('subject')) or '').strip()}")
        except Exception:
            continue

    digest = "\n".join(lines)[:20000]

    sent: Optional[Dict[str, Any]] = None
    if send_it and not dry_run:
        sres = send_email(
            {
                "to": [x.strip() for x in to],
                "subject": subject or "Weekly mail digest",
                "body": digest,
                "user_confirmation": True,
            }
        )
        if not sres.get("ok"):
            return {"ok": False, "data": {"step": "send_email", "details": sres.get("data")}, "error": sres.get("error")}
        sent = sres.get("data")

    logger.info("app_weekly_mail_digest: emails=%s send=%s", len(emails), bool(send_it and not dry_run))

    return {
        "ok": True,
        "data": {
            "gmail_query": query or "newer_than:7d",
            "max_messages": int(max_messages),
            "dry_run": dry_run,
            "digest": digest,
            "sent": sent,
        },
        "error": None,
    }


def app_bulk_rename_files(args: Dict[str, Any]) -> Dict[str, Any]:
    root_dir = args.get("root_dir")
    pattern = args.get("pattern", "*")
    find = args.get("find")
    replace = args.get("replace", "")
    use_regex = _as_bool(args.get("use_regex"), False)

    dry_run = _as_bool(args.get("dry_run"), False)
    user_confirmation = args.get("user_confirmation")

    max_depth = _as_int(args.get("max_depth"), _DEFAULT_MAX_DEPTH)
    max_seconds = _as_float(args.get("max_seconds"), 10.0)
    max_files = _as_int(args.get("max_files"), 5000)

    if not isinstance(root_dir, str) or not root_dir.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid root_dir"}
    if not isinstance(pattern, str) or not pattern.strip():
        return {"ok": False, "data": None, "error": "Invalid pattern"}
    if not isinstance(find, str) or not find:
        return {"ok": False, "data": None, "error": "Missing or invalid find"}
    if not isinstance(replace, str):
        return {"ok": False, "data": None, "error": "Invalid replace"}

    if max_depth < 1 or max_depth > 20:
        return {"ok": False, "data": None, "error": "Invalid max_depth (1..20)"}
    if max_seconds <= 0 or max_seconds > 120:
        return {"ok": False, "data": None, "error": "Invalid max_seconds (0..120]"}
    if max_files < 1 or max_files > 50000:
        return {"ok": False, "data": None, "error": "Invalid max_files (1..50000)"}

    err = _require_confirmation(dry_run, user_confirmation)
    if err:
        return {"ok": False, "data": None, "error": err}

    root_path, perr = _resolve_allowed_dir(root_dir, "root_dir")
    if perr:
        return {"ok": False, "data": None, "error": perr}
    if root_path is None or not root_path.exists() or not root_path.is_dir():
        return {"ok": False, "data": None, "error": "root_dir does not exist or is not a directory"}

    paths, truncated, truncated_reason = _iter_files_rglob(
        root_path,
        pattern=pattern,
        max_depth=max_depth,
        max_seconds=max_seconds,
        max_files=max_files,
    )

    renames: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    if use_regex:
        try:
            rx = re.compile(find)
        except Exception as exc:
            return {"ok": False, "data": None, "error": f"Invalid regex: {exc}"}
    else:
        rx = None

    for p in paths:
        try:
            old = p.name
            if rx is not None:
                new = rx.sub(replace, old)
            else:
                new = old.replace(find, replace)
            if new == old:
                continue
            dst = p.with_name(new)
            if dst.exists():
                errors.append({"src": str(p), "dst": str(dst), "error": "Destination exists"})
                continue
            renames.append({"src": str(p), "dst": str(dst)})
        except Exception as exc:
            errors.append({"path": str(p), "error": str(exc)})

    if dry_run:
        return {
            "ok": True,
            "data": {
                "root_dir": str(root_path),
                "pattern": pattern,
                "dry_run": True,
                "renames": renames[: min(len(renames), 2000)],
                "renames_truncated": len(renames) > 2000,
                "errors": errors,
                "truncated": truncated,
                "truncated_reason": truncated_reason,
            },
            "error": None,
        }

    renamed = 0
    for r in renames:
        src = _safe_str(r.get("src"))
        dst = _safe_str(r.get("dst"))
        try:
            s_path, se = check_path_allowed(src)
            d_path, de = check_path_allowed(dst)
            if se or de or s_path is None or d_path is None:
                raise RuntimeError(se or de or "path not allowed")
            s_path.rename(d_path)
            renamed += 1
        except Exception as exc:
            errors.append({"src": src, "dst": dst, "error": str(exc)})

    logger.info("app_bulk_rename_files: root=%s renamed=%s errors=%s", str(root_path), renamed, len(errors))

    return {
        "ok": True,
        "data": {
            "root_dir": str(root_path),
            "pattern": pattern,
            "dry_run": False,
            "planned": len(renames),
            "renamed": renamed,
            "errors": errors,
            "truncated": truncated,
            "truncated_reason": truncated_reason,
        },
        "error": None,
    }


def app_auto_backup_folder(args: Dict[str, Any]) -> Dict[str, Any]:
    src_folder = args.get("src_folder")
    backup_dir = args.get("backup_dir")
    backup_name = args.get("backup_name")
    drive_folder_name = args.get("drive_folder_name")

    dry_run = _as_bool(args.get("dry_run"), False)
    user_confirmation = args.get("user_confirmation")

    if not isinstance(src_folder, str) or not src_folder.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid src_folder"}
    if not isinstance(backup_dir, str) or not backup_dir.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid backup_dir"}
    if backup_name is not None and (not isinstance(backup_name, str) or not backup_name.strip()):
        return {"ok": False, "data": None, "error": "Invalid backup_name"}
    if drive_folder_name is not None and (not isinstance(drive_folder_name, str) or not drive_folder_name.strip()):
        return {"ok": False, "data": None, "error": "Invalid drive_folder_name"}

    err = _require_confirmation(dry_run, user_confirmation)
    if err:
        return {"ok": False, "data": None, "error": err}

    src, se = _resolve_allowed_dir(src_folder, "src_folder")
    if se:
        return {"ok": False, "data": None, "error": se}
    dst_dir, de = _resolve_allowed_dir(backup_dir, "backup_dir")
    if de:
        return {"ok": False, "data": None, "error": de}

    if src is None or not src.exists() or not src.is_dir():
        return {"ok": False, "data": None, "error": "src_folder does not exist or is not a directory"}
    if dst_dir is None:
        return {"ok": False, "data": None, "error": "backup_dir not allowed"}

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = (backup_name.strip() if isinstance(backup_name, str) and backup_name.strip() else f"backup_{ts}")

    zip_path = dst_dir / f"{base}.zip"

    if dry_run:
        return {
            "ok": True,
            "data": {
                "src_folder": str(src),
                "backup_dir": str(dst_dir),
                "backup_zip": str(zip_path),
                "drive_folder_name": drive_folder_name.strip() if isinstance(drive_folder_name, str) else None,
                "dry_run": True,
            },
            "error": None,
        }

    dst_dir.mkdir(parents=True, exist_ok=True)

    try:
        # make_archive expects base_name without extension
        base_name = str(zip_path.with_suffix(""))
        shutil.make_archive(base_name, "zip", root_dir=str(src))
    except Exception as exc:
        return {"ok": False, "data": None, "error": f"Backup zip failed: {exc}"}

    upload_info: Optional[Dict[str, Any]] = None
    if isinstance(drive_folder_name, str) and drive_folder_name.strip():
        folder_id, ensure_data, derr = _drive_folder_id(
            drive_folder_name.strip(),
            args.get("parent_folder_id"),
            user_confirmation=True if user_confirmation is True else None,
        )
        if derr:
            return {"ok": False, "data": {"step": "drive_ensure_folder", "details": ensure_data}, "error": derr}
        assert folder_id is not None

        sha, herr = _sha256_file(zip_path)
        if not sha:
            return {"ok": False, "data": {"backup_zip": str(zip_path)}, "error": herr or "sha256 failed"}

        if _sha256_seen(folder_id, sha) is None:
            up_res = drive_upload_local_file(
                {
                    "local_path": str(zip_path),
                    "folder_id": folder_id,
                    "filename": zip_path.name,
                    "mime_type": "application/zip",
                    "user_confirmation": True if user_confirmation is True else None,
                }
            )
            if not up_res.get("ok"):
                return {"ok": False, "data": {"backup_zip": str(zip_path)}, "error": up_res.get("error")}
            upload_info = up_res.get("data")
            _sha256_mark(folder_id, sha, {"drive_file": (upload_info or {}).get("file"), "filename": zip_path.name, "ts_utc": _now_iso()})
        else:
            upload_info = {"skipped": True, "reason": "duplicate_sha256"}

    logger.info("app_auto_backup_folder: src=%s zip=%s", str(src), str(zip_path))

    return {
        "ok": True,
        "data": {
            "src_folder": str(src),
            "backup_dir": str(dst_dir),
            "backup_zip": str(zip_path),
            "drive_folder_name": drive_folder_name.strip() if isinstance(drive_folder_name, str) else None,
            "drive_upload": upload_info,
            "dry_run": False,
        },
        "error": None,
    }


def app_find_large_files(args: Dict[str, Any]) -> Dict[str, Any]:
    root = args.get("root")
    top_n = _as_int(args.get("top_n"), 20)
    pattern = args.get("pattern", "*")

    max_depth = _as_int(args.get("max_depth"), _DEFAULT_MAX_DEPTH)
    max_seconds = _as_float(args.get("max_seconds"), 10.0)
    max_files = _as_int(args.get("max_files"), 20000)

    if not isinstance(root, str) or not root.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid root"}
    if not isinstance(pattern, str) or not pattern.strip():
        return {"ok": False, "data": None, "error": "Invalid pattern"}
    if top_n < 1 or top_n > 200:
        return {"ok": False, "data": None, "error": "Invalid top_n (1..200)"}

    if max_depth < 1 or max_depth > 20:
        return {"ok": False, "data": None, "error": "Invalid max_depth (1..20)"}
    if max_seconds <= 0 or max_seconds > 120:
        return {"ok": False, "data": None, "error": "Invalid max_seconds (0..120]"}
    if max_files < 1 or max_files > 200000:
        return {"ok": False, "data": None, "error": "Invalid max_files"}

    root_path, perr = _resolve_allowed_dir(root, "root")
    if perr:
        return {"ok": False, "data": None, "error": perr}
    if root_path is None or not root_path.exists() or not root_path.is_dir():
        return {"ok": False, "data": None, "error": "root does not exist or is not a directory"}

    paths, truncated, truncated_reason = _iter_files_rglob(
        root_path,
        pattern=pattern,
        max_depth=max_depth,
        max_seconds=max_seconds,
        max_files=max_files,
    )

    items: List[Dict[str, Any]] = []
    for p in paths:
        try:
            st = p.stat()
            items.append({"path": str(p), "name": p.name, "size_bytes": int(st.st_size)})
        except Exception:
            continue

    items.sort(key=lambda x: int(x.get("size_bytes") or 0), reverse=True)

    return {
        "ok": True,
        "data": {
            "root": str(root_path),
            "pattern": pattern,
            "top_n": top_n,
            "results": items[:top_n],
            "truncated": truncated,
            "truncated_reason": truncated_reason,
        },
        "error": None,
    }


def app_clean_temp_files(args: Dict[str, Any]) -> Dict[str, Any]:
    root = args.get("root")
    patterns = args.get("patterns")
    min_age_days = _as_int(args.get("min_age_days"), 7)

    dry_run = _as_bool(args.get("dry_run"), False)
    user_confirmation = args.get("user_confirmation")

    max_depth = _as_int(args.get("max_depth"), _DEFAULT_MAX_DEPTH)
    max_seconds = _as_float(args.get("max_seconds"), 10.0)
    max_files = _as_int(args.get("max_files"), 5000)

    if not isinstance(root, str) or not root.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid root"}

    if patterns is None:
        patterns_list = ["*.tmp", "*.temp", "*.bak", "~*", "*.swp"]
    else:
        if not isinstance(patterns, list) or not patterns or not all(isinstance(x, str) and x.strip() for x in patterns):
            return {"ok": False, "data": None, "error": "Invalid patterns (must be non-empty list of strings)"}
        patterns_list = [x.strip() for x in patterns]

    if min_age_days < 0 or min_age_days > 3650:
        return {"ok": False, "data": None, "error": "Invalid min_age_days (0..3650)"}

    if max_depth < 1 or max_depth > 20:
        return {"ok": False, "data": None, "error": "Invalid max_depth (1..20)"}
    if max_seconds <= 0 or max_seconds > 120:
        return {"ok": False, "data": None, "error": "Invalid max_seconds (0..120]"}
    if max_files < 1 or max_files > 50000:
        return {"ok": False, "data": None, "error": "Invalid max_files (1..50000)"}

    err = _require_confirmation(dry_run, user_confirmation)
    if err:
        return {"ok": False, "data": None, "error": err}

    root_path, perr = _resolve_allowed_dir(root, "root")
    if perr:
        return {"ok": False, "data": None, "error": perr}
    if root_path is None or not root_path.exists() or not root_path.is_dir():
        return {"ok": False, "data": None, "error": "root does not exist or is not a directory"}

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=int(min_age_days))

    paths, truncated, truncated_reason = _iter_files_rglob(
        root_path,
        pattern="*",
        max_depth=max_depth,
        max_seconds=max_seconds,
        max_files=max_files,
    )

    targets: List[Path] = []
    for p in paths:
        try:
            if not any(fnmatch.fnmatch(p.name, pat) for pat in patterns_list):
                continue
            st = p.stat()
            mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
            if mtime > cutoff:
                continue
            targets.append(p)
        except Exception:
            continue

    deleted = 0
    errors: List[Dict[str, Any]] = []

    if dry_run:
        return {
            "ok": True,
            "data": {
                "root": str(root_path),
                "patterns": patterns_list,
                "min_age_days": int(min_age_days),
                "dry_run": True,
                "files_matched": len(targets),
                "files_deleted": 0,
                "sample": [str(p) for p in targets[:200]],
                "sample_truncated": len(targets) > 200,
                "errors": [],
                "truncated": truncated,
                "truncated_reason": truncated_reason,
            },
            "error": None,
        }

    for p in targets:
        try:
            pp, e = check_path_allowed(str(p))
            if e or pp is None:
                raise RuntimeError(e or "path not allowed")
            pp.unlink(missing_ok=True)
            deleted += 1
        except Exception as exc:
            errors.append({"path": str(p), "error": str(exc)})

    logger.info("app_clean_temp_files: root=%s deleted=%s errors=%s", str(root_path), deleted, len(errors))

    return {
        "ok": True,
        "data": {
            "root": str(root_path),
            "patterns": patterns_list,
            "min_age_days": int(min_age_days),
            "dry_run": False,
            "files_matched": len(targets),
            "files_deleted": deleted,
            "errors": errors,
            "truncated": truncated,
            "truncated_reason": truncated_reason,
        },
        "error": None,
    }
