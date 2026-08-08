# MedicTrace — Backend (FastAPI + SQLite)

> **Research and educational prototype only. Not for clinical use. Do not use for
> diagnosis, treatment, triage, or emergency decisions.**

Backend for the **MedicTrace** MIMIC-IV data quality monitor and grounded Q&A tool
(SGTDP AI Hackathon, Track 1). Python 3.11, FastAPI, SQLite, pandas/SQLAlchemy for
ingest, Groq (Llama 3.3 70B) for text-to-SQL and summarization.

---

## Quick start

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate                      # or: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                      # then add your GROQ_API_KEY

# Ingest (Stage 1+2+3) — CSV sources in ../mimic-iv-clinical-database-demo-2.2
.venv\Scripts\python -m app.ingest.run_ingest

# Serve
.venv\Scripts\python -m uvicorn app.main:app --port 8000 --reload
# health check: http://127.0.0.1:8000/api/health
```

Environment variables (`backend/.env`, see `.env.example`):

| Var | Purpose |
|---|---|
| `GROQ_API_KEY` | API key for the LLM (Q&A feature). Unset → `/api/ask` returns a clean `error` state with a config hint |
| `GROQ_MODEL` | Default `llama-3.3-70b-versatile` |
| `DB_PATH` | Default `backend/data/db.sqlite` |
| `CSV_DIR` | Path to the frozen MIMIC-IV Demo v2.2 CSV directory |
| `QUERY_LOG_PATH` | Audit log of every Q&A attempt (default `backend/data/query_log.jsonl`) |

## Layout

```
backend/
├── app/
│   ├── main.py               # FastAPI app, CORS (localhost:4200), route registration, /api/health
│   ├── db.py                 # SQLite init, schema creation, indexes
│   ├── models.py / schemas.py# Pydantic request/response models
│   ├── ingest/
│   │   ├── run_ingest.py     # pipeline orchestrator (Stage 1→2→3)
│   │   ├── stage_raw.py      # Stage 1: verbatim CSV → raw_* tables, count-verified
│   │   ├── transform_events.py # Stage 2: 13 domain mappers → unified `events`, assert row counts
│   │   └── quality_rules.py  # Stage 3: 6 additive DQ rules → `quality_flags` (severity-tiered)
│   ├── routes/
│   │   ├── patients.py       # GET /api/patients
│   │   ├── timeline.py       # GET /api/timeline/{patient_id}, GET /api/group/{patient_id}
│   │   ├── quality.py        # GET /api/quality/summary  (?patient_id scoping)
│   │   ├── ask.py            # POST /api/ask — grounded Q&A pipeline
│   │   └── eval_report.py    # GET /api/eval/report — serves eval/report.json
│   └── llm/
│       ├── client.py         # Groq wrapper (returns None when key missing)
│       ├── prompt.py         # text-to-SQL system prompt (schema + hard rules)
│       ├── scope_guard.py    # DATA/CLINICAL question classification + refusal text
│       └── sql_guard.py      # SELECT-only validator: allowlists, LIMIT, patient filter
├── tests/                    # pytest: SQL guard, ask flow, quality rules
└── data/
    ├── db.sqlite             # SQLite database (events, quality_flags, raw_* tables)
    └── query_log.jsonl       # audit log of Q&A attempts
```

## API

| Endpoint | Behavior |
|---|---|
| `GET /api/health` | `{"status": "ok"}` |
| `GET /api/patients` | 100 patients: `patient_id`, `gender`, `anchor_age`, `encounter_ids` |
| `GET /api/timeline/{patient_id}` | Events grouped by day + `(event_type, event_subtype, source_table, encounter_id)`. Per group: count, first/last timestamp, unit, summary (numeric: min/max/mean; text: mode) and aggregated flags `{rule_id, count}`. 404 when the patient has no events |
| `GET /api/group/{patient_id}?date=…&event_type=…&event_subtype=…&source_table=…&encounter_id=…` | Raw source rows for one timeline group, with `source_table` / `source_row_id` provenance and per-row flag descriptions |
| `GET /api/quality/summary` | DQ dashboard: totals, flags per rule × severity (incl. honest 0 rows), coverage per source table, unit-variation scan. `?patient_id=` scopes KPIs to one patient |
| `GET /api/eval/report` | Serves `eval/report.json` (404 with hint if not yet generated) |
| `POST /api/ask` | Grounded Q&A — see below. Body: `{"patient_id": "...", "question": "..."}` |

## Grounded Q&A pipeline (`POST /api/ask`)

The model is used for exactly two things — generating SQL and summarizing returned
rows. It is **never** allowed to answer from memory.

1. **Scope guard** (`llm/scope_guard.py`) — classifies the question as `DATA`
   (factual, about the structured record) or `CLINICAL` (diagnosis, treatment,
   triage, prognosis, dosing, or any "what should I do" judgment). CLINICAL →
   immediate `status="out_of_scope"` with a fixed refusal text; **no SQL is ever
   generated**. If the classifier is unavailable (rate limit), it fails safe to a
   refusal (SQA fix, BUG #2).
2. **Text-to-SQL** (`llm/prompt.py` + `client.py`) — Llama 3.3 70B, temperature 0.1.
   The prompt embeds the exact schema and hard rules: one SELECT, allowlisted
   tables, always filter by `patient_id`, always select `event_id` /
   `event_subtype` / `source_table` / `event_timestamp` for citability, no bare
   aggregates, return raw SQL only.
3. **SQL guard** (`llm/sql_guard.py`) — validates before execution:
   - parseable, exactly one `SELECT` statement, no comments, no placeholders;
   - tables in `{events, quality_flags, raw_patients}`, columns and functions
     allowlisted, safe literals only;
   - **patient isolation enforced**: `patient_id`/`subject_id` must appear in a
     filter *inside* a WHERE clause (blocks `GROUP BY patient_id` leaks — SQA fix,
     BUG #1);
   - `LIMIT ≤ 100` (appended if missing).
   Rejected SQL is returned to the model once as feedback for a corrected retry;
   every attempt is written to the audit log.
4. **Execution with isolation wrapper** — `SELECT * FROM ({cleaned}) _g WHERE
   _g.patient_id = :pid LIMIT 100`; if an aggregate-only query cannot be wrapped,
   every returned row is re-filtered to the requested patient at the DB level.
5. **Result handling** — zero rows → `status="not_found"` (first-class answer; the
   model is instructed never to answer from memory). Otherwise `status="answered"`
   with an `[AI-generated summary]` (temperature 0.2, max 30 rows, values truncated
   at 120 chars), **citations** (up to 50: `source_table`, `event_id`,
   `event_timestamp`, field label, value, unit) and the executed SQL.
6. **Audit log** — every attempt appended to `data/query_log.jsonl`: timestamp,
   patient, question, generated SQL, guard verdict/reason, scope verdict, execution
   errors, row counts.

**Response statuses:** `answered` | `not_found` | `out_of_scope` | `error`
(rate limit / missing key → clean error, never a bare 500).

## Ingestion pipeline (no silent data loss)

- **Stage 1** `stage_raw.py` — loads every `.csv.gz` verbatim (`dtype=str`) into
  `raw_*` tables; row counts must equal the gzip line counts (31/31 verified).
- **Stage 2** `transform_events.py` — 13 domain mappers (labevents, chartevents,
  prescriptions, emar, omr, diagnoses_icd, procedures_icd, admissions, transfers,
  icustays, datetimeevents, outputevents, procedureevents) → unified `events` table
  (866,848 rows). Every mapper asserts `inserted == expected`; the pipeline aborts
  loudly on mismatch — silent data loss is impossible by design.
- **Stage 3** `quality_rules.py` — six additive rules writing only to
  `quality_flags` (never modifying/deleting source rows, `flag_type =
  "data_quality"`, reversible):

| rule | logic | severity |
|---|---|---|
| `missing_value` | required value/timestamp absent (incl. MIMIC placeholders `___`, `""`, `unknown`, `n/a`, `na`, `none`, `-`, `null`, `nan`) for lab/ICU obs/medication/measurement types | — |
| `duplicate` | identical (patient, type, subtype, timestamp, value) row repeated | — |
| `implausible_range` | value outside documented adult plausibility bounds (per-subtype constants) — plausibility, not clinical alerting | — |
| `temporal_misalignment` | event > 2 h (± `TEMPORAL_TOLERANCE = 120` min) outside its ICU stay / admission window | minor ≤12 h · moderate 12–24 h · severe >24 h |
| `chronology_violation` | discharge time precedes admission time (ICU stay & hospital level) — no tolerance, structural | severe |
| `bp_relationship_invalid` | systolic < diastolic in the same reading (NIBP/ABP pairs) | severe |

Current dataset results: **43,707 flags** — missing_value 38,129 · duplicate 2,359 ·
implausible_range 33 · temporal_misalignment 3,186 (minor 2,283 / moderate 766 / severe
137) · chronology_violation 0 · bp_relationship_invalid 0 (last two zero in this
subset — correctness proven on seeded synthetic data, see `eval/dq_quality.py`).

## Testing

```bash
.venv\Scripts\python -m pytest tests -q      # SQL guard + ask flow + quality rules (7 passed)
.venv\Scripts\python ..\eval\run_eval.py     # 24-question eval → 4 track metrics + latency (24/24)
.venv\Scripts\python ..\eval\dq_quality.py   # rule precision/recall on seeded synthetic data
```

Latest eval (patient 10000032): **24/24** — fact 13/13, order 3/3, provenance 15/16,
abstention 8/8; latency mean 6.29 s / p50 6.53 / p95 14.16 / max 15.40. Full report:
`EVAL.md` and `eval/report.json`.

## Safety & responsible use

- Research/educational prototype only — the required notice is shown in the UI
  (`safety-banner`) and in all docs.
- No diagnosis, treatment, triage, or dosing output: enforced by the scope guard, not
  just documented.
- All patient-level output carries source provenance (table, row id, timestamp) and
  DQ flags; AI-generated summaries are visually tagged `[AI-generated summary]`.
- Flags are additive and reversible; the original data is preserved; every
  transformation is logged.
- Only the question text (no patient rows) is sent to the external LLM service; the
  dataset is deidentified and date-shifted; no reidentification attempts.
