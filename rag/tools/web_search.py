"""Web search tool stub."""

from __future__ import annotations

from typing import Any, Dict


def search_web(args: Dict[str, Any]) -> Dict[str, Any]:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `query`"}
    return {
        "ok": True,
        "data": {
            "results": [],
            "message": "search_web is a stub (not connected). Wire SerpAPI or another provider.",
        },
    }
