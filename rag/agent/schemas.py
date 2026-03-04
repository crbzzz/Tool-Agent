"""Tool parameter JSON Schemas (parameters-only) and tool definitions for reference."""

from __future__ import annotations

from typing import Any, Dict, List


SEARCH_DOCUMENTS_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
        "filters": {"type": "object", "additionalProperties": True},
    },
    "required": ["query"],
    "additionalProperties": False,
}

FETCH_URL_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "minLength": 1},
        "max_chars": {"type": "integer", "minimum": 256, "maximum": 20000, "default": 5000},
        "timeout_s": {"type": "number", "minimum": 1, "maximum": 30, "default": 10},
    },
    "required": ["url"],
    "additionalProperties": False,
}

SEARCH_WEB_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
    },
    "required": ["query"],
    "additionalProperties": False,
}

LIST_EMAILS_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
    },
    "required": [],
    "additionalProperties": False,
}

GET_EMAIL_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {"email_id": {"type": "string", "minLength": 1}},
    "required": ["email_id"],
    "additionalProperties": False,
}

LIST_DRIVE_FILES_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
    },
    "required": [],
    "additionalProperties": False,
}

GET_DRIVE_FILE_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {"file_id": {"type": "string", "minLength": 1}},
    "required": ["file_id"],
    "additionalProperties": False,
}

SEND_EMAIL_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "to": {"type": "array", "items": {"type": "string", "minLength": 3}, "minItems": 1},
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "user_confirmation": {"type": "boolean", "default": False},
    },
    "required": ["to", "subject", "body", "user_confirmation"],
    "additionalProperties": False,
}


TOOL_PARAM_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "search_documents": SEARCH_DOCUMENTS_PARAMS_SCHEMA,
    "fetch_url": FETCH_URL_PARAMS_SCHEMA,
    "search_web": SEARCH_WEB_PARAMS_SCHEMA,
    "list_emails": LIST_EMAILS_PARAMS_SCHEMA,
    "get_email": GET_EMAIL_PARAMS_SCHEMA,
    "list_drive_files": LIST_DRIVE_FILES_PARAMS_SCHEMA,
    "get_drive_file": GET_DRIVE_FILE_PARAMS_SCHEMA,
    "send_email": SEND_EMAIL_PARAMS_SCHEMA,
}


TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Search local documents (RAG). Returns relevant chunks if available.",
            "parameters": SEARCH_DOCUMENTS_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch a URL and return basic extracted text (untrusted).",
            "parameters": FETCH_URL_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Web search (stub).",
            "parameters": SEARCH_WEB_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_emails",
            "description": "List emails (stub; not connected).",
            "parameters": LIST_EMAILS_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_email",
            "description": "Get one email by id (stub; not connected).",
            "parameters": GET_EMAIL_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_drive_files",
            "description": "List Drive files (stub; not connected).",
            "parameters": LIST_DRIVE_FILES_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_drive_file",
            "description": "Get a Drive file by id (stub; not connected).",
            "parameters": GET_DRIVE_FILE_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email (stub; requires explicit user_confirmation=true).",
            "parameters": SEND_EMAIL_PARAMS_SCHEMA,
        },
    },
]
