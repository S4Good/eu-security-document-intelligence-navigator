from fastapi import FastAPI

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