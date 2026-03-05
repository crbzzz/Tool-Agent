"""Google Drive tools (OAuth-based).

If Google OAuth is not connected, returns a clear error.
"""

from __future__ import annotations

import base64
import io
import logging
import mimetypes
from typing import Any, Dict, List

from rag.integrations.google_oauth import drive_service, load_credentials
from rag.security.guard import SecurityError, SecurityGuard
from rag.state.audit_log import append_audit
from rag.tools.fs import check_path_allowed


logger = logging.getLogger(__name__)


def _audit(action: str, status: str, *, error: str | None = None, extra: Dict[str, Any] | None = None) -> None:
    try:
        append_audit(action=action, status=status, error=error, extra=extra)
    except Exception:
        return


def _confirm_and_batch(
    action: str,
    args: Dict[str, Any],
    *,
    file_count: int = 0,
    total_bytes: int = 0,
) -> tuple[SecurityGuard, None | str]:
    g = SecurityGuard.from_env()
    user_confirmation = args.get("user_confirmation")
    try:
        g.require_confirmation(action, user_confirmation if isinstance(user_confirmation, bool) else None)
    except SecurityError as exc:
        return g, str(exc)

    try:
        g.check_batch(action, file_count=int(file_count), total_bytes=int(total_bytes))
        return g, None
    except SecurityError as exc:
        if exc.requires_confirmation and user_confirmation is True:
            return g, None
        return g, str(exc)


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


def drive_ensure_folder(args: Dict[str, Any]) -> Dict[str, Any]:
    folder_name = args.get("folder_name")
    parent_folder_id = args.get("parent_folder_id")

    if not isinstance(folder_name, str) or not folder_name.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `folder_name`"}
    if parent_folder_id is not None and (not isinstance(parent_folder_id, str) or not parent_folder_id.strip()):
        return {"ok": False, "data": None, "error": "Invalid `parent_folder_id`"}

    try:
        creds = load_credentials()
        svc = drive_service(creds)

        name_escaped = folder_name.replace("'", "\\'")
        q_parts = [
            "mimeType='application/vnd.google-apps.folder'",
            f"name='{name_escaped}'",
            "trashed=false",
        ]
        if isinstance(parent_folder_id, str) and parent_folder_id.strip():
            q_parts.append(f"'{parent_folder_id.strip()}' in parents")
        q = " and ".join(q_parts)

        resp = svc.files().list(q=q, pageSize=10, fields="files(id,name)").execute()
        files = resp.get("files", []) or []
        if files:
            fid = str(files[0].get("id") or "")
            if fid:
                _audit("drive_ensure_folder", "ok", extra={"created": False, "folder_id": fid})
                return {"ok": True, "data": {"folder_id": fid, "created": False}}

        _g, confirm_err = _confirm_and_batch("drive_ensure_folder:create", args, file_count=1, total_bytes=0)
        if confirm_err:
            _audit("drive_ensure_folder", "denied", error=confirm_err, extra={"would_create": True})
            return {"ok": False, "data": None, "error": confirm_err}

        body: Dict[str, Any] = {"name": folder_name.strip(), "mimeType": "application/vnd.google-apps.folder"}
        if isinstance(parent_folder_id, str) and parent_folder_id.strip():
            body["parents"] = [parent_folder_id.strip()]

        created = svc.files().create(body=body, fields="id,name").execute()
        fid = str(created.get("id") or "")
        if not fid:
            return {"ok": False, "data": None, "error": "Drive folder creation returned no id"}
        _audit("drive_ensure_folder", "ok", extra={"created": True, "folder_id": fid})
        return {"ok": True, "data": {"folder_id": fid, "created": True}}
    except Exception as exc:
        logger.warning("drive_ensure_folder failed: %s", exc)
        _audit("drive_ensure_folder", "error", error=str(exc))
        return {"ok": False, "data": None, "error": f"Drive not available: {exc}"}


def drive_upload_file(args: Dict[str, Any]) -> Dict[str, Any]:
    folder_id = args.get("folder_id")
    filename = args.get("filename")
    mime_type = args.get("mime_type")
    content_base64 = args.get("content_base64")

    if not isinstance(folder_id, str) or not folder_id.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `folder_id`"}
    if not isinstance(filename, str) or not filename.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `filename`"}
    if not isinstance(mime_type, str) or not mime_type.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `mime_type`"}
    if not isinstance(content_base64, str) or not content_base64.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `content_base64`"}

    try:
        blob = base64.b64decode(content_base64.encode("utf-8"), validate=False)
    except Exception:
        return {"ok": False, "data": None, "error": "Invalid base64 in `content_base64`"}

    _g, confirm_err = _confirm_and_batch("drive_upload_file", args, file_count=1, total_bytes=len(blob))
    if confirm_err:
        _audit(
            "drive_upload_file",
            "denied",
            error=confirm_err,
            extra={"folder_id": folder_id, "filename": filename, "size_bytes": len(blob)},
        )
        return {"ok": False, "data": None, "error": confirm_err}

    # Safety limit: keep uploads bounded.
    if len(blob) > 30_000_000:
        return {
            "ok": False,
            "data": {"size_bytes": len(blob), "max_bytes": 30_000_000},
            "error": "File exceeds 30MB safety limit",
        }

    try:
        from googleapiclient.http import MediaIoBaseUpload  # type: ignore

        creds = load_credentials()
        svc = drive_service(creds)

        body: Dict[str, Any] = {
            "name": filename.strip(),
            "parents": [folder_id.strip()],
        }

        media = MediaIoBaseUpload(io.BytesIO(blob), mimetype=mime_type.strip(), resumable=False)
        created = svc.files().create(body=body, media_body=media, fields="id,name,mimeType,size,webViewLink").execute()
        _audit(
            "drive_upload_file",
            "ok",
            extra={
                "folder_id": folder_id.strip(),
                "filename": filename.strip(),
                "mime_type": mime_type.strip(),
                "size_bytes": len(blob),
                "drive_file_id": created.get("id"),
            },
        )
        return {"ok": True, "data": {"file": created}}
    except Exception as exc:
        logger.warning("drive_upload_file failed: %s", exc)
        _audit("drive_upload_file", "error", error=str(exc), extra={"folder_id": folder_id, "filename": filename})
        return {"ok": False, "data": None, "error": f"Drive not available: {exc}"}


def drive_list_folders(args: Dict[str, Any]) -> Dict[str, Any]:
    """List Drive folders.

    Supports raw Drive `q` syntax via `query` plus an optional parent filter.
    """

    query = args.get("query")
    parent_folder_id = args.get("parent_folder_id")
    max_results = args.get("max_results", 10)

    if query is not None and not isinstance(query, str):
        return {"ok": False, "data": None, "error": "Invalid `query`"}
    if parent_folder_id is not None and (not isinstance(parent_folder_id, str) or not parent_folder_id.strip()):
        return {"ok": False, "data": None, "error": "Invalid `parent_folder_id`"}
    if max_results is not None and not isinstance(max_results, int):
        return {"ok": False, "data": None, "error": "Invalid `max_results`"}

    try:
        creds = load_credentials()
        svc = drive_service(creds)

        q_parts = ["mimeType='application/vnd.google-apps.folder'", "trashed=false"]
        if isinstance(parent_folder_id, str) and parent_folder_id.strip():
            q_parts.append(f"'{parent_folder_id.strip()}' in parents")
        if isinstance(query, str) and query.strip():
            q_parts.append(f"({query.strip()})")
        q = " and ".join(q_parts)

        resp = svc.files().list(
            pageSize=int(max_results),
            q=q,
            fields="files(id,name,parents,createdTime,modifiedTime)",
        ).execute()
        folders = resp.get("files", []) or []
        return {"ok": True, "data": {"folders": folders}}
    except Exception as exc:
        logger.warning("drive_list_folders failed: %s", exc)
        return {"ok": False, "data": None, "error": f"Drive not available: {exc}"}


def drive_create_folder(args: Dict[str, Any]) -> Dict[str, Any]:
    """Create a Drive folder.

    Note: this always creates a new folder (may create duplicates). Use drive_ensure_folder
    if you want idempotent behavior.
    """

    folder_name = args.get("folder_name")
    parent_folder_id = args.get("parent_folder_id")

    if not isinstance(folder_name, str) or not folder_name.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `folder_name`"}
    if parent_folder_id is not None and (not isinstance(parent_folder_id, str) or not parent_folder_id.strip()):
        return {"ok": False, "data": None, "error": "Invalid `parent_folder_id`"}

    _g, confirm_err = _confirm_and_batch("drive_create_folder", args, file_count=1, total_bytes=0)
    if confirm_err:
        _audit("drive_create_folder", "denied", error=confirm_err, extra={"folder_name": folder_name, "parent_folder_id": parent_folder_id})
        return {"ok": False, "data": None, "error": confirm_err}

    try:
        creds = load_credentials()
        svc = drive_service(creds)

        body: Dict[str, Any] = {"name": folder_name.strip(), "mimeType": "application/vnd.google-apps.folder"}
        if isinstance(parent_folder_id, str) and parent_folder_id.strip():
            body["parents"] = [parent_folder_id.strip()]

        created = svc.files().create(body=body, fields="id,name,parents,createdTime").execute()
        fid = str(created.get("id") or "")
        if not fid:
            return {"ok": False, "data": None, "error": "Drive folder creation returned no id"}
        _audit("drive_create_folder", "ok", extra={"folder_id": fid, "folder_name": folder_name.strip()})
        return {"ok": True, "data": {"folder": created}}
    except Exception as exc:
        logger.warning("drive_create_folder failed: %s", exc)
        _audit("drive_create_folder", "error", error=str(exc))
        return {"ok": False, "data": None, "error": f"Drive not available: {exc}"}


def drive_rename_folder(args: Dict[str, Any]) -> Dict[str, Any]:
    folder_id = args.get("folder_id")
    new_name = args.get("new_name")

    if not isinstance(folder_id, str) or not folder_id.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `folder_id`"}
    if not isinstance(new_name, str) or not new_name.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `new_name`"}

    _g, confirm_err = _confirm_and_batch("drive_rename_folder", args, file_count=1, total_bytes=0)
    if confirm_err:
        _audit("drive_rename_folder", "denied", error=confirm_err, extra={"folder_id": folder_id, "new_name": new_name})
        return {"ok": False, "data": None, "error": confirm_err}

    try:
        creds = load_credentials()
        svc = drive_service(creds)
        updated = svc.files().update(
            fileId=folder_id.strip(),
            body={"name": new_name.strip()},
            fields="id,name,parents,modifiedTime",
        ).execute()
        _audit("drive_rename_folder", "ok", extra={"folder_id": folder_id.strip(), "new_name": new_name.strip()})
        return {"ok": True, "data": {"folder": updated}}
    except Exception as exc:
        logger.warning("drive_rename_folder failed: %s", exc)
        _audit("drive_rename_folder", "error", error=str(exc), extra={"folder_id": folder_id})
        return {"ok": False, "data": None, "error": f"Drive not available: {exc}"}


def drive_move_folder(args: Dict[str, Any]) -> Dict[str, Any]:
    folder_id = args.get("folder_id")
    new_parent_folder_id = args.get("new_parent_folder_id")
    remove_other_parents = args.get("remove_other_parents", True)

    if not isinstance(folder_id, str) or not folder_id.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `folder_id`"}
    if not isinstance(new_parent_folder_id, str) or not new_parent_folder_id.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `new_parent_folder_id`"}
    if remove_other_parents is not None and not isinstance(remove_other_parents, bool):
        return {"ok": False, "data": None, "error": "Invalid `remove_other_parents`"}

    _g, confirm_err = _confirm_and_batch("drive_move_folder", args, file_count=1, total_bytes=0)
    if confirm_err:
        _audit(
            "drive_move_folder",
            "denied",
            error=confirm_err,
            extra={"folder_id": folder_id, "new_parent_folder_id": new_parent_folder_id},
        )
        return {"ok": False, "data": None, "error": confirm_err}

    try:
        creds = load_credentials()
        svc = drive_service(creds)

        current = svc.files().get(fileId=folder_id.strip(), fields="id,parents").execute()
        parents = current.get("parents", []) or []

        remove_parents = None
        if remove_other_parents is True and parents:
            target_parent = new_parent_folder_id.strip()
            remove_parents = ",".join([str(p) for p in parents if p and str(p) != target_parent]) or None

        updated = svc.files().update(
            fileId=folder_id.strip(),
            addParents=new_parent_folder_id.strip(),
            removeParents=remove_parents,
            fields="id,name,parents,modifiedTime",
        ).execute()
        _audit(
            "drive_move_folder",
            "ok",
            extra={"folder_id": folder_id.strip(), "new_parent_folder_id": new_parent_folder_id.strip()},
        )
        return {
            "ok": True,
            "data": {
                "folder": updated,
                "removed_parents": parents if remove_parents else [],
            },
        }
    except Exception as exc:
        logger.warning("drive_move_folder failed: %s", exc)
        _audit("drive_move_folder", "error", error=str(exc), extra={"folder_id": folder_id})
        return {"ok": False, "data": None, "error": f"Drive not available: {exc}"}


def drive_delete_folder(args: Dict[str, Any]) -> Dict[str, Any]:
    folder_id = args.get("folder_id")

    _g, confirm_err = _confirm_and_batch("drive_delete_folder", args, file_count=1, total_bytes=0)
    if confirm_err:
        _audit("drive_delete_folder", "denied", error=confirm_err, extra={"folder_id": folder_id})
        return {"ok": False, "data": None, "error": confirm_err}
    if not isinstance(folder_id, str) or not folder_id.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `folder_id`"}

    try:
        creds = load_credentials()
        svc = drive_service(creds)
        svc.files().delete(fileId=folder_id.strip()).execute()
        _audit("drive_delete_folder", "ok", extra={"folder_id": folder_id.strip()})
        return {"ok": True, "data": {"folder_id": folder_id.strip(), "deleted": True}}
    except Exception as exc:
        logger.warning("drive_delete_folder failed: %s", exc)
        _audit("drive_delete_folder", "error", error=str(exc), extra={"folder_id": folder_id})
        return {"ok": False, "data": None, "error": f"Drive not available: {exc}"}


def drive_upload_local_file(args: Dict[str, Any]) -> Dict[str, Any]:
    """Upload a local file to Drive by path.

    This avoids passing large base64 blobs through the model/UI.
    """

    local_path = args.get("local_path")
    folder_id = args.get("folder_id")
    filename = args.get("filename")
    mime_type = args.get("mime_type")

    if not isinstance(local_path, str) or not local_path.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `local_path`"}
    if not isinstance(folder_id, str) or not folder_id.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `folder_id`"}
    if filename is not None and (not isinstance(filename, str) or not filename.strip()):
        return {"ok": False, "data": None, "error": "Invalid `filename`"}
    if mime_type is not None and (not isinstance(mime_type, str) or not mime_type.strip()):
        return {"ok": False, "data": None, "error": "Invalid `mime_type`"}

    g = SecurityGuard.from_env()
    user_confirmation = args.get("user_confirmation")
    try:
        g.require_confirmation("drive_upload_local_file", user_confirmation if isinstance(user_confirmation, bool) else None)
    except SecurityError as exc:
        _audit("drive_upload_local_file", "denied", error=str(exc), extra={"folder_id": folder_id, "local_path": local_path})
        return {"ok": False, "data": None, "error": str(exc)}

    path, err = check_path_allowed(local_path)
    if err:
        return {"ok": False, "data": None, "error": err}
    if path is None or not path.exists() or not path.is_file():
        return {"ok": False, "data": None, "error": "local_path does not exist or is not a file"}

    try:
        raw = path.read_bytes()
    except Exception as exc:
        _audit("drive_upload_local_file", "error", error=str(exc), extra={"local_path": local_path})
        return {"ok": False, "data": None, "error": f"Read failed: {exc}"}

    # Safety limit (same as base64 upload tool): 30MB
    if len(raw) > 30_000_000:
        return {"ok": False, "data": None, "error": "File too large (>30MB)"}

    try:
        g.check_batch("drive_upload_local_file", file_count=1, total_bytes=len(raw))
    except SecurityError as exc:
        if not (exc.requires_confirmation and user_confirmation is True):
            _audit("drive_upload_local_file", "denied", error=str(exc), extra={"local_path": local_path, "size_bytes": len(raw)})
            return {"ok": False, "data": None, "error": str(exc)}

    guessed_mime, _ = mimetypes.guess_type(str(path))
    resolved_mime = (mime_type.strip() if isinstance(mime_type, str) and mime_type.strip() else guessed_mime) or "application/octet-stream"
    resolved_name = (filename.strip() if isinstance(filename, str) and filename.strip() else path.name)

    try:
        creds = load_credentials()
        svc = drive_service(creds)

        from googleapiclient.http import MediaIoBaseUpload  # type: ignore

        file_metadata = {"name": resolved_name, "parents": [folder_id.strip()]}
        media = MediaIoBaseUpload(io.BytesIO(raw), mimetype=resolved_mime, resumable=False)
        created = svc.files().create(body=file_metadata, media_body=media, fields="id,name,parents").execute()
        fid = str(created.get("id") or "")
        if not fid:
            return {"ok": False, "data": None, "error": "Drive upload returned no id"}

        _audit(
            "drive_upload_local_file",
            "ok",
            extra={
                "folder_id": folder_id.strip(),
                "local_path": str(path),
                "filename": resolved_name,
                "mime_type": resolved_mime,
                "size_bytes": len(raw),
                "drive_file_id": fid,
            },
        )
        return {
            "ok": True,
            "data": {
                "file": created,
                "local_path": str(path),
                "filename": resolved_name,
                "mime_type": resolved_mime,
                "size_bytes": len(raw),
            },
            "error": None,
        }
    except Exception as exc:
        logger.warning("drive_upload_local_file failed: %s", exc)
        _audit("drive_upload_local_file", "error", error=str(exc), extra={"local_path": local_path, "folder_id": folder_id})
        return {"ok": False, "data": None, "error": f"Drive not available: {exc}"}
