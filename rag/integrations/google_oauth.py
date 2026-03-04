"""Google OAuth (Gmail/Drive) helper.

This module implements a minimal OAuth2 authorization-code flow suitable for local dev:
- `/oauth/google/start` returns a redirect to Google's consent screen
- `/oauth/google/callback` stores tokens locally (JSON)

Token storage is local-file based by default and should be treated as sensitive.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
import base64
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


DEFAULT_TOKEN_PATH = ".secrets/google_token.json"


_STATE_TTL_S = 10 * 60
_state_lock = threading.Lock()
_state_store: Dict[str, Dict[str, Any]] = {}


GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
]


def _token_path() -> Path:
    return Path(os.environ.get("GOOGLE_TOKEN_PATH", DEFAULT_TOKEN_PATH)).resolve()


def _client_config() -> Dict[str, Any]:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("GOOGLE_CLIENT_ID and/or GOOGLE_CLIENT_SECRET are not set")

    # Google can issue OAuth clients of type "web" or "installed".
    # We support both because users often configure one or the other.
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
    }


def _build_flow() -> Flow:
    """Build a Flow instance using either 'installed' or 'web' config.

    Use `GOOGLE_OAUTH_CLIENT_TYPE` to force one: 'installed' or 'web'.
    """

    cfg = _client_config()
    forced = (os.environ.get("GOOGLE_OAUTH_CLIENT_TYPE") or "").strip().lower()
    redirect_uri = _redirect_uri()
    scopes = _scopes()

    if forced in ("installed", "web"):
        return Flow.from_client_config({forced: cfg[forced]}, scopes=scopes, redirect_uri=redirect_uri)

    # Try installed first, then web.
    try:
        return Flow.from_client_config({"installed": cfg["installed"]}, scopes=scopes, redirect_uri=redirect_uri)
    except Exception:
        return Flow.from_client_config({"web": cfg["web"]}, scopes=scopes, redirect_uri=redirect_uri)


def _pkce_verifier() -> str:
    # RFC 7636: 43-128 chars; use URL-safe base64-like string.
    return secrets.token_urlsafe(64)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    b64 = base64.urlsafe_b64encode(digest).decode("utf-8")
    return b64.rstrip("=")


def _purge_expired_states() -> None:
    now = time.time()
    expired = [k for k, v in _state_store.items() if now - float(v.get("ts", 0)) > _STATE_TTL_S]
    for k in expired:
        _state_store.pop(k, None)


def oauth_prepare() -> Tuple[str, str]:
    """Create an auth URL and state, storing PKCE verifier for the callback."""

    flow = _build_flow()
    state = secrets.token_urlsafe(24)
    verifier = _pkce_verifier()
    challenge = _pkce_challenge(verifier)

    with _state_lock:
        _purge_expired_states()
        _state_store[state] = {"ts": time.time(), "verifier": verifier}

    auth_url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    return auth_url, state


def _redirect_uri() -> str:
    # Must match what you configure in Google Cloud Console.
    return os.environ.get("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/oauth/google/callback")


def _scopes() -> list[str]:
    scopes = []
    scopes.extend(GMAIL_SCOPES)
    scopes.extend(DRIVE_SCOPES)
    # De-dup while preserving order
    seen = set()
    out: list[str] = []
    for s in scopes:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def load_credentials() -> Optional[Credentials]:
    """Load stored credentials and refresh if needed."""

    token_path = _token_path()
    if not token_path.exists():
        return None

    creds = Credentials.from_authorized_user_file(str(token_path), scopes=_scopes())
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_credentials(creds)
        except Exception as exc:
            logger.warning("Failed to refresh Google credentials: %s", exc)
    return creds


def save_credentials(creds: Credentials) -> None:
    token_path = _token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")


def delete_credentials() -> None:
    token_path = _token_path()
    if token_path.exists():
        token_path.unlink()


def oauth_start_url(state: str) -> str:
    """Backward-compatible wrapper: build consent URL with provided state.

    Prefer `oauth_prepare()` which handles PKCE + state storage.
    """

    flow = _build_flow()
    verifier = _pkce_verifier()
    challenge = _pkce_challenge(verifier)
    with _state_lock:
        _purge_expired_states()
        _state_store[state] = {"ts": time.time(), "verifier": verifier}
    auth_url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    return auth_url


def oauth_exchange_code(code: str, state: Optional[str] = None) -> Credentials:
    """Exchange authorization code for tokens and store them locally."""

    verifier: Optional[str] = None
    if state:
        with _state_lock:
            entry = _state_store.pop(state, None)
            if entry:
                verifier = entry.get("verifier")

    flow = _build_flow()
    if verifier:
        flow.fetch_token(code=code, code_verifier=verifier)
    else:
        # Best-effort fallback: some flows may not require PKCE.
        flow.fetch_token(code=code)
    creds = flow.credentials
    save_credentials(creds)
    return creds


def is_connected() -> bool:
    creds = load_credentials()
    return bool(creds and creds.valid)


def gmail_service(creds: Optional[Credentials] = None) -> Any:
    creds = creds or load_credentials()
    if not creds or not creds.valid:
        raise RuntimeError("Google OAuth not connected")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def drive_service(creds: Optional[Credentials] = None) -> Any:
    creds = creds or load_credentials()
    if not creds or not creds.valid:
        raise RuntimeError("Google OAuth not connected")
    return build("drive", "v3", credentials=creds, cache_discovery=False)
