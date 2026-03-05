"""Persistent app state tools.

This is a tiny file-backed key/value store meant for agents.
Values are stored as strings; callers decide encoding (e.g. JSON string).

Sensitive: app_state_set requires explicit user_confirmation=true.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict


_lock = threading.Lock()


def _state_path() -> Path:
    # Keep it out of the repo by default.
    raw = os.environ.get("APP_STATE_PATH") or ".secrets/app_state.json"
    return Path(raw).resolve()


def _load_state() -> Dict[str, str]:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, str] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, str):
            out[k] = v
    return out


def _save_state(state: Dict[str, str]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def app_state_get(args: Dict[str, Any]) -> Dict[str, Any]:
    key = args.get("key")
    if not isinstance(key, str) or not key.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `key`"}

    with _lock:
        state = _load_state()
        return {"ok": True, "data": {"key": key, "value": state.get(key)}}


def app_state_set(args: Dict[str, Any]) -> Dict[str, Any]:
    key = args.get("key")
    value = args.get("value")
    confirmation = args.get("user_confirmation")

    if confirmation is not True:
        return {"ok": False, "data": None, "error": "Confirmation required: set user_confirmation=true"}

    if not isinstance(key, str) or not key.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `key`"}
    if not isinstance(value, str):
        return {"ok": False, "data": None, "error": "Missing or invalid `value` (must be string)"}

    with _lock:
        state = _load_state()
        state[key] = value
        _save_state(state)

    return {"ok": True, "data": {"key": key, "value": value}}
