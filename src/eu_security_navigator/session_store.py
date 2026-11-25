from __future__ import annotations

import hashlib
import io
import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pypdf import PdfReader
from pypdf.errors import PdfReadError

ALLOWED_EXTENSIONS = frozenset({".pdf", ".json"})


@dataclass(frozen=True)
class SessionLimits:
    max_files: int = 50
    max_file_bytes: int = 25 * 1024 * 1024
    max_total_bytes: int = 100 * 1024 * 1024
    max_pdf_pages: int = 500
    max_json_depth: int = 64
    max_json_fields: int = 50_000


class ImportValidationError(Exception):
    """Raised when an uploaded file violates format, content, or size constraints."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class PdfPageRecord:
    page_number: int
    text: str
    searchable_text: str


@dataclass(frozen=True)
class JsonFieldRecord:
    field_path: str
    display_path: str
    key_name: str
    value_text: str
    searchable_text: str


@dataclass
class SessionDocument:
    document_id: str
    filename: str
    file_type: str
    size_bytes: int
    sha256: str
    imported_at: str
    warnings: list[str] = field(default_factory=list)
    pdf_bytes: bytes | None = None
    pdf_pages: list[PdfPageRecord] = field(default_factory=list)
    json_data: Any = None
    json_fields: list[JsonFieldRecord] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "file_type": self.file_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "imported_at": self.imported_at,
            "page_count": len(self.pdf_pages) if self.file_type == "pdf" else None,
            "field_count": len(self.json_fields) if self.file_type == "json" else None,
            "warnings": list(self.warnings),
        }


def sanitize_filename(raw_name: str | None) -> str:
    if not raw_name:
        raise ImportValidationError("Uploaded file is missing a filename.", status_code=400)

    normalized = raw_name.replace("\\", "/")
    basename = Path(normalized).name.strip()
    if not basename or basename in {".", ".."}:
        raise ImportValidationError("Invalid filename.", status_code=400)

    if any(ord(ch) < 32 for ch in basename):
        raise ImportValidationError(
            "Filename contains invalid control characters.",
            status_code=400,
        )

    return basename


def _normalize_pdf_text(text: str) -> str:
    # Join soft line-break hyphenation common in German and English PDFs.
    joined = re.sub(r"([A-Za-zÄÖÜäöüß])-\r?\n([a-zäöüß])", r"\1\2", text)
    return re.sub(r"\s+", " ", joined).strip()


def _json_pointer_escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _json_pointer_unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _format_display_path(tokens: list[str | int]) -> str:
    if not tokens:
        return "$"

    parts: list[str] = []
    for token in tokens:
        if isinstance(token, int):
            if not parts:
                parts.append(f"$[{token}]")
            else:
                parts[-1] = f"{parts[-1]}[{token}]"
        else:
            if not parts:
                parts.append(token)
            elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
                parts.append(f".{token}")
            else:
                parts.append(f"[{json.dumps(token, ensure_ascii=False)}]")
    return "".join(parts)


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _make_excerpt(text: str, phrase: str, fallback_term: str, length: int = 280) -> str:
    clean_text = re.sub(r"\s+", " ", text).strip()
    if not clean_text:
        return ""

    lowered = clean_text.casefold()
    position = lowered.find(phrase)
    if position < 0:
        position = lowered.find(fallback_term)

    if position < 0:
        suffix = "…" if len(clean_text) > length else ""
        return f"{clean_text[:length]}{suffix}"

    start = max(0, position - 80)
    end = min(len(clean_text), position + length)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(clean_text) else ""
    return f"{prefix}{clean_text[start:end]}{suffix}"


def extract_pdf_pages(
    raw_bytes: bytes,
    filename: str,
    max_pages: int,
) -> tuple[list[PdfPageRecord], list[str]]:
    if not raw_bytes.lstrip().startswith(b"%PDF-"):
        raise ImportValidationError(
            f"'{filename}' is not a valid PDF file (missing %PDF header).",
            status_code=400,
        )

    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
    except (PdfReadError, Exception) as exc:
        raise ImportValidationError(
            f"Could not read PDF '{filename}': file may be corrupted or unsupported.",
            status_code=400,
        ) from exc

    if reader.is_encrypted:
        raise ImportValidationError(
            f"'{filename}' is encrypted or password-protected and cannot be indexed offline.",
            status_code=400,
        )

    total_pages = len(reader.pages)
    if total_pages == 0:
        raise ImportValidationError(f"'{filename}' contains no pages.", status_code=400)

    if total_pages > max_pages:
        raise ImportValidationError(
            f"'{filename}' has {total_pages} pages, exceeding the {max_pages}-page limit.",
            status_code=413,
        )

    pages: list[PdfPageRecord] = []
    empty_pages = 0

    for page_index, page in enumerate(reader.pages, start=1):
        try:
            raw_text = page.extract_text() or ""
        except Exception as exc:
            raise ImportValidationError(
                f"Failed to extract text from page {page_index} of '{filename}'.",
                status_code=400,
            ) from exc

        cleaned = _normalize_pdf_text(raw_text)
        if not cleaned:
            empty_pages += 1

        pages.append(
            PdfPageRecord(
                page_number=page_index,
                text=cleaned,
                searchable_text=cleaned.casefold(),
            )
        )

    if empty_pages == total_pages:
        raise ImportValidationError(
            f"'{filename}' has no extractable text. "
            "Scanned or image-only PDFs are not supported in this offline release.",
            status_code=422,
        )

    warnings: list[str] = []
    if empty_pages > 0:
        label = "page" if empty_pages == 1 else "pages"
        warnings.append(f"{empty_pages} {label} contained no extractable text.")

    return pages, warnings


def extract_json_fields(
    raw_bytes: bytes,
    filename: str,
    max_depth: int,
    max_fields: int,
) -> tuple[list[JsonFieldRecord], Any]:
    try:
        decoded = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportValidationError(
            f"'{filename}' is not valid UTF-8 text.",
            status_code=400,
        ) from exc

    try:
        parsed = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise ImportValidationError(
            f"'{filename}' is not valid JSON (line {exc.lineno}, column {exc.colno}: {exc.msg}).",
            status_code=400,
        ) from exc
    except RecursionError as exc:
        raise ImportValidationError(
            f"'{filename}' exceeds the maximum nesting depth of {max_depth}.",
            status_code=400,
        ) from exc

    fields: list[JsonFieldRecord] = []
    # Explicit stack avoids Python recursion limit issues on deeply nested inputs.
    stack: list[tuple[Any, list[str | int], int]] = [(parsed, [], 0)]

    while stack:
        current, tokens, depth = stack.pop()
        if depth > max_depth:
            raise ImportValidationError(
                f"'{filename}' exceeds the maximum JSON nesting depth of {max_depth}.",
                status_code=400,
            )

        if isinstance(current, dict):
            # Push in reverse order so fields are indexed in original document order.
            items = list(current.items())
            for key, value in reversed(items):
                stack.append((value, [*tokens, str(key)], depth + 1))
        elif isinstance(current, list):
            for idx in range(len(current) - 1, -1, -1):
                stack.append((current[idx], [*tokens, idx], depth + 1))
        else:
            if len(fields) >= max_fields:
                raise ImportValidationError(
                    f"'{filename}' exceeds the {max_fields}-field limit for JSON indexing.",
                    status_code=413,
                )

            pointer = (
                "/" + "/".join(_json_pointer_escape(str(tok)) for tok in tokens)
                if tokens
                else "/"
            )
            display_path = _format_display_path(tokens)
            key_name = str(tokens[-1]) if tokens else "$"
            value_text = _format_scalar(current)
            combined = f"{display_path} {key_name}: {value_text}".strip()

            fields.append(
                JsonFieldRecord(
                    field_path=pointer,
                    display_path=display_path,
                    key_name=key_name,
                    value_text=value_text,
                    searchable_text=combined.casefold(),
                )
            )

    if not fields:
        raise ImportValidationError(
            f"'{filename}' contains no searchable JSON fields.",
            status_code=422,
        )

    return fields, parsed


def _resolve_json_pointer(data: Any, pointer: str) -> tuple[Any, str | None, Any]:
    """Resolve an RFC 6901 JSON Pointer and return (value, parent_pointer, parent_obj)."""
    if pointer in {"", "/"}:
        return data, None, None

    if not pointer.startswith("/"):
        raise KeyError("JSON pointer must start with '/'.")

    raw_tokens = pointer[1:].split("/")
    current = data
    parent: Any = None
    parent_tokens: list[str] = []

    for index, raw_token in enumerate(raw_tokens):
        token = _json_pointer_unescape(raw_token)
        parent = current
        parent_tokens = raw_tokens[:index]

        if isinstance(current, dict):
            if token not in current:
                raise KeyError(f"Key not found: {token}")
            current = current[token]
        elif isinstance(current, list):
            try:
                idx = int(token)
            except ValueError as exc:
                raise KeyError(f"Invalid array index: {token}") from exc
            if idx < 0 or idx >= len(current):
                raise KeyError(f"Array index out of range: {idx}")
            current = current[idx]
        else:
            raise KeyError(f"Cannot traverse into primitive value at '{token}'.")

    parent_pointer = "/" + "/".join(parent_tokens) if parent_tokens else "/"
    return current, parent_pointer, parent


class SessionStore:
    """Thread-safe in-memory store for offline PDF and JSON documents."""

    def __init__(self, limits: SessionLimits | None = None) -> None:
        self.limits = limits or SessionLimits()
        self._lock = threading.RLock()
        self._documents: dict[str, SessionDocument] = {}
        self._total_bytes = 0

    def has_documents(self) -> bool:
        with self._lock:
            return bool(self._documents)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "document_count": len(self._documents),
                "total_bytes": self._total_bytes,
                "limits": {
                    "max_files": self.limits.max_files,
                    "max_file_bytes": self.limits.max_file_bytes,
                    "max_total_bytes": self.limits.max_total_bytes,
                    "max_pdf_pages": self.limits.max_pdf_pages,
                    "max_json_depth": self.limits.max_json_depth,
                    "max_json_fields": self.limits.max_json_fields,
                    "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
                },
                "documents": [doc.to_metadata() for doc in self._documents.values()],
            }

    def import_file(self, raw_filename: str | None, raw_bytes: bytes) -> dict[str, Any]:
        filename = sanitize_filename(raw_filename)
        extension = Path(filename).suffix.casefold()

        if extension not in ALLOWED_EXTENSIONS:
            ext_label = extension or "(no extension)"
            raise ImportValidationError(
                f"Unsupported file type '{ext_label}' for '{filename}'. "
                "Only text-based .pdf and .json files are supported.",
                status_code=415,
            )

        size_bytes = len(raw_bytes)
        if size_bytes == 0:
            raise ImportValidationError(f"'{filename}' is empty (0 bytes).", status_code=400)

        if size_bytes > self.limits.max_file_bytes:
            max_mb = self.limits.max_file_bytes // (1024 * 1024)
            raise ImportValidationError(
                f"'{filename}' exceeds the {max_mb} MB per-file size limit.",
                status_code=413,
            )

        with self._lock:
            if len(self._documents) >= self.limits.max_files:
                raise ImportValidationError(
                    f"Session limit reached ({self.limits.max_files} files). "
                    "Remove a file or clear the session to import more.",
                    status_code=413,
                )
            if self._total_bytes + size_bytes > self.limits.max_total_bytes:
                max_total_mb = self.limits.max_total_bytes // (1024 * 1024)
                raise ImportValidationError(
                    f"Adding '{filename}' would exceed the {max_total_mb} MB total session limit.",
                    status_code=413,
                )

        # Parse outside the lock so CPU-bound extraction does not block concurrent reads.
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        imported_at = datetime.now(UTC).isoformat()
        document_id = uuid.uuid4().hex

        if extension == ".pdf":
            pdf_pages, warnings = extract_pdf_pages(
                raw_bytes,
                filename=filename,
                max_pages=self.limits.max_pdf_pages,
            )
            document = SessionDocument(
                document_id=document_id,
                filename=filename,
                file_type="pdf",
                size_bytes=size_bytes,
                sha256=content_hash,
                imported_at=imported_at,
                warnings=warnings,
                pdf_bytes=raw_bytes,
                pdf_pages=pdf_pages,
            )
        else:
            json_fields, parsed_json = extract_json_fields(
                raw_bytes,
                filename=filename,
                max_depth=self.limits.max_json_depth,
                max_fields=self.limits.max_json_fields,
            )
            document = SessionDocument(
                document_id=document_id,
                filename=filename,
                file_type="json",
                size_bytes=size_bytes,
                sha256=content_hash,
                imported_at=imported_at,
                json_data=parsed_json,
                json_fields=json_fields,
            )

        with self._lock:
            if len(self._documents) >= self.limits.max_files:
                raise ImportValidationError(
                    f"Session limit reached ({self.limits.max_files} files).",
                    status_code=413,
                )
            if self._total_bytes + size_bytes > self.limits.max_total_bytes:
                max_total_mb = self.limits.max_total_bytes // (1024 * 1024)
                raise ImportValidationError(
                    f"Adding '{filename}' would exceed the {max_total_mb} MB total session limit.",
                    status_code=413,
                )
            self._documents[document_id] = document
            self._total_bytes += size_bytes

        return document.to_metadata()

    def search(
        self,
        query: str,
        limit: int = 10,
        file_type: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_query = re.sub(r"\s+", " ", query).strip().casefold()
        terms = [term for term in normalized_query.split(" ") if term]
        if not terms:
            return []

        with self._lock:
            documents = list(self._documents.values())

        matches: list[dict[str, Any]] = []

        for doc in documents:
            if file_type and doc.file_type != file_type:
                continue

            if doc.file_type == "pdf":
                for page in doc.pdf_pages:
                    if not page.searchable_text:
                        continue
                    if not all(term in page.searchable_text for term in terms):
                        continue

                    phrase_bonus = 10 if normalized_query in page.searchable_text else 0
                    score = phrase_bonus + sum(page.searchable_text.count(term) for term in terms)
                    matches.append(
                        {
                            "document_id": doc.document_id,
                            "filename": doc.filename,
                            "file_type": "pdf",
                            "title": doc.filename,
                            "page_number": page.page_number,
                            "field_path": None,
                            "display_path": None,
                            "citation_label": f"{doc.filename} — page {page.page_number}",
                            "excerpt": _make_excerpt(page.text, normalized_query, terms[0]),
                            "score": score,
                            "open_url": (
                                f"/api/v1/session/documents/{doc.document_id}"
                                f"/pdf#page={page.page_number}"
                            ),
                        }
                    )
            else:
                for entry in doc.json_fields:
                    if not all(term in entry.searchable_text for term in terms):
                        continue

                    value_lower = entry.value_text.casefold()
                    phrase_in_value = 12 if normalized_query in value_lower else 0
                    phrase_any = 6 if normalized_query in entry.searchable_text else 0
                    term_hits = sum(entry.searchable_text.count(term) for term in terms)
                    score = phrase_in_value + phrase_any + term_hits

                    excerpt_source = f"{entry.key_name}: {entry.value_text}"
                    matches.append(
                        {
                            "document_id": doc.document_id,
                            "filename": doc.filename,
                            "file_type": "json",
                            "title": doc.filename,
                            "page_number": None,
                            "field_path": entry.field_path,
                            "display_path": entry.display_path,
                            "citation_label": f"{doc.filename} — {entry.field_path}",
                            "excerpt": _make_excerpt(excerpt_source, normalized_query, terms[0]),
                            "score": score,
                            "open_url": (
                                f"/api/v1/session/documents/{doc.document_id}"
                                f"/field?path={quote(entry.field_path, safe='')}"
                            ),
                        }
                    )

        matches.sort(
            key=lambda item: (
                -int(item["score"]),
                str(item["filename"]).casefold(),
                int(item["page_number"] or 0),
                str(item["field_path"] or ""),
            )
        )
        return matches[:limit]

    def get_pdf_document(self, document_id: str) -> tuple[str, bytes] | None:
        with self._lock:
            doc = self._documents.get(document_id)
            if doc is None or doc.file_type != "pdf" or doc.pdf_bytes is None:
                return None
            return doc.filename, doc.pdf_bytes

    def get_json_field(self, document_id: str, field_path: str) -> dict[str, Any] | None:
        with self._lock:
            doc = self._documents.get(document_id)
            if doc is None or doc.file_type != "json":
                return None
            filename = doc.filename
            data = doc.json_data
            matching_entry = next(
                (entry for entry in doc.json_fields if entry.field_path == field_path),
                None,
            )

        try:
            value, parent_path, parent_obj = _resolve_json_pointer(data, field_path)
        except KeyError:
            return None

        parent_preview = ""
        if parent_obj is not None:
            serialized = json.dumps(parent_obj, ensure_ascii=False, indent=2)
            if len(serialized) > 4000:
                parent_preview = f"{serialized[:4000]}\n… (truncated)"
            else:
                parent_preview = serialized

        return {
            "document_id": document_id,
            "filename": filename,
            "field_path": field_path,
            "display_path": matching_entry.display_path if matching_entry else field_path,
            "value": value,
            "parent_path": parent_path,
            "parent_preview": parent_preview,
        }

    def remove_document(self, document_id: str) -> bool:
        with self._lock:
            doc = self._documents.pop(document_id, None)
            if doc is None:
                return False
            self._total_bytes = max(0, self._total_bytes - doc.size_bytes)
            return True

    def clear(self) -> dict[str, int]:
        with self._lock:
            cleared_docs = len(self._documents)
            cleared_bytes = self._total_bytes
            self._documents.clear()
            self._total_bytes = 0
            return {
                "cleared_documents": cleared_docs,
                "cleared_bytes": cleared_bytes,
                "document_count": 0,
            }
