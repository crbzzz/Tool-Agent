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


LOCAL_LIST_DIR_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "max_entries": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
    },
    "required": ["path"],
    "additionalProperties": False,
}


LOCAL_READ_TEXT_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "max_bytes": {"type": "integer", "minimum": 256, "maximum": 2000000},
        "encoding": {"type": "string"},
    },
    "required": ["path"],
    "additionalProperties": False,
}


LOCAL_WRITE_TEXT_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "content": {"type": "string"},
        "overwrite": {"type": "boolean", "default": False},
        "create_parents": {"type": "boolean", "default": False},
        "user_confirmation": {"type": "boolean", "default": False},
    },
    "required": ["path", "content", "user_confirmation"],
    "additionalProperties": False,
}


LOCAL_DELETE_PATH_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "recursive": {"type": "boolean", "default": False},
        "user_confirmation": {"type": "boolean", "default": False},
    },
    "required": ["path", "user_confirmation"],
    "additionalProperties": False,
}


LOCAL_SEARCH_FILES_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "root": {"type": "string", "minLength": 1},
        "pattern": {"type": "string", "default": "*"},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 200},
        "include_dirs": {"type": "boolean", "default": False},
    },
    "required": ["root"],
    "additionalProperties": False,
}


FS_LIST_DIR_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "recursive": {"type": "boolean", "default": False},
        "max_entries": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 2000},
    },
    "required": ["path"],
    "additionalProperties": False,
}


FS_SEARCH_FILES_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "root": {"type": "string", "minLength": 1},
        "pattern": {"type": "string", "default": "*"},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 20000, "default": 1000},
        "include_dirs": {"type": "boolean", "default": False},
    },
    "required": ["root"],
    "additionalProperties": False,
}


FS_READ_FILE_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "mode": {"type": "string", "enum": ["text", "binary"], "default": "text"},
        "max_chars": {"type": "integer", "minimum": 256, "maximum": 2000000, "default": 8000},
    },
    "required": ["path"],
    "additionalProperties": False,
}


FS_WRITE_FILE_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "content": {"type": "string"},
        "overwrite": {"type": "boolean", "default": False},
        "user_confirmation": {"type": "boolean", "default": False},
    },
    "required": ["path", "content", "user_confirmation"],
    "additionalProperties": False,
}


FS_DELETE_PATH_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "recursive": {"type": "boolean", "default": False},
        "user_confirmation": {"type": "boolean", "default": False},
    },
    "required": ["path", "user_confirmation"],
    "additionalProperties": False,
}


FS_MOVE_PATH_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "src_path": {"type": "string", "minLength": 1},
        "dst_path": {"type": "string", "minLength": 1},
        "overwrite": {"type": "boolean", "default": False},
        "user_confirmation": {"type": "boolean", "default": False},
    },
    "required": ["src_path", "dst_path", "user_confirmation"],
    "additionalProperties": False,
}


FS_MKDIR_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "parents": {"type": "boolean", "default": True},
        "exist_ok": {"type": "boolean", "default": True},
        "user_confirmation": {"type": "boolean", "default": False},
    },
    "required": ["path", "user_confirmation"],
    "additionalProperties": False,
}


SYSTEM_GET_USER_INFO_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


SYSTEM_GET_PATHS_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


SYSTEM_GET_ENV_VAR_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "variable_name": {
            "type": "string",
            "minLength": 1,
            "description": "Name of the environment variable.",
        }
    },
    "required": ["variable_name"],
    "additionalProperties": False,
}


DOC_DETECT_TYPE_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {"path": {"type": "string", "description": "Path to the file."}},
    "required": ["path"],
    "additionalProperties": False,
}


DOC_READ_TEXT_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to a text file."},
        "max_chars": {"type": "integer", "minimum": 200, "maximum": 200000},
        "encoding_hint": {"type": "string", "description": "Optional encoding hint like 'utf-8'."},
    },
    "required": ["path"],
    "additionalProperties": False,
}


DOC_EXTRACT_PDF_TEXT_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to the PDF."},
        "page_start": {"type": "integer", "minimum": 0},
        "page_end": {"type": "integer", "minimum": 0},
        "max_chars_per_page": {"type": "integer", "minimum": 200, "maximum": 50000},
    },
    "required": ["path"],
    "additionalProperties": False,
}


DOC_OCR_IMAGE_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to an image file (png/jpg/webp)."},
        "max_chars": {"type": "integer", "minimum": 200, "maximum": 200000},
        "language": {"type": "string", "description": "OCR language hint, e.g. 'eng'."},
    },
    "required": ["path"],
    "additionalProperties": False,
}


DOC_EXTRACT_DOCX_TEXT_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to the DOCX file."},
        "max_chars": {"type": "integer", "minimum": 200, "maximum": 400000},
    },
    "required": ["path"],
    "additionalProperties": False,
}


DOC_EXTRACT_ANY_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to the document."},
        "max_chars": {"type": "integer", "minimum": 200, "maximum": 400000},
        "prefer_ocr": {"type": "boolean", "description": "If true, force OCR if possible."},
    },
    "required": ["path"],
    "additionalProperties": False,
}


RAG_INGEST_EXTRACTED_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "source_name": {"type": "string", "description": "Human-readable source label (filename, etc.)."},
        "text": {"type": "string", "description": "Extracted text to ingest."},
        "chunk_size": {"type": "integer", "minimum": 200, "maximum": 5000},
        "chunk_overlap": {"type": "integer", "minimum": 0, "maximum": 1000},
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["source_name", "text", "user_confirmation"],
    "additionalProperties": False,
}


TOOL_PARAM_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "search_documents": SEARCH_DOCUMENTS_PARAMS_SCHEMA,
    "doc_detect_type": DOC_DETECT_TYPE_PARAMS_SCHEMA,
    "doc_read_text": DOC_READ_TEXT_PARAMS_SCHEMA,
    "doc_extract_pdf_text": DOC_EXTRACT_PDF_TEXT_PARAMS_SCHEMA,
    "doc_ocr_image": DOC_OCR_IMAGE_PARAMS_SCHEMA,
    "doc_extract_docx_text": DOC_EXTRACT_DOCX_TEXT_PARAMS_SCHEMA,
    "doc_extract_any": DOC_EXTRACT_ANY_PARAMS_SCHEMA,
    "rag_ingest_extracted": RAG_INGEST_EXTRACTED_PARAMS_SCHEMA,
    "fetch_url": FETCH_URL_PARAMS_SCHEMA,
    "search_web": SEARCH_WEB_PARAMS_SCHEMA,
    "list_emails": LIST_EMAILS_PARAMS_SCHEMA,
    "get_email": GET_EMAIL_PARAMS_SCHEMA,
    "list_drive_files": LIST_DRIVE_FILES_PARAMS_SCHEMA,
    "get_drive_file": GET_DRIVE_FILE_PARAMS_SCHEMA,
    "send_email": SEND_EMAIL_PARAMS_SCHEMA,
    "local_list_dir": LOCAL_LIST_DIR_PARAMS_SCHEMA,
    "local_read_text": LOCAL_READ_TEXT_PARAMS_SCHEMA,
    "local_write_text": LOCAL_WRITE_TEXT_PARAMS_SCHEMA,
    "local_delete_path": LOCAL_DELETE_PATH_PARAMS_SCHEMA,
    "local_search_files": LOCAL_SEARCH_FILES_PARAMS_SCHEMA,
    "fs_list_dir": FS_LIST_DIR_PARAMS_SCHEMA,
    "fs_search_files": FS_SEARCH_FILES_PARAMS_SCHEMA,
    "fs_read_file": FS_READ_FILE_PARAMS_SCHEMA,
    "fs_write_file": FS_WRITE_FILE_PARAMS_SCHEMA,
    "fs_delete_path": FS_DELETE_PATH_PARAMS_SCHEMA,
    "fs_move_path": FS_MOVE_PATH_PARAMS_SCHEMA,
    "fs_mkdir": FS_MKDIR_PARAMS_SCHEMA,
    "system_get_user_info": SYSTEM_GET_USER_INFO_PARAMS_SCHEMA,
    "system_get_paths": SYSTEM_GET_PATHS_PARAMS_SCHEMA,
    "system_get_environment_variable": SYSTEM_GET_ENV_VAR_PARAMS_SCHEMA,
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
            "name": "doc_detect_type",
            "description": "Detect file type and basic metadata for a given path.",
            "parameters": DOC_DETECT_TYPE_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "doc_read_text",
            "description": "Read a text file safely and return up to max_chars.",
            "parameters": DOC_READ_TEXT_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "doc_extract_pdf_text",
            "description": "Extract text from a PDF file by pages.",
            "parameters": DOC_EXTRACT_PDF_TEXT_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "doc_ocr_image",
            "description": "Perform OCR on an image and return extracted text.",
            "parameters": DOC_OCR_IMAGE_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "doc_extract_docx_text",
            "description": "Extract text from a DOCX document.",
            "parameters": DOC_EXTRACT_DOCX_TEXT_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "doc_extract_any",
            "description": "Extract text from a document (pdf/image/docx/text). Backend picks the right extractor.",
            "parameters": DOC_EXTRACT_ANY_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rag_ingest_extracted",
            "description": "Ingest extracted text into the RAG index (requires confirmation).",
            "parameters": RAG_INGEST_EXTRACTED_PARAMS_SCHEMA,
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
    {
        "type": "function",
        "function": {
            "name": "local_list_dir",
            "description": "List a local directory within allowlisted roots (LOCAL_FS_ALLOWED_ROOTS).",
            "parameters": LOCAL_LIST_DIR_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "local_read_text",
            "description": "Read a local text file within allowlisted roots (LOCAL_FS_ALLOWED_ROOTS).",
            "parameters": LOCAL_READ_TEXT_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "local_write_text",
            "description": "Write a local text file (disabled unless LOCAL_FS_ENABLE_DESTRUCTIVE=true; requires user_confirmation=true).",
            "parameters": LOCAL_WRITE_TEXT_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "local_delete_path",
            "description": "Delete a local file/folder (disabled unless LOCAL_FS_ENABLE_DESTRUCTIVE=true; requires user_confirmation=true).",
            "parameters": LOCAL_DELETE_PATH_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "local_search_files",
            "description": "Search for files under a local root using a glob pattern (within LOCAL_FS_ALLOWED_ROOTS).",
            "parameters": LOCAL_SEARCH_FILES_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_list_dir",
            "description": "List a directory (ACCESS_MODE enforced).",
            "parameters": FS_LIST_DIR_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_search_files",
            "description": "Search files under a root using a glob pattern (ACCESS_MODE enforced).",
            "parameters": FS_SEARCH_FILES_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_read_file",
            "description": "Read a file as text or base64 (ACCESS_MODE enforced).",
            "parameters": FS_READ_FILE_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_write_file",
            "description": "Write a file (requires user_confirmation=true; ACCESS_MODE enforced).",
            "parameters": FS_WRITE_FILE_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_delete_path",
            "description": "Delete a path (requires user_confirmation=true; ACCESS_MODE enforced).",
            "parameters": FS_DELETE_PATH_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_move_path",
            "description": "Move/rename a path (requires user_confirmation=true; ACCESS_MODE enforced).",
            "parameters": FS_MOVE_PATH_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_mkdir",
            "description": "Create a directory (requires user_confirmation=true; ACCESS_MODE enforced).",
            "parameters": FS_MKDIR_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_get_user_info",
            "description": "Get basic user/OS info (username, home, cwd, desktop, hostname, architecture).",
            "parameters": SYSTEM_GET_USER_INFO_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_get_paths",
            "description": "Get common OS paths (home, desktop, documents, downloads, temp).",
            "parameters": SYSTEM_GET_PATHS_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_get_environment_variable",
            "description": "Read a single environment variable value (denylisted names are blocked).",
            "parameters": SYSTEM_GET_ENV_VAR_PARAMS_SCHEMA,
        },
    },
]
