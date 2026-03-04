"""Compatibility entrypoint for `uvicorn api.main:app`."""

from __future__ import annotations

from rag.api.main import app  # noqa: F401
