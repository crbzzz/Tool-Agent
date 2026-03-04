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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


logger = logging.getLogger(__name__)


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
    """Resolve and authorize a path according to ACCESS_MODE.

    - ACCESS_MODE=safe: only allow paths within WORKSPACE_ROOT
    - ACCESS_MODE=full_disk: allow most paths, but deny obvious secret paths
    """

    if not isinstance(path_str, str) or not path_str.strip():
        return None, "Invalid path"

    try:
        path = _resolve_path(path_str)
    except Exception as exc:
        return None, f"Invalid path: {exc}"

    mode = _env("ACCESS_MODE", "safe").strip().lower()
    if mode not in {"safe", "full_disk"}:
        return None, "Invalid ACCESS_MODE (expected 'safe' or 'full_disk')"

    if mode == "safe":
        root_raw = _env("WORKSPACE_ROOT", "./rag/data")
        try:
            root = _resolve_path(root_raw)
        except Exception as exc:
            return None, f"Invalid WORKSPACE_ROOT: {exc}"
        if not _is_within(path, root):
            return None, f"Path is outside WORKSPACE_ROOT: {root}"
        return path, None

    denied, reason = _is_denied_in_full_disk(path)
    if denied:
        return None, reason or "Path is denied"
    return path, None


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
    path, err = check_path_allowed(args.get("path"))
    if err:
        return {"ok": False, "data": None, "error": err}

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
        return {"ok": False, "data": None, "error": f"List failed: {exc}"}

    return {
        "ok": True,
        "data": {"path": str(path), "recursive": recursive, "items": items, "truncated": truncated},
        "error": None,
    }


def fs_search_files(args: Dict[str, Any]) -> Dict[str, Any]:
    root, err = check_path_allowed(args.get("root"))
    if err:
        return {"ok": False, "data": None, "error": err}

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
        return {"ok": False, "data": None, "error": f"Search failed: {exc}"}

    return {
        "ok": True,
        "data": {"root": str(root), "pattern": pattern, "results": results, "truncated": truncated},
        "error": None,
    }


def fs_read_file(args: Dict[str, Any]) -> Dict[str, Any]:
    path, err = check_path_allowed(args.get("path"))
    if err:
        return {"ok": False, "data": None, "error": err}

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
        return {"ok": False, "data": None, "error": f"Read failed: {exc}"}

    if mode == "text":
        if b"\x00" in raw[:4096]:
            return {"ok": False, "data": None, "error": "File appears binary; use mode=binary"}
        text = raw.decode("utf-8", errors="replace")
        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars]
            truncated = True
        return {
            "ok": True,
            "data": {"path": str(path), "mode": "text", "content": text, "truncated": truncated},
            "error": None,
        }

    # binary
    b64 = base64.b64encode(raw).decode("ascii")
    truncated = False
    if len(b64) > max_chars:
        b64 = b64[:max_chars]
        truncated = True
    return {
        "ok": True,
        "data": {"path": str(path), "mode": "binary", "content_base64": b64, "truncated": truncated},
        "error": None,
    }


def fs_write_file(args: Dict[str, Any]) -> Dict[str, Any]:
    if args.get("user_confirmation") is not True:
        return {"ok": False, "data": None, "error": "Refusing to write without user_confirmation=true"}

    path, err = check_path_allowed(args.get("path"))
    if err:
        return {"ok": False, "data": None, "error": err}

    content = args.get("content")
    if not isinstance(content, str):
        return {"ok": False, "data": None, "error": "Invalid content"}

    overwrite = bool(args.get("overwrite", False))

    try:
        if path.exists() and path.is_dir():
            return {"ok": False, "data": None, "error": "Target is a directory"}
        if path.exists() and not overwrite:
            return {"ok": False, "data": None, "error": "File exists; set overwrite=true"}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {
            "ok": True,
            "data": {"path": str(path), "bytes_written": len(content.encode('utf-8')), "ts_utc": _now_iso()},
            "error": None,
        }
    except Exception as exc:
        logger.warning("fs_write_file failed: %s", exc)
        return {"ok": False, "data": None, "error": f"Write failed: {exc}"}


def fs_delete_path(args: Dict[str, Any]) -> Dict[str, Any]:
    if args.get("user_confirmation") is not True:
        return {"ok": False, "data": None, "error": "Refusing to delete without user_confirmation=true"}

    path, err = check_path_allowed(args.get("path"))
    if err:
        return {"ok": False, "data": None, "error": err}

    recursive = bool(args.get("recursive", False))

    if not path.exists():
        return {"ok": False, "data": None, "error": "Path does not exist"}

    try:
        if path.is_dir():
            if not recursive:
                return {"ok": False, "data": None, "error": "Refusing to delete directory without recursive=true"}
            shutil.rmtree(path)
        else:
            path.unlink()
        return {"ok": True, "data": {"path": str(path), "deleted": True, "ts_utc": _now_iso()}, "error": None}
    except Exception as exc:
        logger.warning("fs_delete_path failed: %s", exc)
        return {"ok": False, "data": None, "error": f"Delete failed: {exc}"}


def fs_move_path(args: Dict[str, Any]) -> Dict[str, Any]:
    if args.get("user_confirmation") is not True:
        return {"ok": False, "data": None, "error": "Refusing to move without user_confirmation=true"}

    src, err = check_path_allowed(args.get("src_path"))
    if err:
        return {"ok": False, "data": None, "error": f"src_path: {err}"}
    dst, err = check_path_allowed(args.get("dst_path"))
    if err:
        return {"ok": False, "data": None, "error": f"dst_path: {err}"}

    overwrite = bool(args.get("overwrite", False))

    if not src.exists():
        return {"ok": False, "data": None, "error": "Source does not exist"}

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
        return {
            "ok": True,
            "data": {"src_path": str(src), "dst_path": str(dst), "moved": True, "ts_utc": _now_iso()},
            "error": None,
        }
    except Exception as exc:
        logger.warning("fs_move_path failed: %s", exc)
        return {"ok": False, "data": None, "error": f"Move failed: {exc}"}


def fs_mkdir(args: Dict[str, Any]) -> Dict[str, Any]:
    if args.get("user_confirmation") is not True:
        return {"ok": False, "data": None, "error": "Refusing to mkdir without user_confirmation=true"}

    path, err = check_path_allowed(args.get("path"))
    if err:
        return {"ok": False, "data": None, "error": err}

    parents = bool(args.get("parents", True))
    exist_ok = bool(args.get("exist_ok", True))
    try:
        path.mkdir(parents=parents, exist_ok=exist_ok)
        return {"ok": True, "data": {"path": str(path), "created": True, "ts_utc": _now_iso()}, "error": None}
    except Exception as exc:
        logger.warning("fs_mkdir failed: %s", exc)
        return {"ok": False, "data": None, "error": f"Mkdir failed: {exc}"}
