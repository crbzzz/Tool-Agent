"""Gmail tools (OAuth-based).

If Google OAuth is not connected, returns a clear error.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional

from rag.integrations.google_oauth import gmail_service, load_credentials


logger = logging.getLogger(__name__)


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
    if max_results is not None and not isinstance(max_results, int):
        return {"ok": False, "data": None, "error": "Invalid `max_results`"}

    try:
        creds = load_credentials()
        svc = gmail_service(creds)
        resp = (
            svc.users()
            .messages()
            .list(userId="me", maxResults=int(max_results))
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
    if not isinstance(email_id, str) or not email_id.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `email_id`"}

    try:
        creds = load_credentials()
        svc = gmail_service(creds)
        mdata = (
            svc.users()
            .messages()
            .get(userId="me", id=str(email_id), format="full")
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
