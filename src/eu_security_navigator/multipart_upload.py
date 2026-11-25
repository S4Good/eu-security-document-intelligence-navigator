"""Bounded, purely in-memory multipart/form-data parser with zero disk spooling."""

from __future__ import annotations

import codecs
from dataclasses import dataclass, field
from urllib.parse import unquote

from fastapi import Request
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header

from eu_security_navigator.session_store import ImportValidationError, SessionLimits

MAX_HEADER_BYTES = 16 * 1024
MAX_PART_HEADERS = 32
MULTIPART_FRAMING_OVERHEAD_BYTES = 4 * 1024 * 1024


@dataclass
class InMemoryUploadedFile:
    filename: str
    content_type: str | None
    data: bytes


@dataclass
class _ActivePart:
    field_name: str = ""
    filename: str | None = None
    content_type: str | None = None
    is_file: bool = False
    header_bytes: int = 0
    header_count: int = 0
    header_name: bytearray = field(default_factory=bytearray)
    header_value: bytearray = field(default_factory=bytearray)
    content_disposition: bytes = b""
    buffer: bytearray = field(default_factory=bytearray)
    actual_bytes: int = 0


def _decode_header_value(raw: bytes, charset: str) -> str:
    try:
        return raw.decode(charset)
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _extract_filename(options: dict[bytes, bytes], charset: str) -> str | None:
    if b"filename*" in options:
        raw_ext = _decode_header_value(options[b"filename*"], "latin-1")
        if "''" in raw_ext:
            ext_charset, _, encoded_name = raw_ext.partition("''")
            return unquote(encoded_name, encoding=ext_charset or "utf-8", errors="replace")
        return unquote(raw_ext, encoding="utf-8", errors="replace")

    if b"filename" in options:
        return _decode_header_value(options[b"filename"], charset)

    return None


async def parse_in_memory_multipart(
    request: Request,
    limits: SessionLimits,
    *,
    expected_field: str = "files",
) -> list[InMemoryUploadedFile]:
    """Stream multipart file uploads into bounded in-memory buffers without touching disk."""
    content_type = request.headers.get("content-type", "")
    media_type, params = parse_options_header(content_type.encode("latin-1"))
    if media_type.lower() != b"multipart/form-data":
        raise ImportValidationError(
            "Expected a multipart/form-data file upload.",
            status_code=400,
        )

    boundary = params.get(b"boundary")
    if not boundary:
        raise ImportValidationError(
            "Missing multipart boundary in Content-Type header.",
            status_code=400,
        )

    raw_charset = params.get(b"charset", b"utf-8")
    charset_str = raw_charset.decode("latin-1") if isinstance(raw_charset, bytes) else "utf-8"
    try:
        charset = codecs.lookup(charset_str).name
    except LookupError:
        charset = "utf-8"

    max_request_bytes = limits.max_total_bytes + MULTIPART_FRAMING_OVERHEAD_BYTES
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise ImportValidationError("Invalid Content-Length header.", status_code=400) from exc
        if declared_length > max_request_bytes:
            max_total_mb = limits.max_total_bytes // (1024 * 1024)
            raise ImportValidationError(
                f"Upload request exceeds the {max_total_mb} MB total session limit.",
                status_code=413,
            )

    per_file_cap = limits.max_file_bytes + 1
    uploaded_files: list[InMemoryUploadedFile] = []
    part = _ActivePart()
    file_part_count = 0

    def on_part_begin() -> None:
        nonlocal part
        part = _ActivePart()

    def on_header_field(data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        part.header_bytes += len(chunk)
        if part.header_bytes > MAX_HEADER_BYTES:
            raise ImportValidationError(
                "Multipart part headers exceed size limit.",
                status_code=400,
            )
        part.header_name.extend(chunk)

    def on_header_value(data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        part.header_bytes += len(chunk)
        if part.header_bytes > MAX_HEADER_BYTES:
            raise ImportValidationError(
                "Multipart part headers exceed size limit.",
                status_code=400,
            )
        part.header_value.extend(chunk)

    def on_header_end() -> None:
        part.header_count += 1
        if part.header_count > MAX_PART_HEADERS:
            raise ImportValidationError("Too many headers in multipart upload.", status_code=400)

        name = bytes(part.header_name).lower()
        value = bytes(part.header_value)
        if name == b"content-disposition":
            part.content_disposition = value
        elif name == b"content-type":
            part.content_type = _decode_header_value(value, "latin-1")

        part.header_name.clear()
        part.header_value.clear()

    def on_headers_finished() -> None:
        nonlocal file_part_count
        _, options = parse_options_header(part.content_disposition)
        raw_field = options.get(b"name")
        if raw_field is None:
            raise ImportValidationError(
                "Multipart upload part is missing Content-Disposition name.",
                status_code=400,
            )
        part.field_name = _decode_header_value(raw_field, charset)
        part.filename = _extract_filename(options, charset)

        if part.filename is not None and part.field_name == expected_field:
            file_part_count += 1
            if file_part_count > limits.max_files:
                raise ImportValidationError(
                    f"Upload exceeds the {limits.max_files}-file session limit.",
                    status_code=413,
                )
            part.is_file = True

    def on_part_data(data: bytes, start: int, end: int) -> None:
        if not part.is_file:
            return
        chunk = data[start:end]
        part.actual_bytes += len(chunk)
        remaining = per_file_cap - len(part.buffer)
        if remaining > 0:
            part.buffer.extend(chunk[:remaining])

    def on_part_end() -> None:
        if not part.is_file:
            return
        uploaded_files.append(
            InMemoryUploadedFile(
                filename=part.filename or "unnamed",
                content_type=part.content_type,
                data=bytes(part.buffer),
            )
        )
        part.buffer.clear()

    callbacks = {
        "on_part_begin": on_part_begin,
        "on_header_field": on_header_field,
        "on_header_value": on_header_value,
        "on_header_end": on_header_end,
        "on_headers_finished": on_headers_finished,
        "on_part_data": on_part_data,
        "on_part_end": on_part_end,
    }

    parser = MultipartParser(boundary, callbacks)
    total_streamed = 0

    try:
        async for chunk in request.stream():
            if not chunk:
                continue
            total_streamed += len(chunk)
            if total_streamed > max_request_bytes:
                max_total_mb = limits.max_total_bytes // (1024 * 1024)
                raise ImportValidationError(
                    f"Upload request exceeds the {max_total_mb} MB total session limit.",
                    status_code=413,
                )
            parser.write(chunk)
        parser.finalize()
    except ImportValidationError:
        raise
    except FormParserError as exc:
        raise ImportValidationError("Invalid multipart upload data.", status_code=400) from exc

    return uploaded_files
