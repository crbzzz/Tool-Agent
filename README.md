# Tool-Agent

Production-minded Mistral Agents orchestrator with tool-calling for a RAG project.

## Setup

1) Create a `.env` from the example:

```bash
copy .env.example .env
```

2) Fill in:

- `MISTRAL_API_KEY`
- `MISTRAL_AGENT_ID` (example: `ag_019cb5ef077f777a9dcf3d569eXXXXX`)
- `INDEX_DIR` (optional, defaults to `data/indexes/faiss`)

3) Install:

```bash
pip install -e .
```

## Run API

```bash
uvicorn api.main:app --reload
```

## Desktop UI (optional)

Start the API first, then run:

```bash
python desktop_app.py
```

## Google OAuth (Gmail/Drive)

This project includes a minimal local OAuth flow to connect Gmail + Drive tools.

1) In Google Cloud Console:
- Create a project
- Configure **OAuth consent screen** (External is fine for local testing)
- Create **OAuth Client ID** (Application type: Desktop app or Web application)
- Add an **Authorized redirect URI**:
	- `http://127.0.0.1:8000/oauth/google/callback`

2) Put these in your `.env` (see `.env.example`):
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI` (must match exactly)

3) Start the API:

```bash
uvicorn api.main:app --reload
```

4) Open in a browser:
- `http://127.0.0.1:8000/oauth/google/start`

5) Check status:
- `http://127.0.0.1:8000/oauth/google/status`

Logout (delete local token):

```bash
curl.exe -X POST http://127.0.0.1:8000/oauth/google/logout
```

## Try `/chat`

```bash
curl.exe -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" --data-binary "{`"message`":`"Search my docs for onboarding notes and summarize`"}"
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Notes

- Web search + Google (Gmail/Drive) tools are stubs by default.
- `send_email` is blocked unless `user_confirmation=true`.
- `search_documents` returns an empty result if no FAISS index is present.

