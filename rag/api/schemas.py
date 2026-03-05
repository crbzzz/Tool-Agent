"""Pydantic models for the API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = Field(
        default=None,
        description="Optional session identifier to preserve conversation context across calls.",
    )


class ToolTraceItem(BaseModel):
    step_index: int
    tool_name: str
    args_summary: str
    started_at_iso: str
    finished_at_iso: str
    duration_ms: int
    ok: bool
    error: Optional[str] = None
    affected_items_count: Optional[int] = None


class ChatResponse(BaseModel):
    ok: bool = True
    run_id: str
    result: Dict[str, Any]
    tool_trace: List[ToolTraceItem]
    session_id: str | None = None
