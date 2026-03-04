"""Pydantic models for the API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)


class ToolTraceItem(BaseModel):
    name: str
    arguments: Dict[str, Any]
    ok: bool
    error: Optional[str] = None


class ChatResponse(BaseModel):
    final_answer: str
    tool_trace: List[ToolTraceItem]
