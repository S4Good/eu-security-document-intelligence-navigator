from fastapi.testclient import TestClient

import eu_security_navigator.main as main

client = TestClient(main.app)


def test_search_returns_citation_results(monkeypatch) -> None:
    expected_results = [
        {
            "source_id": "bsi-standard-200-1",
            "title": "BSI-Standard 200-1",
            "official_url": "https://www.bsi.bund.de/",
            "page_number": 20,
            "citation_label": "BSI-Standard 200-1 — page 20",
            "excerpt": "Management muss Informationssicherheit steuern.",
            "score": 1,
        }
    ]
    monkeypatch.setattr(main, "search_citations", lambda query, limit: expected_results)

    response = client.get("/api/v1/search?q=Informationssicherheit")

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["results"] == expected_results


def test_search_rejects_short_query() -> None:
    response = client.get("/api/v1/search?q=a")

    assert response.status_code == 422