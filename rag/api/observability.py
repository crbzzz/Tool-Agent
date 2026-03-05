from __future__ import annotations

from fastapi import APIRouter, HTTPException

from rag.state import runs

router = APIRouter(tags=["observability"])


@router.get("/runs/recent")
def runs_recent(limit: int = 50) -> dict:
    items = runs.list_recent(limit=limit)
    return {"ok": True, "runs": items}


@router.get("/runs/{run_id}")
def runs_get(run_id: str) -> dict:
    rid = (run_id or "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="Missing run_id")

    item = runs.get_run(rid)
    if item is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return {"ok": True, "run": item}


@router.get("/stats/summary")
def stats_summary(days: int = 7) -> dict:
    stats = runs.stats_summary(days=days)
    return {"ok": True, "stats": stats}
