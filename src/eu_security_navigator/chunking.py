import argparse
import json
import re
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

ARTICLE_PATTERN = re.compile(
    r"^(?:Artikel|Article)\s+(\d+[a-zA-Z]?)\b.*$",
    flags=re.IGNORECASE,
)


def split_into_article_sections(text: str) -> list[dict[str, str | None]]:
    sections: list[dict[str, str | None]] = []
    current_heading = "Preamble"
    current_article_number: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        cleaned_line = line.strip()
        if not cleaned_line:
            continue

        match = ARTICLE_PATTERN.match(cleaned_line)
        if match:
            if current_lines:
                sections.append(
                    {
                        "heading": current_heading,
                        "article_number": current_article_number,
                        "text": "\n".join(current_lines),
                    }
                )

            current_heading = cleaned_line
            current_article_number = match.group(1)
            current_lines = [cleaned_line]
        else:
            current_lines.append(cleaned_line)

    if current_lines:
        sections.append(
            {
                "heading": current_heading,
                "article_number": current_article_number,
                "text": "\n".join(current_lines),
            }
        )

    return sections


def build_chunks(document: dict[str, Any]) -> list[dict[str, Any]]:
    sections = split_into_article_sections(document["text"])
    chunks: list[dict[str, Any]] = []

    for index, section in enumerate(sections, start=1):
        section_id = section["article_number"] or f"preamble-{index}"

        chunks.append(
            {
                "chunk_id": f"{document['source_id']}::{section_id}",
                "source_id": document["source_id"],
                "document_title": document["title"],
                "authority": document["authority"],
                "jurisdiction": document["jurisdiction"],
                "language": document["language"],
                "canonical_url": document["canonical_url"],
                "retrieved_at": document["retrieved_at"],
                "content_sha256": document["content_sha256"],
                "section_heading": section["heading"],
                "article_number": section["article_number"],
                "citation_label": (
                    f"{document['title']} — {section['heading']}"
                ),
                "text": section["text"],
            }
        )

    return chunks


def chunk_source(source_id: str) -> Path:
    input_path = PROCESSED_DATA_DIR / f"{source_id}.json"
    output_path = PROCESSED_DATA_DIR / f"{source_id}.chunks.jsonl"

    document = json.loads(input_path.read_text(encoding="utf-8"))
    chunks = build_chunks(document)

    with output_path.open("w", encoding="utf-8") as output_file:
        for chunk in chunks:
            output_file.write(json.dumps(chunk, ensure_ascii=False))
            output_file.write("\n")

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split one normalised legal source into citation-ready chunks."
    )
    parser.add_argument("source_id", help="Source ID from sources/registry.yml")
    args = parser.parse_args()

    output_path = chunk_source(args.source_id)
    print(f"Citation-ready chunks written to: {output_path}")


if __name__ == "__main__":
    main()