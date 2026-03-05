"""System information tools.

These tools return basic, non-secret system context for the agent.

Security goals:
- Provide only high-level info (user, OS, paths, hostname, architecture).
- Avoid leaking secrets (no bulk env dump; denylist sensitive env var names).

Note: This is not a sandbox.
"""

from __future__ import annotations

import os
import platform
import re
import getpass
from pathlib import Path
from typing import Any, Dict, List, Optional


_DENYLIST_ENV_TOKENS = ["SECRET", "TOKEN", "KEY", "PASSWORD", "PRIVATE"]
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _ok(data: Any) -> Dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str) -> Dict[str, Any]:
    return {"ok": False, "data": None, "error": msg}


def _first_existing_dir(candidates: List[Path]) -> Optional[Path]:
    for p in candidates:
        try:
            if p.exists() and p.is_dir():
                return p
        except Exception:
            continue
    return None


def _candidate_bases() -> List[Path]:
    bases: List[Path] = []

    # USERPROFILE is the most reliable on Windows.
    userprofile = os.getenv("USERPROFILE")
    if userprofile:
        bases.append(Path(userprofile))

    # OneDrive variants (Desktop is often redirected here).
    for key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        val = os.getenv(key)
        if val:
            bases.append(Path(val))

    # Fallback.
    try:
        bases.append(Path.home())
    except Exception:
        pass

    # De-dup while preserving order.
    uniq: List[Path] = []
    seen = set()
    for b in bases:
        s = str(b).lower()
        if s in seen:
            continue
        seen.add(s)
        uniq.append(b)
    return uniq


def _pick_known_folder(name: str, bases: List[Path]) -> Dict[str, Any]:
    candidates = [b / name for b in bases]
    picked = _first_existing_dir(candidates)
    return {
        "path": str(picked) if picked else str(candidates[0]) if candidates else None,
        "candidates": [str(p) for p in candidates],
        "exists": bool(picked),
    }


def system_get_user_info(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        username = getpass.getuser()
        home_path = Path.home()
        home = str(home_path)
        cwd = str(Path.cwd())
        hostname = platform.node()
        os_name = platform.system()
        os_version = platform.version()
        architecture = platform.machine()

        bases = _candidate_bases()
        desktop_info = _pick_known_folder("Desktop", bases)
        documents_info = _pick_known_folder("Documents", bases)
        downloads_info = _pick_known_folder("Downloads", bases)

        desktop = desktop_info["path"]

        return _ok(
            {
                "username": username,
                "home_directory": home,
                "userprofile": os.getenv("USERPROFILE"),
                "onedrive": os.getenv("OneDrive") or os.getenv("OneDriveConsumer") or os.getenv("OneDriveCommercial"),
                "current_working_directory": cwd,
                "desktop_path": desktop,
                "desktop_candidates": desktop_info["candidates"],
                "hostname": hostname,
                "os": os_name,
                "os_version": os_version,
                "architecture": architecture,
                "documents_path": documents_info["path"],
                "downloads_path": downloads_info["path"],
            }
        )
    except Exception as exc:
        return _err(str(exc))


def system_get_paths(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        home = Path.home()
        bases = _candidate_bases()
        desktop_info = _pick_known_folder("Desktop", bases)
        documents_info = _pick_known_folder("Documents", bases)
        downloads_info = _pick_known_folder("Downloads", bases)
        temp = os.getenv("TEMP") or os.getenv("TMP") or "/tmp"

        paths = {
            "home": str(home),
            "desktop": desktop_info["path"],
            "desktop_candidates": desktop_info["candidates"],
            "documents": documents_info["path"],
            "documents_candidates": documents_info["candidates"],
            "downloads": downloads_info["path"],
            "downloads_candidates": downloads_info["candidates"],
            "temp": str(Path(temp)),
        }

        return _ok(paths)
    except Exception as exc:
        return _err(str(exc))


def system_get_environment_variable(args: Dict[str, Any]) -> Dict[str, Any]:
    var = args.get("variable_name")

    if not isinstance(var, str) or not var.strip():
        return _err("Missing variable_name")

    var = var.strip()
    if len(var) > 128:
        return _err("Invalid variable_name")

    if not _ENV_NAME_RE.match(var):
        return _err("Invalid variable_name")

    upper = var.upper()
    for word in _DENYLIST_ENV_TOKENS:
        if word in upper:
            return _err("Access to sensitive environment variables is not allowed.")

    value: Optional[str] = os.getenv(var)
    return _ok({"value": value})
