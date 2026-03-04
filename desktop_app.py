"""Minimal desktop UI (Tkinter) for the Tool-Agent FastAPI `/chat` endpoint.

Run the API first:
  uvicorn api.main:app --reload

Then run:
  python desktop_app.py
"""

from __future__ import annotations

import json
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import ttk

import requests


DEFAULT_API_URL = "http://127.0.0.1:8000"


class DesktopApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Tool-Agent Desktop")
        self.root.geometry("900x650")

        self.api_url_var = tk.StringVar(value=DEFAULT_API_URL)
        self.status_var = tk.StringVar(value="Ready")

        top = ttk.Frame(root, padding=10)
        top.pack(fill=tk.X)

        ttk.Label(top, text="API URL").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.api_url_var, width=45).pack(side=tk.LEFT, padx=(6, 12))
        ttk.Button(top, text="Health", command=self.on_health).pack(side=tk.LEFT)
        ttk.Button(top, text="Connect Google", command=self.on_connect_google).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(top, text="OAuth Status", command=self.on_oauth_status).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(top, textvariable=self.status_var).pack(side=tk.RIGHT)

        mid = ttk.Frame(root, padding=(10, 0, 10, 10))
        mid.pack(fill=tk.X)

        ttk.Label(mid, text="Message").pack(anchor=tk.W)
        self.msg_text = tk.Text(mid, height=4, wrap=tk.WORD)
        self.msg_text.pack(fill=tk.X)
        self.msg_text.insert("1.0", "hello")

        btns = ttk.Frame(root, padding=(10, 0, 10, 10))
        btns.pack(fill=tk.X)
        self.send_btn = ttk.Button(btns, text="Send", command=self.on_send)
        self.send_btn.pack(side=tk.LEFT)
        ttk.Button(btns, text="Clear", command=self.on_clear).pack(side=tk.LEFT, padx=8)

        paned = ttk.PanedWindow(root, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        resp_frame = ttk.Labelframe(paned, text="Assistant Answer")
        self.resp_text = tk.Text(resp_frame, height=14, wrap=tk.WORD)
        self.resp_text.pack(fill=tk.BOTH, expand=True)
        paned.add(resp_frame, weight=2)

        trace_frame = ttk.Labelframe(paned, text="Tool Trace")
        self.trace_text = tk.Text(trace_frame, height=10, wrap=tk.NONE)
        self.trace_text.pack(fill=tk.BOTH, expand=True)
        paned.add(trace_frame, weight=1)

        self.root.bind("<Control-Return>", lambda _e: self.on_send())

        # Auto-load OAuth status
        self.on_oauth_status()

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)
        self.root.update_idletasks()

    def _api(self) -> str:
        return self.api_url_var.get().strip().rstrip("/")

    def on_clear(self) -> None:
        self.resp_text.delete("1.0", tk.END)
        self.trace_text.delete("1.0", tk.END)
        self._set_status("Ready")

    def on_health(self) -> None:
        def work() -> None:
            self._set_status("Checking health...")
            try:
                r = requests.get(f"{self._api()}/health", timeout=5)
                self._set_status(f"Health: {r.status_code}")
            except Exception as exc:
                self._set_status(f"Health error: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def on_oauth_status(self) -> None:
        def work() -> None:
            self._set_status("Checking OAuth...")
            try:
                r = requests.get(f"{self._api()}/oauth/google/status", timeout=5)
                if r.status_code != 200:
                    self._set_status(f"OAuth status HTTP {r.status_code}")
                    return
                payload = r.json()
                connected = bool(payload.get("connected"))
                self._set_status("OAuth: connected" if connected else "OAuth: not connected")
            except Exception as exc:
                self._set_status(f"OAuth error: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def on_connect_google(self) -> None:
        # Open default browser to start OAuth.
        url = f"{self._api()}/oauth/google/start"
        try:
            webbrowser.open(url)
            self._set_status("Opened browser for Google OAuth")
        except Exception as exc:
            self._set_status(f"Cannot open browser: {exc}")

    def on_send(self) -> None:
        message = self.msg_text.get("1.0", tk.END).strip()
        if not message:
            self._set_status("Message is empty")
            return

        self.send_btn.configure(state=tk.DISABLED)

        def work() -> None:
            started = time.perf_counter()
            self._set_status("Sending...")
            try:
                r = requests.post(
                    f"{self._api()}/chat",
                    json={"message": message},
                    timeout=60,
                )
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                if r.status_code != 200:
                    self._write_response(f"HTTP {r.status_code}\n{r.text}")
                    self._write_trace("[]")
                    self._set_status(f"Error ({elapsed_ms} ms)")
                    return

                payload = r.json()
                self._write_response(payload.get("final_answer", ""))
                self._write_trace(json.dumps(payload.get("tool_trace", []), ensure_ascii=False, indent=2))
                self._set_status(f"Done ({elapsed_ms} ms)")
            except Exception as exc:
                self._write_response(f"Request failed: {exc}")
                self._write_trace("[]")
                self._set_status("Request failed")
            finally:
                self.send_btn.configure(state=tk.NORMAL)

        threading.Thread(target=work, daemon=True).start()

    def _write_response(self, text: str) -> None:
        self.resp_text.delete("1.0", tk.END)
        self.resp_text.insert("1.0", text or "")

    def _write_trace(self, text: str) -> None:
        self.trace_text.delete("1.0", tk.END)
        self.trace_text.insert("1.0", text or "")


def main() -> None:
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    DesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
