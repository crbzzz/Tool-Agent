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
    from rag.tools.gmail import get_email, list_emails
    from rag.tools.rag_search import search_documents
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
        }
    )
