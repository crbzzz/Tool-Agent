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
import urllib.parse
import urllib.request
import warnings
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
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
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
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


def oauth_prepare(return_to: str | None = None) -> Tuple[str, str]:
    """Create an auth URL and state, storing PKCE verifier for the callback."""

    flow = _build_flow()
    state = secrets.token_urlsafe(24)
    verifier = _pkce_verifier()
    # Let google-auth-oauthlib compute the challenge from this verifier.
    flow.code_verifier = verifier

    with _state_lock:
        _purge_expired_states()
        _state_store[state] = {"ts": time.time(), "verifier": verifier, "return_to": return_to}

    auth_url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="false",
        prompt="consent",
        state=state,
    )
    return auth_url, state


def pop_state(state: str) -> Dict[str, Any] | None:
    """Pop and return the stored state entry (verifier, return_to).

    Returns None if the state is missing/expired.
    """

    with _state_lock:
        _purge_expired_states()
        entry = _state_store.pop(state, None)
    return entry


def _redirect_uri() -> str:
    # Must match what you configure in Google Cloud Console.
    if os.environ.get("GOOGLE_REDIRECT_URI"):
        return os.environ["GOOGLE_REDIRECT_URI"]

    # Desktop launcher defaults to 8002; keep a sensible local default.
    port = os.environ.get("BART_AI_PORT") or "8002"
    return f"http://127.0.0.1:{port}/oauth/google/callback"


def _token_uri() -> str:
    cfg = _client_config()
    # token_uri is identical for both client types.
    return str(cfg["installed"]["token_uri"])


def _manual_exchange_code(code: str, verifier: str) -> Credentials:
    """Exchange code for tokens via a direct POST to Google's token endpoint.

    This is a fallback when library PKCE propagation is unreliable.
    """

    token_uri = _token_uri()
    redirect_uri = _redirect_uri()
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("GOOGLE_CLIENT_ID and/or GOOGLE_CLIENT_SECRET are not set")

    form = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    data = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(token_uri, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
        raise RuntimeError(f"Token endpoint HTTP {exc.code}: {body}")
    except URLError as exc:
        raise RuntimeError(f"Token endpoint unreachable: {exc}")

    token_data = json.loads(payload or "{}")
    access_token = token_data.get("access_token")
    if not access_token:
        raise RuntimeError(f"Token endpoint response missing access_token: {token_data}")

    creds = Credentials(
        token=access_token,
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_uri,
        client_id=client_id,
        client_secret=client_secret,
        scopes=_scopes(),
    )

    expires_in = token_data.get("expires_in")
    if isinstance(expires_in, (int, float)):
        creds.expiry = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

    if token_data.get("id_token"):
        # google-auth stores id_token as a plain attribute.
        setattr(creds, "id_token", token_data.get("id_token"))

    return creds


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

    try:
        creds = Credentials.from_authorized_user_file(str(token_path), scopes=_scopes())
    except ValueError as exc:
        # Common when we changed requested scopes but a previous token file exists.
        msg = str(exc)
        if "Scope has changed" in msg or "scopes" in msg.lower():
            logger.info("Stored Google token scopes no longer match; deleting token and requiring reconnect")
            try:
                token_path.unlink()
            except Exception:
                pass
            return None
        raise
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
    flow.code_verifier = verifier
    with _state_lock:
        _purge_expired_states()
        _state_store[state] = {"ts": time.time(), "verifier": verifier}
    auth_url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="false",
        prompt="consent",
        state=state,
    )
    return auth_url


def oauth_exchange_code(
    code: str,
    state: Optional[str] = None,
    verifier: Optional[str] = None,
) -> Credentials:
    """Exchange authorization code for tokens and store them locally."""

    if not verifier and state:
        entry = pop_state(state)
        if entry:
            verifier = entry.get("verifier")

    flow = _build_flow()
    if verifier:
        # Set on the Flow and also pass explicitly to ensure the token
        # request includes `code_verifier` across library versions.
        flow.code_verifier = verifier
        try:
            # Pass code_verifier explicitly to guarantee it is sent.
            # Some environments treat warnings as errors; ignore scope-change warnings.
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=r"Scope has changed.*")
                flow.fetch_token(code=code, code_verifier=verifier)
        except Exception as exc:
            msg = str(exc)
            if "Missing code verifier" in msg or "code verifier" in msg or "invalid_grant" in msg:
                logger.warning("Flow.fetch_token failed (%s); falling back to manual token exchange", msg)
                creds = _manual_exchange_code(code=code, verifier=verifier)
                save_credentials(creds)
                return creds
            raise
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
