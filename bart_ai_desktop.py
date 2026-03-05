"""Bart AI desktop launcher.

This starts the local FastAPI backend and opens the React UI in a native desktop window.

Prereqs:
- Build the UI once: cd project && npm install && npm run build
- Install Python deps: pip install -e .

Run:
- python bart_ai_desktop.py
"""

from __future__ import annotations

import os
import platform
import socket
import threading
import time
import webbrowser
from pathlib import Path

import requests
import uvicorn
from dotenv import find_dotenv, load_dotenv


def _ensure_port_available(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))


def _wait_for_health(port: int, timeout_s: float = 10.0) -> bool:
    deadline = time.time() + timeout_s
    url = f"http://127.0.0.1:{port}/health"
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=1)
            if r.ok:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def main() -> None:
    load_dotenv(find_dotenv(".env"), override=False)

    # Filesystem tool access defaults.
    # - ACCESS_MODE=safe restricts access to WORKSPACE_ROOT (default ./rag/data).
    # - ACCESS_MODE=full_disk allows reading from the full machine (with a small denylist).
    # Users can override any of these via environment variables or .env.
    os.environ.setdefault("ACCESS_MODE", "full_disk")
    if platform.system().lower().startswith("win"):
        drive = (os.environ.get("SystemDrive") or "C:").rstrip("\\/")
        root = f"{drive}\\"
        os.environ.setdefault("WORKSPACE_ROOT", root)
        os.environ.setdefault("LOCAL_FS_ALLOWED_ROOTS", root)
    else:
        os.environ.setdefault("WORKSPACE_ROOT", "/")
        os.environ.setdefault("LOCAL_FS_ALLOWED_ROOTS", "/")

    repo_root = Path(__file__).resolve().parent
    ui_index = repo_root / "project" / "dist" / "index.html"
    if not ui_index.exists():
        raise SystemExit(
            "UI build not found. Run: cd project && npm install && npm run build"
        )

    port = int(os.environ.get("BART_AI_PORT", "8002"))
    try:
        _ensure_port_available(port)
    except OSError:
        raise SystemExit(
            f"Port {port} is already in use. Close the process using it and try again."
        )

    config = uvicorn.Config(
        "rag.api.main:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    if not _wait_for_health(port):
        server.should_exit = True
        raise SystemExit("Backend failed to start (health check timeout).")

    try:
        import webview  # pywebview
    except Exception as exc:
        server.should_exit = True
        raise SystemExit(
            f"pywebview is required for the desktop app. Install it with: pip install pywebview\n{exc}"
        )

    class _JsApi:
        def open_external(self, url: str) -> dict:
            try:
                ok = bool(webbrowser.open(url))
                return {"ok": ok}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    url = f"http://127.0.0.1:{port}/ui/"
    window = webview.create_window(
        "Bart AI",
        url,
        width=1200,
        height=800,
        js_api=_JsApi(),
    )

    def _on_closed() -> None:
        server.should_exit = True

    window.events.closed += _on_closed
    webview.start()


if __name__ == "__main__":
    main()
