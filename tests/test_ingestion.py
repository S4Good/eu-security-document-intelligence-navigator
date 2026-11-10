import pytest

from eu_security_navigator.ingestion import extract_html_text, find_source


def test_extract_html_text_removes_non_content_elements() -> None:
    markup = """
    <html>
        <head>
            <title>Hidden title</title>
            <script>do_not_keep_this()</script>
        </head>
        <body>
            <main>
                <h1>GDPR</h1>
                <p>Article 1 protects personal data.</p>
            </main>
        </body>
    </html>
    """

    text = extract_html_text(markup)

    assert "GDPR" in text
    assert "Article 1 protects personal data." in text
    assert "do_not_keep_this" not in text
    assert "Hidden title" not in text


def test_find_source_returns_matching_source() -> None:
    sources = [{"id": "eu-gdpr-de"}, {"id": "eu-ai-act-de"}]

    source = find_source("eu-gdpr-de", sources)

    assert source["id"] == "eu-gdpr-de"


def test_find_source_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="Unknown source ID"):
        find_source("missing-source", [])