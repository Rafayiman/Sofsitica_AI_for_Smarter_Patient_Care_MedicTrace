"""GET /api/eval/report — machine-readable eval report.

Serves eval/report.json, written by `eval/run_eval.py --out` after a full
24-question run. The dashboard renders it as "Eval & rubric evidence" with an
explainer; 404 when no run has produced a report yet. Read-only.
"""
import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

REPORT_PATH = Path(__file__).resolve().parents[3] / "eval" / "report.json"


@router.get("/api/eval/report")
def eval_report() -> JSONResponse:
    if not REPORT_PATH.is_file():
        return JSONResponse({"error": "not_run"}, status_code=404)
    return JSONResponse(json.loads(REPORT_PATH.read_text(encoding="utf-8")))
