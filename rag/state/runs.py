from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

from rag.security.guard import SecurityGuard
from rag.security.policy import get_policy


RunStatus = Literal["success", "error"]
OutputType = Literal["text", "code", "mixed", "tool_call"]


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _env_path(name: str, default: str) -> Path:
    raw = (os.getenv(name) or default).strip() or default
    return Path(raw).resolve()


def _runs_path() -> Path:
    return _env_path("RUNS_DB_PATH", "./rag/state/runs.sqlite")


def _split_patterns(raw: Optional[str]) -> List[str]:
    if not isinstance(raw, str) or not raw.strip():
        return []
    parts: List[str] = []
    for chunk in raw.split(","):
        s = chunk.strip()
        if s:
            parts.append(s)
    return parts


_DEFAULT_REDACT_PATTERNS: List[str] = [
    r"(?i)bearer\s+[a-z0-9._\-]+",
    r"(?i)access[_-]?token\s*[:=]\s*[^\s,]+",
    r"(?i)refresh[_-]?token\s*[:=]\s*[^\s,]+",
    r"(?i)api[_-]?key\s*[:=]\s*[^\s,]+",
    r"(?i)authorization\s*[:=]\s*[^\s,]+",
    r"(?i)client[_-]?secret\s*[:=]\s*[^\s,]+",
    r"(?i)password\s*[:=]\s*[^\s,]+",
    r"(?i)secret\s*[:=]\s*[^\s,]+",
]


def _compiled_redactors() -> List[re.Pattern[str]]:
    pats = _split_patterns(os.getenv("OBS_REDACT_PATTERNS"))
    if not pats:
        pats = _DEFAULT_REDACT_PATTERNS

    out: List[re.Pattern[str]] = []
    for p in pats:
        try:
            out.append(re.compile(p))
        except Exception:
            # Treat invalid regex as literal substring.
            try:
                out.append(re.compile(re.escape(p)))
            except Exception:
                continue
    return out


_REDACTORS = _compiled_redactors()


def redact_text(text: Optional[str], *, max_len: int = 2000) -> str:
    s = "" if text is None else str(text)
    if not s:
        return ""
    out = s
    for rx in _REDACTORS:
        try:
            out = rx.sub("<redacted>", out)
        except Exception:
            continue
    if len(out) > max_len:
        out = out[:max_len]
    return out


_PATHLIKE_KEYS = {
    "path",
    "root_path",
    "src_path",
    "dst_path",
    "file_path",
    "folder_path",
    "local_path",
    "dir",
    "directory",
    "workspace_root",
}

_SECRET_KEYS = {
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "api_key",
    "apikey",
    "client_secret",
    "password",
    "secret",
}


def _is_pathlike_key(key: str) -> bool:
    k = (key or "").strip().lower()
    if not k:
        return False
    if k in _PATHLIKE_KEYS:
        return True
    return "path" in k or k.endswith("_file") or k.endswith("_dir")


def _is_secret_key(key: str) -> bool:
    k = (key or "").strip().lower()
    if not k:
        return False
    if k in _SECRET_KEYS:
        return True
    return "token" in k or "secret" in k or "password" in k


def redact_args_summary(tool_name: str, args: Any, *, max_len: int = 800) -> str:
    guard = SecurityGuard.from_env()

    def _redact_value(k: str, v: Any) -> Any:
        if _is_secret_key(k):
            return "<redacted>"
        if _is_pathlike_key(k) and isinstance(v, str) and v.strip():
            return guard.redact_path(v)
        if _is_pathlike_key(k) and isinstance(v, list):
            out: List[Any] = []
            for item in v[:25]:
                if isinstance(item, str):
                    out.append(guard.redact_path(item))
                else:
                    out.append("<redacted>")
            if len(v) > 25:
                out.append("<truncated>")
            return out
        return v

    safe: Any = args
    if isinstance(args, dict):
        safe = {str(k): _redact_value(str(k), v) for k, v in list(args.items())[:50]}
    elif isinstance(args, list):
        safe = ["<list>"]

    try:
        raw = json.dumps({"tool": tool_name, "args": safe}, ensure_ascii=False)
    except Exception:
        raw = str({"tool": tool_name, "args": "<unserializable>"})

    out = redact_text(raw, max_len=max_len)
    return out


def infer_affected_items_count(result: Any) -> Optional[int]:
    if not isinstance(result, dict):
        return None
    data = result.get("data")
    if isinstance(data, dict):
        for key in ("deleted", "moved", "uploaded", "count", "file_count", "items_count"):
            v = data.get(key)
            if isinstance(v, int):
                return int(v)
        for key in ("items", "results", "files", "entries"):
            v = data.get(key)
            if isinstance(v, list):
                return len(v)
    return None


@dataclass(frozen=True)
class ToolTraceEntry:
    step_index: int
    tool_name: str
    args_summary: str
    started_at_iso: str
    finished_at_iso: str
    duration_ms: int
    ok: bool
    error: Optional[str] = None
    affected_items_count: Optional[int] = None


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    started_at_iso: str
    finished_at_iso: Optional[str]
    user_id: str
    input_summary: str
    access_mode: str
    status: RunStatus
    error_message: Optional[str]
    output_type: Optional[OutputType]
    grounded: Optional[bool]


class RunsStore:
    def start_run(self, record: RunRecord) -> None:
        raise NotImplementedError

    def append_tool(self, run_id: str, entry: ToolTraceEntry) -> None:
        raise NotImplementedError

    def finish_run(self, run_id: str, *, finished_at_iso: str, status: RunStatus, error_message: Optional[str], output_type: Optional[OutputType], grounded: Optional[bool]) -> None:
        raise NotImplementedError

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def stats_summary(self, days: int = 7) -> Dict[str, Any]:
        raise NotImplementedError


class SQLiteRunsStore(RunsStore):
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.path))
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self) -> None:
        with self._lock:
            with closing(self._conn()) as c:
                c.execute(
                    """
                    CREATE TABLE IF NOT EXISTS runs (
                        run_id TEXT PRIMARY KEY,
                        started_at_iso TEXT NOT NULL,
                        finished_at_iso TEXT,
                        user_id TEXT NOT NULL,
                        input_summary TEXT NOT NULL,
                        access_mode TEXT NOT NULL,
                        status TEXT NOT NULL,
                        error_message TEXT,
                        output_type TEXT,
                        grounded INTEGER
                    )
                    """
                )
                c.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tool_calls (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        step_index INTEGER NOT NULL,
                        tool_name TEXT NOT NULL,
                        args_summary TEXT NOT NULL,
                        started_at_iso TEXT NOT NULL,
                        finished_at_iso TEXT NOT NULL,
                        duration_ms INTEGER NOT NULL,
                        ok INTEGER NOT NULL,
                        error TEXT,
                        affected_items_count INTEGER,
                        FOREIGN KEY(run_id) REFERENCES runs(run_id)
                    )
                    """
                )
                c.execute("CREATE INDEX IF NOT EXISTS idx_tool_calls_run_id ON tool_calls(run_id)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at_iso)")
                c.commit()

    def start_run(self, record: RunRecord) -> None:
        with self._lock:
            with closing(self._conn()) as c:
                c.execute(
                    """
                    INSERT OR REPLACE INTO runs(
                        run_id, started_at_iso, finished_at_iso, user_id, input_summary,
                        access_mode, status, error_message, output_type, grounded
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """ ,
                    (
                        record.run_id,
                        record.started_at_iso,
                        record.finished_at_iso,
                        record.user_id,
                        record.input_summary,
                        record.access_mode,
                        record.status,
                        record.error_message,
                        record.output_type,
                        None if record.grounded is None else (1 if record.grounded else 0),
                    ),
                )
                c.commit()

    def append_tool(self, run_id: str, entry: ToolTraceEntry) -> None:
        with self._lock:
            with closing(self._conn()) as c:
                c.execute(
                    """
                    INSERT INTO tool_calls(
                        run_id, step_index, tool_name, args_summary,
                        started_at_iso, finished_at_iso, duration_ms, ok, error, affected_items_count
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """ ,
                    (
                        run_id,
                        int(entry.step_index),
                        entry.tool_name,
                        entry.args_summary,
                        entry.started_at_iso,
                        entry.finished_at_iso,
                        int(entry.duration_ms),
                        1 if entry.ok else 0,
                        entry.error,
                        entry.affected_items_count,
                    ),
                )
                c.commit()

    def finish_run(self, run_id: str, *, finished_at_iso: str, status: RunStatus, error_message: Optional[str], output_type: Optional[OutputType], grounded: Optional[bool]) -> None:
        with self._lock:
            with closing(self._conn()) as c:
                c.execute(
                    """
                    UPDATE runs
                    SET finished_at_iso=?, status=?, error_message=?, output_type=?, grounded=?
                    WHERE run_id=?
                    """,
                    (
                        finished_at_iso,
                        status,
                        error_message,
                        output_type,
                        None if grounded is None else (1 if grounded else 0),
                        run_id,
                    ),
                )
                c.commit()

    def _tool_calls_for_run(self, c: sqlite3.Connection, run_id: str) -> List[Dict[str, Any]]:
        rows = c.execute(
            """
            SELECT step_index, tool_name, args_summary, started_at_iso, finished_at_iso, duration_ms,
                   ok, error, affected_items_count
            FROM tool_calls
            WHERE run_id=?
            ORDER BY step_index ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "step_index": int(r["step_index"]),
                    "tool_name": str(r["tool_name"]),
                    "args_summary": str(r["args_summary"]),
                    "started_at_iso": str(r["started_at_iso"]),
                    "finished_at_iso": str(r["finished_at_iso"]),
                    "duration_ms": int(r["duration_ms"]),
                    "ok": bool(r["ok"]),
                    "error": r["error"],
                    "affected_items_count": r["affected_items_count"],
                }
            )
        return out

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with closing(self._conn()) as c:
                row = c.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
                if row is None:
                    return None
                run = dict(row)
                run["grounded"] = None if run.get("grounded") is None else bool(run.get("grounded"))
                run["tool_calls"] = self._tool_calls_for_run(c, run_id)
                return run

    def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        lim = int(limit) if isinstance(limit, int) else 50
        if lim < 1:
            lim = 1
        if lim > 200:
            lim = 200
        with self._lock:
            with closing(self._conn()) as c:
                rows = c.execute(
                    """
                    SELECT run_id, started_at_iso, finished_at_iso, user_id, input_summary,
                           access_mode, status, error_message, output_type, grounded
                    FROM runs
                    ORDER BY started_at_iso DESC
                    LIMIT ?
                    """,
                    (lim,),
                ).fetchall()
                out: List[Dict[str, Any]] = []
                for r in rows:
                    d = dict(r)
                    d["grounded"] = None if d.get("grounded") is None else bool(d.get("grounded"))
                    out.append(d)
                return out

    def stats_summary(self, days: int = 7) -> Dict[str, Any]:
        d = int(days) if isinstance(days, int) else 7
        if d < 1:
            d = 1
        if d > 90:
            d = 90

        with self._lock:
            with closing(self._conn()) as c:
                # Use lexicographic compare since we store ISO UTC.
                since = datetime.now(tz=timezone.utc).timestamp() - (d * 86400)
                since_iso = datetime.fromtimestamp(since, tz=timezone.utc).isoformat()

                total = c.execute(
                    "SELECT COUNT(1) AS n FROM runs WHERE started_at_iso >= ?",
                    (since_iso,),
                ).fetchone()["n"]
                success = c.execute(
                    "SELECT COUNT(1) AS n FROM runs WHERE started_at_iso >= ? AND status='success'",
                    (since_iso,),
                ).fetchone()["n"]
                error = c.execute(
                    "SELECT COUNT(1) AS n FROM runs WHERE started_at_iso >= ? AND status='error'",
                    (since_iso,),
                ).fetchone()["n"]

                tool_rows = c.execute(
                    """
                    SELECT tool_name, COUNT(1) AS n
                    FROM tool_calls
                    WHERE started_at_iso >= ?
                    GROUP BY tool_name
                    ORDER BY n DESC
                    LIMIT 10
                    """,
                    (since_iso,),
                ).fetchall()
                top_tools = [{"tool": str(r["tool_name"]), "count": int(r["n"])} for r in tool_rows]

                lat_row = c.execute(
                    "SELECT AVG(duration_ms) AS avg_ms FROM tool_calls WHERE started_at_iso >= ?",
                    (since_iso,),
                ).fetchone()
                avg_tool_latency_ms = float(lat_row["avg_ms"]) if lat_row and lat_row["avg_ms"] is not None else 0.0

                per_day_rows = c.execute(
                    """
                    SELECT substr(started_at_iso, 1, 10) AS day, COUNT(1) AS n
                    FROM runs
                    WHERE started_at_iso >= ?
                    GROUP BY day
                    ORDER BY day ASC
                    """,
                    (since_iso,),
                ).fetchall()
                runs_per_day = [{"day": str(r["day"]), "count": int(r["n"])} for r in per_day_rows]

        total_i = int(total or 0)
        success_i = int(success or 0)
        error_i = int(error or 0)
        success_rate = (success_i / total_i) if total_i else 0.0
        error_rate = (error_i / total_i) if total_i else 0.0

        return {
            "total_runs": total_i,
            "success_rate": success_rate,
            "error_rate": error_rate,
            "top_tools": top_tools,
            "avg_tool_latency_ms": avg_tool_latency_ms,
            "runs_per_day": runs_per_day,
        }


class JSONLRunsStore(RunsStore):
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, obj: Dict[str, Any]) -> None:
        line = json.dumps(obj, ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def start_run(self, record: RunRecord) -> None:
        self._append({"type": "run_start", **asdict(record)})

    def append_tool(self, run_id: str, entry: ToolTraceEntry) -> None:
        self._append({"type": "tool", "run_id": run_id, **asdict(entry)})

    def finish_run(self, run_id: str, *, finished_at_iso: str, status: RunStatus, error_message: Optional[str], output_type: Optional[OutputType], grounded: Optional[bool]) -> None:
        self._append(
            {
                "type": "run_finish",
                "run_id": run_id,
                "finished_at_iso": finished_at_iso,
                "status": status,
                "error_message": error_message,
                "output_type": output_type,
                "grounded": grounded,
            }
        )

    def _read_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            try:
                if not self.path.exists():
                    return []
            except Exception:
                return []
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except Exception:
                return []
        out: List[Dict[str, Any]] = []
        for line in lines:
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    out.append(obj)
            except Exception:
                continue
        return out

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        # Best-effort reconstruct from events.
        events = [e for e in self._read_all() if e.get("run_id") == run_id]
        if not events:
            return None

        run: Dict[str, Any] = {}
        tool_calls: List[Dict[str, Any]] = []
        for e in events:
            t = e.get("type")
            if t == "run_start":
                run = {k: v for k, v in e.items() if k != "type"}
            elif t == "tool":
                tool_calls.append({k: v for k, v in e.items() if k not in {"type"}})
            elif t == "run_finish":
                run["finished_at_iso"] = e.get("finished_at_iso")
                run["status"] = e.get("status")
                run["error_message"] = e.get("error_message")
                run["output_type"] = e.get("output_type")
                run["grounded"] = e.get("grounded")
        run["tool_calls"] = sorted(tool_calls, key=lambda x: int(x.get("step_index") or 0))
        return run if run else None

    def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        lim = int(limit) if isinstance(limit, int) else 50
        if lim < 1:
            lim = 1
        if lim > 200:
            lim = 200

        # Very simple: list run_start events and attach most recent finish metadata.
        all_events = self._read_all()
        starts = [e for e in all_events if e.get("type") == "run_start"]
        starts.sort(key=lambda x: str(x.get("started_at_iso") or ""), reverse=True)

        out: List[Dict[str, Any]] = []
        for e in starts[:lim]:
            run_id = str(e.get("run_id") or "")
            run = {k: v for k, v in e.items() if k != "type"}
            # attach finish if present
            for f in reversed(all_events):
                if f.get("type") == "run_finish" and f.get("run_id") == run_id:
                    run["finished_at_iso"] = f.get("finished_at_iso")
                    run["status"] = f.get("status")
                    run["error_message"] = f.get("error_message")
                    run["output_type"] = f.get("output_type")
                    run["grounded"] = f.get("grounded")
                    break
            out.append(run)
        return out

    def stats_summary(self, days: int = 7) -> Dict[str, Any]:
        # Minimal for JSONL; compute off recent runs.
        d = int(days) if isinstance(days, int) else 7
        if d < 1:
            d = 1
        if d > 90:
            d = 90

        runs = self.list_recent(limit=1000)
        total = len(runs)
        success = len([r for r in runs if r.get("status") == "success"])
        error = len([r for r in runs if r.get("status") == "error"])

        success_rate = (success / total) if total else 0.0
        error_rate = (error / total) if total else 0.0

        # Tool stats not supported without scanning all tool events; return empty.
        return {
            "total_runs": total,
            "success_rate": success_rate,
            "error_rate": error_rate,
            "top_tools": [],
            "avg_tool_latency_ms": 0.0,
            "runs_per_day": [],
        }


_STORE: Optional[RunsStore] = None
_STORE_LOCK = threading.Lock()


def get_store() -> RunsStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is not None:
            return _STORE
        p = _runs_path()
        if p.suffix.lower() == ".jsonl":
            _STORE = JSONLRunsStore(p)
        else:
            _STORE = SQLiteRunsStore(p)
        return _STORE


def new_run_id() -> str:
    return str(uuid.uuid4())


def start_run(*, user_id: str, input_summary: str) -> str:
    p = get_policy(refresh=True)
    run_id = new_run_id()
    record = RunRecord(
        run_id=run_id,
        started_at_iso=_now_iso(),
        finished_at_iso=None,
        user_id=user_id or "default",
        input_summary=(input_summary or "").strip()[:200],
        access_mode=str(p.access_mode),
        status="success",
        error_message=None,
        output_type=None,
        grounded=None,
    )
    get_store().start_run(record)
    return run_id


def append_tool_trace(run_id: str, entry: ToolTraceEntry) -> None:
    get_store().append_tool(run_id, entry)


def finish_run(
    run_id: str,
    *,
    status: RunStatus,
    error_message: Optional[str],
    output_type: Optional[OutputType],
    grounded: Optional[bool],
) -> None:
    get_store().finish_run(
        run_id,
        finished_at_iso=_now_iso(),
        status=status,
        error_message=redact_text(error_message) if error_message else None,
        output_type=output_type,
        grounded=grounded,
    )


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    r = get_store().get_run(run_id)
    if r is None:
        return None
    # Ensure no secrets leak even if old data was stored.
    if r.get("error_message"):
        r["error_message"] = redact_text(r.get("error_message"))
    if isinstance(r.get("tool_calls"), list):
        for t in r["tool_calls"]:
            if isinstance(t, dict):
                if t.get("args_summary"):
                    t["args_summary"] = redact_text(t.get("args_summary"), max_len=1200)
                if t.get("error"):
                    t["error"] = redact_text(t.get("error"), max_len=1200)
    return r


def list_recent(limit: int = 50) -> List[Dict[str, Any]]:
    rows = get_store().list_recent(limit=limit)
    out: List[Dict[str, Any]] = []
    for r in rows:
        if r.get("error_message"):
            r["error_message"] = redact_text(r.get("error_message"), max_len=1200)
        out.append(r)
    return out


def stats_summary(days: int = 7) -> Dict[str, Any]:
    return get_store().stats_summary(days=days)
