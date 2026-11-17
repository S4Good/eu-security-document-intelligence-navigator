from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from azure.ai.documentintelligence.models import DocumentContentFormat
from azure.core.exceptions import HttpResponseError

import eu_security_navigator.document_analysis as document_analysis
from eu_security_navigator.document_analysis import analyze_local_pdf


def test_analyze_local_pdf_has_safe_default_pages() -> None:
    assert analyze_local_pdf.__defaults__ == ("1-2",)


def test_analyze_local_pdf_extracts_page_citations(monkeypatch, tmp_path) -> None:
    document_path = tmp_path / "sample.pdf"
    document_path.write_bytes(b"%PDF-1.4 test fixture")

    page_1_content = "# Artikel 1\nPersonal data is protected."
    page_2_content = "# Artikel 2\nThis regulation applies."
    separator = "\n\n"
    full_content = page_1_content + separator + page_2_content

    fake_result = SimpleNamespace(
        model_id="prebuilt-layout",
        content=full_content,
        pages=[
            SimpleNamespace(
                page_number=3,
                spans=[SimpleNamespace(offset=0, length=len(page_1_content))],
            ),
            SimpleNamespace(
                page_number=4,
                spans=[
                    SimpleNamespace(
                        offset=len(page_1_content) + len(separator),
                        length=len(page_2_content),
                    )
                ],
            ),
        ],
    )

    poller = MagicMock()
    poller.result.return_value = fake_result
    client = MagicMock()
    client.begin_analyze_document.return_value = poller
    monkeypatch.setattr(
        document_analysis,
        "get_document_intelligence_client",
        lambda: client,
    )

    result = analyze_local_pdf(document_path, pages="3-4")

    assert result == {
        "model_id": "prebuilt-layout",
        "page_count": 2,
        "content": full_content,
        "citations": [
            {
                "source": "sample.pdf",
                "page_number": 3,
                "citation_label": "sample.pdf — page 3",
                "content": page_1_content,
            },
            {
                "source": "sample.pdf",
                "page_number": 4,
                "citation_label": "sample.pdf — page 4",
                "content": page_2_content,
            },
        ],
    }

    client.begin_analyze_document.assert_called_once()
    call_args, call_kwargs = client.begin_analyze_document.call_args
    assert call_args == ("prebuilt-layout",)
    assert call_kwargs["pages"] == "3-4"
    assert call_kwargs["output_content_format"] == DocumentContentFormat.MARKDOWN
    poller.result.assert_called_once_with()


def test_analyze_local_pdf_handles_page_with_empty_spans(monkeypatch, tmp_path) -> None:
    document_path = tmp_path / "sample.pdf"
    document_path.write_bytes(b"%PDF-1.4 test fixture")

    fake_result = SimpleNamespace(
        model_id="prebuilt-layout",
        content="Document content without a page span.",
        pages=[SimpleNamespace(page_number=5, spans=[])],
    )

    poller = MagicMock()
    poller.result.return_value = fake_result
    client = MagicMock()
    client.begin_analyze_document.return_value = poller
    monkeypatch.setattr(
        document_analysis,
        "get_document_intelligence_client",
        lambda: client,
    )

    result = analyze_local_pdf(document_path, pages="5")

    assert result["citations"] == [
        {
            "source": "sample.pdf",
            "page_number": 5,
            "citation_label": "sample.pdf — page 5",
            "content": "",
        }
    ]


def test_analyze_local_pdf_wraps_azure_failure_with_document_context(
    monkeypatch,
    tmp_path,
) -> None:
    document_path = tmp_path / "sample.pdf"
    document_path.write_bytes(b"%PDF-1.4 test fixture")

    service_error = HttpResponseError(message="Document analysis service unavailable")
    poller = MagicMock()
    poller.result.side_effect = service_error
    client = MagicMock()
    client.begin_analyze_document.return_value = poller
    monkeypatch.setattr(
        document_analysis,
        "get_document_intelligence_client",
        lambda: client,
    )

    with pytest.raises(
        RuntimeError,
        match=r"Document analysis failed for sample\.pdf",
    ) as exc_info:
        analyze_local_pdf(document_path)

    assert exc_info.value.__cause__ is service_error


def test_analyze_local_pdf_preserves_file_not_found_behavior(
    monkeypatch,
    tmp_path,
) -> None:
    document_path = tmp_path / "missing.pdf"

    def fail_if_client_is_created() -> None:
        raise AssertionError("Azure client should not be created for a missing file")

    monkeypatch.setattr(
        document_analysis,
        "get_document_intelligence_client",
        fail_if_client_is_created,
    )

    with pytest.raises(FileNotFoundError, match=r"PDF not found: .*missing\.pdf"):
        analyze_local_pdf(document_path)