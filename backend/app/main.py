"""FastAPI app: route registration + CORS."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .routes import ask, eval_report, patients, quality, timeline

app = FastAPI(
    title="Structured Patient Timeline & Evidence Retrieval",
    description="MIMIC-IV Clinical Database Demo v2.2 — timeline + grounded Q&A (Track 1).",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://127.0.0.1:4200",
        "https://sofsitica-ai-for-smarter-patient-ca.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(patients.router)
app.include_router(timeline.router)
app.include_router(ask.router)
app.include_router(quality.router)
app.include_router(eval_report.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
