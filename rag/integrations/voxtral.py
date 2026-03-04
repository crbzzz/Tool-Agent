"""Audio transcription via Mistral Voxtral.

This module is intentionally small and dependency-light: it uses the official
`mistralai` SDK (already used elsewhere in the project) and exposes a single
function for audio -> text.
"""

from __future__ import annotations

import os
from typing import Optional


def transcribe_audio(
    *,
    audio_bytes: bytes,
    filename: str,
    content_type: Optional[str] = None,
    language: Optional[str] = None,
) -> str:
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set")

    model = os.environ.get("MISTRAL_VOXTRAL_MODEL", "voxtral-small")

    try:
        from mistralai import Mistral  # type: ignore
        from mistralai.models.file import File  # type: ignore
    except Exception as exc:
        raise RuntimeError("mistralai SDK is required for Voxtral transcription") from exc

    client = Mistral(api_key=api_key)
    file = File(fileName=filename, content=audio_bytes, content_type=content_type)

    kwargs = {}
    if language:
        kwargs["language"] = language

    resp = client.audio.transcriptions.complete(model=model, file=file, **kwargs)

    # SDK responses are pydantic models; best-effort extraction.
    text = getattr(resp, "text", None)
    if isinstance(text, str) and text.strip():
        return text

    dump = getattr(resp, "model_dump", None)
    if callable(dump):
        data = dump()
        if isinstance(data, dict):
            maybe_text = data.get("text") or data.get("transcription")
            if isinstance(maybe_text, str):
                return maybe_text

    return str(resp)
