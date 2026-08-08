"""POST /api/ask — grounded Q&A (text-to-SQL, SELECT-only, cited).

Flow: generate SQL -> guard -> execute -> rows -> citations + AI summary,
or "not_found" when no supporting rows exist. Never answers from memory.
"""
import json
import os
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from ..db import engine
from ..llm import client as llm
from ..llm.prompt import build_sql_prompt, build_summarize_prompt, SUMMARIZE_SYSTEM_PROMPT
from ..llm.scope_guard import classify_scope, OUT_OF_SCOPE_SUMMARY
from ..llm.sql_guard import validate
from ..schemas import AskRequest, AskResponse, Citation

try:  # groq is a hard requirement only when an API key is configured
    from groq import RateLimitError
except ImportError:  # pragma: no cover - fallback keeps /api/ask importable
    RateLimitError = type("RateLimitError", (Exception,), {})

router = APIRouter()

QUERY_LOG = os.getenv("QUERY_LOG_PATH", "./data/query_log.jsonl")

MAX_SUMMARY_ROWS = 30


def _log(entry: dict) -> None:
    try:
        with open(QUERY_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except OSError:
        pass


def _summarize_rows(rows: list[dict]) -> str:
    trimmed = []
    for row in rows[:MAX_SUMMARY_ROWS]:
        trimmed.append({k: (str(v)[:120] if v is not None else None) for k, v in row.items()})
    user = build_summarize_prompt(json.dumps(trimmed))
    summary = llm.chat(SUMMARIZE_SYSTEM_PROMPT, user, temperature=0.2)
    if not summary:
        return f"[AI-generated summary] {len(rows)} row(s) returned by the query; model unavailable to summarize."
    return summary


def _citations(rows: list[dict]) -> list[Citation]:
    cited = [r for r in rows[:50] if r.get("source_table") and r.get("event_id") is not None]
    ids = [str(r["event_id"]) for r in cited]
    meta: dict[str, tuple] = {}
    if ids:
        ph = ", ".join(f":id{i}" for i in range(len(ids)))
        with engine.connect() as conn:
            for event_id, value, value_numeric, unit in conn.execute(
                text(f"SELECT event_id, value, value_numeric, unit FROM events WHERE event_id IN ({ph})"),
                {f"id{i}": ids[i] for i in range(len(ids))},
            ):
                meta[event_id] = (value, value_numeric, unit)
    out = []
    for row in cited:
        field = row.get("event_subtype") or row.get("event_type") or "value"
        value, value_numeric, unit = meta.get(str(row["event_id"]), (None, None, None))
        out.append(
            Citation(
                table=row["source_table"],
                field=field,
                event_id=str(row["event_id"]),
                timestamp=row.get("event_timestamp"),
                value=value,
                value_numeric=value_numeric,
                unit=unit,
            )
        )
    return out


def _outer_patient_filtered(sql: str) -> bool:
    """Defense in depth (SQA BUG #1): does the *outer* query carry a patient
    predicate? Subquery segments are stripped first, so `patient_id = ...`
    hidden inside a nested SELECT does not count. Used before the raw-SQL
    fallback for aggregate queries, which the patient-isolation wrapper
    cannot apply to."""
    stripped = sql
    prev = None
    while prev != stripped:
        prev = stripped
        stripped = re.sub(r"\([^()]*\)", "", stripped)
    prefix = re.split(r"\b(GROUP|ORDER|HAVING|LIMIT)\b", stripped, flags=re.IGNORECASE)[0]
    return bool(re.search(r"\b(patient_id|subject_id)\s*=", prefix, re.IGNORECASE))


@router.post("/api/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    ts = datetime.now(timezone.utc).isoformat()
    if llm.get_client() is None:
        return AskResponse(
            status="error",
            answer_summary="LLM not configured: GROQ_API_KEY is missing. Add it to backend/.env to enable Q&A.",
        )

    try:
        return _ask_impl(req, ts)
    except RateLimitError as exc:
        _log({"ts": ts, "patient_id": req.patient_id, "question": req.question,
              "llm_error": "rate_limited", "detail": str(exc)[:300]})
        return AskResponse(
            status="error",
            answer_summary=(
                "The LLM service is temporarily rate-limited (Groq daily token quota "
                "reached). No SQL was executed for this question; retry later."
            ),
        )


def _ask_impl(req: AskRequest, ts: str) -> AskResponse:
    # Fail safe on scope classification (SQA BUG #2): when the Groq quota is
    # exhausted the classifier cannot run; refuse the question as out_of_scope
    # instead of degrading the refusal to a generic error. Refusal stays a
    # refusal even during outages.
    try:
        scope = classify_scope(req.question)
    except RateLimitError:
        scope = "CLINICAL"
    _log({"ts": ts, "patient_id": req.patient_id, "question": req.question,
          "scope": scope, "scope_sql_skipped": scope == "CLINICAL"})
    if scope == "CLINICAL":
        return AskResponse(
            status="out_of_scope",
            answer_summary=OUT_OF_SCOPE_SUMMARY,
        )

    raw_sql = ""
    cleaned = ""
    reason = ""
    ok = False
    for attempt in range(2):
        feedback = (
            f"\n\nYour previous attempt was rejected by the validator: {reason}. "
            "Fix the SQL so it passes validation. Return ONLY the corrected SQL."
            if attempt > 0
            else ""
        )
        raw_sql = llm.chat(build_sql_prompt(req.patient_id, req.question) + feedback, "Generate the SQL now.") or ""
        ok, cleaned, reason = validate(raw_sql)
        _log({"ts": ts, "patient_id": req.patient_id, "question": req.question,
              "attempt": attempt + 1, "sql_generated": raw_sql,
              "guard": "passed" if ok else "rejected", "guard_reason": reason})
        if ok:
            break

    if not ok:
        return AskResponse(
            status="not_found",
            answer_summary="No supporting rows found in the data for this question.",
        )

    rows = None
    try:
        with engine.connect() as conn:
            # Patient-isolation wrapper: every returned row must belong to the requested patient.
            try:
                res = conn.execute(
                    text(f"SELECT * FROM ({cleaned}) _g WHERE _g.patient_id = :pid LIMIT 100"),
                    {"pid": req.patient_id},
                )
            except OperationalError:
                # Aggregate-only queries (e.g. COUNT(*)) have no patient_id
                # column: run scoped as generated. Never run a fallback query
                # whose outer level lacks a patient predicate (SQA BUG #1).
                if not _outer_patient_filtered(cleaned):
                    raise ValueError("fallback query lacks an outer patient filter")
                res = conn.execute(text(cleaned))
            rows = [dict(r._mapping) for r in res.fetchall()]
    except Exception as exc:  # noqa: BLE001 - log any execution failure
        _log({"ts": ts, "patient_id": req.patient_id, "question": req.question,
              "sql_generated": cleaned, "guard": "passed", "exec_error": str(exc)})
        return AskResponse(
            status="error",
            answer_summary="The generated query could not be executed against the data.",
        )

    _log({"ts": ts, "patient_id": req.patient_id, "question": req.question,
          "sql_generated": cleaned, "guard": "passed", "row_count": len(rows)})

    if not rows:
        return AskResponse(
            status="not_found",
            answer_summary="No supporting rows found in the data for this question.",
            query=cleaned,
        )

    return AskResponse(
        status="answered",
        answer_summary=_summarize_rows(rows),
        citations=_citations(rows),
        query=cleaned,
    )
