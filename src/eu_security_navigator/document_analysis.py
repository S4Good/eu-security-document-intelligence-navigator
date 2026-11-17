from pathlib import Path

from azure.ai.documentintelligence.models import DocumentContentFormat
from azure.core.exceptions import AzureError

from eu_security_navigator.document_intelligence import get_document_intelligence_client


def analyze_local_pdf(document_path: Path, pages: str = "1-2") -> dict[str, object]:
    """Analyze selected pages from a local PDF with the prebuilt layout model."""
    if not document_path.is_file():
        raise FileNotFoundError(f"PDF not found: {document_path}")

    client = get_document_intelligence_client()

    try:
        with document_path.open("rb") as document:
            poller = client.begin_analyze_document(
                "prebuilt-layout",
                body=document,
                pages=pages,
                output_content_format=DocumentContentFormat.MARKDOWN,
            )

        result = poller.result()
    except AzureError as error:
        raise RuntimeError(
            f"Document analysis failed for {document_path.name}"
        ) from error

    content = result.content or ""
    result_pages = result.pages or []
    citations = []

    for page in result_pages:
        page_content = "".join(
            content[span.offset : span.offset + span.length]
            for span in (page.spans or [])
        )
        citations.append(
            {
                "source": document_path.name,
                "page_number": page.page_number,
                "citation_label": f"{document_path.name} — page {page.page_number}",
                "content": page_content,
            }
        )

    return {
        "model_id": result.model_id,
        "page_count": len(result_pages),
        "content": content,
        "citations": citations,
    }