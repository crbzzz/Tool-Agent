"""In-memory session store for chat message history.

This is intentionally simple for a runnable skeleton. For production, replace with
Redis/DB storage.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from rag.agent.policy import build_policy_message


DEFAULT_TTL_S = 60 * 60  # 1 hour


@dataclass
class Session:
    session_id: str
    messages: List[Dict[str, Any]]
    updated_ts: float


_lock = threading.Lock()
_sessions: Dict[str, Session] = {}


def _purge_expired(ttl_s: int) -> None:
    now = time.time()
    expired = [sid for sid, s in _sessions.items() if now - s.updated_ts > ttl_s]
    for sid in expired:
        _sessions.pop(sid, None)


def get_or_create_session(session_id: str, ttl_s: int = DEFAULT_TTL_S) -> Session:
    with _lock:
        _purge_expired(ttl_s)
        s = _sessions.get(session_id)
        if s is None:
            s = Session(session_id=session_id, messages=[build_policy_message()], updated_ts=time.time())
            _sessions[session_id] = s
        return s


def reset_session(session_id: str) -> None:
    with _lock:
        _sessions.pop(session_id, None)


def update_session(session_id: str, messages: List[Dict[str, Any]]) -> None:
    # Keep session memory bounded.
    if len(messages) > 100:
        if messages and messages[0].get("role") == "system":
            messages = [messages[0], *messages[-99:]]
        else:
            messages = messages[-100:]
    with _lock:
        _sessions[session_id] = Session(session_id=session_id, messages=messages, updated_ts=time.time())
