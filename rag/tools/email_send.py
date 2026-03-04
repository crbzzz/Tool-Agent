"""Email send tool using Gmail API with explicit user confirmation."""

from __future__ import annotations

import base64
import logging
from email.message import EmailMessage
from typing import Any, Dict

from rag.integrations.google_oauth import gmail_service, load_credentials


logger = logging.getLogger(__name__)


def send_email(args: Dict[str, Any]) -> Dict[str, Any]:
    to = args.get("to")
    subject = args.get("subject")
    body = args.get("body")
    user_confirmation = args.get("user_confirmation")

    if not isinstance(to, list) or not to or not all(isinstance(x, str) and x.strip() for x in to):
        return {"ok": False, "data": None, "error": "Invalid `to` (must be non-empty list of strings)"}
    if not isinstance(subject, str):
        return {"ok": False, "data": None, "error": "Invalid `subject`"}
    if not isinstance(body, str):
        return {"ok": False, "data": None, "error": "Invalid `body`"}
    if user_confirmation is not True:
        return {
            "ok": False,
            "data": None,
            "error": "Refusing to send_email without explicit user_confirmation=true.",
        }

    try:
        creds = load_credentials()
        svc = gmail_service(creds)

        msg = EmailMessage()
        msg["To"] = ", ".join([x.strip() for x in to])
        msg["Subject"] = subject
        msg.set_content(body)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"ok": True, "data": {"id": sent.get("id"), "threadId": sent.get("threadId")}}
    except Exception as exc:
        logger.warning("send_email failed: %s", exc)
        return {"ok": False, "data": None, "error": f"send_email failed: {exc}"}
