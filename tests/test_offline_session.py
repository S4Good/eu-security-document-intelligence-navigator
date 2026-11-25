from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import eu_security_navigator.main as main
from eu_security_navigator.launcher import main as launcher_main
from eu_security_navigator.session_store import (
    ImportValidationError,
    SessionLimits,
    SessionStore,
)


def build_synthetic_pdf(page_texts: list[str]) -> bytes:
    """Create a minimal valid PDF 1.4 document with one text stream per page."""
    objects: list[bytes] = []

    def add_obj(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    # Reserve object IDs: 1=Catalog, 2=Pages, 3=Font
    add_obj(b"")  # placeholder for Catalog
    add_obj(b"")  # placeholder for Pages
    font_id = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_ids: list[int] = []
    for text in page_texts:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if escaped:
            stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET\n".encode("latin-1")
        else:
            stream = b""
        content_body = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"endstream"
        )
        content_id = add_obj(content_body)
        page_body = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("ascii")
        page_ids.append(add_obj(page_body))

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = [0]
    for obj_num, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{obj_num} 0 obj\n".encode("ascii"))
        out.extend(body)
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    out.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(out)


@pytest.fixture(autouse=True)
def clean_session():
    main.session_store.clear()
    yield
    main.session_store.clear()


def test_offline_end_to_end_page_five_nested_json_and_clear() -> None:
    client = TestClient(main.app)

    synthetic_pdf = build_synthetic_pdf(
        [
            "ISMS Handbook Cover Page",
            "Section 1 Scope and Objectives",
            "Section 2 Access Control Policy",
            "Section 3 Incident Response Roles",
            "Section 4 Resilience: Quarterly backup restoration drill verified with audit log.",
            "Section 5 Document Revision History",
        ]
    )
    synthetic_json = json.dumps(
        {
            "assessment": {
                "framework": "ISMS-Synthetic-Baseline",
                "controls": [
                    {
                        "id": "CTRL-01",
                        "status": "implemented",
                        "evidence": {"owner": "Platform Team"},
                    },
                    {
                        "id": "CTRL-02",
                        "status": "in_progress",
                        "evidence": {
                            "owner": "Security Operations",
                            "notes": (
                                "Key rotation procedure pending quarterly tabletop validation."
                            ),
                        },
                    },
                ],
            }
        }
    ).encode("utf-8")

    # Import both synthetic files in one multi-file offline upload
    upload_response = client.post(
        "/api/v1/session/files",
        files=[
            ("files", ("synthetic-isms-policy.pdf", synthetic_pdf, "application/pdf")),
            ("files", ("synthetic-isms-controls.json", synthetic_json, "application/json")),
        ],
    )
    assert upload_response.status_code == 200
    assert upload_response.headers["cache-control"] == "no-store"
    assert upload_response.headers["x-content-type-options"] == "nosniff"
    upload_payload = upload_response.json()
    assert len(upload_payload["imported"]) == 2
    assert upload_payload["errors"] == []
    assert upload_payload["session"]["document_count"] == 2

    # 1. Verify phrase that exists ONLY on page 5
    pdf_search = client.get(
        "/api/v1/search",
        params={"q": "Quarterly backup restoration drill", "scope": "session"},
    )
    assert pdf_search.status_code == 200
    pdf_data = pdf_search.json()
    assert pdf_data["count"] == 1
    pdf_hit = pdf_data["results"][0]
    assert pdf_hit["filename"] == "synthetic-isms-policy.pdf"
    assert pdf_hit["file_type"] == "pdf"
    assert pdf_hit["page_number"] == 5
    assert "Quarterly backup restoration drill" in pdf_hit["excerpt"]
    assert pdf_hit["open_url"].endswith("#page=5")

    # Open the cited PDF stream from memory
    pdf_doc_id = pdf_hit["document_id"]
    pdf_stream = client.get(f"/api/v1/session/documents/{pdf_doc_id}/pdf")
    assert pdf_stream.status_code == 200
    assert pdf_stream.headers["content-type"] == "application/pdf"
    assert pdf_stream.headers["cache-control"] == "no-store"
    assert pdf_stream.content.startswith(b"%PDF-1.4")

    # 2. Verify nested JSON field match
    json_search = client.get(
        "/api/v1/search",
        params={"q": "tabletop validation", "scope": "session"},
    )
    assert json_search.status_code == 200
    json_data = json_search.json()
    assert json_data["count"] == 1
    json_hit = json_data["results"][0]
    assert json_hit["filename"] == "synthetic-isms-controls.json"
    assert json_hit["file_type"] == "json"
    assert json_hit["field_path"] == "/assessment/controls/1/evidence/notes"
    assert json_hit["display_path"] == "assessment.controls[1].evidence.notes"
    assert "tabletop validation" in json_hit["excerpt"]

    # Inspect cited JSON field
    json_doc_id = json_hit["document_id"]
    field_response = client.get(
        f"/api/v1/session/documents/{json_doc_id}/field",
        params={"path": json_hit["field_path"]},
    )
    assert field_response.status_code == 200
    field_payload = field_response.json()
    assert field_payload["filename"] == "synthetic-isms-controls.json"
    assert "tabletop validation" in field_payload["value"]
    assert "Security Operations" in field_payload["parent_preview"]

    # 3. Clear the session and verify BOTH results disappear
    clear_response = client.post("/api/v1/session/clear")
    assert clear_response.status_code == 200
    assert clear_response.json()["cleared_documents"] == 2
    assert clear_response.json()["document_count"] == 0

    after_clear_pdf = client.get(
        "/api/v1/search",
        params={"q": "Quarterly backup restoration drill", "scope": "session"},
    )
    after_clear_json = client.get(
        "/api/v1/search",
        params={"q": "tabletop validation", "scope": "session"},
    )
    assert after_clear_pdf.status_code == 200
    assert after_clear_pdf.json()["count"] == 0
    assert after_clear_json.status_code == 200
    assert after_clear_json.json()["count"] == 0

    # Document endpoints return 404 after clearing session
    assert client.get(f"/api/v1/session/documents/{pdf_doc_id}/pdf").status_code == 404
    assert (
        client.get(
            f"/api/v1/session/documents/{json_doc_id}/field",
            params={"path": json_hit["field_path"]},
        ).status_code
        == 404
    )


def test_search_page_serves_offline_html() -> None:
    client = TestClient(main.app)
    response = client.get("/search")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Open PDF / JSON files" in response.text
    assert "Clear session" in response.text


def test_unsupported_and_invalid_files_return_useful_errors() -> None:
    client = TestClient(main.app)

    # Unsupported extension
    res_ext = client.post(
        "/api/v1/session/files",
        files=[("files", ("policy.docx", b"not-a-pdf", "application/octet-stream"))],
    )
    assert res_ext.status_code == 415
    assert "Unsupported file type" in res_ext.json()["detail"]

    # Invalid PDF bytes
    res_bad_pdf = client.post(
        "/api/v1/session/files",
        files=[("files", ("broken.pdf", b"not a real pdf", "application/pdf"))],
    )
    assert res_bad_pdf.status_code == 400
    assert "valid PDF" in res_bad_pdf.json()["detail"]

    # Image-only / textless PDF
    blank_pdf = build_synthetic_pdf(["", ""])
    res_blank = client.post(
        "/api/v1/session/files",
        files=[("files", ("scanned.pdf", blank_pdf, "application/pdf"))],
    )
    assert res_blank.status_code == 422
    assert "Scanned or image-only PDFs" in res_blank.json()["detail"]

    # Malformed JSON
    res_bad_json = client.post(
        "/api/v1/session/files",
        files=[("files", ("broken.json", b'{"a": [1, 2}', "application/json"))],
    )
    assert res_bad_json.status_code == 400
    assert "not valid JSON" in res_bad_json.json()["detail"]

    # Mixed batch: one valid JSON + one unsupported file imports valid file and reports error
    res_mixed = client.post(
        "/api/v1/session/files",
        files=[
            ("files", ("valid.json", b'{"control": "ISO-27001"}', "application/json")),
            ("files", ("notes.txt", b"plain text", "text/plain")),
        ],
    )
    assert res_mixed.status_code == 200
    mixed_payload = res_mixed.json()
    assert len(mixed_payload["imported"]) == 1
    assert len(mixed_payload["errors"]) == 1
    assert mixed_payload["errors"][0]["filename"] == "notes.txt"


def test_session_store_enforces_size_page_and_depth_limits() -> None:
    limits = SessionLimits(
        max_files=2,
        max_file_bytes=2048,
        max_total_bytes=3000,
        max_pdf_pages=3,
        max_json_depth=4,
        max_json_fields=5,
    )
    store = SessionStore(limits=limits)

    # Exceeds per-file byte limit
    with pytest.raises(ImportValidationError, match="size limit") as exc_size:
        store.import_file("big.json", b'{"x": "' + b"a" * 3000 + b'"}')
    assert exc_size.value.status_code == 413

    # Exceeds PDF page limit
    four_page_pdf = build_synthetic_pdf(["Page 1", "Page 2", "Page 3", "Page 4"])
    with pytest.raises(ImportValidationError, match="3-page limit") as exc_pages:
        store.import_file("too-many-pages.pdf", four_page_pdf)
    assert exc_pages.value.status_code == 413

    # Exceeds JSON nesting depth
    deep_json = b'{"a": {"b": {"c": {"d": {"e": "too deep"}}}}}'
    with pytest.raises(ImportValidationError, match="nesting depth") as exc_depth:
        store.import_file("deep.json", deep_json)
    assert exc_depth.value.status_code == 400

    # Exceeds JSON field count
    many_fields = json.dumps({f"k{i}": f"v{i}" for i in range(6)}).encode("utf-8")
    with pytest.raises(ImportValidationError, match="5-field limit") as exc_fields:
        store.import_file("wide.json", many_fields)
    assert exc_fields.value.status_code == 413


def test_launcher_refuses_non_loopback_host_by_default() -> None:
    with pytest.raises(SystemExit, match="Refusing to bind non-loopback host"):
        launcher_main(["--host", "0.0.0.0", "--no-browser"])


def test_large_upload_above_1mb_spool_threshold_writes_zero_temp_files(
    monkeypatch,
    tmp_path,
) -> None:
    """Regression test: uploads > 1 MB (Starlette's default spool threshold) must not touch disk."""
    import tempfile

    isolated_temp = tmp_path / "isolated_tmp"
    isolated_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(isolated_temp))

    def forbid_temp_file(*args, **kwargs):
        raise AssertionError("Multipart upload attempted to create a temporary file on disk")

    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", forbid_temp_file)
    monkeypatch.setattr(tempfile, "TemporaryFile", forbid_temp_file)
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", forbid_temp_file)

    # Synthetic >1.2 MB PDF (unique phrase only on page 5) and >1.2 MB nested JSON
    pad_sentence = "Synthetic ISMS baseline padding sentence for memory upload verification. "
    filler_page = pad_sentence * 4000  # ~292 KB per page -> 6 pages > 1.7 MB
    large_pdf = build_synthetic_pdf(
        [
            f"Cover {filler_page}",
            f"Page 2 {filler_page}",
            f"Page 3 {filler_page}",
            f"Page 4 {filler_page}",
            "Page 5 target: Zero-spool offline evidence marker on page five.",
            f"Page 6 {filler_page}",
        ]
    )
    large_json = json.dumps(
        {
            "assessment": {
                "padding": "P" * 1_250_000,
                "controls": [
                    {"id": "CTRL-01", "evidence": {"owner": "Platform"}},
                    {
                        "id": "CTRL-02",
                        "evidence": {
                            "owner": "SecOps",
                            "notes": "Zero-spool nested JSON field verified.",
                        },
                    },
                ],
            }
        }
    ).encode("utf-8")

    assert len(large_pdf) > 1_048_576
    assert len(large_json) > 1_048_576

    client = TestClient(main.app)
    upload = client.post(
        "/api/v1/session/files",
        files=[
            ("files", ("large-synthetic.pdf", large_pdf, "application/pdf")),
            ("files", ("large-synthetic.json", large_json, "application/json")),
        ],
    )
    assert upload.status_code == 200
    assert upload.json()["session"]["document_count"] == 2
    assert list(isolated_temp.iterdir()) == []

    # Verify matches on page 5 and nested JSON field
    pdf_hit = client.get(
        "/api/v1/search",
        params={"q": "Zero-spool offline evidence marker", "scope": "session"},
    ).json()
    assert pdf_hit["count"] == 1
    assert pdf_hit["results"][0]["page_number"] == 5

    json_hit = client.get(
        "/api/v1/search",
        params={"q": "Zero-spool nested JSON field", "scope": "session"},
    ).json()
    assert json_hit["count"] == 1
    assert json_hit["results"][0]["field_path"] == "/assessment/controls/1/evidence/notes"

    # Clear session and verify zero temp files and zero remaining matches
    clear = client.post("/api/v1/session/clear")
    assert clear.status_code == 200
    assert clear.json()["document_count"] == 0
    assert list(isolated_temp.iterdir()) == []

    assert (
        client.get(
            "/api/v1/search",
            params={"q": "Zero-spool offline evidence marker", "scope": "session"},
        ).json()["count"]
        == 0
    )
    assert (
        client.get(
            "/api/v1/search",
            params={"q": "Zero-spool nested JSON field", "scope": "session"},
        ).json()["count"]
        == 0
    )


def test_multipart_rejects_non_multipart_and_oversized_request(monkeypatch) -> None:
    client = TestClient(main.app)

    bad_ct = client.post(
        "/api/v1/session/files",
        content=b'{"not": "multipart"}',
        headers={"Content-Type": "application/json"},
    )
    assert bad_ct.status_code == 400
    assert "multipart/form-data" in bad_ct.json()["detail"]

    # Temporarily cap session store limits to test streaming total-body 413 guard
    small_store = SessionStore(
        limits=SessionLimits(max_file_bytes=1024, max_total_bytes=2048),
    )
    monkeypatch.setattr(main, "session_store", small_store)
    oversized = b'{"x": "' + b"a" * 2048 + b'"}'
    res = client.post(
        "/api/v1/session/files",
        files=[("files", ("too-big.json", oversized, "application/json"))],
    )
    assert res.status_code == 413
    assert "limit" in res.json()["detail"]
