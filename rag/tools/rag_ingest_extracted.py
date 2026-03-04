"""Ingest extracted text into a lightweight local store.

This repo's original `search_documents` is a skeleton without embeddings.
To keep the workflow usable, we implement a simple chunk store backed by JSONL.

- Ingestion requires explicit user_confirmation=true.
- Search can later read these chunks and do a basic term-frequency score.

This is intentionally simple (no FAISS/embeddings) to avoid heavy deps.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def _store_dir() -> Path:
    return Path(os.environ.get("EXTRACTED_STORE_DIR", "data/indexes/extracted")).resolve()


def _chunks_path() -> Path:
    return _store_dir() / "chunks.jsonl"


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> Iterable[str]:
    s = (text or "").strip()
    if not s:
        return []

    size = max(1, int(chunk_size))
    overlap = max(0, int(chunk_overlap))
    overlap = min(overlap, size - 1) if size > 1 else 0

    chunks: List[str] = []
    start = 0
    while start < len(s):
        end = min(len(s), start + size)
        chunks.append(s[start:end])
        if end >= len(s):
            break
        start = max(0, end - overlap)

    return chunks


def ingest_extracted(args: Dict[str, Any]) -> Dict[str, Any]:
    if args.get("user_confirmation") is not True:
        return {
            "ok": False,
            "data": None,
            "error": "Missing explicit user_confirmation=true",
        }

    source_name = args.get("source_name")
    text = args.get("text")
    if not isinstance(source_name, str) or not source_name.strip():
        return {"ok": False, "data": None, "error": "Invalid source_name"}
    if not isinstance(text, str) or not text.strip():
        return {"ok": False, "data": None, "error": "Invalid text"}

    chunk_size = args.get("chunk_size", 1200)
    chunk_overlap = args.get("chunk_overlap", 150)
    if not isinstance(chunk_size, int) or chunk_size < 200 or chunk_size > 5000:
        return {"ok": False, "data": None, "error": "Invalid chunk_size (200..5000)"}
    if not isinstance(chunk_overlap, int) or chunk_overlap < 0 or chunk_overlap > 1000:
        return {"ok": False, "data": None, "error": "Invalid chunk_overlap (0..1000)"}

    store_dir = _store_dir()
    store_dir.mkdir(parents=True, exist_ok=True)

    ts = int(time.time())
    doc_id = uuid.uuid4().hex

    chunks = list(_chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap))
    if not chunks:
        return {"ok": False, "data": None, "error": "Nothing to ingest after chunking"}

    out_path = _chunks_path()
    written = 0
    with out_path.open("a", encoding="utf-8") as f:
        for i, chunk in enumerate(chunks):
            rec = {
                "id": f"{doc_id}:{i}",
                "doc_id": doc_id,
                "source_name": source_name,
                "chunk_index": i,
                "text": chunk,
                "created_at_unix": ts,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1

    return {
        "ok": True,
        "data": {
            "store_dir": str(store_dir),
            "chunks_path": str(out_path),
            "doc_id": doc_id,
            "source_name": source_name,
            "chunks_written": written,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
        },
        "error": None,
    }


def _score_chunk(text: str, query_terms: List[str]) -> int:
    t = (text or "").lower()
    score = 0
    for term in query_terms:
        if not term:
            continue
        # Count occurrences (bounded-ish)
        score += t.count(term)
    return score


def simple_search(args: Dict[str, Any]) -> Dict[str, Any]:
    query = args.get("query")
    if query is None:
        query = args.get("question")
    top_k = args.get("top_k", 5)
    if not isinstance(query, str) or not query.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid `query`"}
    if not isinstance(top_k, int) or top_k < 1 or top_k > 50:
        return {"ok": False, "data": None, "error": "Invalid `top_k` (1..50)"}

    chunks_path = _chunks_path()
    if not chunks_path.exists():
        return {
            "ok": True,
            "data": {"results": [], "message": f"No extracted chunk store found at {chunks_path}"},
            "error": None,
        }

    terms = [t for t in query.lower().split() if len(t) >= 2]
    if not terms:
        return {"ok": True, "data": {"results": [], "message": "Query too short"}, "error": None}

    scored: List[Tuple[int, Dict[str, Any]]] = []
    with chunks_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            txt = (rec.get("text") or "")
            s = _score_chunk(txt, terms)
            if s <= 0:
                continue
            scored.append((s, rec))

    scored.sort(key=lambda x: x[0], reverse=True)
    results: List[Dict[str, Any]] = []
    for score, rec in scored[:top_k]:
        snippet = (rec.get("text") or "")
        if len(snippet) > 500:
            snippet = snippet[:500]
        results.append(
            {
                "score": score,
                "source_name": rec.get("source_name"),
                "id": rec.get("id"),
                "text": rec.get("text"),
                "snippet": snippet,
            }
        )

    return {"ok": True, "data": {"results": results, "message": "ok"}, "error": None}
