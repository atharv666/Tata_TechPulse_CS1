"""Safe upload validation; filenames are metadata and are never trusted file paths."""

from __future__ import annotations

import hashlib
from pathlib import PurePath

from app.ingestion.contracts import DocumentFormat, IngestionError

FORMAT_BY_EXTENSION = {
    ".pdf": DocumentFormat.PDF,
    ".docx": DocumentFormat.DOCX,
    ".xlsx": DocumentFormat.XLSX,
    ".csv": DocumentFormat.CSV,
    ".md": DocumentFormat.MARKDOWN,
    ".markdown": DocumentFormat.MARKDOWN,
}
MIME_BY_FORMAT = {
    DocumentFormat.PDF: {"application/pdf"},
    DocumentFormat.DOCX: {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    },
    DocumentFormat.XLSX: {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    DocumentFormat.CSV: {"text/csv", "application/csv", "text/plain"},
    DocumentFormat.MARKDOWN: {"text/markdown", "text/plain"},
}


def safe_filename(filename: str) -> str:
    """Return a display name only; strip all supplied directory components."""
    cleaned = PurePath(filename.replace("\\", "/")).name.strip()
    if not cleaned or cleaned in {".", ".."} or "\x00" in cleaned:
        raise IngestionError("Uploaded filename is invalid.")
    return cleaned[:512]


def validate_upload(
    filename: str, media_type: str | None, content: bytes, max_bytes: int
) -> DocumentFormat:
    """Validate size, extension, simple signatures, and declared MIME when available."""
    safe_name = safe_filename(filename)
    if not content:
        raise IngestionError("Uploaded file is empty.")
    if len(content) > max_bytes:
        raise IngestionError("Uploaded file exceeds configured size limit.")
    document_format = FORMAT_BY_EXTENSION.get(PurePath(safe_name).suffix.lower())
    if document_format is None:
        raise IngestionError("Uploaded file type is not supported.")
    if media_type and media_type.lower() not in MIME_BY_FORMAT[document_format]:
        raise IngestionError("Declared MIME type does not match the uploaded file extension.")
    if document_format is DocumentFormat.PDF and not content.startswith(b"%PDF-"):
        raise IngestionError("Uploaded PDF does not have a valid PDF signature.")
    if document_format in {DocumentFormat.DOCX, DocumentFormat.XLSX} and not content.startswith(
        b"PK"
    ):
        raise IngestionError("Uploaded Office document does not have a valid ZIP signature.")
    return document_format


def content_hash(content: bytes) -> str:
    """Return the immutable SHA-256 source checksum used for duplicate detection."""
    return hashlib.sha256(content).hexdigest()
