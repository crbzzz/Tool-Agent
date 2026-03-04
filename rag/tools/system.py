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
from typing import Any, Dict, Optional


_DENYLIST_ENV_TOKENS = ["SECRET", "TOKEN", "KEY", "PASSWORD", "PRIVATE"]
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _ok(data: Any) -> Dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str) -> Dict[str, Any]:
    return {"ok": False, "data": None, "error": msg}


def system_get_user_info(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        username = getpass.getuser()
        home = str(Path.home())
        cwd = str(Path.cwd())
        hostname = platform.node()
        os_name = platform.system()
        os_version = platform.version()
        architecture = platform.machine()

        desktop = str(Path.home() / "Desktop")

        return _ok(
            {
                "username": username,
                "home_directory": home,
                "current_working_directory": cwd,
                "desktop_path": desktop,
                "hostname": hostname,
                "os": os_name,
                "os_version": os_version,
                "architecture": architecture,
            }
        )
    except Exception as exc:
        return _err(str(exc))


def system_get_paths(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        home = Path.home()
        temp = os.getenv("TEMP") or os.getenv("TMP") or "/tmp"

        paths = {
            "home": str(home),
            "desktop": str(home / "Desktop"),
            "documents": str(home / "Documents"),
            "downloads": str(home / "Downloads"),
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
