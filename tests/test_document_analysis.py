from eu_security_navigator.document_analysis import analyze_local_pdf


def test_analyze_local_pdf_has_safe_default_pages() -> None:
    assert analyze_local_pdf.__defaults__ == ("1-2",)