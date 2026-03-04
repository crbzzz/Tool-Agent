"""Supabase PostgREST helper.

We use PostgREST (SUPABASE_URL/rest/v1) with the project's anon key and the
signed-in user's access token (JWT) to perform DB operations under RLS.

This keeps the desktop app backend dependency-light (no direct DB driver).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

import requests

from rag.integrations.supabase_auth import SupabaseConfig


class SupabaseRestError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class SupabaseRestClient:
    cfg: SupabaseConfig

    @property
    def base_url(self) -> str:
        return f"{self.cfg.url}/rest/v1"

    def _headers(self, access_token: str, prefer: str | None = None) -> Dict[str, str]:
        headers = {
            "apikey": self.cfg.anon_key,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def request(
        self,
        method: str,
        table: str,
        access_token: str,
        *,
        params: Optional[Dict[str, str]] = None,
        json_body: Any | None = None,
        prefer: str | None = None,
        timeout_s: int = 20,
    ) -> Any:
        url = f"{self.base_url}/{table.lstrip('/')}"
        r = requests.request(
            method=method.upper(),
            url=url,
            headers=self._headers(access_token=access_token, prefer=prefer),
            params=params,
            json=json_body,
            timeout=timeout_s,
        )

        if r.status_code >= 400:
            text = r.text or ""
            raise SupabaseRestError(status_code=r.status_code, message=text.strip() or f"HTTP {r.status_code}")

        if r.status_code == 204:
            return None

        # PostgREST returns JSON arrays/objects.
        if not r.text:
            return None
        return r.json()
