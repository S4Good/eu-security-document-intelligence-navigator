from pathlib import Path

from eu_security_navigator.document_analysis import analyze_local_pdf

NIS2_OFFICIAL_PDF = Path("data/raw/nis2-directive.pdf")


def main() -> None:
    result = analyze_local_pdf(NIS2_OFFICIAL_PDF)

    print(f"Model: {result['model_id']}")
    print(f"Pages analysed: {result['page_count']}")
    print("\n--- Extracted content preview ---\n")
    print(str(result["content"])[:2000])


if __name__ == "__main__":
    main()