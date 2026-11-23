import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

SOURCE_METADATA = {
    "bsi-standard-200-1.pdf": {
        "source_id": "bsi-standard-200-1",
        "title": "BSI-Standard 200-1: Managementsysteme für Informationssicherheit",
        "official_url": (
            "https://www.bsi.bund.de/SharedDocs/Downloads/DE/BSI/Grundschutz/"
            "BSI_Standards/standard_200_1.pdf?__blob=publicationFile&v=2"
        ),
    }
}


def _clean_text(text: str) -> str:
    without_comments = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    return re.sub(r"\s+", " ", without_comments).strip()


def _make_excerpt(text: str, query: str, length: int = 320) -> str:
    clean_text = _clean_text(text)
    position = clean_text.casefold().find(query.casefold())

    if position < 0:
        return clean_text[:length]

    start = max(0, position - 80)
    end = min(len(clean_text), position + length)

    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(clean_text) else ""
    return f"{prefix}{clean_text[start:end]}{suffix}"


def load_citations(processed_dir: Path = PROCESSED_DIR) -> list[dict[str, object]]:
    citations: list[dict[str, object]] = []

    for result_path in processed_dir.glob("*.document-intelligence.json"):
        payload = json.loads(result_path.read_text(encoding="utf-8"))

        for citation in payload.get("citations", []):
            source = str(citation["source"])
            metadata = SOURCE_METADATA.get(
                source,
                {
                    "source_id": result_path.stem,
                    "title": source,
                    "official_url": "",
                },
            )

            citations.append(
                {
                    **metadata,
                    "page_number": citation["page_number"],
                    "content": citation["content"],
                }
            )

    return citations


def search_citations(
    query: str,
    limit: int = 10,
    processed_dir: Path = PROCESSED_DIR,
) -> list[dict[str, object]]:
    terms = [term for term in query.casefold().split() if term]
    matches: list[dict[str, object]] = []

    for citation in load_citations(processed_dir):
        content = str(citation["content"])
        searchable_content = content.casefold()
        score = sum(searchable_content.count(term) for term in terms)

        if score == 0:
            continue

        matches.append(
            {
                "source_id": citation["source_id"],
                "title": citation["title"],
                "official_url": citation["official_url"],
                "page_number": citation["page_number"],
                "citation_label": (
                    f"{citation['title']} — page {citation['page_number']}"
                ),
                "excerpt": _make_excerpt(content, terms[0]),
                "score": score,
            }
        )

    return sorted(
        matches,
        key=lambda result: (-int(result["score"]), int(result["page_number"])),
    )[:limit]