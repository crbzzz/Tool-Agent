"""Local document search tool (FAISS if present; placeholder otherwise)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _index_dir() -> Path:
    return Path(os.environ.get("INDEX_DIR", "data/indexes/faiss")).resolve()


def search_documents(args: Dict[str, Any]) -> Dict[str, Any]:
    """Search local documents.

    If a FAISS index is not available (or not configured), returns an empty list with a message.
    This skeleton intentionally avoids assuming a specific index/docstore format.
    """

    # Remote agent configurations sometimes use `question` instead of `query`.
    query = args.get("query")
    if query is None:
        query = args.get("question")
    top_k = args.get("top_k", 5)
    if not isinstance(query, str) or not query.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `query`"}
    if not isinstance(top_k, int):
        return {"ok": False, "data": None, "error": "Invalid `top_k` (must be int)"}

    index_dir = _index_dir()
    if not index_dir.exists():
        return {
            "ok": True,
            "data": {"results": [], "message": f"No FAISS index dir found at {index_dir}"},
        }

    faiss_files = list(index_dir.glob("*.faiss"))
    if not faiss_files and (index_dir / "index.faiss").exists():
        faiss_files = [index_dir / "index.faiss"]

    if not faiss_files:
        return {
            "ok": True,
            "data": {"results": [], "message": f"No FAISS index found in {index_dir}"},
        }

    logger.info("FAISS index detected at %s, but no configured embedder/docstore. Returning empty results.", faiss_files[0])
    return {
        "ok": True,
        "data": {
            "results": [],
            "message": "FAISS index detected, but this skeleton does not include an embedding/docstore pipeline yet.",
        },
    }
