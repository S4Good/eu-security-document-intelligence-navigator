from fastapi import FastAPI, HTTPException, Query

from eu_security_navigator.search import search_citations

app = FastAPI(
    title="EU Security & Privacy Document Intelligence Navigator",
    version="0.1.0",
    description="A responsible, source-linked document intelligence portfolio project.",
)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "EU Security & Privacy Document Intelligence Navigator",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "eu-security-document-intelligence-navigator",
    }

@app.get("/api/v1/search")
def search(
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, object]:
    """Search locally processed document citations."""
    query = q.strip()

    if len(query) < 2:
        raise HTTPException(
            status_code=422,
            detail="q must contain at least two non-space characters.",
        )

    results = search_citations(query, limit=limit)

    return {
        "query": query,
        "count": len(results),
        "results": results,
    }