import json

from eu_security_navigator.search import search_citations


def test_search_citations_returns_page_level_result(tmp_path) -> None:
    result_file = tmp_path / "bsi.document-intelligence.json"
    result_file.write_text(
        json.dumps(
            {
                "citations": [
                    {
                        "source": "bsi-standard-200-1.pdf",
                        "page_number": 20,
                        "content": (
                        '<!-- PageHeader="Management" --> '
                            "Management muss Informationssicherheit steuern."
                        ),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    results = search_citations("Informationssicherheit", processed_dir=tmp_path)

    assert len(results) == 1
    assert results[0]["page_number"] == 20
    assert results[0]["source_id"] == "bsi-standard-200-1"
    assert "Informationssicherheit" in str(results[0]["excerpt"])
    assert "<!--" not in str(results[0]["excerpt"])