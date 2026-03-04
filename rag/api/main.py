"""FastAPI app exposing chat endpoint for the orchestrator."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

from dotenv import find_dotenv, load_dotenv

from rag.api.deps import get_orchestrator
from rag.api.schemas import ChatRequest, ChatResponse


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)

# Load local .env (if present) for all endpoints, including OAuth routes.
load_dotenv(find_dotenv(".env"), override=False)

app = FastAPI(title="Tool-Agent API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


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
        result = orch.run(req.message)
        return ChatResponse(final_answer=result.final_answer, tool_trace=result.tool_trace)
    except Exception as exc:
        logging.exception("/chat failed")
        raise HTTPException(status_code=500, detail=str(exc))
