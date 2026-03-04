# Bart AI (Tool-Agent)

Production-minded Mistral Agents orchestrator with tool-calling for a RAG project.

The primary interface is a desktop app window (Bart AI) that embeds the React UI.

## Setup

1) Create a `.env` from the example:

```bash
copy .env.example .env
```

2) Fill in:

- `MISTRAL_API_KEY`
- `MISTRAL_AGENT_ID` (example: `ag_019cb5ef077fXXXXXXXXXXXX`)
- `INDEX_DIR` (optional, defaults to `data/indexes/faiss`)

3) Install:

```bash
pip install -e .
```

## Run API

```bash
uvicorn api.main:app --reload --port 8002
```

## Desktop App (Bart AI)

1) Build the UI once:

```bash
cd project
npm install
npm run build
```

2) Install Python deps:

```bash
pip install -e .
```

3) Launch Bart AI:

```bash
python bart_ai_desktop.py
```

## Legacy Desktop UI (Tkinter)

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
	- `http://127.0.0.1:8002/oauth/google/callback`

2) Put these in your `.env` (see `.env.example`):
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI` (must match exactly)

3) Start the API:

```bash
uvicorn api.main:app --reload --port 8002
```

4) Open in a browser:
- `http://127.0.0.1:8002/oauth/google/start`

5) Check status:
- `http://127.0.0.1:8002/oauth/google/status`

Logout (delete local token):

```bash
curl.exe -X POST http://127.0.0.1:8002/oauth/google/logout
```

## Try `/chat`

```bash
curl.exe -X POST http://127.0.0.1:8002/chat -H "Content-Type: application/json" --data-binary "{`"message`":`"Search my docs for onboarding notes and summarize`"}"
```

### Sessions (memory)

`/chat` supports an optional `session_id` to preserve context between calls.

- If you omit it, the server returns a new `session_id`.
- Send it back on subsequent calls to keep conversation history.

Health check:

```bash
curl http://127.0.0.1:8002/health
```

## Local filesystem access (Windows)

This project includes **local filesystem tools** for listing/reading files. These are powerful and can be risky.

### fs_* tools access mode

The agent may call `fs_list_dir`, `fs_search_files`, `fs_read_file`, etc. Access is controlled by:

```dotenv
ACCESS_MODE=safe
WORKSPACE_ROOT=./rag/data
FS_DENYLIST=
```

- `ACCESS_MODE=safe`: only paths under `WORKSPACE_ROOT` are allowed.
- `ACCESS_MODE=full_disk`: allows most paths, but blocks obvious secrets (e.g. `.ssh`, `.env`, keys) and anything in `FS_DENYLIST`.

### Limited mode (recommended)

By default, the agent can only access files under allowlisted roots. Configure in your `.env`:

```dotenv
LOCAL_FS_ALLOWED_ROOTS=C:\\Users\\<you>\\Documents;C:\\Users\\<you>\\Desktop
LOCAL_FS_MAX_READ_BYTES=200000
LOCAL_FS_ENABLE_DESTRUCTIVE=false
```

### Destructive actions (write/delete)

Write/delete tools are **disabled by default**. To enable them:

```dotenv
LOCAL_FS_ENABLE_DESTRUCTIVE=true
```

They still require `user_confirmation=true` in tool arguments.

### Admin mode (optional)

If you need access to protected locations, you generally must **run the API as Administrator**.
One pragmatic approach is to run two servers:

- Normal server (limited): `http://127.0.0.1:8000`
- Admin server (elevated): `http://127.0.0.1:8001`

Start the admin server by opening **PowerShell as Administrator** and running:

```bash
uvicorn api.main:app --reload --port 8001
```

## Notes

- Web search + Google (Gmail/Drive) tools are stubs by default.
- `send_email` is blocked unless `user_confirmation=true`.
- `search_documents` returns an empty result if no FAISS index is present.

