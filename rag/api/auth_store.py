"""In-memory auth store for the desktop app.

This keeps Supabase sessions server-side so the React UI can remain simple.
For production, replace with Redis/DB and encrypt refresh tokens at rest.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional


DEFAULT_TTL_S = 60 * 60 * 24  # 24h
DEFAULT_OAUTH_TTL_S = 60 * 10  # 10 minutes


@dataclass
class AuthSession:
    access_token: str
    refresh_token: str | None
    expires_at: int | None
    user: Dict[str, Any] | None
    updated_ts: float


@dataclass
class PendingOAuth:
    poll_token: str
    code_verifier: str
    created_ts: float
    kind: str  # "signin" | "link"
    error: str | None = None
    session: AuthSession | None = None


_lock = threading.Lock()
_client_sessions: Dict[str, AuthSession] = {}
_pending: Dict[str, PendingOAuth] = {}


def new_client_id() -> str:
    return uuid.uuid4().hex


def _purge_expired(now: float | None = None) -> None:
    if now is None:
        now = time.time()

    expired_clients = [
        cid for cid, s in _client_sessions.items() if now - s.updated_ts > DEFAULT_TTL_S
    ]
    for cid in expired_clients:
        _client_sessions.pop(cid, None)

    expired_pending = [
        token for token, p in _pending.items() if now - p.created_ts > DEFAULT_OAUTH_TTL_S
    ]
    for token in expired_pending:
        _pending.pop(token, None)


def get_client_session(client_id: str) -> AuthSession | None:
    with _lock:
        _purge_expired()
        return _client_sessions.get(client_id)


def set_client_session(client_id: str, session: AuthSession) -> None:
    with _lock:
        _purge_expired()
        session.updated_ts = time.time()
        _client_sessions[client_id] = session


def clear_client_session(client_id: str) -> None:
    with _lock:
        _client_sessions.pop(client_id, None)


def create_pending_oauth(kind: str, code_verifier: str) -> str:
    poll_token = uuid.uuid4().hex
    with _lock:
        _purge_expired()
        _pending[poll_token] = PendingOAuth(
            poll_token=poll_token,
            code_verifier=code_verifier,
            created_ts=time.time(),
            kind=kind,
        )
    return poll_token


def get_pending_oauth(poll_token: str) -> PendingOAuth | None:
    with _lock:
        _purge_expired()
        return _pending.get(poll_token)


def set_oauth_result(poll_token: str, session: AuthSession | None, error: str | None) -> None:
    with _lock:
        entry = _pending.get(poll_token)
        if entry is None:
            return
        entry.session = session
        entry.error = error


def consume_oauth_result(poll_token: str) -> PendingOAuth | None:
    with _lock:
        _purge_expired()
        return _pending.pop(poll_token, None)
