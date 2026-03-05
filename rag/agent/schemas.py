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
        "query": {
            "type": "string",
            "description": "Optional Gmail search query (e.g. 'has:attachment filename:pdf').",
        },
    },
    "required": [],
    "additionalProperties": False,
}

GET_EMAIL_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "email_id": {"type": "string", "minLength": 1, "description": "Legacy alias for message_id."},
        "message_id": {"type": "string", "minLength": 1, "description": "Gmail message ID."},
    },
    "required": [],
    "anyOf": [{"required": ["message_id"]}, {"required": ["email_id"]}],
    "additionalProperties": False,
}


GMAIL_LIST_ATTACHMENTS_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "message_id": {
            "type": "string",
            "description": "Gmail message ID.",
        }
    },
    "required": ["message_id"],
    "additionalProperties": False,
}


GMAIL_DOWNLOAD_ATTACHMENT_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "message_id": {
            "type": "string",
            "description": "Gmail message ID.",
        },
        "attachment_id": {
            "type": "string",
            "description": "Gmail attachment ID for that message.",
        },
        "max_bytes": {
            "type": "integer",
            "minimum": 1024,
            "maximum": 30000000,
            "description": "Maximum bytes allowed to download (safety limit).",
        },
    },
    "required": ["message_id", "attachment_id"],
    "additionalProperties": False,
}


GMAIL_APPLY_LABEL_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "message_id": {"type": "string"},
        "label_name": {"type": "string"},
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["message_id", "label_name", "user_confirmation"],
    "additionalProperties": False,
}


GMAIL_TRASH_MESSAGE_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "message_id": {"type": "string"},
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["message_id", "user_confirmation"],
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


DRIVE_ENSURE_FOLDER_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "folder_name": {
            "type": "string",
            "description": "Name of the folder to ensure exists.",
        },
        "parent_folder_id": {
            "type": "string",
            "description": "Optional parent folder id. If omitted, uses Drive root.",
        },
        "user_confirmation": {
            "type": "boolean",
            "enum": [True],
            "description": "Required only if a new folder must be created.",
        },
    },
    "required": ["folder_name"],
    "additionalProperties": False,
}


DRIVE_UPLOAD_FILE_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "folder_id": {
            "type": "string",
            "description": "Destination Google Drive folder ID.",
        },
        "filename": {
            "type": "string",
            "description": "File name (e.g. 'invoice.pdf').",
        },
        "mime_type": {
            "type": "string",
            "description": "MIME type (e.g. 'application/pdf').",
        },
        "content_base64": {
            "type": "string",
            "description": "Base64-encoded file content.",
        },
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["folder_id", "filename", "mime_type", "content_base64", "user_confirmation"],
    "additionalProperties": False,
}


DRIVE_UPLOAD_LOCAL_FILE_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "local_path": {"type": "string", "minLength": 1, "description": "Local file path to upload."},
        "folder_id": {"type": "string", "minLength": 1, "description": "Destination Drive folder ID."},
        "filename": {"type": "string", "description": "Optional filename override."},
        "mime_type": {"type": "string", "description": "Optional MIME type override."},
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["local_path", "folder_id", "user_confirmation"],
    "additionalProperties": False,
}


DRIVE_LIST_FOLDERS_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "parent_folder_id": {
            "type": "string",
            "description": "Optional parent folder id. If omitted, lists across Drive.",
        },
        "query": {
            "type": "string",
            "description": "Optional raw Drive q fragment to AND with folder filters.",
        },
        "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
    },
    "required": [],
    "additionalProperties": False,
}


DRIVE_CREATE_FOLDER_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "folder_name": {"type": "string", "minLength": 1},
        "parent_folder_id": {
            "type": "string",
            "description": "Optional parent folder id. If omitted, uses Drive root.",
        },
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["folder_name", "user_confirmation"],
    "additionalProperties": False,
}


DRIVE_RENAME_FOLDER_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "folder_id": {"type": "string", "minLength": 1},
        "new_name": {"type": "string", "minLength": 1},
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["folder_id", "new_name", "user_confirmation"],
    "additionalProperties": False,
}


DRIVE_MOVE_FOLDER_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "folder_id": {"type": "string", "minLength": 1},
        "new_parent_folder_id": {"type": "string", "minLength": 1},
        "remove_other_parents": {"type": "boolean", "default": True},
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["folder_id", "new_parent_folder_id", "user_confirmation"],
    "additionalProperties": False,
}


DRIVE_DELETE_FOLDER_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "folder_id": {"type": "string", "minLength": 1},
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["folder_id", "user_confirmation"],
    "additionalProperties": False,
}


POLICY_GET_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


POLICY_SET_MODE_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "mode": {"type": "string", "enum": ["safe", "full_disk"]},
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["mode", "user_confirmation"],
    "additionalProperties": False,
}


APP_STATE_GET_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {"key": {"type": "string"}},
    "required": ["key"],
    "additionalProperties": False,
}


APP_STATE_SET_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "key": {"type": "string"},
        "value": {"type": "string"},
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["key", "value", "user_confirmation"],
    "additionalProperties": False,
}


APP_UPLOAD_FILES_TO_DRIVE_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "search_root": {
            "type": "string",
            "minLength": 1,
            "description": "Optional root directory where recursive search should start. If omitted, the server searches common user folders (Desktop/Documents/Downloads).",
        },
        "drive_folder_name": {
            "type": "string",
            "minLength": 1,
            "description": "Destination Google Drive folder name.",
        },
        "parent_folder_id": {
            "type": "string",
            "minLength": 1,
            "description": "Optional Drive parent folder id.",
        },
        "extensions": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
            "description": "List of file extensions to include (e.g. ['.pdf','.docx']).",
        },
        "name_contains": {
            "type": "string",
            "description": "Optional substring that filenames must contain.",
        },
        "max_depth": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
        "max_seconds": {
            "type": "number",
            "minimum": 0.1,
            "maximum": 120,
            "default": 12,
            "description": "Time budget for the recursive search.",
        },
        "max_files": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5000,
            "default": 200,
            "description": "Maximum number of files to consider (speed/safety cap).",
        },
        "dry_run": {"type": "boolean", "default": False},
        "user_confirmation": {
            "type": "boolean",
            "enum": [True],
            "description": "Must be true to execute upload (not required for dry_run).",
        },
    },
    "required": ["drive_folder_name", "extensions"],
    "anyOf": [
        {"properties": {"dry_run": {"enum": [True]}}},
        {"required": ["user_confirmation"]},
    ],
    "additionalProperties": False,
}


APP_SYNC_LOCAL_FOLDER_TO_DRIVE_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "local_folder": {"type": "string", "minLength": 1},
        "drive_folder_name": {"type": "string", "minLength": 1},
        "parent_folder_id": {"type": "string", "minLength": 1},
        "pattern": {"type": "string", "default": "*", "description": "Glob pattern (e.g. '*.pdf')."},
        "max_depth": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
        "max_seconds": {"type": "number", "minimum": 0.1, "maximum": 300, "default": 12},
        "max_files": {"type": "integer", "minimum": 1, "maximum": 20000, "default": 200},
        "dry_run": {"type": "boolean", "default": False},
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["local_folder", "drive_folder_name"],
    "anyOf": [{"properties": {"dry_run": {"enum": [True]}}}, {"required": ["user_confirmation"]}],
    "additionalProperties": False,
}


APP_ORGANIZE_DIRECTORY_BY_TYPE_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "root_dir": {"type": "string", "minLength": 1},
        "max_depth": {"type": "integer", "minimum": 0, "maximum": 10, "default": 1},
        "max_seconds": {"type": "number", "minimum": 0.1, "maximum": 120, "default": 10},
        "max_files": {"type": "integer", "minimum": 1, "maximum": 50000, "default": 5000},
        "dry_run": {"type": "boolean", "default": False},
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["root_dir"],
    "anyOf": [{"properties": {"dry_run": {"enum": [True]}}}, {"required": ["user_confirmation"]}],
    "additionalProperties": False,
}


APP_EMAIL_PDF_PIPELINE_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "gmail_query": {"type": "string", "description": "Gmail search query."},
        "max_messages": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        "drive_folder_name": {"type": "string", "minLength": 1},
        "parent_folder_id": {"type": "string", "minLength": 1},
        "label_name": {"type": "string", "description": "Optional Gmail label to apply."},
        "dry_run": {"type": "boolean", "default": False},
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["drive_folder_name"],
    "anyOf": [{"properties": {"dry_run": {"enum": [True]}}}, {"required": ["user_confirmation"]}],
    "additionalProperties": False,
}


APP_WEEKLY_MAIL_DIGEST_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "gmail_query": {"type": "string", "description": "Gmail search query (default: newer_than:7d)."},
        "max_messages": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
        "send_email": {"type": "boolean", "default": False},
        "to": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 3}},
        "subject": {"type": "string"},
        "dry_run": {"type": "boolean", "default": False},
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": [],
    "anyOf": [
        {"properties": {"send_email": {"enum": [False]}}},
        {"required": ["to", "user_confirmation"]},
        {"properties": {"dry_run": {"enum": [True]}}},
    ],
    "additionalProperties": False,
}


APP_BULK_RENAME_FILES_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "root_dir": {"type": "string", "minLength": 1},
        "pattern": {"type": "string", "default": "*"},
        "find": {"type": "string", "minLength": 1},
        "replace": {"type": "string", "default": ""},
        "use_regex": {"type": "boolean", "default": False},
        "max_depth": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
        "max_seconds": {"type": "number", "minimum": 0.1, "maximum": 120, "default": 10},
        "max_files": {"type": "integer", "minimum": 1, "maximum": 50000, "default": 5000},
        "dry_run": {"type": "boolean", "default": False},
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["root_dir", "find"],
    "anyOf": [{"properties": {"dry_run": {"enum": [True]}}}, {"required": ["user_confirmation"]}],
    "additionalProperties": False,
}


APP_AUTO_BACKUP_FOLDER_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "src_folder": {"type": "string", "minLength": 1},
        "backup_dir": {"type": "string", "minLength": 1},
        "backup_name": {"type": "string"},
        "drive_folder_name": {"type": "string"},
        "parent_folder_id": {"type": "string", "minLength": 1},
        "dry_run": {"type": "boolean", "default": False},
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["src_folder", "backup_dir"],
    "anyOf": [{"properties": {"dry_run": {"enum": [True]}}}, {"required": ["user_confirmation"]}],
    "additionalProperties": False,
}


APP_FIND_LARGE_FILES_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "root": {"type": "string", "minLength": 1},
        "pattern": {"type": "string", "default": "*"},
        "top_n": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
        "max_depth": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
        "max_seconds": {"type": "number", "minimum": 0.1, "maximum": 120, "default": 10},
        "max_files": {"type": "integer", "minimum": 1, "maximum": 200000, "default": 20000},
    },
    "required": ["root"],
    "additionalProperties": False,
}


APP_CLEAN_TEMP_FILES_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "root": {"type": "string", "minLength": 1},
        "patterns": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
        "min_age_days": {"type": "integer", "minimum": 0, "maximum": 3650, "default": 7},
        "max_depth": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
        "max_seconds": {"type": "number", "minimum": 0.1, "maximum": 120, "default": 10},
        "max_files": {"type": "integer", "minimum": 1, "maximum": 50000, "default": 5000},
        "dry_run": {"type": "boolean", "default": False},
        "user_confirmation": {"type": "boolean", "enum": [True]},
    },
    "required": ["root"],
    "anyOf": [{"properties": {"dry_run": {"enum": [True]}}}, {"required": ["user_confirmation"]}],
    "additionalProperties": False,
}

SEND_EMAIL_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "to": {"type": "array", "items": {"type": "string", "minLength": 3}, "minItems": 1},
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "attachment_file_ids": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "user_confirmation": {"type": "boolean", "default": False},
    },
    "required": ["to", "subject", "body", "user_confirmation"],
    "additionalProperties": False,
}


SEND_EMAIL_WITH_ATTACHMENTS_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "to": {"type": "array", "items": {"type": "string", "minLength": 3}, "minItems": 1},
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "attachment_file_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
        },
        "user_confirmation": {"type": "boolean", "default": False},
    },
    "required": ["to", "subject", "body", "attachment_file_ids", "user_confirmation"],
    "additionalProperties": False,
}


UPLOAD_LIST_FILES_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
    },
    "required": [],
    "additionalProperties": False,
}


UPLOAD_GET_FILE_INFO_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {"file_id": {"type": "string", "minLength": 1}},
    "required": ["file_id"],
    "additionalProperties": False,
}


UPLOAD_DELETE_FILE_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "file_id": {"type": "string", "minLength": 1},
        "user_confirmation": {"type": "boolean", "default": False},
    },
    "required": ["file_id", "user_confirmation"],
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


FS_SEARCH_RECURSIVE_PARAMS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "root": {
            "type": "string",
            "minLength": 1,
            "description": "Optional root directory to search. If omitted, the server searches common user folders (Desktop/Documents/Downloads) within the allowed filesystem policy.",
        },
        "root_path": {
            "type": "string",
            "minLength": 1,
            "description": "Alias for root (accepted for robustness).",
        },
        "pattern": {"type": "string", "default": "*"},
        "extensions": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
            "description": "Optional list of file extensions to include (e.g. ['.pdf','.docx']).",
        },
        "name_contains": {
            "type": "string",
            "description": "Optional substring that filenames must contain.",
        },
        "max_results": {"type": "integer", "minimum": 1, "maximum": 20000, "default": 1000},
        "include_dirs": {"type": "boolean", "default": False},
        "max_depth": {
            "type": "integer",
            "minimum": 0,
            "maximum": 50,
            "description": "Optional recursion depth limit relative to root.",
        },
        "max_seconds": {
            "type": "number",
            "minimum": 0.1,
            "maximum": 120,
            "default": 10,
            "description": "Time budget for the search; returns truncated=true when exceeded.",
        },
    },
    "required": [],
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
    "gmail_list_attachments": GMAIL_LIST_ATTACHMENTS_PARAMS_SCHEMA,
    "gmail_download_attachment": GMAIL_DOWNLOAD_ATTACHMENT_PARAMS_SCHEMA,
    "gmail_apply_label": GMAIL_APPLY_LABEL_PARAMS_SCHEMA,
    "gmail_trash_message": GMAIL_TRASH_MESSAGE_PARAMS_SCHEMA,
    "list_drive_files": LIST_DRIVE_FILES_PARAMS_SCHEMA,
    "get_drive_file": GET_DRIVE_FILE_PARAMS_SCHEMA,
    "drive_ensure_folder": DRIVE_ENSURE_FOLDER_PARAMS_SCHEMA,
    "drive_upload_file": DRIVE_UPLOAD_FILE_PARAMS_SCHEMA,
    "drive_upload_local_file": DRIVE_UPLOAD_LOCAL_FILE_PARAMS_SCHEMA,
    "drive_list_folders": DRIVE_LIST_FOLDERS_PARAMS_SCHEMA,
    "drive_create_folder": DRIVE_CREATE_FOLDER_PARAMS_SCHEMA,
    "drive_rename_folder": DRIVE_RENAME_FOLDER_PARAMS_SCHEMA,
    "drive_move_folder": DRIVE_MOVE_FOLDER_PARAMS_SCHEMA,
    "drive_delete_folder": DRIVE_DELETE_FOLDER_PARAMS_SCHEMA,
    "send_email": SEND_EMAIL_PARAMS_SCHEMA,
    "send_email_with_attachments": SEND_EMAIL_WITH_ATTACHMENTS_PARAMS_SCHEMA,
    "upload_list_files": UPLOAD_LIST_FILES_PARAMS_SCHEMA,
    "upload_get_file_info": UPLOAD_GET_FILE_INFO_PARAMS_SCHEMA,
    "upload_delete_file": UPLOAD_DELETE_FILE_PARAMS_SCHEMA,
    "local_list_dir": LOCAL_LIST_DIR_PARAMS_SCHEMA,
    "local_read_text": LOCAL_READ_TEXT_PARAMS_SCHEMA,
    "local_write_text": LOCAL_WRITE_TEXT_PARAMS_SCHEMA,
    "local_delete_path": LOCAL_DELETE_PATH_PARAMS_SCHEMA,
    "local_search_files": LOCAL_SEARCH_FILES_PARAMS_SCHEMA,
    "fs_list_dir": FS_LIST_DIR_PARAMS_SCHEMA,
    "fs_search_files": FS_SEARCH_FILES_PARAMS_SCHEMA,
    "fs_search_recursive": FS_SEARCH_RECURSIVE_PARAMS_SCHEMA,
    "fs_read_file": FS_READ_FILE_PARAMS_SCHEMA,
    "fs_write_file": FS_WRITE_FILE_PARAMS_SCHEMA,
    "fs_delete_path": FS_DELETE_PATH_PARAMS_SCHEMA,
    "fs_move_path": FS_MOVE_PATH_PARAMS_SCHEMA,
    "fs_mkdir": FS_MKDIR_PARAMS_SCHEMA,
    "system_get_user_info": SYSTEM_GET_USER_INFO_PARAMS_SCHEMA,
    "system_get_paths": SYSTEM_GET_PATHS_PARAMS_SCHEMA,
    "system_get_environment_variable": SYSTEM_GET_ENV_VAR_PARAMS_SCHEMA,
    "app_state_get": APP_STATE_GET_PARAMS_SCHEMA,
    "app_state_set": APP_STATE_SET_PARAMS_SCHEMA,
    "app_upload_files_to_drive": APP_UPLOAD_FILES_TO_DRIVE_PARAMS_SCHEMA,
    "app_sync_local_folder_to_drive": APP_SYNC_LOCAL_FOLDER_TO_DRIVE_PARAMS_SCHEMA,
    "app_organize_directory_by_type": APP_ORGANIZE_DIRECTORY_BY_TYPE_PARAMS_SCHEMA,
    "app_email_pdf_pipeline": APP_EMAIL_PDF_PIPELINE_PARAMS_SCHEMA,
    "app_weekly_mail_digest": APP_WEEKLY_MAIL_DIGEST_PARAMS_SCHEMA,
    "app_bulk_rename_files": APP_BULK_RENAME_FILES_PARAMS_SCHEMA,
    "app_auto_backup_folder": APP_AUTO_BACKUP_FOLDER_PARAMS_SCHEMA,
    "app_find_large_files": APP_FIND_LARGE_FILES_PARAMS_SCHEMA,
    "app_clean_temp_files": APP_CLEAN_TEMP_FILES_PARAMS_SCHEMA,
    "policy_get": POLICY_GET_PARAMS_SCHEMA,
    "policy_set_mode": POLICY_SET_MODE_PARAMS_SCHEMA,
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
            "name": "app_upload_files_to_drive",
            "description": "Recursively search local files and upload them to a Drive folder (fast single-call).",
            "parameters": APP_UPLOAD_FILES_TO_DRIVE_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_sync_local_folder_to_drive",
            "description": "Sync a local folder to Drive by uploading new content (SHA256 dedupe).",
            "parameters": APP_SYNC_LOCAL_FOLDER_TO_DRIVE_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_organize_directory_by_type",
            "description": "Organize files in a directory into subfolders by type (documents/images/etc).",
            "parameters": APP_ORGANIZE_DIRECTORY_BY_TYPE_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_email_pdf_pipeline",
            "description": "Fetch PDF attachments from Gmail and upload them to Drive (optional label).",
            "parameters": APP_EMAIL_PDF_PIPELINE_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_weekly_mail_digest",
            "description": "Generate a weekly digest from Gmail; optionally email it (confirmation required).",
            "parameters": APP_WEEKLY_MAIL_DIGEST_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_bulk_rename_files",
            "description": "Bulk rename files under a directory using simple replace or regex.",
            "parameters": APP_BULK_RENAME_FILES_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_auto_backup_folder",
            "description": "Create a zip backup of a folder; optionally upload the zip to Drive (SHA256 dedupe).",
            "parameters": APP_AUTO_BACKUP_FOLDER_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_find_large_files",
            "description": "Find the largest files under a directory.",
            "parameters": APP_FIND_LARGE_FILES_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_clean_temp_files",
            "description": "Delete temp-like files under a directory (dry_run supported; confirmation required).",
            "parameters": APP_CLEAN_TEMP_FILES_PARAMS_SCHEMA,
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
            "name": "gmail_list_attachments",
            "description": "List attachments for a Gmail message (filename, mime_type, size_bytes, attachment_id).",
            "parameters": GMAIL_LIST_ATTACHMENTS_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_download_attachment",
            "description": "Download a Gmail attachment (returns base64 bytes + metadata).",
            "parameters": GMAIL_DOWNLOAD_ATTACHMENT_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_apply_label",
            "description": "Apply a label to a Gmail message (creates label if missing).",
            "parameters": GMAIL_APPLY_LABEL_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_trash_message",
            "description": "Move a Gmail message to trash (requires explicit user_confirmation=true).",
            "parameters": GMAIL_TRASH_MESSAGE_PARAMS_SCHEMA,
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
            "name": "drive_ensure_folder",
            "description": "Ensure a Drive folder exists by name (optionally under a parent). Returns folder_id.",
            "parameters": DRIVE_ENSURE_FOLDER_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drive_upload_file",
            "description": "Upload a file to Drive from base64 content into a folder.",
            "parameters": DRIVE_UPLOAD_FILE_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drive_upload_local_file",
            "description": "Upload a local file to Drive by path (avoids base64 in the prompt).",
            "parameters": DRIVE_UPLOAD_LOCAL_FILE_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drive_list_folders",
            "description": "List Drive folders (optionally filtered by parent_folder_id and/or Drive query).",
            "parameters": DRIVE_LIST_FOLDERS_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drive_create_folder",
            "description": "Create a Drive folder (may create duplicates).",
            "parameters": DRIVE_CREATE_FOLDER_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drive_rename_folder",
            "description": "Rename a Drive folder.",
            "parameters": DRIVE_RENAME_FOLDER_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drive_move_folder",
            "description": "Move a Drive folder under a new parent folder.",
            "parameters": DRIVE_MOVE_FOLDER_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drive_delete_folder",
            "description": "Delete a Drive folder (requires explicit user_confirmation=true).",
            "parameters": DRIVE_DELETE_FOLDER_PARAMS_SCHEMA,
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
            "name": "send_email_with_attachments",
            "description": "Send an email with uploaded attachments (requires explicit user_confirmation=true).",
            "parameters": SEND_EMAIL_WITH_ATTACHMENTS_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upload_list_files",
            "description": "List uploaded files available for attachment by file_id.",
            "parameters": UPLOAD_LIST_FILES_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upload_get_file_info",
            "description": "Get metadata about an uploaded file by file_id.",
            "parameters": UPLOAD_GET_FILE_INFO_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upload_delete_file",
            "description": "Delete an uploaded file by file_id (requires explicit user_confirmation=true).",
            "parameters": UPLOAD_DELETE_FILE_PARAMS_SCHEMA,
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
            "name": "fs_search_recursive",
            "description": "Recursively search files under a root with time/depth limits (ACCESS_MODE enforced).",
            "parameters": FS_SEARCH_RECURSIVE_PARAMS_SCHEMA,
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
            "name": "app_state_get",
            "description": "Read persistent app state by key.",
            "parameters": APP_STATE_GET_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_state_set",
            "description": "Write persistent app state by key (requires explicit user_confirmation=true).",
            "parameters": APP_STATE_SET_PARAMS_SCHEMA,
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
    {
        "type": "function",
        "function": {
            "name": "policy_get",
            "description": "Get current effective security policy (safe to display).",
            "parameters": POLICY_GET_PARAMS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "policy_set_mode",
            "description": "Set security policy access_mode (requires explicit confirmation).",
            "parameters": POLICY_SET_MODE_PARAMS_SCHEMA,
        },
    },
]
