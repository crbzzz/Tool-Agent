from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


_LOCK = threading.Lock()


def _default_audit_path() -> Path:
    raw = os.getenv("SECURITY_AUDIT_PATH") or "./rag/state/audit.jsonl"
    return Path(raw).resolve()


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def append_audit(
    *,
    action: str,
    status: str,
    paths: Optional[List[str]] = None,
    file_count: Optional[int] = None,
    total_bytes: Optional[int] = None,
    risk_score: Optional[int] = None,
    error: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    audit_path: Optional[Path] = None,
) -> None:
    """Append a JSONL audit entry.

    Never include secrets or file contents here.
    """

    entry: Dict[str, Any] = {
        "ts_utc": _now_iso(),
        "action": str(action),
        "status": str(status),
    }
    if paths:
        entry["paths"] = [str(p) for p in paths][:50]
    if file_count is not None:
        entry["file_count"] = int(file_count)
    if total_bytes is not None:
        entry["total_bytes"] = int(total_bytes)
    if risk_score is not None:
        entry["risk_score"] = int(risk_score)
    if error:
        entry["error"] = str(error)[:2000]
    if extra and isinstance(extra, dict):
        # Keep small and safe.
        entry["extra"] = {k: v for k, v in list(extra.items())[:25]}

    line = json.dumps(entry, ensure_ascii=False)

    ap = audit_path or _default_audit_path()

    with _LOCK:
        ap.parent.mkdir(parents=True, exist_ok=True)
        with ap.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def read_recent(limit: int = 100, audit_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    lim = int(limit) if isinstance(limit, int) else 100
    if lim < 1:
        lim = 1
    if lim > 1000:
        lim = 1000

    ap = audit_path or _default_audit_path()

    try:
        if not ap.exists():
            return []
    except Exception:
        return []

    # Simple: read all, then keep tail (files expected to remain small locally).
    try:
        lines = ap.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for line in lines[-lim:]:
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            continue
    return out
