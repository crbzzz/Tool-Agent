"""Tool registry mapping tool names to handler callables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


ToolHandler = Callable[[Dict[str, Any]], Dict[str, Any]]


@dataclass
class ToolRegistry:
    tools: Dict[str, ToolHandler]

    def get(self, name: str) -> Optional[ToolHandler]:
        return self.tools.get(name)


def build_default_registry() -> ToolRegistry:
    from rag.tools.drive import get_drive_file, list_drive_files
    from rag.tools.email_send import send_email
    from rag.tools.fs import (
        fs_delete_path,
        fs_list_dir,
        fs_mkdir,
        fs_move_path,
        fs_read_file,
        fs_search_files,
        fs_write_file,
    )
    from rag.tools.gmail import get_email, list_emails
    from rag.tools.local_fs import (
        local_delete_path,
        local_list_dir,
        local_read_text,
        local_search_files,
        local_write_text,
    )
    from rag.tools.rag_search import search_documents
    from rag.tools.system import (
        system_get_environment_variable,
        system_get_paths,
        system_get_user_info,
    )
    from rag.tools.web_fetch import fetch_url
    from rag.tools.web_search import search_web

    return ToolRegistry(
        tools={
            "search_documents": search_documents,
            "fetch_url": fetch_url,
            "search_web": search_web,
            "list_emails": list_emails,
            "get_email": get_email,
            "list_drive_files": list_drive_files,
            "get_drive_file": get_drive_file,
            "send_email": send_email,
            "local_list_dir": local_list_dir,
            "local_read_text": local_read_text,
            "local_search_files": local_search_files,
            "local_write_text": local_write_text,
            "local_delete_path": local_delete_path,
            # fs_* tools (exact names expected by agent tool calls)
            "fs_list_dir": fs_list_dir,
            "fs_search_files": fs_search_files,
            "fs_read_file": fs_read_file,
            "fs_write_file": fs_write_file,
            "fs_delete_path": fs_delete_path,
            "fs_move_path": fs_move_path,
            "fs_mkdir": fs_mkdir,
            # system_* tools (safe system context)
            "system_get_user_info": system_get_user_info,
            "system_get_paths": system_get_paths,
            "system_get_environment_variable": system_get_environment_variable,
        }
    )
