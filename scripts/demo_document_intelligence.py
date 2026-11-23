from pathlib import Path

from eu_security_navigator.document_analysis import (
    analyze_local_pdf,
    save_analysis_result,
)

BSI_STANDARD_PDF = Path("data/raw/bsi-standard-200-1.pdf")
OUTPUT_PATH = Path(
    "data/processed/bsi-standard-200-1-pages-20-21.document-intelligence.json"
)
PAGES = "20-21"


def main() -> None:
    result = analyze_local_pdf(BSI_STANDARD_PDF, pages=PAGES)
    save_analysis_result(result, OUTPUT_PATH)

    print(f"Model: {result['model_id']}")
    print(f"Pages analysed: {result['page_count']}")
    print("\n--- Extracted content preview ---\n")
    print(str(result["content"])[:2000])
    print(f"Saved local result: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()