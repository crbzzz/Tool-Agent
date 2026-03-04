"""Document detection and extraction tools.

These tools sit "above" raw filesystem tools: they reuse the same server-side
path authorization as fs_* via rag.tools.fs.check_path_allowed.

Extraction strategy:
- Text files: read directly (bounded)
- PDF: extract text per page (bounded)
- DOCX: extract paragraph text (bounded)
- Images: OCR via pytesseract (requires local Tesseract install)

All outputs are best-effort and should be treated as untrusted by the agent.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rag.tools.fs import check_path_allowed

logger = logging.getLogger(__name__)


_TEXT_EXTS = {
    ".txt",
    ".md",
    ".markdown",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".csv",
    ".log",
}

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def _safe_stat(path: Path) -> Tuple[Optional[int], Optional[bool]]:
    try:
        st = path.stat()
        return int(st.st_size), bool(path.is_file())
    except Exception:
        return None, None


def doc_detect_type(args: Dict[str, Any]) -> Dict[str, Any]:
    path, err = check_path_allowed(args.get("path"))
    if err:
        return {"ok": False, "data": None, "error": err}

    if not path.exists():
        return {"ok": False, "data": None, "error": "Path does not exist"}
    if not path.is_file():
        return {"ok": False, "data": None, "error": "Path is not a file"}

    ext = path.suffix.lower()
    mime_guess, _enc = mimetypes.guess_type(str(path))
    size_bytes, _is_file = _safe_stat(path)

    return {
        "ok": True,
        "data": {
            "path": str(path),
            "mime_guess": mime_guess or "application/octet-stream",
            "extension": ext or "",
            "size_bytes": size_bytes,
        },
        "error": None,
    }


def doc_read_text(args: Dict[str, Any]) -> Dict[str, Any]:
    path, err = check_path_allowed(args.get("path"))
    if err:
        return {"ok": False, "data": None, "error": err}

    max_chars = args.get("max_chars", 50_000)
    if not isinstance(max_chars, int) or max_chars < 200 or max_chars > 200_000:
        return {"ok": False, "data": None, "error": "Invalid max_chars (200..200000)"}

    encoding_hint = args.get("encoding_hint")
    if encoding_hint is not None and not isinstance(encoding_hint, str):
        return {"ok": False, "data": None, "error": "Invalid encoding_hint"}

    if not path.exists():
        return {"ok": False, "data": None, "error": "Path does not exist"}
    if not path.is_file():
        return {"ok": False, "data": None, "error": "Path is not a file"}

    try:
        raw = path.read_bytes()
    except Exception as exc:
        return {"ok": False, "data": None, "error": f"Read failed: {exc}"}

    # Best-effort heuristic: refuse NUL-containing files as text
    if b"\x00" in raw[:4096]:
        return {"ok": False, "data": None, "error": "File appears binary"}

    enc = (encoding_hint or "utf-8").strip() or "utf-8"
    text = raw.decode(enc, errors="replace")
    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True

    return {
        "ok": True,
        "data": {
            "path": str(path),
            "text": text,
            "truncated": truncated,
            "encoding_used": enc,
        },
        "error": None,
    }


def doc_extract_pdf_text(args: Dict[str, Any]) -> Dict[str, Any]:
    path, err = check_path_allowed(args.get("path"))
    if err:
        return {"ok": False, "data": None, "error": err}

    page_start = args.get("page_start")
    page_end = args.get("page_end")
    max_chars_per_page = args.get("max_chars_per_page", 20_000)

    if page_start is not None and (not isinstance(page_start, int) or page_start < 0):
        return {"ok": False, "data": None, "error": "Invalid page_start"}
    if page_end is not None and (not isinstance(page_end, int) or page_end < 0):
        return {"ok": False, "data": None, "error": "Invalid page_end"}
    if not isinstance(max_chars_per_page, int) or max_chars_per_page < 200 or max_chars_per_page > 50_000:
        return {"ok": False, "data": None, "error": "Invalid max_chars_per_page (200..50000)"}

    if not path.exists():
        return {"ok": False, "data": None, "error": "Path does not exist"}
    if not path.is_file():
        return {"ok": False, "data": None, "error": "Path is not a file"}

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        num_pages = len(reader.pages)

        start = int(page_start) if page_start is not None else 0
        # If page_end missing, take a small slice (0..5) to avoid huge reads.
        default_end = min(num_pages - 1, start + 5)
        end = int(page_end) if page_end is not None else default_end

        if start >= num_pages:
            return {"ok": False, "data": None, "error": f"page_start out of range (num_pages={num_pages})"}
        if end < start:
            end = start
        end = min(end, num_pages - 1)

        pages: List[Dict[str, Any]] = []
        for idx in range(start, end + 1):
            try:
                txt = reader.pages[idx].extract_text() or ""
            except Exception:
                txt = ""
            if len(txt) > max_chars_per_page:
                txt = txt[:max_chars_per_page]
            pages.append({"page": idx, "text": txt})

        return {
            "ok": True,
            "data": {"num_pages": num_pages, "pages": pages},
            "error": None,
        }
    except Exception as exc:
        logger.exception("doc_extract_pdf_text failed")
        return {"ok": False, "data": None, "error": f"PDF extraction failed: {exc}"}


def doc_extract_docx_text(args: Dict[str, Any]) -> Dict[str, Any]:
    path, err = check_path_allowed(args.get("path"))
    if err:
        return {"ok": False, "data": None, "error": err}

    max_chars = args.get("max_chars", 200_000)
    if not isinstance(max_chars, int) or max_chars < 200 or max_chars > 400_000:
        return {"ok": False, "data": None, "error": "Invalid max_chars (200..400000)"}

    if not path.exists():
        return {"ok": False, "data": None, "error": "Path does not exist"}
    if not path.is_file():
        return {"ok": False, "data": None, "error": "Path is not a file"}

    try:
        from docx import Document

        doc = Document(str(path))
        parts: List[str] = []
        for p in doc.paragraphs:
            t = (p.text or "").strip()
            if t:
                parts.append(t)

        text = "\n".join(parts)
        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars]
            truncated = True

        return {
            "ok": True,
            "data": {
                "path": str(path),
                "text": text,
                "truncated": truncated,
            },
            "error": None,
        }
    except Exception as exc:
        logger.exception("doc_extract_docx_text failed")
        return {"ok": False, "data": None, "error": f"DOCX extraction failed: {exc}"}


def doc_ocr_image(args: Dict[str, Any]) -> Dict[str, Any]:
    path, err = check_path_allowed(args.get("path"))
    if err:
        return {"ok": False, "data": None, "error": err}

    max_chars = args.get("max_chars", 50_000)
    if not isinstance(max_chars, int) or max_chars < 200 or max_chars > 200_000:
        return {"ok": False, "data": None, "error": "Invalid max_chars (200..200000)"}

    language = args.get("language")
    if language is not None and not isinstance(language, str):
        return {"ok": False, "data": None, "error": "Invalid language"}

    if not path.exists():
        return {"ok": False, "data": None, "error": "Path does not exist"}
    if not path.is_file():
        return {"ok": False, "data": None, "error": "Path is not a file"}

    try:
        from PIL import Image
        import pytesseract

        # Validate Tesseract presence early for clearer errors.
        try:
            _ = pytesseract.get_tesseract_version()
        except Exception as exc:
            return {
                "ok": False,
                "data": None,
                "error": (
                    "OCR backend not available (Tesseract not installed/configured). "
                    "Install Tesseract OCR and ensure it is on PATH, then retry. "
                    f"Details: {exc}"
                ),
            }

        img = Image.open(str(path))
        txt = pytesseract.image_to_string(img, lang=(language or "eng"))
        txt = (txt or "").strip()
        truncated = False
        if len(txt) > max_chars:
            txt = txt[:max_chars]
            truncated = True

        return {
            "ok": True,
            "data": {"path": str(path), "text": txt, "truncated": truncated},
            "error": None,
        }
    except Exception as exc:
        logger.exception("doc_ocr_image failed")
        return {"ok": False, "data": None, "error": f"OCR failed: {exc}"}


def doc_extract_any(args: Dict[str, Any]) -> Dict[str, Any]:
    path, err = check_path_allowed(args.get("path"))
    if err:
        return {"ok": False, "data": None, "error": err}

    max_chars = args.get("max_chars", 200_000)
    if not isinstance(max_chars, int) or max_chars < 200 or max_chars > 400_000:
        return {"ok": False, "data": None, "error": "Invalid max_chars (200..400000)"}

    prefer_ocr = bool(args.get("prefer_ocr", False))

    if not path.exists():
        return {"ok": False, "data": None, "error": "Path does not exist"}
    if not path.is_file():
        return {"ok": False, "data": None, "error": "Path is not a file"}

    ext = path.suffix.lower()
    mime_guess, _enc = mimetypes.guess_type(str(path))

    # Decide type.
    doc_type = "binary"
    if ext == ".pdf" or (mime_guess == "application/pdf"):
        doc_type = "pdf"
    elif ext == ".docx" or (mime_guess in {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}):
        doc_type = "docx"
    elif ext in _IMAGE_EXTS or (mime_guess or "").startswith("image/"):
        doc_type = "image"
    elif ext in _TEXT_EXTS or (mime_guess or "").startswith("text/"):
        doc_type = "text"

    if doc_type == "text":
        r = doc_read_text({"path": str(path), "max_chars": min(max_chars, 200_000)})
        if not r.get("ok"):
            return r
        return {
            "ok": True,
            "data": {
                "path": str(path),
                "type": "text",
                "extracted_text": (r.get("data") or {}).get("text", ""),
                "pages": None,
            },
            "error": None,
        }

    if doc_type == "docx":
        r = doc_extract_docx_text({"path": str(path), "max_chars": max_chars})
        if not r.get("ok"):
            return r
        return {
            "ok": True,
            "data": {
                "path": str(path),
                "type": "docx",
                "extracted_text": (r.get("data") or {}).get("text", ""),
                "pages": None,
            },
            "error": None,
        }

    if doc_type == "image":
        # For images, OCR is the only extraction we support.
        r = doc_ocr_image({"path": str(path), "max_chars": max_chars})
        if not r.get("ok"):
            return r
        return {
            "ok": True,
            "data": {
                "path": str(path),
                "type": "image",
                "extracted_text": (r.get("data") or {}).get("text", ""),
                "pages": None,
            },
            "error": None,
        }

    if doc_type == "pdf":
        # PDFs: extract by page. If prefer_ocr, we still do text-extraction here
        # (OCR per page requires rasterization, not implemented).
        # Keep bounded slice to avoid huge extraction.
        r = doc_extract_pdf_text({"path": str(path)})
        if not r.get("ok"):
            return r
        pages = (r.get("data") or {}).get("pages") or []
        collected: List[str] = []
        total = 0
        for p in pages:
            t = (p or {}).get("text") or ""
            if not t:
                continue
            remaining = max_chars - total
            if remaining <= 0:
                break
            if len(t) > remaining:
                collected.append(t[:remaining])
                total = max_chars
                break
            collected.append(t)
            total += len(t)

        return {
            "ok": True,
            "data": {
                "path": str(path),
                "type": "pdf",
                "extracted_text": "\n\n".join(collected).strip(),
                "pages": pages,
                "note": "PDF extraction is limited to a small page slice unless you call doc_extract_pdf_text with explicit page ranges.",
                "prefer_ocr": prefer_ocr,
            },
            "error": None,
        }

    return {
        "ok": False,
        "data": None,
        "error": f"Unsupported document type for extension '{ext}' (mime={mime_guess})",
    }
