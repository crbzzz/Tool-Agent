"""Audio transcription via Mistral Voxtral.

The UI records short audio clips (webm/ogg) and uploads them to the backend.
The backend forwards them to Mistral's transcription API (Voxtral).

Model selection:
- `MISTRAL_VOXTRAL_MODEL` (default: "voxtral-small")
- If the configured model fails (typo / unavailable), we retry with safe fallbacks.
"""

from __future__ import annotations

import os
from typing import Optional


def _candidate_models(configured: str | None) -> list[str]:
    candidates: list[str] = []

    def add(m: str | None) -> None:
        if not m:
            return
        m2 = str(m).strip()
        if not m2:
            return
        if m2 not in candidates:
            candidates.append(m2)

    configured = (configured or "").strip() or None
    add(configured)

    # Common typo: "voxstral" vs "voxtral".
    if configured and "voxstral" in configured:
        add(configured.replace("voxstral", "voxtral"))

    # Known default.
    add("voxtral-small")

    return candidates


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

    configured_model = os.environ.get("MISTRAL_VOXTRAL_MODEL", "voxtral-small")
    models = _candidate_models(configured_model)

    try:
        from mistralai import Mistral  # type: ignore
        from mistralai.models.file import File  # type: ignore
    except Exception as exc:
        raise RuntimeError("mistralai SDK is required for Voxtral transcription") from exc

    client = Mistral(api_key=api_key)
    file = File(fileName=filename, content=audio_bytes, content_type=content_type)

    last_exc: Exception | None = None
    for model in models:
        try:
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
                    if isinstance(maybe_text, str) and maybe_text.strip():
                        return maybe_text

            # Last resort.
            rendered = str(resp).strip()
            if rendered:
                return rendered
        except Exception as exc:  # pragma: no cover
            last_exc = exc
            continue

    attempted = ", ".join(models)
    raise RuntimeError(
        f"Voxtral transcription failed (attempted models: {attempted}). Last error: {last_exc}"
    )
