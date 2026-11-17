from pathlib import Path

from azure.ai.documentintelligence.models import DocumentContentFormat

from eu_security_navigator.document_intelligence import get_document_intelligence_client


def analyze_local_pdf(document_path: Path, pages: str = "1-2") -> dict[str, object]:
    """Analyze selected pages from a local PDF with the prebuilt layout model."""
    if not document_path.is_file():
        raise FileNotFoundError(f"PDF not found: {document_path}")

    client = get_document_intelligence_client()

    with document_path.open("rb") as document:
        poller = client.begin_analyze_document(
            "prebuilt-layout",
            body=document,
            pages=pages,
            output_content_format=DocumentContentFormat.MARKDOWN,
        )

    result = poller.result()

    return {
        "model_id": result.model_id,
        "page_count": len(result.pages or []),
        "content": result.content or "",
    }