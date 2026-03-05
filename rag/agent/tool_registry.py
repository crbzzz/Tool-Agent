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
    from rag.tools.apps import (
        app_auto_backup_folder,
        app_bulk_rename_files,
        app_clean_temp_files,
        app_email_pdf_pipeline,
        app_find_large_files,
        app_organize_directory_by_type,
        app_sync_local_folder_to_drive,
        app_upload_files_to_drive,
        app_weekly_mail_digest,
    )
    from rag.tools.documents import (
        doc_detect_type,
        doc_extract_any,
        doc_extract_docx_text,
        doc_extract_pdf_text,
        doc_ocr_image,
        doc_read_text,
    )
    from rag.tools.drive import (
        drive_create_folder,
        drive_delete_folder,
        drive_ensure_folder,
        drive_list_folders,
        drive_move_folder,
        drive_rename_folder,
        drive_upload_local_file,
        drive_upload_file,
        get_drive_file,
        list_drive_files,
    )
    from rag.tools.email_send import send_email, send_email_with_attachments
    from rag.tools.uploads import upload_delete_file, upload_get_file_info, upload_list_files
    from rag.tools.fs import (
        fs_delete_path,
        fs_list_dir,
        fs_mkdir,
        fs_move_path,
        fs_read_file,
        fs_search_files,
        fs_search_recursive,
        fs_write_file,
    )
    from rag.tools.gmail import (
        get_email,
        gmail_apply_label,
        gmail_download_attachment,
        gmail_list_attachments,
        gmail_trash_message,
        list_emails,
    )
    from rag.tools.app_state import app_state_get, app_state_set
    from rag.tools.local_fs import (
        local_delete_path,
        local_list_dir,
        local_read_text,
        local_search_files,
        local_write_text,
    )
    from rag.tools.rag_ingest_extracted import ingest_extracted
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
            "doc_detect_type": doc_detect_type,
            "doc_read_text": doc_read_text,
            "doc_extract_pdf_text": doc_extract_pdf_text,
            "doc_ocr_image": doc_ocr_image,
            "doc_extract_docx_text": doc_extract_docx_text,
            "doc_extract_any": doc_extract_any,
            "rag_ingest_extracted": ingest_extracted,
            "fetch_url": fetch_url,
            "search_web": search_web,
            "list_emails": list_emails,
            "get_email": get_email,
            "gmail_list_attachments": gmail_list_attachments,
            "gmail_download_attachment": gmail_download_attachment,
            "gmail_apply_label": gmail_apply_label,
            "gmail_trash_message": gmail_trash_message,
            "list_drive_files": list_drive_files,
            "get_drive_file": get_drive_file,
            "drive_ensure_folder": drive_ensure_folder,
            "drive_upload_file": drive_upload_file,
            "drive_upload_local_file": drive_upload_local_file,
            "drive_list_folders": drive_list_folders,
            "drive_create_folder": drive_create_folder,
            "drive_rename_folder": drive_rename_folder,
            "drive_move_folder": drive_move_folder,
            "drive_delete_folder": drive_delete_folder,
            "send_email": send_email,
            "send_email_with_attachments": send_email_with_attachments,
            "app_state_get": app_state_get,
            "app_state_set": app_state_set,
            # Macro app_* tools
            "app_upload_files_to_drive": app_upload_files_to_drive,
            "app_sync_local_folder_to_drive": app_sync_local_folder_to_drive,
            "app_organize_directory_by_type": app_organize_directory_by_type,
            "app_email_pdf_pipeline": app_email_pdf_pipeline,
            "app_weekly_mail_digest": app_weekly_mail_digest,
            "app_bulk_rename_files": app_bulk_rename_files,
            "app_auto_backup_folder": app_auto_backup_folder,
            "app_find_large_files": app_find_large_files,
            "app_clean_temp_files": app_clean_temp_files,
            "upload_list_files": upload_list_files,
            "upload_get_file_info": upload_get_file_info,
            "upload_delete_file": upload_delete_file,
            "local_list_dir": local_list_dir,
            "local_read_text": local_read_text,
            "local_search_files": local_search_files,
            "local_write_text": local_write_text,
            "local_delete_path": local_delete_path,
            # fs_* tools (exact names expected by agent tool calls)
            "fs_list_dir": fs_list_dir,
            "fs_search_files": fs_search_files,
            "fs_search_recursive": fs_search_recursive,
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
