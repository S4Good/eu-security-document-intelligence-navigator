from eu_security_navigator.document_intelligence import get_document_intelligence_client


def test_creates_document_intelligence_client(monkeypatch) -> None:
    monkeypatch.setenv(
        "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT",
        "https://example.cognitiveservices.azure.com/",
    )
    monkeypatch.setenv("AZURE_DOCUMENT_INTELLIGENCE_KEY", "test-key")

    client = get_document_intelligence_client()

    assert client is not None