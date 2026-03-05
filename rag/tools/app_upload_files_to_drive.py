"""App tool: recursively search local files and upload to Google Drive.

Goal: keep the agent orchestration simple and fast by doing all steps server-side.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rag.tools.fs import check_path_allowed
from rag.tools.drive import drive_ensure_folder, drive_upload_local_file

logger = logging.getLogger(__name__)


_DEFAULT_MAX_DEPTH = 8
_DEFAULT_MAX_SECONDS = 12.0
_DEFAULT_MAX_FILES = 200


@dataclass(frozen=True)
class _FoundFile:
    path: Path
    name: str
    size_bytes: int
    mime_type: str


def _lower_ext(ext: str) -> str:
    e = (ext or "").strip().lower()
    if not e:
        return ""
    if not e.startswith("."):
        e = f".{e}"
    return e


def _hash_file_md5(path: Path, max_bytes: int = 30_000_000) -> Optional[str]:
    try:
        if path.stat().st_size > max_bytes:
            return None
    except Exception:
        return None

    h = hashlib.md5()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _is_within_depth(root: Path, current_dir: Path, max_depth: int) -> bool:
    try:
        rel = current_dir.relative_to(root)
        # depth: number of parts in relative path
        depth = len(rel.parts)
        return depth <= max_depth
    except Exception:
        return True


def _walk_files(
    root: Path,
    extensions: List[str],
    name_contains: str,
    max_depth: int,
    max_seconds: float,
    max_files: int,
) -> Tuple[List[_FoundFile], bool, str]:
    started = time.monotonic()
    results: List[_FoundFile] = []

    ext_set = {e for e in (_lower_ext(x) for x in extensions or []) if e}
    needle = (name_contains or "").strip().lower()

    truncated = False
    reason = ""

    def _timed_out() -> bool:
        return (time.monotonic() - started) >= max_seconds

    root_str = str(root)

    for dirpath, dirnames, filenames in os.walk(root_str, topdown=True, followlinks=False):
        if _timed_out():
            truncated = True
            reason = f"search timed out after {max_seconds} seconds"
            break

        cur_dir = Path(dirpath)
        if not _is_within_depth(root, cur_dir, max_depth):
            dirnames[:] = []
            continue

        for fn in filenames:
            if _timed_out():
                truncated = True
                reason = f"search timed out after {max_seconds} seconds"
                break

            p = cur_dir / fn

            # Extension filter
            if ext_set:
                if _lower_ext(p.suffix) not in ext_set:
                    continue

            # Name filter
            if needle and needle not in fn.lower():
                continue

            try:
                st = p.stat()
            except Exception:
                continue

            if not st or not st.st_size:
                continue

            guessed_mime, _ = mimetypes.guess_type(str(p))
            mime = guessed_mime or "application/octet-stream"

            results.append(_FoundFile(path=p, name=fn, size_bytes=int(st.st_size), mime_type=mime))

            if len(results) >= max_files:
                truncated = True
                reason = f"files limited to {max_files}"
                break

        if truncated:
            break

    return results, truncated, reason


def app_upload_files_to_drive(args: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively search for files and upload them to a Drive folder.

    Args schema is defined in rag.agent.schemas.
    """

    # Delegate to the canonical macro-tool implementation.
    from rag.tools.apps import app_upload_files_to_drive as _impl

    logger.info("Delegating legacy app_upload_files_to_drive to rag.tools.apps")
    return _impl(args)

    search_root = args.get("search_root")
    drive_folder_name = args.get("drive_folder_name")
    extensions = args.get("extensions")
    name_contains = args.get("name_contains")
    max_depth = args.get("max_depth", _DEFAULT_MAX_DEPTH)
    dry_run = bool(args.get("dry_run", False))
    user_confirmation = args.get("user_confirmation")

    if not isinstance(search_root, str) or not search_root.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid search_root"}
    if not isinstance(drive_folder_name, str) or not drive_folder_name.strip():
        return {"ok": False, "data": None, "error": "Missing or invalid drive_folder_name"}
    if not isinstance(extensions, list) or not all(isinstance(x, str) and x.strip() for x in extensions):
        return {"ok": False, "data": None, "error": "Missing or invalid extensions"}
    if name_contains is not None and not isinstance(name_contains, str):
        return {"ok": False, "data": None, "error": "Invalid name_contains"}
    if max_depth is not None and (not isinstance(max_depth, int) or max_depth < 1 or max_depth > 20):
        return {"ok": False, "data": None, "error": "Invalid max_depth (1..20)"}

    if not dry_run and user_confirmation is not True:
        return {"ok": False, "data": None, "error": "Confirmation required: set user_confirmation=true"}

    root_path, err = check_path_allowed(search_root)
    if err:
        return {"ok": False, "data": None, "error": err}
    if root_path is None or not root_path.exists() or not root_path.is_dir():
        return {"ok": False, "data": None, "error": "search_root does not exist or is not a directory"}

    # Keep the tool fast by default.
    max_seconds = float(args.get("max_seconds", _DEFAULT_MAX_SECONDS) or _DEFAULT_MAX_SECONDS)
    if max_seconds <= 0 or max_seconds > 120:
        return {"ok": False, "data": None, "error": "Invalid max_seconds (0..120)"}

    max_files = int(args.get("max_files", _DEFAULT_MAX_FILES) or _DEFAULT_MAX_FILES)
    if max_files < 1 or max_files > 5000:
        return {"ok": False, "data": None, "error": "Invalid max_files (1..5000)"}

    found, truncated, truncated_reason = _walk_files(
        root=root_path,
        extensions=extensions,
        name_contains=str(name_contains or ""),
        max_depth=int(max_depth or _DEFAULT_MAX_DEPTH),
        max_seconds=max_seconds,
        max_files=max_files,
    )

    if not found:
        return {
            "ok": True,
            "data": {
                "search_root": str(root_path),
                "drive_folder_name": drive_folder_name.strip(),
                "dry_run": dry_run,
                "files_found": 0,
                "files_uploaded": 0,
                "duplicates_skipped": 0,
                "errors": [],
                "truncated": truncated,
                "truncated_reason": truncated_reason,
            },
            "error": None,
        }

    # Ensure the Drive folder.
    ensure_res = drive_ensure_folder({"folder_name": drive_folder_name.strip()})
    if not ensure_res.get("ok"):
        return {"ok": False, "data": {"step": "drive_ensure_folder", "details": ensure_res}, "error": ensure_res.get("error")}

    folder_id = None
    try:
        folder_id = ensure_res.get("data", {}).get("folder_id")
    except Exception:
        folder_id = None

    if not isinstance(folder_id, str) or not folder_id.strip():
        return {"ok": False, "data": {"step": "drive_ensure_folder", "details": ensure_res}, "error": "drive_ensure_folder returned no folder_id"}

    uploaded = 0
    duplicates = 0
    errors: List[Dict[str, Any]] = []

    # Build a lightweight existing-name set to prevent accidental duplicate uploads.
    # (Name-only is not perfect but avoids expensive Drive hashing/listing across big folders.)
    existing_names: set[str] = set()
    try:
        # Lazy import to avoid hard dependency at import time.
        from rag.integrations.google_oauth import drive_service, load_credentials

        creds = load_credentials()
        svc = drive_service(creds)
        q = f"'{folder_id.strip()}' in parents and trashed=false"
        page_token: Optional[str] = None
        while True:
            resp = (
                svc.files()
                .list(
                    q=q,
                    pageSize=200,
                    fields="nextPageToken,files(id,name,size,md5Checksum)",
                    pageToken=page_token,
                )
                .execute()
            )
            for f in resp.get("files", []) or []:
                nm = str(f.get("name") or "").strip()
                if nm:
                    existing_names.add(nm.lower())
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
    except Exception:
        # If listing existing files fails, we still proceed.
        existing_names = set()

    to_upload = found

    # Dry run: return what would happen.
    if dry_run:
        return {
            "ok": True,
            "data": {
                "search_root": str(root_path),
                "drive_folder_name": drive_folder_name.strip(),
                "drive_folder_id": folder_id.strip(),
                "dry_run": True,
                "files_found": len(to_upload),
                "files_uploaded": 0,
                "duplicates_skipped": 0,
                "errors": [],
                "truncated": truncated,
                "truncated_reason": truncated_reason,
                "files": [
                    {
                        "local_path": str(f.path),
                        "filename": f.name,
                        "mime_type": f.mime_type,
                        "size_bytes": f.size_bytes,
                        "already_exists_by_name": f.name.lower() in existing_names,
                    }
                    for f in to_upload
                ],
            },
            "error": None,
        }

    for f in to_upload:
        if f.name.lower() in existing_names:
            duplicates += 1
            continue

        up_res = drive_upload_local_file(
            {
                "local_path": str(f.path),
                "folder_id": folder_id.strip(),
                "filename": f.name,
                "mime_type": f.mime_type,
            }
        )

        if not up_res.get("ok"):
            errors.append({"local_path": str(f.path), "error": up_res.get("error")})
            continue

        uploaded += 1
        existing_names.add(f.name.lower())

    return {
        "ok": True,
        "data": {
            "search_root": str(root_path),
            "drive_folder_name": drive_folder_name.strip(),
            "drive_folder_id": folder_id.strip(),
            "dry_run": False,
            "files_found": len(to_upload),
            "files_uploaded": uploaded,
            "duplicates_skipped": duplicates,
            "errors": errors,
            "truncated": truncated,
            "truncated_reason": truncated_reason,
        },
        "error": None,
    }
