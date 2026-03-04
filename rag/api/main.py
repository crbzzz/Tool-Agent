"""FastAPI app exposing chat endpoint for the orchestrator."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from urllib.parse import urlencode

import requests
from json import JSONDecodeError

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

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

app = FastAPI(title="Bart AI API", version="0.1.0")


class _ClientIdCookieMiddleware(BaseHTTPMiddleware):
    """Ensure the embedded UI keeps a stable client_id cookie.

    We use this to associate a Supabase session with the desktop app webview.
    """

    COOKIE_NAME = "bart_ai_client_id"

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if self.COOKIE_NAME not in request.cookies:
            from rag.api.auth_store import new_client_id

            cid = new_client_id()
            response.set_cookie(
                self.COOKIE_NAME,
                cid,
                httponly=True,
                samesite="lax",
            )
        return response


app.add_middleware(_ClientIdCookieMiddleware)


def _uploads_dir() -> Path:
    # rag/api/main.py -> rag/ -> repo root
    repo_root = Path(__file__).resolve().parents[2]
    up = repo_root / "rag" / "data" / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    return up


def _mount_ui_if_present(app: FastAPI) -> None:
    """Mount the built desktop UI (Vite dist) if available.

    This keeps the project as an application: the desktop launcher opens this UI
    inside a local webview. The UI build output is not required for API-only usage.
    """

    # rag/api/main.py -> rag/ -> repo root
    repo_root = Path(__file__).resolve().parents[2]
    dist_dir = repo_root / "project" / "dist"
    index_html = dist_dir / "index.html"
    if index_html.exists() and dist_dir.is_dir():
        app.mount("/ui", StaticFiles(directory=str(dist_dir), html=True), name="ui")


_mount_ui_if_present(app)


def _mount_ui_if_present(app: FastAPI) -> None:
    """Mount the built desktop UI (Vite dist) if available."""

    # rag/api/main.py -> rag/ -> repo root
    repo_root = Path(__file__).resolve().parents[2]
    dist_dir = repo_root / "project" / "dist"
    index_html = dist_dir / "index.html"
    if index_html.exists() and dist_dir.is_dir():
        app.mount("/ui", StaticFiles(directory=str(dist_dir), html=True), name="ui")


_mount_ui_if_present(app)


def _client_id_from_request(request: Request) -> str:
    return (request.cookies.get(_ClientIdCookieMiddleware.COOKIE_NAME) or "").strip()


def _supabase_client():
    from rag.integrations.supabase_auth import SupabaseAuthClient, load_supabase_config

    try:
        cfg = load_supabase_config()
        return SupabaseAuthClient(cfg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _require_auth_session(request: Request):
    from rag.api.auth_store import get_client_session

    client_id = _client_id_from_request(request)
    if not client_id:
        raise HTTPException(status_code=401, detail="Not signed in")
    s = get_client_session(client_id)
    if not s or not s.access_token or not s.user:
        raise HTTPException(status_code=401, detail="Not signed in")
    return s


def _supabase_rest():
    from rag.integrations.supabase_auth import load_supabase_config
    from rag.integrations.supabase_rest import SupabaseRestClient

    try:
        cfg = load_supabase_config()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return SupabaseRestClient(cfg)


def _safe_title(text: str, max_len: int = 80) -> str:
    t = (text or "").strip().replace("\n", " ")
    if not t:
        return "New chat"
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def _callback_url(request: Request, poll_token: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/auth/oauth/callback?{urlencode({'poll_token': poll_token})}"


async def _read_json(request: Request) -> dict:
    try:
        payload = await request.json()
    except JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON")
    return payload


@app.get("/auth/status")
def auth_status(request: Request) -> dict:
    """Return current signed-in user (if any) for this desktop client."""

    from rag.api.auth_store import get_client_session

    client_id = _client_id_from_request(request)
    if not client_id:
        return {"ok": True, "signed_in": False, "user": None}

    s = get_client_session(client_id)
    if not s or not s.access_token:
        return {"ok": True, "signed_in": False, "user": None}

    return {"ok": True, "signed_in": True, "user": (s.user or None)}


@app.get("/chats")
def chats_list(request: Request) -> dict:
    """List chats for the signed-in user."""

    s = _require_auth_session(request)
    rest = _supabase_rest()
    try:
        rows = rest.request(
            "GET",
            "chats",
            s.access_token,
            params={
                "select": "id,title,created_at,updated_at",
                "order": "updated_at.desc",
            },
        )
        return {"ok": True, "chats": rows or []}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/chats")
async def chats_create(request: Request) -> dict:
    """Create an empty chat."""

    s = _require_auth_session(request)
    payload = {}
    try:
        payload = await _read_json(request)
    except HTTPException:
        # allow empty body
        payload = {}

    title = payload.get("title") if isinstance(payload, dict) else None
    if title is not None and not isinstance(title, str):
        raise HTTPException(status_code=400, detail="Invalid title")

    chat_id = uuid.uuid4().hex
    rest = _supabase_rest()
    user_id = (s.user or {}).get("id")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Not signed in")

    body = {"id": chat_id, "user_id": user_id, "title": (title or None)}
    try:
        rows = rest.request(
            "POST",
            "chats",
            s.access_token,
            json_body=body,
            prefer="return=representation",
        )
        chat = (rows or [{}])[0]
        return {"ok": True, "chat": chat}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.patch("/chats/{chat_id}")
async def chats_rename(chat_id: str, request: Request) -> dict:
    """Rename a chat (update its title)."""

    s = _require_auth_session(request)
    payload = await _read_json(request)
    title = payload.get("title")
    if title is None:
        raise HTTPException(status_code=400, detail="Missing title")
    if not isinstance(title, str):
        raise HTTPException(status_code=400, detail="Invalid title")

    title = title.strip()
    rest = _supabase_rest()
    try:
        rows = rest.request(
            "PATCH",
            "chats",
            s.access_token,
            params={"id": f"eq.{chat_id}"},
            json_body={"title": (title or None)},
            prefer="return=representation",
        )
        chat = (rows or [{}])[0]
        return {"ok": True, "chat": chat}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/chats/{chat_id}")
def chats_delete(chat_id: str, request: Request) -> dict:
    """Delete a chat (and cascade-delete its messages)."""

    s = _require_auth_session(request)
    rest = _supabase_rest()
    try:
        rest.request(
            "DELETE",
            "chats",
            s.access_token,
            params={"id": f"eq.{chat_id}"},
        )
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/chats/{chat_id}/messages")
def chats_messages(chat_id: str, request: Request) -> dict:
    """List messages for a chat."""

    s = _require_auth_session(request)
    rest = _supabase_rest()
    try:
        rows = rest.request(
            "GET",
            "chat_messages",
            s.access_token,
            params={
                "select": "id,chat_id,role,content,created_at",
                "chat_id": f"eq.{chat_id}",
                "order": "created_at.asc",
            },
        )
        return {"ok": True, "messages": rows or []}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/auth/login")
async def auth_login(request: Request) -> dict:
    payload = await _read_json(request)
    email = (payload.get("email") or "").strip()
    password = (payload.get("password") or "").strip()
    if not email or not password:
        raise HTTPException(status_code=400, detail="Missing email/password")

    client = _supabase_client()
    try:
        data = client.sign_in_password(email=email, password=password)
        access_token = (data.get("access_token") or "").strip()
        if not access_token:
            raise HTTPException(status_code=401, detail="Login failed")

        user = None
        try:
            user = client.get_user(access_token)
        except Exception:
            user = data.get("user")

        from rag.api.auth_store import AuthSession, set_client_session

        client_id = _client_id_from_request(request)
        if not client_id:
            raise HTTPException(status_code=400, detail="Missing client session")
        set_client_session(
            client_id,
            AuthSession(
                access_token=access_token,
                refresh_token=data.get("refresh_token"),
                expires_at=data.get("expires_at"),
                user=user,
                updated_ts=0.0,
            ),
        )
        return {"ok": True, "user": user}
    except requests.HTTPError as exc:  # type: ignore[name-defined]
        msg = getattr(exc.response, "text", None) or str(exc)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/auth/signup")
async def auth_signup(request: Request) -> dict:
    payload = await _read_json(request)
    email = (payload.get("email") or "").strip()
    password = (payload.get("password") or "").strip()
    if not email or not password:
        raise HTTPException(status_code=400, detail="Missing email/password")

    client = _supabase_client()
    try:
        data = client.sign_up(email=email, password=password)

        # Depending on project settings, Supabase may return a session or require email confirmation.
        access_token = (data.get("access_token") or "").strip()
        user = data.get("user")
        if access_token:
            try:
                user = client.get_user(access_token)
            except Exception:
                pass

            from rag.api.auth_store import AuthSession, set_client_session

            client_id = _client_id_from_request(request)
            if not client_id:
                raise HTTPException(status_code=400, detail="Missing client session")
            set_client_session(
                client_id,
                AuthSession(
                    access_token=access_token,
                    refresh_token=data.get("refresh_token"),
                    expires_at=data.get("expires_at"),
                    user=user,
                    updated_ts=0.0,
                ),
            )

        return {
            "ok": True,
            "user": user,
            "needs_email_confirmation": bool(not access_token),
        }
    except requests.HTTPError as exc:  # type: ignore[name-defined]
        msg = getattr(exc.response, "text", None) or str(exc)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/auth/logout")
async def auth_logout(request: Request) -> dict:
    from rag.api.auth_store import clear_client_session, get_client_session

    client_id = _client_id_from_request(request)
    if not client_id:
        return {"ok": True}

    s = get_client_session(client_id)
    if s and s.access_token:
        try:
            _supabase_client().logout(s.access_token)
        except Exception:
            pass
    clear_client_session(client_id)
    return {"ok": True}


@app.post("/auth/oauth/google/start")
async def supabase_google_oauth_start(request: Request) -> dict:
    """Start Google OAuth with Supabase in the system browser.

    Returns { auth_url, poll_token }. The UI should open auth_url externally,
    then poll /auth/oauth/poll and finally call /auth/oauth/consume.
    """

    payload = await _read_json(request)
    mode = (payload.get("mode") or "signin").strip().lower()
    if mode not in ("signin", "link"):
        raise HTTPException(status_code=400, detail="Invalid mode")

    from rag.api.auth_store import create_pending_oauth, get_client_session
    from rag.integrations.supabase_auth import generate_code_verifier, code_challenge_s256

    client = _supabase_client()
    verifier = generate_code_verifier()
    poll_token = create_pending_oauth(kind=mode, code_verifier=verifier)
    redirect_to = _callback_url(request, poll_token)

    if mode == "signin":
        challenge = code_challenge_s256(verifier)
        auth_url = client.build_authorize_url(
            provider="google",
            redirect_to=redirect_to,
            code_challenge=challenge,
            code_challenge_method="s256",
        )
        return {"ok": True, "auth_url": auth_url, "poll_token": poll_token}

    # mode == link
    client_id = _client_id_from_request(request)
    if not client_id:
        raise HTTPException(status_code=400, detail="Missing client session")
    s = get_client_session(client_id)
    if not s or not s.access_token:
        raise HTTPException(status_code=401, detail="Not signed in")

    challenge = code_challenge_s256(verifier)
    data = client.identities_authorize(
        access_token=s.access_token,
        provider="google",
        redirect_to=redirect_to,
        code_challenge=challenge,
        code_challenge_method="s256",
    )
    url = data.get("url")
    if not isinstance(url, str) or not url:
        raise HTTPException(status_code=500, detail="Supabase did not return an authorize URL")
    return {"ok": True, "auth_url": url, "poll_token": poll_token}


@app.get("/auth/oauth/callback", response_class=HTMLResponse)
def supabase_oauth_callback(
    request: Request,
    poll_token: str | None = None,
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> HTMLResponse:
    from rag.api.auth_store import get_pending_oauth, set_oauth_result, AuthSession

    token = (poll_token or "").strip()
    if not token:
        return HTMLResponse("Missing poll_token", status_code=400)

    pending = get_pending_oauth(token)
    if pending is None:
        return HTMLResponse("This login link has expired. Please restart from the app.", status_code=400)

    if error:
        set_oauth_result(token, session=None, error=(error_description or error))
        return HTMLResponse(
            """<!doctype html><html><body style="font-family: system-ui; padding: 24px;">
<h2>Connexion échouée</h2>
<p>Tu peux fermer cet onglet et réessayer depuis Bart AI.</p>
</body></html>""",
            status_code=200,
        )

    if not code:
        set_oauth_result(token, session=None, error="Missing code")
        return HTMLResponse("Missing code", status_code=400)

    try:
        client = _supabase_client()
        data = client.exchange_code_for_session(code=code, code_verifier=pending.code_verifier)
        access_token = (data.get("access_token") or "").strip()
        if not access_token:
            raise RuntimeError("Missing access_token")

        user = None
        try:
            user = client.get_user(access_token)
        except Exception:
            user = data.get("user")

        s = AuthSession(
            access_token=access_token,
            refresh_token=data.get("refresh_token"),
            expires_at=data.get("expires_at"),
            user=user,
            updated_ts=0.0,
        )
        set_oauth_result(token, session=s, error=None)
        return HTMLResponse(
            """<!doctype html><html><body style="font-family: system-ui; padding: 24px;">
<h2>Connecté</h2>
<p>Tu peux fermer cet onglet et revenir dans Bart AI.</p>
</body></html>""",
            status_code=200,
        )
    except Exception as exc:
        set_oauth_result(token, session=None, error=str(exc))
        return HTMLResponse(
            """<!doctype html><html><body style="font-family: system-ui; padding: 24px;">
<h2>Connexion échouée</h2>
<p>Tu peux fermer cet onglet et réessayer depuis Bart AI.</p>
</body></html>""",
            status_code=200,
        )


@app.get("/auth/oauth/poll")
def supabase_oauth_poll(poll_token: str) -> dict:
    from rag.api.auth_store import get_pending_oauth

    token = (poll_token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Missing poll_token")

    entry = get_pending_oauth(token)
    if entry is None:
        return {"ok": True, "status": "expired"}
    if entry.error:
        return {"ok": True, "status": "error", "error": entry.error}
    if entry.session is not None:
        return {"ok": True, "status": "done", "user": entry.session.user}
    return {"ok": True, "status": "pending"}


@app.post("/auth/oauth/consume")
async def supabase_oauth_consume(request: Request) -> dict:
    from rag.api.auth_store import consume_oauth_result, set_client_session

    payload = await _read_json(request)
    token = (payload.get("poll_token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Missing poll_token")

    entry = consume_oauth_result(token)
    if entry is None:
        raise HTTPException(status_code=400, detail="Expired poll_token")
    if entry.error:
        raise HTTPException(status_code=400, detail=entry.error)
    if entry.session is None:
        raise HTTPException(status_code=400, detail="No session")

    client_id = _client_id_from_request(request)
    if not client_id:
        raise HTTPException(status_code=400, detail="Missing client session")
    set_client_session(client_id, entry.session)
    return {"ok": True, "user": entry.session.user}


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
def google_oauth_start(return_to: str | None = None) -> RedirectResponse:
    from rag.integrations.google_oauth import oauth_prepare

    # Avoid open redirects: only allow local relative paths.
    if return_to:
        rt = return_to.strip()
        if not rt.startswith("/") or rt.startswith("//") or "://" in rt:
            raise HTTPException(status_code=400, detail="Invalid return_to")
        return_to = rt

    try:
        url, _state = oauth_prepare(return_to=return_to)
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

    from rag.integrations.google_oauth import oauth_exchange_code, pop_state

    try:
        verifier = None
        return_to = None
        if state:
            entry = pop_state(state)
            if entry:
                verifier = entry.get("verifier")
                return_to = entry.get("return_to")

        if not verifier:
            raise HTTPException(
                status_code=400,
                detail=(
                    "OAuth token exchange failed: missing PKCE code verifier. "
                    "Please restart the Google connection from Settings."
                ),
            )

        oauth_exchange_code(code, verifier=verifier)

        if isinstance(return_to, str) and return_to:
            return RedirectResponse(url=return_to)

        return {"ok": True, "connected": True}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Google OAuth callback failed")
        msg = str(exc)
        if "Scope has changed" in msg:
            try:
                from rag.integrations.google_oauth import delete_credentials

                delete_credentials()
            except Exception:
                pass
            raise HTTPException(
                status_code=400,
                detail=(
                    f"OAuth token exchange failed: {msg}. "
                    "Les permissions Google demandées ont changé; reconnecte Google depuis Settings."
                ),
            )
        if "invalid_grant" in msg or "Token endpoint" in msg:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"OAuth token exchange failed: {msg}. "
                    "Please restart the Google connection from Settings (don’t reuse an old callback URL)."
                ),
            )
        raise HTTPException(status_code=500, detail=f"OAuth token exchange failed: {msg}")


@app.get("/oauth/google/connected", response_class=HTMLResponse)
def google_oauth_connected() -> HTMLResponse:
        return HTMLResponse(
                """<!doctype html>
<html lang=\"en\">
    <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
        <title>Bart AI - Google Connected</title>
    </head>
    <body style=\"font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 24px;\">
        <h2>Google connecté</h2>
        <p>Tu peux fermer cet onglet et revenir dans l’application Bart AI.</p>
    </body>
</html>""",
                status_code=200,
        )


@app.post("/oauth/google/logout")
def google_oauth_logout() -> dict:
    from rag.integrations.google_oauth import delete_credentials

    delete_credentials()
    return {"ok": True}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request) -> ChatResponse:
    try:
        # Require a signed-in user: chat history is backed up per user.
        auth_session = _require_auth_session(request)
        user_id = (auth_session.user or {}).get("id")
        if not isinstance(user_id, str) or not user_id:
            raise HTTPException(status_code=401, detail="Not signed in")

        orch = get_orchestrator()
        session_id = req.session_id or uuid.uuid4().hex
        session = get_or_create_session(session_id)

        # Append this user turn and run the orchestrator with the session history.
        session.messages.append({"role": "user", "content": req.message})
        result, updated_messages = orch.run_with_messages(session.messages)
        update_session(session_id, updated_messages)

        # Persist this turn (best-effort). The session_id doubles as chat_id.
        try:
            rest = _supabase_rest()

            # Ensure chat exists (idempotent upsert).
            title = _safe_title(req.message)
            rest.request(
                "POST",
                "chats",
                auth_session.access_token,
                params={"on_conflict": "id"},
                json_body={"id": session_id, "user_id": user_id, "title": title},
                prefer="return=representation,resolution=ignore-duplicates",
            )

            # Insert user + assistant messages.
            rest.request(
                "POST",
                "chat_messages",
                auth_session.access_token,
                json_body=[
                    {"chat_id": session_id, "user_id": user_id, "role": "user", "content": req.message},
                    {"chat_id": session_id, "user_id": user_id, "role": "assistant", "content": result.final_answer},
                ],
                prefer="return=minimal",
            )
        except Exception:
            logging.exception("Failed to persist chat turn")

        return ChatResponse(
            final_answer=result.final_answer,
            tool_trace=result.tool_trace,
            session_id=session_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("/chat failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/documents/upload")
async def documents_upload(file: UploadFile = File(...)) -> dict:
    """Upload a user-provided document for later extraction by doc_* tools.

    The file is stored under rag/data/uploads so it remains readable in ACCESS_MODE=safe
    with the default WORKSPACE_ROOT.

    Returns: { ok: true, data: { path, original_name, size_bytes, content_type } }
    """

    try:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty file")

        uploads_dir = _uploads_dir()
        suffix = ""
        try:
            # Keep extension if present in the filename
            suffix = Path(file.filename or "").suffix
        except Exception:
            suffix = ""

        safe_name = (Path(file.filename or "uploaded").name or "uploaded")
        # Prefix with uuid to avoid collisions
        out_name = f"{uuid.uuid4().hex}_{safe_name}"
        out_path = uploads_dir / out_name
        out_path.write_bytes(data)

        return {
            "ok": True,
            "data": {
                "path": str(out_path.resolve()),
                "original_name": safe_name,
                "size_bytes": len(data),
                "content_type": file.content_type,
            },
            "error": None,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("/documents/upload failed")
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
