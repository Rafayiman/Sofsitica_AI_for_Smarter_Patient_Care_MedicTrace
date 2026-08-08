# Clinical Timeline — MIMIC-IV Data Quality & Grounded Q&A

**Research and educational prototype only. Not for clinical use. Do not use for diagnosis, treatment, triage, or emergency decisions.**

**Problem.** Clinical data is messy, and LLM interfaces on top of it are only trustworthy if
every answer can be traced back to the source row it came from. This demo shows a complete
pipeline that ingests a MIMIC-IV sample, flags data-quality issues with six explicit,
documented rules (severity-tiered), and answers natural-language questions with
**SELECT-only SQL, per-patient isolation, and row-level citations** — or explicitly says
"not found" / "out of scope" instead of guessing.

**Data.** MIMIC-IV Clinical Database Demo v2.2 (PhysioNet), 100 patients, deidentified and
date-shifted. Research/descriptive use only — not for clinical decision-making.

## Architecture

```
mimic-iv CSV files (v2.2 demo)
   │  Stage 1: stage_raw.py (verbatim → raw_* tables, no column guessing)
   ▼
SQLite (data/db.sqlite)
   │  Stage 2: transform_events.py (per-domain mappers → unified `events` table,
   │           row-count asserts per source, no silent loss)
   │  Stage 3: quality_rules.py (6 additive rules, severity-tiered → `quality_flags`,
   │           never mutates rows)
   ▼
FastAPI backend (port 8000)
   ├─ GET  /api/patients
   ├─ GET  /api/timeline/{patient_id}     → grouped-by-day timeline + flag badges
   ├─ GET  /api/group/{patient_id}        → raw source rows for one timeline group
   ├─ GET  /api/quality/summary           → data-quality dashboard (flags × rule/severity,
   │                                        coverage per table, unit-variation scan)
   └─ POST /api/ask                       → text-to-SQL (Groq Llama 3.3 70B)
         scope_guard.py: clinical questions (treatment/triage/prognosis/dosing)
         → immediate out_of_scope refusal, no SQL generated
         LLM generates SQL → sql_guard.py validates (SELECT-only, allowlisted
         tables/columns, LIMIT ≤ 100, patient filter enforced, injection blocked)
         → one retry with guard feedback → rows → summary + per-row citations
         → answered | not_found | out_of_scope | error (never a memory-based answer)
   ▼
Angular frontend (port 4200) — dark clinical-tool UI
   ├─ Patient search box + dropdown (exact-ID search with explicit unknown-ID error)
   ├─ Timeline (color-coded by event type, DQ badges with rule tooltips)
   ├─ DQ dashboard toggle (flags by rule & severity, coverage, unit variation)
   ├─ Click-through modal (raw source table.row_id for every row)
   └─ Grounded Q&A panel (AI-generated tag, citation chips, distinct not-found state)
```

**Guardrails baked into the pipeline (not just docs):**
- SQL validator rejects every non-SELECT statement, unknown table/column, comment-based
  injection, and queries without a patient filter; limit capped at 100 rows.
- A runtime wrapper re-filters every returned row by the requested patient_id.
- Data-quality flags are additive only, labeled `data_quality` — never clinical labels —
  and severity-tiered (minor/moderate/severe) for the temporal-window rule.
- A scope guard refuses clinical-judgment questions (treatment, triage, prognosis, dosing)
  with an explicit `out_of_scope` state before any SQL is generated.
- "not found" is a first-class answer; the model is instructed to never answer from memory.

## How to run

```bash
# 1. Backend
cd backend
python -m venv .venv && .venv\Scripts\activate        # or: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                                # 
.venv\Scripts\python -m ingest.run_ingest             # Stage 1+2+3 (CSVs in ../mimic-iv-clinical-database-demo-2.2)
.venv\Scripts\python -m uvicorn app.main:app --port 8000

# 2. Frontend
cd frontend
npm install
ng serve --port 4200     # open http://localhost:4200

# 3. Evaluation (backend running)
cd backend
.venv\Scripts\python ..\eval\run_eval.py              # 24-question eval set → PASS/FAIL + 4 track metrics
.venv\Scripts\python -m pytest tests -q               # API + guard tests
```

## Quality rules (all thresholds documented in `backend/app/ingest/quality_rules.py`)

| rule_id | Logic | Threshold source |
|---|---|---|
| `missing_value` | required value/timestamp absent | structural — row type defines requirement |
| `duplicate` | same patient/type/subtype/timestamp/value repeated | exact-match equality |
| `implausible_range` | numeric value outside plausible adult range (e.g. creatinine, potassium, sodium, heart rate, SpO₂, temperature) | standard adult reference ranges; per-subtype constants in code |
| `temporal_misalignment` | event timestamp more than 2 h outside its encounter's admission–discharge window (severity: minor ≤12 h, moderate 12–24 h, severe >24 h) | admissions/icustays windows in the source data; `TEMPORAL_TOLERANCE = "120"` min |
| `chronology_violation` | discharge time precedes admission time (ICU stay and hospital level) | structural, no tolerance; severe |
| `bp_relationship_invalid` | systolic < diastolic within the same (patient, encounter, timestamp, source) NIBP/ABP reading | structural pair check; severe |

## Evaluation (summary — full report in `EVAL.md`)

24-question set (13 fact, 3 order, 4 unanswerable, 4 out-of-scope; all labeled
`[SYNTHETIC]`): **24/24 passed** on the final run (fact 13/13, order 3/3, provenance
15/16, abstention 8/8). Four track metrics, compared against a no-LLM keyword/template
baseline scoring 14/24 (58%) — demonstrating why the guarded LLM path exists. Fixes made
during the eval rounds: guard-rejection retry with feedback, demographics table exposure,
prompt hardening against bare `COUNT(*)`, a provenance-check bug, a scope misclassification,
and flaky LLM date arithmetic (question rephrased + evidence-based check). Full detail in
`EVAL.md`.

See `EVAL.md`, `references.md`, `AI_DISCLOSURE.md`.
