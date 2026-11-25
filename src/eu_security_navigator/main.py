from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from eu_security_navigator.multipart_upload import parse_in_memory_multipart
from eu_security_navigator.search import search_citations
from eu_security_navigator.session_store import ImportValidationError, SessionStore

app = FastAPI(
    title="EU Security & Privacy Document Intelligence Navigator",
    version="0.1.0",
    description="Offline-first, source-linked document search for text-based PDFs and JSON files.",
)

session_store = SessionStore()


def _resolve_asset(filename: str) -> Path:
    package_asset = Path(__file__).with_name(filename)
    if package_asset.is_file():
        return package_asset

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled_asset = Path(meipass) / "eu_security_navigator" / filename
        if bundled_asset.is_file():
            return bundled_asset

    return package_asset


def _safe_content_disposition_name(filename: str) -> str:
    cleaned = re.sub(r'["\\\r\n;]', "_", filename)
    ascii_only = cleaned.encode("ascii", "replace").decode("ascii")
    return ascii_only or "document.pdf"


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "EU Security & Privacy Document Intelligence Navigator",
        "search_ui": "/search",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "eu-security-document-intelligence-navigator",
    }


@app.get("/api/v1/session")
def get_session() -> dict[str, object]:
    """Return metadata and limits for the current in-memory offline session."""
    return session_store.summary()


@app.post("/api/v1/session/files")
async def import_session_files(request: Request) -> JSONResponse:
    """Import one or more text-based PDF or JSON files strictly in memory (no disk spooling)."""
    try:
        files = await parse_in_memory_multipart(request, limits=session_store.limits)
    except ImportValidationError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.message,
                "imported": [],
                "errors": [
                    {
                        "filename": "upload",
                        "error": exc.message,
                        "status_code": exc.status_code,
                    }
                ],
                "session": session_store.summary(),
            },
        )

    if not files:
        raise HTTPException(status_code=400, detail="Select at least one PDF or JSON file.")

    imported: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []

    for upload in files:
        raw_name = upload.filename or "unnamed"
        try:
            metadata = session_store.import_file(raw_name, upload.data)
            imported.append(metadata)
        except ImportValidationError as exc:
            errors.append(
                {
                    "filename": raw_name,
                    "error": exc.message,
                    "status_code": exc.status_code,
                }
            )

    if not imported and errors:
        primary_status = int(errors[0]["status_code"])
        return JSONResponse(
            status_code=primary_status,
            content={
                "detail": str(errors[0]["error"]),
                "imported": [],
                "errors": errors,
                "session": session_store.summary(),
            },
        )

    return JSONResponse(
        status_code=200,
        content={
            "imported": imported,
            "errors": errors,
            "session": session_store.summary(),
        },
    )


@app.post("/api/v1/session/clear")
@app.delete("/api/v1/session")
def clear_session() -> dict[str, int]:
    """Remove all imported files, extracted text, and search data from memory."""
    return session_store.clear()


@app.delete("/api/v1/session/documents/{document_id}")
def remove_session_document(document_id: str) -> dict[str, object]:
    """Remove a single imported document from the in-memory session."""
    if not session_store.remove_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found in current session.")
    return {"removed": document_id, "session": session_store.summary()}


@app.get("/api/v1/session/documents/{document_id}/pdf")
def open_session_pdf(document_id: str) -> Response:
    """Serve an imported PDF inline from memory so browsers can jump to #page=N."""
    document = session_store.get_pdf_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="PDF not found in current session.")

    filename, pdf_bytes = document
    safe_name = _safe_content_disposition_name(filename)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}"',
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/v1/session/documents/{document_id}/field")
def inspect_session_json_field(
    document_id: str,
    path: str = Query(..., min_length=1, max_length=2048),
) -> dict[str, object]:
    """Return the cited JSON field value and parent object context from memory."""
    field_info = session_store.get_json_field(document_id, path)
    if field_info is None:
        raise HTTPException(status_code=404, detail="JSON field not found in current session.")
    return field_info


@app.get("/api/v1/search")
def search(
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(10, ge=1, le=50),
    scope: Literal["auto", "session", "local"] = Query("auto"),
    file_type: Literal["pdf", "json"] | None = Query(None),
) -> dict[str, object]:
    """Search in-memory session files or locally saved Document Intelligence citations."""
    query = q.strip()

    if len(query) < 2:
        raise HTTPException(
            status_code=422,
            detail="q must contain at least two non-space characters.",
        )

    if scope == "session":
        results = session_store.search(query, limit=limit, file_type=file_type)
    elif scope == "local":
        results = search_citations(query, limit=limit)
    elif session_store.has_documents():
        results = session_store.search(query, limit=limit, file_type=file_type)
    else:
        results = search_citations(query, limit=limit)

    return {
        "query": query,
        "count": len(results),
        "results": results,
    }


@app.get("/search", response_class=FileResponse, include_in_schema=False)
def search_page() -> FileResponse:
    return FileResponse(_resolve_asset("search.html"), media_type="text/html")
