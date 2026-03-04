"""Local filesystem tools with safety guardrails.

Default stance:
- Read/list operations are allowed only within allowlisted roots.
- Destructive operations (write/delete) are disabled unless explicitly enabled via env.

This is NOT a sandbox. For production, prefer running in a constrained environment
and replacing this with a dedicated file service with strong authz.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _env_true(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_roots() -> List[Path]:
    raw = os.getenv("LOCAL_FS_ALLOWED_ROOTS", "").strip()
    if not raw:
        return []

    parts = [p.strip().strip('"') for p in raw.split(";") if p.strip()]
    roots: List[Path] = []
    for p in parts:
        try:
            root = Path(p).expanduser().resolve()
            roots.append(root)
        except Exception:
            continue
    # De-dup
    uniq: List[Path] = []
    for r in roots:
        if r not in uniq:
            uniq.append(r)
    return uniq


def _is_under_root(target: Path, root: Path) -> bool:
    try:
        # On Windows, commonpath is case-insensitive for drive letters in practice.
        common = os.path.commonpath([str(target), str(root)])
        return Path(common).resolve() == root
    except Exception:
        return False


def _resolve_allowed(path_str: Any) -> Tuple[Optional[Path], Optional[str]]:
    if not isinstance(path_str, str) or not path_str.strip():
        return None, "Invalid `path`"

    roots = _parse_roots()
    if not roots:
        return None, "LOCAL_FS_ALLOWED_ROOTS is not configured (set it in .env)"

    try:
        target = Path(path_str).expanduser().resolve()
    except Exception as exc:
        return None, f"Invalid path: {exc}"

    for root in roots:
        if _is_under_root(target, root):
            return target, None

    roots_str = "; ".join(str(r) for r in roots)
    return None, f"Path is outside allowed roots. Allowed roots: {roots_str}"


def local_list_dir(args: Dict[str, Any]) -> Dict[str, Any]:
    path, err = _resolve_allowed(args.get("path"))
    if err:
        return {"ok": False, "data": None, "error": err}

    max_entries = args.get("max_entries", 100)
    if not isinstance(max_entries, int) or max_entries < 1 or max_entries > 500:
        return {"ok": False, "data": None, "error": "Invalid `max_entries` (1..500)"}

    if not path.exists():
        return {"ok": False, "data": None, "error": "Path does not exist"}
    if not path.is_dir():
        return {"ok": False, "data": None, "error": "Path is not a directory"}

    items: List[Dict[str, Any]] = []
    try:
        for idx, child in enumerate(path.iterdir()):
            if idx >= max_entries:
                break
            try:
                st = child.stat()
                mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
                size = int(st.st_size)
            except Exception:
                mtime = None
                size = None
            items.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "is_dir": bool(child.is_dir()),
                    "size_bytes": size,
                    "modified_utc": mtime,
                }
            )
    except Exception as exc:
        return {"ok": False, "data": None, "error": f"Failed to list directory: {exc}"}

    return {"ok": True, "data": {"path": str(path), "items": items, "truncated": len(items) >= max_entries}}


def local_read_text(args: Dict[str, Any]) -> Dict[str, Any]:
    path, err = _resolve_allowed(args.get("path"))
    if err:
        return {"ok": False, "data": None, "error": err}

    max_bytes = args.get("max_bytes")
    if max_bytes is None:
        max_bytes = int(os.getenv("LOCAL_FS_MAX_READ_BYTES", "200000") or "200000")
    if not isinstance(max_bytes, int) or max_bytes < 256 or max_bytes > 2_000_000:
        return {"ok": False, "data": None, "error": "Invalid `max_bytes` (256..2000000)"}

    if not path.exists():
        return {"ok": False, "data": None, "error": "Path does not exist"}
    if not path.is_file():
        return {"ok": False, "data": None, "error": "Path is not a file"}

    try:
        raw = path.read_bytes()
    except Exception as exc:
        return {"ok": False, "data": None, "error": f"Failed to read file: {exc}"}

    if b"\x00" in raw[:4096]:
        return {"ok": False, "data": None, "error": "File appears to be binary; refusing to decode as text"}

    truncated = False
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
        truncated = True

    encoding = args.get("encoding")
    if encoding is not None and not isinstance(encoding, str):
        return {"ok": False, "data": None, "error": "Invalid `encoding`"}
    enc = encoding or "utf-8"
    try:
        text = raw.decode(enc, errors="replace")
    except Exception as exc:
        return {"ok": False, "data": None, "error": f"Decode failed: {exc}"}

    return {
        "ok": True,
        "data": {"path": str(path), "encoding": enc, "content": text, "truncated": truncated},
    }


def local_search_files(args: Dict[str, Any]) -> Dict[str, Any]:
    """Search for files under a root using a glob pattern.

    Note: this is best-effort and bounded; for large trees, it may still be slow.
    """

    root, err = _resolve_allowed(args.get("root"))
    if err:
        return {"ok": False, "data": None, "error": err}

    pattern = args.get("pattern", "*")
    if not isinstance(pattern, str) or not pattern.strip():
        return {"ok": False, "data": None, "error": "Invalid `pattern`"}

    max_results = args.get("max_results", 200)
    if not isinstance(max_results, int) or max_results < 1 or max_results > 2000:
        return {"ok": False, "data": None, "error": "Invalid `max_results` (1..2000)"}

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
            try:
                st = child.stat()
                mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
                size = int(st.st_size)
            except Exception:
                mtime = None
                size = None
            results.append(
                {
                    "path": str(child),
                    "name": child.name,
                    "is_dir": bool(child.is_dir()),
                    "size_bytes": size,
                    "modified_utc": mtime,
                }
            )
            if len(results) >= max_results:
                truncated = True
                break
    except Exception as exc:
        return {"ok": False, "data": None, "error": f"Search failed: {exc}"}

    return {
        "ok": True,
        "data": {"root": str(root), "pattern": pattern, "results": results, "truncated": truncated},
    }


def _destructive_enabled() -> bool:
    return _env_true("LOCAL_FS_ENABLE_DESTRUCTIVE", default=False)


def local_write_text(args: Dict[str, Any]) -> Dict[str, Any]:
    if not _destructive_enabled():
        return {
            "ok": False,
            "data": None,
            "error": "Destructive local FS operations are disabled. Set LOCAL_FS_ENABLE_DESTRUCTIVE=true to enable.",
        }
    if args.get("user_confirmation") is not True:
        return {"ok": False, "data": None, "error": "Refusing to write without user_confirmation=true."}

    path, err = _resolve_allowed(args.get("path"))
    if err:
        return {"ok": False, "data": None, "error": err}

    content = args.get("content")
    if not isinstance(content, str):
        return {"ok": False, "data": None, "error": "Invalid `content`"}

    overwrite = bool(args.get("overwrite", False))
    create_parents = bool(args.get("create_parents", False))

    try:
        if path.exists() and (not path.is_file()):
            return {"ok": False, "data": None, "error": "Target exists but is not a file"}
        if path.exists() and not overwrite:
            return {"ok": False, "data": None, "error": "File exists; set overwrite=true to overwrite"}
        if create_parents:
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"ok": True, "data": {"path": str(path), "bytes_written": len(content.encode('utf-8'))}}
    except Exception as exc:
        return {"ok": False, "data": None, "error": f"Write failed: {exc}"}


def local_delete_path(args: Dict[str, Any]) -> Dict[str, Any]:
    if not _destructive_enabled():
        return {
            "ok": False,
            "data": None,
            "error": "Destructive local FS operations are disabled. Set LOCAL_FS_ENABLE_DESTRUCTIVE=true to enable.",
        }
    if args.get("user_confirmation") is not True:
        return {"ok": False, "data": None, "error": "Refusing to delete without user_confirmation=true."}

    path, err = _resolve_allowed(args.get("path"))
    if err:
        return {"ok": False, "data": None, "error": err}

    recursive = bool(args.get("recursive", False))
    if not path.exists():
        return {"ok": False, "data": None, "error": "Path does not exist"}

    try:
        if path.is_dir():
            if not recursive:
                return {"ok": False, "data": None, "error": "Refusing to delete a directory without recursive=true"}
            shutil.rmtree(path)
        else:
            path.unlink()
        return {"ok": True, "data": {"path": str(path), "deleted": True}}
    except Exception as exc:
        return {"ok": False, "data": None, "error": f"Delete failed: {exc}"}
