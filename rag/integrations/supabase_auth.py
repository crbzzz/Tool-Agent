"""Minimal Supabase Auth helper (server-side).

Uses the public anon key. Do NOT put the service role key in the frontend.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests


def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def generate_code_verifier() -> str:
    # 32 bytes -> 43 chars b64url (no padding)
    return _b64url_no_pad(secrets.token_bytes(32))


def code_challenge_s256(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return _b64url_no_pad(digest)


@dataclass
class SupabaseConfig:
    url: str
    anon_key: str


def load_supabase_config() -> SupabaseConfig:
    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    anon = (os.environ.get("SUPABASE_ANON_KEY") or "").strip()
    if not url:
        raise RuntimeError("SUPABASE_URL is not set")
    if not anon:
        raise RuntimeError("SUPABASE_ANON_KEY is not set")
    return SupabaseConfig(url=url, anon_key=anon)


class SupabaseAuthClient:
    def __init__(self, cfg: SupabaseConfig):
        self.cfg = cfg

    def _headers(self, access_token: str | None = None) -> Dict[str, str]:
        h = {
            "apikey": self.cfg.anon_key,
            "Content-Type": "application/json",
        }
        if access_token:
            h["Authorization"] = f"Bearer {access_token}"
        return h

    def sign_up(self, email: str, password: str) -> Dict[str, Any]:
        url = f"{self.cfg.url}/auth/v1/signup"
        r = requests.post(url, headers=self._headers(), json={"email": email, "password": password}, timeout=20)
        r.raise_for_status()
        return r.json()

    def sign_in_password(self, email: str, password: str) -> Dict[str, Any]:
        url = f"{self.cfg.url}/auth/v1/token?grant_type=password"
        r = requests.post(url, headers=self._headers(), json={"email": email, "password": password}, timeout=20)
        r.raise_for_status()
        return r.json()

    def exchange_code_for_session(self, code: str, code_verifier: str) -> Dict[str, Any]:
        url = f"{self.cfg.url}/auth/v1/token?grant_type=pkce"
        r = requests.post(
            url,
            headers=self._headers(),
            json={"auth_code": code, "code_verifier": code_verifier},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()

    def get_user(self, access_token: str) -> Dict[str, Any]:
        url = f"{self.cfg.url}/auth/v1/user"
        r = requests.get(url, headers=self._headers(access_token=access_token), timeout=20)
        r.raise_for_status()
        return r.json()

    def logout(self, access_token: str) -> None:
        url = f"{self.cfg.url}/auth/v1/logout"
        r = requests.post(url, headers=self._headers(access_token=access_token), timeout=20)
        # best-effort; token could be expired already
        if r.status_code >= 400:
            return

    def identities_authorize(
        self,
        access_token: str,
        provider: str,
        redirect_to: str,
        code_challenge: str | None = None,
        code_challenge_method: str | None = None,
    ) -> Dict[str, Any]:
        url = f"{self.cfg.url}/auth/v1/user/identities/authorize"
        payload: Dict[str, Any] = {"provider": provider, "redirect_to": redirect_to}
        if code_challenge:
            payload["code_challenge"] = code_challenge
        if code_challenge_method:
            payload["code_challenge_method"] = code_challenge_method
        r = requests.post(url, headers=self._headers(access_token=access_token), json=payload, timeout=20)
        r.raise_for_status()
        return r.json()

    def build_authorize_url(
        self,
        provider: str,
        redirect_to: str,
        code_challenge: str,
        code_challenge_method: str = "s256",
    ) -> str:
        base = f"{self.cfg.url}/auth/v1/authorize"
        qs = urlencode(
            {
                "provider": provider,
                "redirect_to": redirect_to,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
            }
        )
        return f"{base}?{qs}"
