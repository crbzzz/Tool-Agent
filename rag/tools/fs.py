"""Filesystem tools.

These tools are powerful. Access is controlled by env:

- ACCESS_MODE: "safe" (default) or "full_disk"
- WORKSPACE_ROOT: root directory allowed when ACCESS_MODE=safe (default: ./rag/data)

In full_disk mode, a small denylist is applied to reduce accidental leakage of secrets.
This is NOT a sandbox.
"""

from __future__ import annotations

import base64
import fnmatch
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from rag.tools.system import system_get_paths
from rag.security.guard import SecurityError, SecurityGuard
from rag.state.audit_log import append_audit


logger = logging.getLogger(__name__)


_GUARD: Optional[SecurityGuard] = None


def _guard() -> SecurityGuard:
    global _GUARD
    if _GUARD is None:
        _GUARD = SecurityGuard.from_env()
    return _GUARD


def _guard_refresh() -> SecurityGuard:
    global _GUARD
    _GUARD = SecurityGuard.from_env()
    return _GUARD


def _audit(
    action: str,
    status: str,
    *,
    paths: Optional[List[str]] = None,
    file_count: Optional[int] = None,
    total_bytes: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    try:
        g = _guard()
        redacted = [g.redact_path(p) for p in (paths or []) if isinstance(p, str)]
        append_audit(
            action=action,
            status=status,
            paths=redacted or None,
            file_count=file_count,
            total_bytes=total_bytes,
            error=error,
        )
    except Exception:
        # Never fail the tool due to audit issues.
        return


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _resolve_path(path_str: str) -> Path:
    # strict=False allows non-existing targets (mkdir/write targets)
    return Path(path_str).expanduser().resolve(strict=False)


def _env(name: str, default: str) -> str:
    val = os.getenv(name)
    if val is None:
        return default
    return val


def _lower_parts(p: Path) -> List[str]:
    try:
        return [part.lower() for part in p.parts]
    except Exception:
        return [str(p).lower()]


def _is_within(child: Path, parent: Path) -> bool:
    try:
        common = os.path.commonpath([str(child), str(parent)])
        return _resolve_path(common) == parent
    except Exception:
        return False


def _is_denied_in_full_disk(path: Path) -> Tuple[bool, Optional[str]]:
    """Return (denied, reason)."""

    # Default denylist patterns (case-insensitive)
    deny_tokens = [
        ".ssh",
        ".env",
        "id_rsa",
        "id_ed25519",
        "secrets",
        ".secrets",
        "credentials",
        "token.json",
    ]

    # Allow user to add more tokens via FS_DENYLIST (semicolon-separated)
    extra = os.getenv("FS_DENYLIST", "").strip()
    if extra:
        deny_tokens.extend([t.strip().lower() for t in extra.split(";") if t.strip()])

    parts = _lower_parts(path)
    filename = path.name.lower()

    # Block any segment or filename that matches/starts-with typical secret names
    for tok in deny_tokens:
        t = tok.lower()
        if not t:
            continue
        if any(part == t for part in parts):
            return True, f"Path contains denied segment '{tok}'"
        if filename == t:
            return True, f"Filename is denied '{tok}'"
        if t == ".env" and filename.startswith(".env"):
            return True, "Refusing .env-like file"

    # Also refuse obvious private keys by glob match
    key_globs = ["*id_rsa*", "*id_ed25519*", "*.pem", "*.p12", "*.key"]
    for g in key_globs:
        if fnmatch.fnmatch(filename, g):
            return True, f"Refusing potential secret file '{filename}'"

    return False, None


def check_path_allowed(path_str: Any) -> Tuple[Optional[Path], Optional[str]]:
    """Backward-compatible path authorization helper.

    Returns (Path, None) on success, else (None, error).
    """

    if not isinstance(path_str, str) or not path_str.strip():
        return None, "Invalid path"

    g = _guard_refresh()
    try:
        g.check_path_allowed(path_str, action="fs_path_check")
        return g.resolve_path(path_str), None
    except SecurityError as exc:
        _audit("fs_path_check", "denied", paths=[path_str], error=str(exc))
        return None, str(exc)
    except Exception as exc:
        _audit("fs_path_check", "error", paths=[path_str], error=str(exc))
        return None, f"Invalid path: {exc}"


def _check_batch(action: str, *, user_confirmation: Any, file_count: int, total_bytes: int) -> Optional[str]:
    g = _guard()
    try:
        g.check_batch(action, file_count=file_count, total_bytes=total_bytes)
        return None
    except SecurityError as exc:
        # Allow bypass only when explicitly confirmed.
        if exc.requires_confirmation and user_confirmation is True:
            return None
        return str(exc)


def _count_tree(path: Path, *, max_items: int) -> int:
    """Best-effort count of files+dirs under a path, capped."""

    count = 0
    try:
        if path.is_file():
            return 1
    except Exception:
        return 0

    root_str = str(path)
    try:
        for _, dirnames, filenames in os.walk(root_str, topdown=True, followlinks=False):
            count += len(dirnames) + len(filenames)
            if count >= max_items:
                return max_items
    except Exception:
        return count
    return count


def _default_search_root_candidates() -> List[str]:
    """Root candidates for "search everywhere".

    Note: candidates are still validated by check_path_allowed.
    We intentionally prioritize common user folders for speed/safety.
    """

    candidates: List[str] = []

    try:
        res = system_get_paths({})
        if res.get("ok"):
            data = res.get("data") or {}
            for key in ("desktop", "documents", "downloads"):
                p = data.get(key)
                if isinstance(p, str) and p.strip():
                    candidates.append(p.strip())
            for key in ("desktop_candidates", "documents_candidates", "downloads_candidates"):
                arr = data.get(key)
                if isinstance(arr, list):
                    for p in arr:
                        if isinstance(p, str) and p.strip():
                            candidates.append(p.strip())
    except Exception:
        pass

    # Include WORKSPACE_ROOT as a fallback.
    # In ACCESS_MODE=safe it's the only allowed place anyway.
    # In full_disk mode, avoid scanning an entire drive root (e.g. C:\) by default.
    try:
        mode = _env("ACCESS_MODE", "safe").strip().lower()
        workspace_root = _env("WORKSPACE_ROOT", "./rag/data")
        wr = _resolve_path(workspace_root)

        is_drive_root = False
        try:
            # On Windows: Path('C:\\').anchor == 'C:\\'
            is_drive_root = str(wr) == str(Path(wr.anchor))
        except Exception:
            is_drive_root = False

        if mode == "safe" or not is_drive_root:
            candidates.append(str(wr))
    except Exception:
        pass

    # Environment fallbacks.
    for env_name in ("USERPROFILE", "OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        v = os.getenv(env_name)
        if isinstance(v, str) and v.strip():
            candidates.append(v.strip())

    # De-dup (case-insensitive) while preserving order.
    uniq: List[str] = []
    seen = set()
    for c in candidates:
        k = c.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(c)
    return uniq


def _stat_info(p: Path) -> Dict[str, Any]:
    try:
        st = p.stat()
        mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
        size = int(st.st_size)
    except Exception:
        mtime = None
        size = None
    return {
        "name": p.name,
        "path": str(p),
        "is_dir": bool(p.is_dir()),
        "size_bytes": size,
        "modified_utc": mtime,
    }


def fs_list_dir(args: Dict[str, Any]) -> Dict[str, Any]:
    raw = args.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return {"ok": False, "data": None, "error": "Invalid path"}
    try:
        g = _guard_refresh()
        g.check_path_allowed(raw, action="fs_list_dir")
        path = g.resolve_path(raw)
    except SecurityError as exc:
        _audit("fs_list_dir", "denied", paths=[raw], error=str(exc))
        return {"ok": False, "data": None, "error": str(exc)}
    except Exception as exc:
        _audit("fs_list_dir", "error", paths=[raw], error=str(exc))
        return {"ok": False, "data": None, "error": f"Invalid path: {exc}"}

    recursive = bool(args.get("recursive", False))
    max_entries = args.get("max_entries", 2000)
    if not isinstance(max_entries, int) or max_entries < 1 or max_entries > 10000:
        return {"ok": False, "data": None, "error": "Invalid max_entries (1..10000)"}

    if not path.exists():
        return {"ok": False, "data": None, "error": "Path does not exist"}
    if not path.is_dir():
        return {"ok": False, "data": None, "error": "Path is not a directory"}

    items: List[Dict[str, Any]] = []
    truncated = False
    try:
        it: Iterable[Path] = path.rglob("*") if recursive else path.iterdir()
        for child in it:
            items.append(_stat_info(child))
            if len(items) >= max_entries:
                truncated = True
                break
    except Exception as exc:
        logger.warning("fs_list_dir failed: %s", exc)
        _audit("fs_list_dir", "error", paths=[str(path)], error=str(exc))
        return {"ok": False, "data": None, "error": f"List failed: {exc}"}

    _audit("fs_list_dir", "ok", paths=[str(path)], file_count=len(items))
    return {
        "ok": True,
        "data": {"path": str(path), "recursive": recursive, "items": items, "truncated": truncated},
        "error": None,
    }


def fs_search_files(args: Dict[str, Any]) -> Dict[str, Any]:
    raw_root = args.get("root")
    if not isinstance(raw_root, str) or not raw_root.strip():
        return {"ok": False, "data": None, "error": "Invalid root"}
    try:
        g = _guard_refresh()
        g.check_path_allowed(raw_root, action="fs_search_files")
        root = g.resolve_path(raw_root)
    except SecurityError as exc:
        _audit("fs_search_files", "denied", paths=[raw_root], error=str(exc))
        return {"ok": False, "data": None, "error": str(exc)}
    except Exception as exc:
        _audit("fs_search_files", "error", paths=[raw_root], error=str(exc))
        return {"ok": False, "data": None, "error": f"Invalid root: {exc}"}

    pattern = args.get("pattern", "*")
    if not isinstance(pattern, str) or not pattern.strip():
        return {"ok": False, "data": None, "error": "Invalid pattern"}

    max_results = args.get("max_results", 1000)
    if not isinstance(max_results, int) or max_results < 1 or max_results > 20000:
        return {"ok": False, "data": None, "error": "Invalid max_results (1..20000)"}

    include_dirs = bool(args.get("include_dirs", False))

    if not root.exists():
        return {"ok": False, "data": None, "error": "Root does not exist"}
    if not root.is_dir():
        return {"ok": False, "data": None, "error": "Root is not a directory"}

    results: List[Dict[str, Any]] = []
    truncated = False
    try:
        for child in root.rglob(pattern):
            if not include_dirs and child.is_dir():
                continue
            results.append(_stat_info(child))
            if len(results) >= max_results:
                truncated = True
                break
    except Exception as exc:
        logger.warning("fs_search_files failed: %s", exc)
        _audit("fs_search_files", "error", paths=[str(root)], error=str(exc))
        return {"ok": False, "data": None, "error": f"Search failed: {exc}"}

    _audit("fs_search_files", "ok", paths=[str(root)], file_count=len(results))

    return {
        "ok": True,
        "data": {"root": str(root), "pattern": pattern, "results": results, "truncated": truncated},
        "error": None,
    }


def fs_search_recursive(args: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively search for files under a root.

    This is a safer alternative to Path.rglob for huge trees (e.g. C:\\), with:
    - max_depth: limit recursion depth
    - max_seconds: stop after a time budget

    Returns quickly with truncated=true when limits are hit.
    """

    # Be tolerant to common arg aliases produced by models.
    raw_root = args.get("root")
    if raw_root is None:
        raw_root = args.get("root_path")
    if raw_root is None:
        raw_root = args.get("search_root")
    g = _guard_refresh()
    roots: List[Path] = []

    # If no root is provided, search common user folders automatically.
    if raw_root is None or (isinstance(raw_root, str) and not raw_root.strip()):
        for cand in _default_search_root_candidates():
            try:
                g.check_path_allowed(cand, action="fs_search_recursive")
                p = g.resolve_path(cand)
            except Exception:
                continue
            try:
                if p.exists() and p.is_dir():
                    roots.append(p)
            except Exception:
                continue

        if not roots:
            return {"ok": False, "data": None, "error": "No allowed default roots to search"}
    else:
        if not isinstance(raw_root, str) or not raw_root.strip():
            return {"ok": False, "data": None, "error": "Invalid root"}
        try:
            g.check_path_allowed(raw_root, action="fs_search_recursive")
            roots = [g.resolve_path(raw_root)]
        except SecurityError as exc:
            _audit("fs_search_recursive", "denied", paths=[raw_root], error=str(exc))
            return {"ok": False, "data": None, "error": str(exc)}
        except Exception as exc:
            _audit("fs_search_recursive", "error", paths=[raw_root], error=str(exc))
            return {"ok": False, "data": None, "error": f"Invalid root: {exc}"}

    pattern = args.get("pattern", "*")
    if not isinstance(pattern, str) or not pattern.strip():
        return {"ok": False, "data": None, "error": "Invalid pattern"}

    # Optional filters (aliases from other tools / natural model output)
    extensions = args.get("extensions")
    name_contains = args.get("name_contains")

    ext_set: Optional[set[str]] = None
    if extensions is not None:
        if not isinstance(extensions, list) or not all(isinstance(x, str) and x.strip() for x in extensions):
            return {"ok": False, "data": None, "error": "Invalid extensions"}
        ext_set = {x.strip().lower() for x in extensions}

    needle = ""
    if name_contains is not None:
        if not isinstance(name_contains, str):
            return {"ok": False, "data": None, "error": "Invalid name_contains"}
        needle = name_contains.strip().lower()

    max_results = args.get("max_results", 1000)
    if not isinstance(max_results, int) or max_results < 1 or max_results > 20000:
        return {"ok": False, "data": None, "error": "Invalid max_results (1..20000)"}

    include_dirs = bool(args.get("include_dirs", False))

    max_depth = args.get("max_depth")
    if max_depth is not None:
        if not isinstance(max_depth, int) or max_depth < 0 or max_depth > 50:
            return {"ok": False, "data": None, "error": "Invalid max_depth (0..50)"}

    max_seconds = args.get("max_seconds", 10)
    if max_seconds is not None:
        if not isinstance(max_seconds, (int, float)) or max_seconds <= 0 or max_seconds > 120:
            return {"ok": False, "data": None, "error": "Invalid max_seconds (0..120)"}

    started = time.monotonic()
    results: List[Dict[str, Any]] = []
    truncated = False
    truncated_reason = ""

    searched_roots: List[str] = []

    # Walk with pruning and graceful permission error handling.
    try:
        for root in roots:
            try:
                if not root.exists() or not root.is_dir():
                    continue
            except Exception:
                continue
            searched_roots.append(str(root))

            root_str = str(root)
            base_depth = root_str.rstrip("\\/").count(os.sep)

            for dirpath, dirnames, filenames in os.walk(root_str, topdown=True, followlinks=False):
                # Timeout check
                if max_seconds is not None and (time.monotonic() - started) >= float(max_seconds):
                    truncated = True
                    truncated_reason = f"search timed out after {max_seconds} seconds"
                    raise StopIteration

                # Depth pruning
                if max_depth is not None:
                    cur_depth = dirpath.rstrip("\\/").count(os.sep) - base_depth
                    if cur_depth >= int(max_depth):
                        dirnames[:] = []

                # Match directories (optional)
                if include_dirs:
                    for dn in list(dirnames):
                        if fnmatch.fnmatch(dn, pattern):
                            results.append(_stat_info(Path(dirpath) / dn))
                            if len(results) >= max_results:
                                truncated = True
                                truncated_reason = f"results limited to {max_results}"
                                raise StopIteration

                # Match files
                for fn in filenames:
                    if not fnmatch.fnmatch(fn, pattern):
                        continue

                    if ext_set is not None:
                        try:
                            if Path(fn).suffix.lower() not in ext_set:
                                continue
                        except Exception:
                            continue

                    if needle:
                        try:
                            if needle not in fn.lower():
                                continue
                        except Exception:
                            continue

                    results.append(_stat_info(Path(dirpath) / fn))
                    if len(results) >= max_results:
                        truncated = True
                        truncated_reason = f"results limited to {max_results}"
                        raise StopIteration

    except StopIteration:
        pass
    except Exception as exc:
        logger.warning("fs_search_recursive failed: %s", exc)
        _audit("fs_search_recursive", "error", paths=searched_roots, error=str(exc))
        return {"ok": False, "data": None, "error": f"Search failed: {exc}"}

    _audit("fs_search_recursive", "ok", paths=searched_roots, file_count=len(results))

    data: Dict[str, Any] = {
        "root": str(roots[0]) if roots else None,
        "roots": searched_roots,
        "pattern": pattern,
        "extensions": sorted(list(ext_set)) if ext_set is not None else None,
        "name_contains": needle or None,
        "results": results,
        "truncated": truncated,
    }
    if truncated_reason:
        data["truncated_reason"] = truncated_reason
    return {"ok": True, "data": data, "error": None}


def fs_read_file(args: Dict[str, Any]) -> Dict[str, Any]:
    raw = args.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return {"ok": False, "data": None, "error": "Invalid path"}
    try:
        g = _guard_refresh()
        g.check_path_allowed(raw, action="fs_read_file")
        path = g.resolve_path(raw)
    except SecurityError as exc:
        _audit("fs_read_file", "denied", paths=[raw], error=str(exc))
        return {"ok": False, "data": None, "error": str(exc)}
    except Exception as exc:
        _audit("fs_read_file", "error", paths=[raw], error=str(exc))
        return {"ok": False, "data": None, "error": f"Invalid path: {exc}"}

    mode = args.get("mode", "text")
    if mode not in ("text", "binary"):
        return {"ok": False, "data": None, "error": "Invalid mode (text|binary)"}

    max_chars = args.get("max_chars", 8000)
    if not isinstance(max_chars, int) or max_chars < 256 or max_chars > 2_000_000:
        return {"ok": False, "data": None, "error": "Invalid max_chars (256..2000000)"}

    if not path.exists():
        return {"ok": False, "data": None, "error": "Path does not exist"}
    if not path.is_file():
        return {"ok": False, "data": None, "error": "Path is not a file"}

    try:
        raw = path.read_bytes()
    except Exception as exc:
        _audit("fs_read_file", "error", paths=[str(path)], error=str(exc))
        return {"ok": False, "data": None, "error": f"Read failed: {exc}"}

    if mode == "text":
        if b"\x00" in raw[:4096]:
            return {"ok": False, "data": None, "error": "File appears binary; use mode=binary"}
        text = raw.decode("utf-8", errors="replace")
        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars]
            truncated = True
        _audit("fs_read_file", "ok", paths=[str(path)], file_count=1, total_bytes=len(raw))
        return {
            "ok": True,
            "data": {"path": str(path), "mode": "text", "content": text, "truncated": truncated},
            "error": None,
        }

    # binary
    b64 = base64.b64encode(raw).decode("ascii")
    if len(b64) > max_chars:
        # Returning partial base64 often breaks downstream uploads and can cause agent loops.
        _audit("fs_read_file", "error", paths=[str(path)], file_count=1, total_bytes=len(raw), error="Refusing to return partial base64")
        return {
            "ok": False,
            "data": {
                "path": str(path),
                "mode": "binary",
                "size_bytes": len(raw),
                "would_truncate": True,
                "max_chars": max_chars,
            },
            "error": "Refusing to return partial base64. Increase max_chars or use drive_upload_local_file.",
        }
    _audit("fs_read_file", "ok", paths=[str(path)], file_count=1, total_bytes=len(raw))
    return {
        "ok": True,
        "data": {"path": str(path), "mode": "binary", "content_base64": b64, "size_bytes": len(raw)},
        "error": None,
    }


def fs_write_file(args: Dict[str, Any]) -> Dict[str, Any]:
    user_confirmation = args.get("user_confirmation")
    g = _guard_refresh()
    try:
        g.require_confirmation("fs_write_file", user_confirmation if isinstance(user_confirmation, bool) else None)
    except SecurityError as exc:
        _audit("fs_write_file", "denied", paths=[str(args.get("path") or "")], error=str(exc))
        return {"ok": False, "data": None, "error": str(exc)}

    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return {"ok": False, "data": None, "error": "Invalid path"}
    try:
        g.check_path_allowed(raw_path, action="fs_write_file")
        path = g.resolve_path(raw_path)
    except SecurityError as exc:
        _audit("fs_write_file", "denied", paths=[raw_path], error=str(exc))
        return {"ok": False, "data": None, "error": str(exc)}

    content = args.get("content")
    if not isinstance(content, str):
        return {"ok": False, "data": None, "error": "Invalid content"}

    content_bytes = content.encode("utf-8")
    batch_err = _check_batch(
        "fs_write_file",
        user_confirmation=user_confirmation,
        file_count=1,
        total_bytes=len(content_bytes),
    )
    if batch_err:
        _audit("fs_write_file", "denied", paths=[raw_path], error=batch_err)
        return {"ok": False, "data": None, "error": batch_err}

    overwrite = bool(args.get("overwrite", False))

    try:
        if path.exists() and path.is_dir():
            return {"ok": False, "data": None, "error": "Target is a directory"}
        if path.exists() and not overwrite:
            return {"ok": False, "data": None, "error": "File exists; set overwrite=true"}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _audit("fs_write_file", "ok", paths=[str(path)], file_count=1, total_bytes=len(content_bytes))
        return {
            "ok": True,
            "data": {"path": str(path), "bytes_written": len(content.encode('utf-8')), "ts_utc": _now_iso()},
            "error": None,
        }
    except Exception as exc:
        logger.warning("fs_write_file failed: %s", exc)
        _audit("fs_write_file", "error", paths=[str(path)], error=str(exc))
        return {"ok": False, "data": None, "error": f"Write failed: {exc}"}


def fs_delete_path(args: Dict[str, Any]) -> Dict[str, Any]:
    user_confirmation = args.get("user_confirmation")
    g = _guard_refresh()
    try:
        g.require_confirmation("fs_delete_path", user_confirmation if isinstance(user_confirmation, bool) else None)
    except SecurityError as exc:
        _audit("fs_delete_path", "denied", paths=[str(args.get("path") or "")], error=str(exc))
        return {"ok": False, "data": None, "error": str(exc)}

    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return {"ok": False, "data": None, "error": "Invalid path"}
    try:
        g.check_path_allowed(raw_path, action="fs_delete_path")
        path = g.resolve_path(raw_path)
    except SecurityError as exc:
        _audit("fs_delete_path", "denied", paths=[raw_path], error=str(exc))
        return {"ok": False, "data": None, "error": str(exc)}

    recursive = bool(args.get("recursive", False))

    if not path.exists():
        return {"ok": False, "data": None, "error": "Path does not exist"}

    # Best-effort batch check.
    est = 1
    try:
        if recursive and path.is_dir():
            est = _count_tree(path, max_items=max(1, g.policy.max_delete_per_run) + 1)
    except Exception:
        est = 1
    batch_err = _check_batch("fs_delete_path", user_confirmation=user_confirmation, file_count=est, total_bytes=0)
    if batch_err:
        _audit("fs_delete_path", "denied", paths=[raw_path], file_count=est, error=batch_err)
        return {"ok": False, "data": None, "error": batch_err}

    try:
        if path.is_dir():
            if not recursive:
                return {"ok": False, "data": None, "error": "Refusing to delete directory without recursive=true"}
            shutil.rmtree(path)
        else:
            path.unlink()
        _audit("fs_delete_path", "ok", paths=[str(path)], file_count=est)
        return {"ok": True, "data": {"path": str(path), "deleted": True, "ts_utc": _now_iso()}, "error": None}
    except Exception as exc:
        logger.warning("fs_delete_path failed: %s", exc)
        _audit("fs_delete_path", "error", paths=[str(path)], file_count=est, error=str(exc))
        return {"ok": False, "data": None, "error": f"Delete failed: {exc}"}


def fs_move_path(args: Dict[str, Any]) -> Dict[str, Any]:
    user_confirmation = args.get("user_confirmation")
    g = _guard_refresh()
    try:
        g.require_confirmation("fs_move_path", user_confirmation if isinstance(user_confirmation, bool) else None)
    except SecurityError as exc:
        _audit(
            "fs_move_path",
            "denied",
            paths=[str(args.get("src_path") or ""), str(args.get("dst_path") or "")],
            error=str(exc),
        )
        return {"ok": False, "data": None, "error": str(exc)}

    raw_src = args.get("src_path")
    raw_dst = args.get("dst_path")
    if not isinstance(raw_src, str) or not raw_src.strip():
        return {"ok": False, "data": None, "error": "Invalid src_path"}
    if not isinstance(raw_dst, str) or not raw_dst.strip():
        return {"ok": False, "data": None, "error": "Invalid dst_path"}

    try:
        g.check_path_allowed(raw_src, action="fs_move_path")
        g.check_path_allowed(raw_dst, action="fs_move_path")
        src = g.resolve_path(raw_src)
        dst = g.resolve_path(raw_dst)
    except SecurityError as exc:
        _audit("fs_move_path", "denied", paths=[raw_src, raw_dst], error=str(exc))
        return {"ok": False, "data": None, "error": str(exc)}

    overwrite = bool(args.get("overwrite", False))

    if not src.exists():
        return {"ok": False, "data": None, "error": "Source does not exist"}

    # Best-effort batch check: treat a directory move as multiple items.
    est = 1
    try:
        if src.is_dir():
            est = _count_tree(src, max_items=max(1, g.policy.max_move_per_run) + 1)
    except Exception:
        est = 1
    batch_err = _check_batch("fs_move_path", user_confirmation=user_confirmation, file_count=est, total_bytes=0)
    if batch_err:
        _audit("fs_move_path", "denied", paths=[raw_src, raw_dst], file_count=est, error=batch_err)
        return {"ok": False, "data": None, "error": batch_err}

    try:
        if dst.exists():
            if not overwrite:
                return {"ok": False, "data": None, "error": "Destination exists; set overwrite=true"}
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        _audit("fs_move_path", "ok", paths=[str(src), str(dst)], file_count=est)
        return {
            "ok": True,
            "data": {"src_path": str(src), "dst_path": str(dst), "moved": True, "ts_utc": _now_iso()},
            "error": None,
        }
    except Exception as exc:
        logger.warning("fs_move_path failed: %s", exc)
        _audit("fs_move_path", "error", paths=[str(src), str(dst)], file_count=est, error=str(exc))
        return {"ok": False, "data": None, "error": f"Move failed: {exc}"}


def fs_mkdir(args: Dict[str, Any]) -> Dict[str, Any]:
    user_confirmation = args.get("user_confirmation")
    g = _guard_refresh()
    try:
        g.require_confirmation("fs_mkdir", user_confirmation if isinstance(user_confirmation, bool) else None)
    except SecurityError as exc:
        _audit("fs_mkdir", "denied", paths=[str(args.get("path") or "")], error=str(exc))
        return {"ok": False, "data": None, "error": str(exc)}

    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return {"ok": False, "data": None, "error": "Invalid path"}
    try:
        g.check_path_allowed(raw_path, action="fs_mkdir")
        path = g.resolve_path(raw_path)
    except SecurityError as exc:
        _audit("fs_mkdir", "denied", paths=[raw_path], error=str(exc))
        return {"ok": False, "data": None, "error": str(exc)}

    parents = bool(args.get("parents", True))
    exist_ok = bool(args.get("exist_ok", True))
    try:
        path.mkdir(parents=parents, exist_ok=exist_ok)
        _audit("fs_mkdir", "ok", paths=[str(path)], file_count=1)
        return {"ok": True, "data": {"path": str(path), "created": True, "ts_utc": _now_iso()}, "error": None}
    except Exception as exc:
        logger.warning("fs_mkdir failed: %s", exc)
        _audit("fs_mkdir", "error", paths=[str(path)], error=str(exc))
        return {"ok": False, "data": None, "error": f"Mkdir failed: {exc}"}
