from eu_security_navigator.chunking import build_chunks, split_into_article_sections


def test_split_into_article_sections_preserves_article_boundaries() -> None:
    text = """
    Introduction text.

    Artikel 1
    Gegenstand
    This is the first article.

    Artikel 2
    Anwendungsbereich
    This is the second article.
    """

    sections = split_into_article_sections(text)

    assert len(sections) == 3
    assert sections[1]["article_number"] == "1"
    assert sections[1]["heading"] == "Artikel 1"
    assert sections[2]["article_number"] == "2"


def test_build_chunks_creates_citation_metadata() -> None:
    document = {
        "source_id": "eu-gdpr-de",
        "title": "Datenschutz-Grundverordnung (DSGVO)",
        "authority": "European Union",
        "jurisdiction": "EU",
        "language": "de",
        "canonical_url": "https://example.test/gdpr",
        "retrieved_at": "2026-11-10T10:00:00+00:00",
        "content_sha256": "abc123",
        "text": "Artikel 1\nGegenstand",
    }

    chunks = build_chunks(document)

    assert len(chunks) == 1
    assert chunks[0]["chunk_id"] == "eu-gdpr-de::1"
    assert chunks[0]["citation_label"] == (
        "Datenschutz-Grundverordnung (DSGVO) — Artikel 1"
    )