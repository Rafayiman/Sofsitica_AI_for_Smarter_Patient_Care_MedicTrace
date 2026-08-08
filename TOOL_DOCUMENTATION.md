# MedicTrace — Tool Documentation

> **Research and educational prototype only. Not for clinical use. Do not use for
> diagnosis, treatment, triage, or emergency decisions.**

**Project:** MedicTrace — MIMIC-IV Data Quality Monitor & Grounded Q&A (SGTDP AI
Hackathon, Track 1 — Structured Patient Timeline & Evidence Retrieval)
**Stack:** Python 3.11 (pandas, SQLAlchemy, SQLite, FastAPI) · Angular 18 · Groq
(Llama 3.3 70B) for text-to-SQL and summarization.

---

## 1. What the tool does

MedicTrace is an end-to-end clinical-data research workbench over a frozen copy of the
MIMIC-IV Clinical Database Demo v2.2 (100 deidentified, date-shifted patients). It does
three jobs, each with a hard guarantee:

1. **Ingest** — reconstructs one patient's hospital journey from 13 relational source
   tables into a unified event store of **866,848 events** with **zero silent data
   loss** (every transform stage asserts exact row counts and aborts loudly on any
   mismatch).
2. **Data-quality monitoring** — flags **43,707** quality issues with **six explicit,
   documented, additive rules**. Flags never modify or delete a source row, are
   labeled `data_quality` (never a clinical label), and are reversible.
3. **Grounded Q&A** — answers natural-language questions about a patient with
   **SELECT-only SQL, per-patient isolation, and row-level citations** — or explicitly
   says `not_found`, `out_of_scope`, or `error` instead of guessing. The LLM is
   **never** allowed to answer from memory.

**Intended users:** clinical-data researchers, educators, and healthcare data teams —
not clinicians making patient-care decisions.

## 2. How it works — end to end

```
mimic-iv CSV files (v2.2 demo, frozen copy)
   │  Stage 1: stage_raw.py — verbatim CSV → raw_* tables, row counts verified
   │                 against gzip line counts (31/31 tables verified)
   ▼
SQLite (backend/data/db.sqlite)
   │  Stage 2: transform_events.py — 13 domain mappers → unified `events` table,
   │                inserted == expected asserted per source (866,848 rows)
   │  Stage 3: quality_rules.py — 6 additive rules (severity-tiered) → `quality_flags`
   ▼
FastAPI backend (port 8000)
   ├─ GET  /api/patients               → patient dropdown list (100 patients)
   ├─ GET  /api/timeline/{patient_id}  → grouped-by-day timeline + DQ flag badges
   ├─ GET  /api/group/{patient_id}     → raw source rows for one timeline group
   ├─ GET  /api/quality/summary        → DQ dashboard (global or per-patient)
   ├─ GET  /api/eval/report            → latest automated eval evidence
   └─ POST /api/ask                    → grounded Q&A (scope guard → SQL guard → citations)
   ▼
Angular frontend (port 4200) — MedicTrace UI: timeline + day rail, DQ badges with
tooltips, expand modal with source provenance, DQ dashboard, grounded Q&A panel
```

### Stage 1 — raw staging

Every `.csv.gz` in the demo folder is loaded **verbatim** (`dtype=str`, nothing
renamed, nothing dropped) into `raw_*` tables. `verify_counts()` demands each table's
row count equals the source file's gzip line count minus the header — any mismatch
stops the pipeline.

### Stage 2 — unified `events` table

13 domain mappers produce a single schema — `event_id`, `patient_id`, `encounter_id`,
`event_type` (10 types: lab, medication, diagnosis, procedure, transfer,
icu_observation, icu_procedure, admission, measurement, icu_stay), `event_subtype`
(human label), `value` / `value_numeric` / `unit`, `event_timestamp`, `source_table`,
`source_row_id` (exact source row id for provenance).

Mappers cover: admissions, transfers, icustays, diagnoses_icd, procedures_icd,
labevents, prescriptions, emar, omr, chartevents, datetimeevents, outputevents,
procedureevents. Deliberately **not** mapped (documented scope decisions):
inputevents/ingredientevents (duplicate coverage), microbiologyevents, hcpcsevents,
pharmacy, poe, poe_detail, drgcodes, services, provider, caregiver, d_hcpcs.

### Stage 3 — data-quality rules

All rules are **additive**: they only write to `quality_flags` (`INSERT OR IGNORE`,
idempotent; `flag_type = "data_quality"`, `reversible = 1`, optional `severity`).

| Rule | Logic | Severity | Live count |
|---|---|---|---|
| `missing_value` | required value or timestamp absent (incl. MIMIC placeholders `___`, `""`, `unknown`, `n/a`, `na`, `none`, `-`, `null`, `nan`) for lab / icu_observation / medication / measurement types | — | **38,129** |
| `duplicate` | identical (patient, type, subtype, timestamp, value) row repeated | — | **2,359** |
| `implausible_range` | value outside documented adult plausibility bounds (17 per-subtype constants, e.g. Creatinine 0.05–25 mg/dL, Heart Rate 0–300 bpm) — plausibility checks, not clinical alert ranges | — | **33** |
| `temporal_misalignment` | event > 2 h outside its ICU stay or admission window (`TEMPORAL_TOLERANCE = 120` min, single source of truth) | minor ≤12 h · moderate 12–24 h · severe >24 h | 2,283 / 766 / 137 |
| `chronology_violation` | discharge time precedes admission time (ICU stay and hospital level); no tolerance, structural | severe | 0 (proven on synthetic data) |
| `bp_relationship_invalid` | systolic < diastolic within the same (patient, encounter, timestamp, source) NIBP/ABP reading | severe | 0 (proven on synthetic data) |

**Total: 43,707 flags.** Reproduce with
`SELECT rule_id, severity, COUNT(*) FROM quality_flags GROUP BY rule_id, severity`.

### Grounded Q&A (`POST /api/ask`) — the AI layer

The LLM does exactly two things: **generate SQL** and **summarize returned rows**. The
flow:

1. **Scope guard** (`llm/scope_guard.py`) — classifies the question as `DATA` or
   `CLINICAL` via a few-shot prompt. CLINICAL questions (diagnosis, treatment,
   triage, prognosis, dosing) are refused immediately with
   `status="out_of_scope"` and a fixed disclaimer — **before any SQL is generated**.
   If the classifier cannot run (e.g. Groq rate limit), it **fails safe to refusal**
   — a refusal stays a refusal even during outages (SQA fix, BUG #2).
2. **Text-to-SQL** (`llm/prompt.py`) — the system prompt embeds the exact schema and
   hard rules: one SELECT, allowlisted tables, always filter by `patient_id`,
   always select `event_id`/`event_subtype`/`source_table`/`event_timestamp` for
   citability, no bare aggregates, raw SQL only.
3. **SQL guard** (`llm/sql_guard.py`) — validates every query before execution:
   - exactly one parseable `SELECT`; no comments, no placeholders;
   - tables in `{events, quality_flags, raw_patients}`; columns and functions
     allowlisted; safe literals only;
   - **patient isolation**: `patient_id`/`subject_id` must appear in a filter
     *inside* a WHERE clause — this blocks patient-leak shapes such as
     `GROUP BY patient_id` or `SELECT patient_id` (SQA fix, BUG #1);
   - `LIMIT ≤ 100` (appended if missing).
   Rejected SQL is fed back to the model once for a corrected retry; all attempts
   are logged.
4. **Execution with isolation wrapper** — `SELECT * FROM ({cleaned}) _g WHERE
   _g.patient_id = :pid LIMIT 100`; aggregate-only queries that cannot be wrapped
   are re-filtered per-row at the DB level (with an outer patient-filter check).
5. **Result handling** — zero rows → `not_found` (first-class answer; the model is
   told never to answer from memory). Otherwise `answered` with an
   `[AI-generated summary]` (temperature 0.2, ≤30 rows, values truncated at 120
   chars) + **citations** (up to 50, each with `source_table`, `event_id`,
   `event_timestamp`, field label, value, unit) + the executed SQL.
6. **Audit log** — every attempt (timestamp, patient, question, SQL, guard verdict,
   scope verdict, row counts) is appended to `backend/data/query_log.jsonl`.

**Response statuses:** `answered` | `not_found` | `out_of_scope` | `error`.

### The frontend (MedicTrace)

- **Patient search** — MRN search box + dropdown; empty state prompts selection;
  unknown MRNs produce an explicit error, no silent fallback.
- **Event timeline** — events color-coded by type, grouped by day; sticky vertical
  **day rail** with a day ruler (labeled major ticks) and a scroll-position hairline;
  click a tick to jump.
- **DQ badges** — per-group flags with rule-tooltips (flip-aware, never clipped);
  clicking a flagged group opens the **expand modal** showing raw source rows with
  `source_table.source_row_id` provenance and per-row flag descriptions.
- **DQ dashboard** — tabs **Overall / Patient MRN {id}**: KPI cards (events, flags,
  flag rate), flags per rule × severity (including honest 0-count rows for the two
  rules with no live findings), coverage per source table, unit-variation scan.
- **Eval & rubric evidence panel** (Overall tab) — the latest `eval/report.json`:
  score, the four track metrics with bars, a plain-language explainer of why it is
  shown, and a collapsed per-question PASS/FAIL table.
- **Grounded Q&A panel** — highlighted value chips, citation chips, "Show all N
  records" toggle (collapsed by default), executed SQL, distinct `not_found` /
  `out_of_scope` / error states, and a Retry button on errors.
- **Safety banner** — fixed research-only notice; AI-generated content is visually
  distinct from source data (`[AI-generated summary]` tag).
- Dark/light theme toggle.

## 3. Disqualification behavior (safety & abstention)

The tool is designed so that **every question it cannot honestly answer from the
record is refused or answered with "not found"** — never guessed:

| Situation | Behavior |
|---|---|
| Clinical-judgment question (diagnosis, treatment, triage, prognosis, dosing) | `out_of_scope` refusal with fixed disclaimer; **no SQL generated or executed**; logged to audit log |
| Question with no supporting rows in the data (blood type, SSN, insurance provider) | `not_found` — the model is instructed never to answer from memory |
| LLM service rate-limited or key missing | clean `error` state with explanation; no SQL executed; fail-safe scope refusal during outages |
| Invalid SQL, banned table/column, injection attempt, missing patient filter | guard rejects; one LLM retry with feedback; then `not_found`; all attempts logged |
| Timestamps/values shifted or missing | visible in the UI as DQ flags with tooltips; provenance always shown |
| Out-of-window or implausible values | flagged as `data_quality` (additive, reversible), never silently "corrected" |

Challenge-rule disqualification boundaries respected:

- **No diagnosis, treatment, triage, or emergency guidance** — enforced by the scope
  guard (code, not just docs).
- **No external patient-level data** — only the organizer-supplied frozen copy is used.
- **No reidentification / no patient rows sent to external services** — only the
  question text and generated SQL are sent to Groq; the dataset is deidentified and
  date-shifted.
- **No free-text notes presented as clinician text** — no notes in scope; AI
  summaries are tagged, structured-code labels are not presented as authored notes.
- **No silent correction of source records** — all flags are additive and reversible,
  every rule documented.
- **Synthetic data kept separate** — seeded precision/recall tests
  (`eval/dq_quality.py`) and eval questions are labeled `[SYNTHETIC]` and never mixed
  with real demo records or used to imply real-world clinical performance.

## 4. Evaluation & evidence

- **24-question automated eval** (`eval/run_eval.py`): 13 fact, 3 temporal-order,
  4 unanswerable, 4 out-of-scope — every check **evidence-based** (status + citation
  counts +, for the temporal question, the executed SQL), never wording-matching.
  **Final: 24/24** — fact 13/13, order 3/3, provenance 15/16, abstention 8/8
  (patient 10000032). Latency: mean 6.29 s / p50 6.53 / p95 14.16 / max 15.40.
- **Baseline comparison** — a no-LLM keyword/template baseline scores 14/24 (58%),
  demonstrating why the guarded LLM path exists. The gap is reported honestly in
  `EVAL.md`.
- **Rule precision/recall on seeded synthetic data** (`eval/dq_quality.py`) — all six
  rules: precision = recall = F1 = 1.000, zero false positives (including the two
  rules that fire 0 times on the real subset). This measures the *rules*, not the
  dataset.
- **Tests** — 7 pytest tests (SQL guard incl. patient-leak shapes, ask flow,
  quality rules) all pass.
- **SQA pass** — all 12 findings from `SQA_BugReport.txt` fixed, verified, and
  documented in `EVAL.md` (incl. the patient-isolation leak, fail-safe scope
  classification, unit-mode fixes, `encounter_id=''` handling, doc-number
  corrections).
- **Known limitation (honest failure case)** — diagnoses have no true timestamp in
  the source; they are stamped with admission time, so diagnosis-relative timing
  questions are structurally unreliable (source-data limitation, not a bug). Fixing
  it would require timestamped diagnosis events (e.g. `poe`/`poe_detail`), out of
  scope.

## 5. Rubric coverage (challenge judging rubric)

Each judged category, and where this project addresses it:

| Category (weight) | What judges assess | Where MedicTrace addresses it |
|---|---|---|
| **Problem & Impact (20%)** | Precise, data-supported problem; realistic research/education user; measurable proxy value; scope appropriate to the demo dataset | Messy multi-table MIMIC data is hard to inspect; researchers need verifiable facts + data-fitness signals. Target user: research/education teams. Proxy value: 24/24 eval + 43,707 DQ flags + coverage/unit-variation scans (`EVAL.md`, `TOOL_DOCUMENTATION.md` §1, dashboard) |
| **AI & Data Quality (25%)** | AI necessary not decorative; sound joins/temporal logic; visible lineage; controlled leakage; appropriate evaluation, baselines, uncertainty | LLM only for text-to-SQL + summarization (guard rails make it necessary, not decorative); 13-mapper joins with row-count asserts (no silent loss); provenance to `source_table.source_row_id`; patient-leak blocked in guard (SQA BUG #1) + isolation wrapper; eval vs keyword baseline + uncertainty (latency, honest failures) in `EVAL.md` |
| **Working Product (20%)** | Functional end-to-end prototype; usable core workflows; reproducible setup; sensible handling of missing/malformed/unsupported inputs | Two full views (timeline + DQ dashboard) + Q&A; reproducible setup (`backend/README.md`, `frontend/README.md`); explicit states for empty search, unknown MRN, missing key, rate limit, `not_found`, `out_of_scope`, 404 eval report |
| **Safety & Reliability (15%)** | Research-only boundaries; provenance; uncertainty; failure testing; human review; privacy/licence compliance; no unsupported clinical claims | Safety banner + scope-guard refusals (code-enforced); citations on every answer; fail-safe refusal under rate limits; additive/reversible flags; no patient rows sent to Groq; PhysioNet licence respected; `AI_DISCLOSURE.md` |
| **Innovation (10%)** | Meaningful, well-justified improvement over a simple baseline; thoughtful use of AI suited to the problem | 14/24 baseline → 24/24 guarded LLM; fail-safe refusal design; evidence-based eval checks; severity-tiered temporal rules; SQL guard with patient-isolation WHERE check (beyond typical allowlists) |
| **Pitch & Clarity (10%)** | Clear communication of problem, data, method, live demo, evidence, tradeoffs, limitations, next validation step | This document (problem → architecture → demo walkthrough); one honest failure case (diagnosis timestamps) stated in eval docs |

**Required deliverables checklist** (challenge brief §4):

| Deliverable | Location |
|---|---|
| Working prototype | `frontend/` (Angular, port 4200) + `backend/` (FastAPI, port 8000) |
| Source code + run instructions | `backend/README.md`, `frontend/README.md`, `README.md` |
| Technical summary (target user, data flow, AI method, source tables, assumptions, design choices) | This document |
| Evaluation report (baseline, protocol, track metrics, results, uncertainty, error examples, limitations) | `EVAL.md` + `eval/report.json` + `eval/run_eval.py` |
| Safety and data statement | `AI_DISCLOSURE.md`, this document §3, in-app safety banner |
| Demo and pitch (problem, product, evidence, one honest failure case) | Live demo walkthrough (`TOOL_DOCUMENTATION.md` §1–§3) |

**Track 1 required metrics** (all reported in `EVAL.md` and shown in the app):
structured-fact accuracy (13/13), temporal-order accuracy (3/3), source-provenance
coverage (15/16), unsupported-answer/abstention accuracy (8/8). Supporting measures:
retrieval latency (mean 6.29 s), duplicate-event handling (2,359 flagged + exact-match
rule), user task completion (walkthrough in `TOOL_DOCUMENTATION.md`).

## 6. How to run

```bash
# Backend
cd backend
pip install -r requirements.txt
copy .env.example .env                     # add GROQ_API_KEY
.venv\Scripts\python -m app.ingest.run_ingest    # stages 1+2+3 (CSVs in demo_data/mimic-iv-clinical-database-demo-2.2)
.venv\Scripts\python -m uvicorn app.main:app --port 8000

# Frontend
cd frontend && npm install && ng serve --port 4200   # http://localhost:4200

# Eval + tests
cd backend
.venv\Scripts\python ..\eval\run_eval.py      # 24-question eval → 4 track metrics + latency
.venv\Scripts\python ..\eval\dq_quality.py    # seeded precision/recall of the quality rules
.venv\Scripts\python -m pytest tests -q
```

**Source of truth for every threshold:** `backend/app/ingest/quality_rules.py`
(constants inline, cited in `references.md`).

## 7. Known limitations

- **n=100, single center, date-shifted** — no generalizability or fairness claims
  possible or intended.
- Diagnoses carry no true timestamp (admission-time approximation) — see honest
  failure case above.
- Dates are shifted by MIMIC — meaningful only within one patient's timeline.
- Results are environment-dependent (Groq model/quota, local machine); latency is
  operational evidence only.
- Groq daily quota exhaustion surfaces as clean `error` / fail-safe refusals; the
  eval then records those as failures until the quota resets.
