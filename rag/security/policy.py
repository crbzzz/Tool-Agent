from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional


AccessMode = Literal["safe", "full_disk"]


def _as_int(v: Any, default: int) -> int:
    try:
        if v is None:
            return default
        if isinstance(v, bool):
            return default
        return int(v)
    except Exception:
        return default


def _split_list(raw: Optional[str]) -> List[str]:
    if not isinstance(raw, str) or not raw.strip():
        return []
    # Accept both ';' and ',' separators.
    parts: List[str] = []
    for chunk in raw.replace(",", ";").split(";"):
        s = chunk.strip()
        if s:
            parts.append(s)
    return parts


def _default_denylist_patterns() -> List[str]:
    # Keep this conservative: avoid leaking obvious secrets.
    return [
        ".env",
        ".ssh",
        "id_rsa",
        "id_ed25519",
        "secrets",
        ".secrets",
        "credentials",
        "token",
        "token.json",
        "key",
        "password",
        "*.pem",
        "*.p12",
        "*.key",
    ]


@dataclass(frozen=True)
class PermissionPolicy:
    access_mode: AccessMode = "safe"
    workspace_root: str = "./rag/data"
    allowed_roots: List[str] = field(default_factory=list)
    denylist_patterns: List[str] = field(default_factory=_default_denylist_patterns)

    max_delete_per_run: int = 10
    max_move_per_run: int = 50
    max_upload_mb_per_run: int = 200
    max_files_per_run: int = 500

    require_confirmation_for: List[str] = field(
        default_factory=lambda: [
            # Filesystem writes
            "fs_write_file",
            "fs_delete_path",
            "fs_move_path",
            "fs_mkdir",
            # External side effects
            "drive_upload_file",
            "drive_upload_local_file",
            "drive_create_folder",
            "drive_ensure_folder:create",
            "drive_rename_folder",
            "drive_move_folder",
            "drive_delete_folder",
            "send_email",
            "send_email_with_attachments",
            "gmail_trash_message",
            "gmail_apply_label",
        ]
    )

    def safe_dict(self) -> Dict[str, Any]:
        # Safe to expose (no secrets).
        d = asdict(self)
        # Normalize paths for display.
        d["workspace_root"] = str(Path(self.workspace_root).resolve())
        d["allowed_roots"] = [str(Path(p).resolve()) for p in (self.allowed_roots or [])]
        return d


_POLICY_LOCK = threading.Lock()
_POLICY_CACHE: Optional[PermissionPolicy] = None


def _state_file() -> Path:
    raw = os.getenv("SECURITY_POLICY_STATE_PATH") or "./rag/state/policy_state.json"
    return Path(raw).resolve()


def _load_state() -> Dict[str, Any]:
    p = _state_file()
    try:
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(data: Dict[str, Any]) -> None:
    p = _state_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def load_policy_from_env() -> PermissionPolicy:
    mode_raw = (os.getenv("ACCESS_MODE") or "safe").strip().lower()
    mode: AccessMode = "safe" if mode_raw != "full_disk" else "full_disk"

    ws = (os.getenv("WORKSPACE_ROOT") or "./rag/data").strip() or "./rag/data"

    allowed = _split_list(os.getenv("ALLOWED_ROOTS"))
    if not allowed:
        allowed = [ws]

    deny = _split_list(os.getenv("DENYLIST_PATTERNS"))
    if not deny:
        deny = _default_denylist_patterns()

    max_delete = _as_int(os.getenv("MAX_DELETE_PER_RUN"), 10)
    max_move = _as_int(os.getenv("MAX_MOVE_PER_RUN"), 50)
    max_upload_mb = _as_int(os.getenv("MAX_UPLOAD_MB_PER_RUN"), 200)
    max_files = _as_int(os.getenv("MAX_FILES_PER_RUN"), 500)

    require_confirm = _split_list(os.getenv("REQUIRE_CONFIRMATION_FOR"))
    policy = PermissionPolicy(
        access_mode=mode,
        workspace_root=ws,
        allowed_roots=allowed,
        denylist_patterns=deny,
        max_delete_per_run=max(0, max_delete),
        max_move_per_run=max(0, max_move),
        max_upload_mb_per_run=max(1, max_upload_mb),
        max_files_per_run=max(1, max_files),
        require_confirmation_for=require_confirm
        if require_confirm
        else PermissionPolicy().require_confirmation_for,
    )

    # Apply persisted override (only access_mode for now).
    state = _load_state()
    override_mode = state.get("access_mode")
    if override_mode in {"safe", "full_disk"}:
        policy = PermissionPolicy(
            **{**asdict(policy), "access_mode": override_mode}  # type: ignore[arg-type]
        )

    return policy


def get_policy(refresh: bool = False) -> PermissionPolicy:
    global _POLICY_CACHE
    with _POLICY_LOCK:
        if _POLICY_CACHE is None or refresh:
            _POLICY_CACHE = load_policy_from_env()
        return _POLICY_CACHE


def set_policy_mode(mode: AccessMode) -> PermissionPolicy:
    state = _load_state()
    state["access_mode"] = mode
    _save_state(state)
    return get_policy(refresh=True)


# Tool wrappers (for the agent registry)

def policy_get(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        p = get_policy(refresh=True)
        return {"ok": True, "data": p.safe_dict(), "error": None}
    except Exception as exc:
        return {"ok": False, "data": None, "error": str(exc)}


def policy_set_mode(args: Dict[str, Any]) -> Dict[str, Any]:
    mode = args.get("mode")
    user_confirmation = args.get("user_confirmation")

    if mode not in {"safe", "full_disk"}:
        return {"ok": False, "data": None, "error": "Invalid mode (safe|full_disk)"}
    if user_confirmation is not True:
        return {
            "ok": False,
            "data": None,
            "error": "Confirmation required: set user_confirmation=true",
        }

    try:
        p = set_policy_mode(mode)  # type: ignore[arg-type]
        return {"ok": True, "data": p.safe_dict(), "error": None}
    except Exception as exc:
        return {"ok": False, "data": None, "error": str(exc)}
