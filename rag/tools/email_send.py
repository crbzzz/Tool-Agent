"""Email send tool using Gmail API with explicit user confirmation."""

from __future__ import annotations

import base64
import logging
from email.message import EmailMessage
import mimetypes
from pathlib import Path
from typing import Any, Dict

from rag.integrations.google_oauth import gmail_service, load_credentials
from rag.security.guard import SecurityError, SecurityGuard
from rag.state.audit_log import append_audit


logger = logging.getLogger(__name__)


def _audit(action: str, status: str, *, error: str | None = None, extra: Dict[str, Any] | None = None) -> None:
    try:
        append_audit(action=action, status=status, error=error, extra=extra)
    except Exception:
        return


def _uploads_dir() -> Path:
    # rag/tools/email_send.py -> rag/ -> repo root
    repo_root = Path(__file__).resolve().parents[2]
    up = repo_root / "rag" / "data" / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    return up


def _resolve_attachment(file_id: str) -> Path:
    fid = (file_id or "").strip()
    if not fid:
        raise ValueError("Empty file_id")
    if Path(fid).name != fid or "/" in fid or "\\" in fid or fid.startswith("."):
        raise ValueError("Invalid file_id")
    p = _uploads_dir() / fid
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"Attachment not found: {fid}")
    return p


def _send_email_impl(args: Dict[str, Any], *, action: str) -> Dict[str, Any]:
    to = args.get("to")
    subject = args.get("subject")
    body = args.get("body")
    attachment_file_ids = args.get("attachment_file_ids")
    user_confirmation = args.get("user_confirmation")

    if not isinstance(to, list) or not to or not all(isinstance(x, str) and x.strip() for x in to):
        return {"ok": False, "data": None, "error": "Invalid `to` (must be non-empty list of strings)"}
    if not isinstance(subject, str):
        return {"ok": False, "data": None, "error": "Invalid `subject`"}
    if not isinstance(body, str):
        return {"ok": False, "data": None, "error": "Invalid `body`"}

    g = SecurityGuard.from_env()
    try:
        g.require_confirmation(action, user_confirmation if isinstance(user_confirmation, bool) else None)
    except SecurityError as exc:
        _audit(action, "denied", error=str(exc), extra={"attachments": len(attachment_file_ids or [])})
        return {"ok": False, "data": None, "error": str(exc)}

    if attachment_file_ids is not None:
        if not isinstance(attachment_file_ids, list) or not all(
            isinstance(x, str) and x.strip() for x in attachment_file_ids
        ):
            return {
                "ok": False,
                "data": None,
                "error": "Invalid attachment_file_ids (must be list of strings)",
            }

    try:
        creds = load_credentials()
        svc = gmail_service(creds)

        msg = EmailMessage()
        msg["To"] = ", ".join([x.strip() for x in to])
        msg["Subject"] = subject
        msg.set_content(body)

        # Attach files from rag/data/uploads by file_id.
        total_bytes = 0
        file_count = 1
        if isinstance(attachment_file_ids, list) and attachment_file_ids:
            file_count += len(attachment_file_ids)
            for fid in attachment_file_ids:
                p = _resolve_attachment(fid)
                data = p.read_bytes()
                total_bytes += len(data)
                # Keep total under Gmail 25MB; be conservative.
                if total_bytes > 20 * 1024 * 1024:
                    return {
                        "ok": False,
                        "data": None,
                        "error": "Attachments too large (limit 20MB total)",
                    }
                mime, _enc = mimetypes.guess_type(str(p))
                if mime and "/" in mime:
                    maintype, subtype = mime.split("/", 1)
                else:
                    maintype, subtype = "application", "octet-stream"
                msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=p.name.split("_", 1)[-1])

        try:
            # Use the same confirmation to authorize a high-risk batch.
            g.check_batch(action, file_count=file_count, total_bytes=total_bytes)
        except SecurityError as exc:
            if not (exc.requires_confirmation and user_confirmation is True):
                _audit(action, "denied", error=str(exc), extra={"file_count": file_count, "total_bytes": total_bytes})
                return {"ok": False, "data": None, "error": str(exc)}

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        _audit(action, "ok", extra={"attachments": len(attachment_file_ids or []), "total_bytes": total_bytes})
        return {"ok": True, "data": {"id": sent.get("id"), "threadId": sent.get("threadId")}}
    except Exception as exc:
        logger.warning("send_email failed: %s", exc)
        _audit(action, "error", error=str(exc), extra={"attachments": len(attachment_file_ids or [])})
        return {"ok": False, "data": None, "error": f"send_email failed: {exc}"}


def send_email(args: Dict[str, Any]) -> Dict[str, Any]:
    return _send_email_impl(args, action="send_email")


def send_email_with_attachments(args: Dict[str, Any]) -> Dict[str, Any]:
    # Enforce at least one attachment for the "with_attachments" tool.
    attachment_file_ids = args.get("attachment_file_ids")
    if not isinstance(attachment_file_ids, list) or len(attachment_file_ids) < 1:
        return {
            "ok": False,
            "data": None,
            "error": "attachment_file_ids must be a non-empty array",
        }
    return _send_email_impl(args, action="send_email_with_attachments")

