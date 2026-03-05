"""Upload helper tools.

These tools expose a safe, file_id-based interface to files stored under
rag/data/uploads. They are intended for workflows like "drag & drop → email
attachment" without giving the agent arbitrary filesystem access.
"""

from __future__ import annotations

import datetime
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional


def _uploads_dir() -> Path:
    # rag/tools/uploads.py -> rag/ -> repo root
    repo_root = Path(__file__).resolve().parents[2]
    up = repo_root / "rag" / "data" / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    return up


def _sanitize_file_id(file_id: Any) -> Optional[str]:
    if not isinstance(file_id, str):
        return None
    fid = file_id.strip()
    if not fid:
        return None
    # Disallow path traversal / separators.
    if Path(fid).name != fid:
        return None
    if "/" in fid or "\\" in fid:
        return None
    if fid.startswith("."):
        return None
    return fid


def _guess_original_name(file_id: str) -> str:
    # We store files as: <uuidhex>_<original_name>
    parts = file_id.split("_", 1)
    if len(parts) == 2 and parts[1]:
        return parts[1]
    return file_id


def upload_list_files(args: Dict[str, Any]) -> Dict[str, Any]:
    limit = args.get("limit", 50)
    if limit is None:
        limit = 50
    if not isinstance(limit, int) or limit < 1 or limit > 100:
        return {"ok": False, "data": None, "error": "Invalid limit (1..100)"}

    uploads = _uploads_dir()
    files: List[Dict[str, Any]] = []

    for p in uploads.iterdir():
        try:
            if not p.is_file():
                continue
            st = p.stat()
            mime, _enc = mimetypes.guess_type(str(p))
            files.append(
                {
                    "file_id": p.name,
                    "filename": _guess_original_name(p.name),
                    "size_bytes": int(st.st_size),
                    "mime_type": mime or "application/octet-stream",
                    "uploaded_at_iso": datetime.datetime.fromtimestamp(
                        st.st_mtime, tz=datetime.timezone.utc
                    ).isoformat(),
                }
            )
        except Exception:
            continue

    files.sort(key=lambda x: x.get("uploaded_at_iso") or "", reverse=True)
    return {"ok": True, "data": {"files": files[:limit]}, "error": None}


def upload_get_file_info(args: Dict[str, Any]) -> Dict[str, Any]:
    fid = _sanitize_file_id(args.get("file_id"))
    if not fid:
        return {"ok": False, "data": None, "error": "Invalid file_id"}

    p = _uploads_dir() / fid
    if not p.exists() or not p.is_file():
        return {"ok": False, "data": None, "error": "File not found"}

    try:
        st = p.stat()
        mime, _enc = mimetypes.guess_type(str(p))
        return {
            "ok": True,
            "data": {
                "file_id": fid,
                "filename": _guess_original_name(fid),
                "size_bytes": int(st.st_size),
                "mime_type": mime or "application/octet-stream",
                "uploaded_at_iso": datetime.datetime.fromtimestamp(
                    st.st_mtime, tz=datetime.timezone.utc
                ).isoformat(),
                # Provide a server-side path for internal tools that require it.
                "path": str(p.resolve()),
            },
            "error": None,
        }
    except Exception as exc:
        return {"ok": False, "data": None, "error": f"Stat failed: {exc}"}


def upload_delete_file(args: Dict[str, Any]) -> Dict[str, Any]:
    fid = _sanitize_file_id(args.get("file_id"))
    if not fid:
        return {"ok": False, "data": None, "error": "Invalid file_id"}

    if args.get("user_confirmation") is not True:
        return {
            "ok": False,
            "data": None,
            "error": "Refusing to delete upload without explicit user_confirmation=true.",
        }

    p = _uploads_dir() / fid
    if not p.exists() or not p.is_file():
        return {"ok": False, "data": None, "error": "File not found"}

    try:
        p.unlink(missing_ok=True)
        return {"ok": True, "data": {"deleted": True, "file_id": fid}, "error": None}
    except Exception as exc:
        return {"ok": False, "data": None, "error": f"Delete failed: {exc}"}
