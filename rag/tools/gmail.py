"""Gmail tools (OAuth-based).

If Google OAuth is not connected, returns a clear error.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional

from rag.integrations.google_oauth import gmail_service, load_credentials
from rag.security.guard import SecurityError, SecurityGuard
from rag.state.audit_log import append_audit


logger = logging.getLogger(__name__)


def _audit(action: str, status: str, *, error: str | None = None, extra: Dict[str, Any] | None = None) -> None:
    try:
        append_audit(action=action, status=status, error=error, extra=extra)
    except Exception:
        return


def _header(headers: List[Dict[str, Any]], name: str) -> Optional[str]:
    for h in headers or []:
        if str(h.get("name", "")).lower() == name.lower():
            v = h.get("value")
            return None if v is None else str(v)
    return None


def _extract_text_from_payload(payload: Dict[str, Any], max_chars: int = 8000) -> str:
    # Best-effort decode of text/plain parts.
    if not payload:
        return ""
    mime = payload.get("mimeType")
    body = payload.get("body") or {}
    data = body.get("data")
    if mime == "text/plain" and isinstance(data, str) and data:
        try:
            raw = base64.urlsafe_b64decode(data.encode("utf-8"))
            return raw.decode("utf-8", errors="ignore")[:max_chars]
        except Exception:
            return ""

    parts = payload.get("parts") or []
    if isinstance(parts, list):
        for p in parts:
            if isinstance(p, dict) and p.get("mimeType") == "text/plain":
                t = _extract_text_from_payload(p, max_chars=max_chars)
                if t:
                    return t
        # fallback: recurse
        for p in parts:
            if isinstance(p, dict):
                t = _extract_text_from_payload(p, max_chars=max_chars)
                if t:
                    return t
    return ""


def list_emails(args: Dict[str, Any]) -> Dict[str, Any]:
    max_results = args.get("max_results", 10)
    query = args.get("query")
    if max_results is not None and not isinstance(max_results, int):
        return {"ok": False, "data": None, "error": "Invalid `max_results`"}
    if query is not None and not isinstance(query, str):
        return {"ok": False, "data": None, "error": "Invalid `query`"}

    try:
        creds = load_credentials()
        svc = gmail_service(creds)
        resp = (
            svc.users()
            .messages()
            .list(userId="me", maxResults=int(max_results), q=(query or None))
            .execute()
        )
        msgs = resp.get("messages", []) or []
        out: List[Dict[str, Any]] = []
        for m in msgs:
            mid = m.get("id")
            if not mid:
                continue
            mdata = (
                svc.users()
                .messages()
                .get(userId="me", id=mid, format="metadata", metadataHeaders=["From", "To", "Subject", "Date"])
                .execute()
            )
            payload = mdata.get("payload") or {}
            headers = payload.get("headers") or []
            out.append(
                {
                    "id": mid,
                    "thread_id": mdata.get("threadId"),
                    "from": _header(headers, "From"),
                    "to": _header(headers, "To"),
                    "subject": _header(headers, "Subject"),
                    "date": _header(headers, "Date"),
                    "snippet": mdata.get("snippet"),
                }
            )
        return {"ok": True, "data": {"emails": out}}
    except Exception as exc:
        logger.warning("list_emails failed: %s", exc)
        return {"ok": False, "data": None, "error": f"Gmail not available: {exc}"}


def get_email(args: Dict[str, Any]) -> Dict[str, Any]:
    email_id = args.get("email_id")
    message_id = args.get("message_id")
    picked = message_id if isinstance(message_id, str) and message_id.strip() else email_id
    if not isinstance(picked, str) or not picked.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `message_id`"}

    try:
        creds = load_credentials()
        svc = gmail_service(creds)
        mdata = (
            svc.users()
            .messages()
            .get(userId="me", id=str(picked), format="full")
            .execute()
        )
        payload = mdata.get("payload") or {}
        headers = payload.get("headers") or []
        text = _extract_text_from_payload(payload)
        return {
            "ok": True,
            "data": {
                "id": mdata.get("id"),
                "thread_id": mdata.get("threadId"),
                "from": _header(headers, "From"),
                "to": _header(headers, "To"),
                "subject": _header(headers, "Subject"),
                "date": _header(headers, "Date"),
                "snippet": mdata.get("snippet"),
                "body_text": text,
            },
        }
    except Exception as exc:
        logger.warning("get_email failed: %s", exc)
        return {"ok": False, "data": None, "error": f"Gmail not available: {exc}"}


def _iter_parts(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    def walk(p: Any) -> None:
        if not isinstance(p, dict):
            return
        out.append(p)
        parts = p.get("parts")
        if isinstance(parts, list):
            for child in parts:
                walk(child)

    walk(payload)
    return out


def gmail_list_attachments(args: Dict[str, Any]) -> Dict[str, Any]:
    message_id = args.get("message_id")
    if not isinstance(message_id, str) or not message_id.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `message_id`"}

    try:
        creds = load_credentials()
        svc = gmail_service(creds)
        mdata = svc.users().messages().get(userId="me", id=str(message_id), format="full").execute()
        payload = mdata.get("payload") or {}
        attachments: List[Dict[str, Any]] = []

        for part in _iter_parts(payload):
            body = part.get("body") or {}
            attachment_id = body.get("attachmentId")
            size = body.get("size")
            filename = part.get("filename")
            mime_type = part.get("mimeType")

            if not attachment_id:
                continue
            attachments.append(
                {
                    "filename": (filename or "").strip() or None,
                    "mime_type": (mime_type or "").strip() or None,
                    "size_bytes": int(size) if isinstance(size, (int, float)) else size,
                    "attachment_id": str(attachment_id),
                }
            )

        return {"ok": True, "data": {"message_id": str(message_id), "attachments": attachments}}
    except Exception as exc:
        logger.warning("gmail_list_attachments failed: %s", exc)
        return {"ok": False, "data": None, "error": f"Gmail not available: {exc}"}


def _urlsafe_b64_to_bytes(data: str) -> bytes:
    # Gmail returns URL-safe base64 without padding.
    s = (data or "").strip()
    if not s:
        return b""
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("utf-8"))


def gmail_download_attachment(args: Dict[str, Any]) -> Dict[str, Any]:
    message_id = args.get("message_id")
    attachment_id = args.get("attachment_id")
    max_bytes = args.get("max_bytes", 10_000_000)

    if not isinstance(message_id, str) or not message_id.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `message_id`"}
    if not isinstance(attachment_id, str) or not attachment_id.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `attachment_id`"}
    if max_bytes is not None and not isinstance(max_bytes, int):
        return {"ok": False, "data": None, "error": "Invalid `max_bytes`"}
    if isinstance(max_bytes, int) and (max_bytes < 1024 or max_bytes > 30_000_000):
        return {"ok": False, "data": None, "error": "`max_bytes` must be between 1024 and 30000000"}

    try:
        creds = load_credentials()
        svc = gmail_service(creds)

        # Best-effort metadata (filename/mime) by scanning the message parts.
        filename: str | None = None
        mime_type: str | None = None
        size_bytes: int | None = None
        try:
            mdata = svc.users().messages().get(userId="me", id=str(message_id), format="full").execute()
            payload = mdata.get("payload") or {}
            for part in _iter_parts(payload):
                body = part.get("body") or {}
                if str(body.get("attachmentId") or "") != str(attachment_id):
                    continue
                filename = (part.get("filename") or "").strip() or None
                mime_type = (part.get("mimeType") or "").strip() or None
                try:
                    size_val = body.get("size")
                    if isinstance(size_val, (int, float)):
                        size_bytes = int(size_val)
                except Exception:
                    size_bytes = None
                break
        except Exception:
            pass

        if isinstance(max_bytes, int) and size_bytes is not None and size_bytes > max_bytes:
            return {
                "ok": False,
                "data": {"size_bytes": size_bytes, "max_bytes": max_bytes},
                "error": "Attachment exceeds max_bytes safety limit",
            }

        resp = (
            svc.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=str(message_id), id=str(attachment_id))
            .execute()
        )

        raw = resp.get("data")
        if not isinstance(raw, str) or not raw.strip():
            return {"ok": False, "data": None, "error": "Attachment download returned no data"}

        blob = _urlsafe_b64_to_bytes(raw)
        if isinstance(max_bytes, int) and len(blob) > max_bytes:
            return {
                "ok": False,
                "data": {"size_bytes": len(blob), "max_bytes": max_bytes},
                "error": "Attachment exceeds max_bytes safety limit",
            }

        content_base64 = base64.b64encode(blob).decode("utf-8")
        return {
            "ok": True,
            "data": {
                "message_id": str(message_id),
                "attachment_id": str(attachment_id),
                "filename": filename,
                "mime_type": mime_type,
                "size_bytes": len(blob),
                "content_base64": content_base64,
            },
        }
    except Exception as exc:
        logger.warning("gmail_download_attachment failed: %s", exc)
        return {"ok": False, "data": None, "error": f"Gmail not available: {exc}"}


def gmail_apply_label(args: Dict[str, Any]) -> Dict[str, Any]:
    message_id = args.get("message_id")
    label_name = args.get("label_name")
    user_confirmation = args.get("user_confirmation")

    if not isinstance(message_id, str) or not message_id.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `message_id`"}
    if not isinstance(label_name, str) or not label_name.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `label_name`"}

    g = SecurityGuard.from_env()
    try:
        g.require_confirmation("gmail_apply_label", user_confirmation if isinstance(user_confirmation, bool) else None)
    except SecurityError as exc:
        _audit("gmail_apply_label", "denied", error=str(exc), extra={"message_id": message_id, "label_name": label_name})
        return {"ok": False, "data": None, "error": str(exc)}

    try:
        creds = load_credentials()
        svc = gmail_service(creds)

        # Find or create the label.
        labels_resp = svc.users().labels().list(userId="me").execute()
        labels = labels_resp.get("labels", []) or []
        label_id: str | None = None
        for lab in labels:
            if str(lab.get("name") or "").strip() == label_name.strip():
                label_id = str(lab.get("id") or "") or None
                break

        if not label_id:
            created = (
                svc.users()
                .labels()
                .create(
                    userId="me",
                    body={
                        "name": label_name.strip(),
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                )
                .execute()
            )
            label_id = str(created.get("id") or "") or None
        if not label_id:
            return {"ok": False, "data": None, "error": "Unable to create/find label"}

        svc.users().messages().modify(
            userId="me",
            id=str(message_id),
            body={"addLabelIds": [label_id], "removeLabelIds": []},
        ).execute()

        _audit(
            "gmail_apply_label",
            "ok",
            extra={"message_id": str(message_id), "label_name": label_name.strip(), "label_id": label_id},
        )

        return {"ok": True, "data": {"message_id": str(message_id), "label_name": label_name.strip(), "label_id": label_id}}
    except Exception as exc:
        logger.warning("gmail_apply_label failed: %s", exc)
        _audit("gmail_apply_label", "error", error=str(exc), extra={"message_id": message_id, "label_name": label_name})
        return {"ok": False, "data": None, "error": f"Gmail not available: {exc}"}


def gmail_trash_message(args: Dict[str, Any]) -> Dict[str, Any]:
    message_id = args.get("message_id")
    user_confirmation = args.get("user_confirmation")
    if not isinstance(message_id, str) or not message_id.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `message_id`"}

    g = SecurityGuard.from_env()
    try:
        g.require_confirmation("gmail_trash_message", user_confirmation if isinstance(user_confirmation, bool) else None)
    except SecurityError as exc:
        _audit("gmail_trash_message", "denied", error=str(exc), extra={"message_id": message_id})
        return {"ok": False, "data": None, "error": str(exc)}

    try:
        creds = load_credentials()
        svc = gmail_service(creds)
        svc.users().messages().trash(userId="me", id=str(message_id)).execute()
        _audit("gmail_trash_message", "ok", extra={"message_id": str(message_id)})
        return {"ok": True, "data": {"message_id": str(message_id), "trashed": True}}
    except Exception as exc:
        logger.warning("gmail_trash_message failed: %s", exc)
        _audit("gmail_trash_message", "error", error=str(exc), extra={"message_id": message_id})
        return {"ok": False, "data": None, "error": f"Gmail not available: {exc}"}
