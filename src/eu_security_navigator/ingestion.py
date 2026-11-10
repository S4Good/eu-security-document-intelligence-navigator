import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "sources" / "registry.yml"
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

USER_AGENT = (
    "EU-Security-Document-Intelligence-Navigator/0.1 "
    "(https://github.com/S4Good/eu-security-document-intelligence-navigator)"
)


def load_sources(registry_path: Path = REGISTRY_PATH) -> list[dict[str, Any]]:
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    return registry["sources"]


def find_source(source_id: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    for source in sources:
        if source["id"] == source_id:
            return source

    raise ValueError(f"Unknown source ID: {source_id}")


def extract_html_text(markup: str) -> str:
    soup = BeautifulSoup(markup, "html.parser")

    for element in soup(["script", "style", "noscript", "title", "meta"]):
        element.decompose()

    content = soup.find("main") or soup.find(id="text") or soup.body or soup
    lines = (line.strip() for line in content.get_text("\n").splitlines())

    return "\n".join(line for line in lines if line)


def fetch_document(url: str) -> tuple[bytes, str, str]:
    with httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        response = client.get(url)
        response.raise_for_status()

    return response.content, response.text, response.headers.get("content-type", "")


def ingest_source(source_id: str) -> Path:
    source = find_source(source_id, load_sources())
    raw_bytes, markup, content_type = fetch_document(source["canonical_url"])

    retrieved_at = datetime.now(UTC)
    text = extract_html_text(markup)
    content_hash = hashlib.sha256(raw_bytes).hexdigest()

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    raw_path = RAW_DATA_DIR / f"{source_id}.html"
    output_path = PROCESSED_DATA_DIR / f"{source_id}.json"

    raw_path.write_bytes(raw_bytes)

    normalized_document = {
        "source_id": source["id"],
        "title": source["title"],
        "authority": source["authority"],
        "jurisdiction": source["jurisdiction"],
        "language": source["language"],
        "canonical_url": source["canonical_url"],
        "retrieved_at": retrieved_at.isoformat(),
        "content_type": content_type,
        "content_sha256": content_hash,
        "text": text,
    }

    output_path.write_text(
        json.dumps(normalized_document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and normalise one registered official source."
    )
    parser.add_argument("source_id", help="Source ID from sources/registry.yml")
    args = parser.parse_args()

    output_path = ingest_source(args.source_id)
    print(f"Normalised source written to: {output_path}")


if __name__ == "__main__":
    main()