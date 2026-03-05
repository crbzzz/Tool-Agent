from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from rag.security.policy import PermissionPolicy, get_policy


class SecurityError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        requires_confirmation: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.requires_confirmation = bool(requires_confirmation)
        self.details = details or {}


_TRAVERSAL_RE = re.compile(r"\0")


@dataclass
class SecurityGuard:
    policy: PermissionPolicy

    @classmethod
    def from_env(cls) -> "SecurityGuard":
        return cls(get_policy(refresh=True))

    def resolve_path(self, path: str) -> Path:
        if not isinstance(path, str) or not path.strip():
            raise SecurityError("Invalid path")
        if _TRAVERSAL_RE.search(path):
            raise SecurityError("Invalid path")
        # strict=False allows non-existing targets.
        try:
            return Path(path).expanduser().resolve(strict=False)
        except Exception as exc:
            raise SecurityError(f"Invalid path: {exc}")

    def redact_path(self, path: str) -> str:
        try:
            p = Path(path)
            parts = list(p.parts)
            if not parts:
                return "<path>"
            if len(parts) <= 3:
                return str(p)
            # Keep drive/root + last 2 segments.
            anchor = parts[0]
            tail = parts[-2:]
            return str(Path(anchor) / "…" / tail[0] / tail[1])
        except Exception:
            return "<path>"

    def is_denied(self, path: Path) -> bool:
        patterns = [str(x).strip().lower() for x in (self.policy.denylist_patterns or []) if str(x).strip()]
        if not patterns:
            return False

        try:
            parts = [p.lower() for p in path.parts]
        except Exception:
            parts = [str(path).lower()]

        filename = (path.name or "").lower()
        full = str(path).lower()

        for pat in patterns:
            if not pat:
                continue

            # Glob patterns.
            if any(ch in pat for ch in "*?["):
                if fnmatch.fnmatch(filename, pat) or fnmatch.fnmatch(full, pat):
                    return True
                continue

            # Special case: .env-like
            if pat == ".env":
                if filename.startswith(".env"):
                    return True

            # For short tokens like 'key', don't match directory names (too noisy).
            if len(pat) <= 4:
                if pat in filename:
                    return True
                continue

            if any(part == pat for part in parts):
                return True
            if pat in filename:
                return True

        return False

    def _is_within(self, child: Path, parent: Path) -> bool:
        try:
            common = os.path.commonpath([str(child), str(parent)])
            return Path(common).resolve(strict=False) == parent
        except Exception:
            return False

    def check_path_allowed(self, path: str, action: str) -> None:
        p = self.resolve_path(path)

        if self.is_denied(p):
            raise SecurityError("Path is denied by security policy")

        mode = self.policy.access_mode
        if mode == "safe":
            roots = self.policy.allowed_roots or [self.policy.workspace_root]
            root_paths = []
            for r in roots:
                try:
                    root_paths.append(Path(r).expanduser().resolve(strict=False))
                except Exception:
                    continue

            if not root_paths:
                raise SecurityError("No allowed_roots configured")

            if not any(self._is_within(p, r) for r in root_paths):
                ws = Path(self.policy.workspace_root).expanduser().resolve(strict=False)
                raise SecurityError(f"Path is outside allowed roots (workspace_root={ws})")

    def _risk_score(self, *, action: str, file_count: int, total_bytes: int) -> int:
        score = 0
        if action in {"fs_delete_path", "drive_delete_folder", "gmail_trash_message"}:
            score += 50
        if action in {"drive_upload_file", "drive_upload_local_file", "send_email", "send_email_with_attachments"}:
            score += 35
        if file_count > max(1, self.policy.max_files_per_run // 2):
            score += 20
        if total_bytes > int(self.policy.max_upload_mb_per_run * 1024 * 1024 * 0.5):
            score += 20
        return min(100, score)

    def check_batch(self, action: str, file_count: int, total_bytes: int) -> None:
        try:
            n = int(file_count)
        except Exception:
            n = 0
        try:
            b = int(total_bytes)
        except Exception:
            b = 0

        if n < 0 or b < 0:
            raise SecurityError("Invalid batch inputs")

        # Action-specific caps.
        if action == "fs_delete_path" and self.policy.max_delete_per_run and n > self.policy.max_delete_per_run:
            raise SecurityError(f"Delete batch too large (>{self.policy.max_delete_per_run})")
        if action == "fs_move_path" and self.policy.max_move_per_run and n > self.policy.max_move_per_run:
            raise SecurityError(f"Move batch too large (>{self.policy.max_move_per_run})")

        # Global caps.
        max_files = int(self.policy.max_files_per_run)
        max_bytes = int(self.policy.max_upload_mb_per_run) * 1024 * 1024

        if n > max_files or b > max_bytes:
            risk = self._risk_score(action=action, file_count=n, total_bytes=b)
            raise SecurityError(
                "High-risk batch: requires user_confirmation=true",
                requires_confirmation=True,
                details={
                    "file_count": n,
                    "total_bytes": b,
                    "max_files_per_run": max_files,
                    "max_upload_bytes_per_run": max_bytes,
                    "risk_score": risk,
                },
            )

    def require_confirmation(self, action: str, user_confirmation: Optional[bool]) -> None:
        required = set(self.policy.require_confirmation_for or [])
        if action in required and user_confirmation is not True:
            raise SecurityError("Confirmation required: set user_confirmation=true", requires_confirmation=True)
