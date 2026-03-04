"""FastAPI app exposing chat endpoint for the orchestrator."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from dotenv import find_dotenv, load_dotenv

from rag.api.deps import get_orchestrator
from rag.api.schemas import ChatRequest, ChatResponse
from rag.api.session_store import get_or_create_session, update_session


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)

# Load local .env (if present) for all endpoints, including OAuth routes.
load_dotenv(find_dotenv(".env"), override=False)

app = FastAPI(title="Tool-Agent API", version="0.1.0")


def _mount_ui_if_present(app: FastAPI) -> None:
    """Mount the built desktop UI (Vite dist) if available."""

    # rag/api/main.py -> rag/ -> repo root
    repo_root = Path(__file__).resolve().parents[2]
    dist_dir = repo_root / "project" / "dist"
    index_html = dist_dir / "index.html"
    if index_html.exists() and dist_dir.is_dir():
        app.mount("/ui", StaticFiles(directory=str(dist_dir), html=True), name="ui")


_mount_ui_if_present(app)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/tools")
def tools() -> dict:
    """Debug endpoint: list tool names available to the orchestrator."""

    orch = get_orchestrator()
    names = sorted(list(getattr(orch.registry, "tools", {}).keys()))
    return {"ok": True, "tools": names}


@app.get("/oauth/google/status")
def google_oauth_status() -> dict:
    from rag.integrations.google_oauth import is_connected

    return {"ok": True, "connected": bool(is_connected())}


@app.get("/oauth/google/start")
def google_oauth_start() -> RedirectResponse:
    from rag.integrations.google_oauth import oauth_prepare

    try:
        url, _state = oauth_prepare()
        return RedirectResponse(url=url)
    except Exception as exc:
        logging.exception("Google OAuth start failed")
        raise HTTPException(
            status_code=500,
            detail=(
                f"Google OAuth is not configured correctly: {exc}. "
                "Check GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET/GOOGLE_REDIRECT_URI."
            ),
        )


@app.get("/oauth/google/callback")
def google_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> dict:
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing `code` query parameter")

    from rag.integrations.google_oauth import oauth_exchange_code

    try:
        oauth_exchange_code(code, state=state)
        return {"ok": True, "connected": True}
    except Exception as exc:
        logging.exception("Google OAuth callback failed")
        raise HTTPException(status_code=500, detail=f"OAuth token exchange failed: {exc}")


@app.post("/oauth/google/logout")
def google_oauth_logout() -> dict:
    from rag.integrations.google_oauth import delete_credentials

    delete_credentials()
    return {"ok": True}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        orch = get_orchestrator()
        session_id = req.session_id or uuid.uuid4().hex
        session = get_or_create_session(session_id)

        # Append this user turn and run the orchestrator with the session history.
        session.messages.append({"role": "user", "content": req.message})
        result, updated_messages = orch.run_with_messages(session.messages)
        update_session(session_id, updated_messages)

        return ChatResponse(
            final_answer=result.final_answer,
            tool_trace=result.tool_trace,
            session_id=session_id,
        )
    except Exception as exc:
        logging.exception("/chat failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/voice/transcribe")
async def voice_transcribe(
    file: UploadFile = File(...),
    language: str | None = Form(None),
) -> dict:
    """Transcribe uploaded audio with Mistral Voxtral.

    Returns: { ok: true, text: "..." }
    """

    no_audio_detail = (
        "No audio detected. Please select an input device in Settings and try again."
    )

    try:
        audio_bytes = await file.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio file")

        logging.info(
            "voice_transcribe: filename=%s content_type=%s bytes=%d language=%s",
            file.filename,
            file.content_type,
            len(audio_bytes),
            language,
        )

        min_bytes = int(os.environ.get("BART_AI_MIN_AUDIO_BYTES", "2048"))
        if len(audio_bytes) < min_bytes:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Audio too short/quiet (got {len(audio_bytes)} bytes; min {min_bytes}). "
                    "Check microphone permission, selected input device, and record a bit longer."
                ),
            )

        if language is None:
            language = (os.environ.get("MISTRAL_VOXTRAL_LANGUAGE") or "").strip() or None

        disable_vad = (os.environ.get("BART_AI_DISABLE_VAD") or "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if not disable_vad:
            from rag.integrations.audio_vad import detect_speech

            vad = detect_speech(
                audio_bytes=audio_bytes,
                filename=file.filename or "audio.webm",
                content_type=file.content_type,
            )
            logging.info(
                "voice_transcribe: vad has_speech=%s reason=%s dbfs=%s analyzed_s=%s speech_ms=%s ratio=%s",
                vad.has_speech,
                vad.reason,
                (None if vad.dbfs is None else round(vad.dbfs, 1)),
                (None if vad.analyzed_seconds is None else round(vad.analyzed_seconds, 2)),
                vad.speech_ms,
                (None if vad.speech_ratio is None else round(vad.speech_ratio, 3)),
            )
            if not vad.has_speech:
                raise HTTPException(
                    status_code=422,
                    detail=no_audio_detail,
                )

        from rag.integrations.voxtral import transcribe_audio

        text = transcribe_audio(
            audio_bytes=audio_bytes,
            filename=file.filename or "audio.webm",
            content_type=file.content_type,
            language=language,
        )
        if not (text or "").strip():
            raise HTTPException(status_code=422, detail=no_audio_detail)
        return {"ok": True, "text": text}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("/voice/transcribe failed")
        raise HTTPException(status_code=500, detail=str(exc))
