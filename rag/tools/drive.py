"""Google Drive tools (OAuth-based).

If Google OAuth is not connected, returns a clear error.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from rag.integrations.google_oauth import drive_service, load_credentials


logger = logging.getLogger(__name__)


def list_drive_files(args: Dict[str, Any]) -> Dict[str, Any]:
    query = args.get("query")
    max_results = args.get("max_results", 10)
    if max_results is not None and not isinstance(max_results, int):
        return {"ok": False, "data": None, "error": "Invalid `max_results`"}
    if query is not None and not isinstance(query, str):
        return {"ok": False, "data": None, "error": "Invalid `query`"}

    try:
        creds = load_credentials()
        svc = drive_service(creds)
        req = svc.files().list(
            pageSize=int(max_results),
            q=query or None,
            fields="files(id,name,mimeType,modifiedTime,size)",
        )
        resp = req.execute()
        files = resp.get("files", []) or []
        return {"ok": True, "data": {"files": files}}
    except Exception as exc:
        logger.warning("list_drive_files failed: %s", exc)
        return {"ok": False, "data": None, "error": f"Drive not available: {exc}"}


def get_drive_file(args: Dict[str, Any]) -> Dict[str, Any]:
    file_id = args.get("file_id")
    if not isinstance(file_id, str) or not file_id.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `file_id`"}

    try:
        creds = load_credentials()
        svc = drive_service(creds)
        meta = svc.files().get(fileId=str(file_id), fields="id,name,mimeType,modifiedTime,size").execute()
        # Best-effort preview: download small text-like files.
        preview: str | None = None
        try:
            data = svc.files().get_media(fileId=str(file_id)).execute()
            if isinstance(data, (bytes, bytearray)):
                preview = bytes(data).decode("utf-8", errors="ignore")[:8000]
        except Exception:
            preview = None
        return {"ok": True, "data": {"file": meta, "preview_text": preview}}
    except Exception as exc:
        logger.warning("get_drive_file failed: %s", exc)
        return {"ok": False, "data": None, "error": f"Drive not available: {exc}"}
