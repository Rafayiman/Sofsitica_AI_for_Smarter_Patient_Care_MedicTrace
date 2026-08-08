# MedicTrace — Frontend (Angular 18)

> **Research and educational prototype only. Not for clinical use. Do not use for
> diagnosis, treatment, triage, or emergency decisions.**

Frontend application for the **MedicTrace** MIMIC-IV data quality monitor and grounded
Q&A tool (SGTDP AI Hackathon, Track 1 — Structured Patient Timeline & Evidence
Retrieval). Angular 18.2, standalone components, TypeScript ~5.5.

---

## Quick start

```bash
npm install
ng serve --port 4200     # http://localhost:4200
```

Prerequisites: the FastAPI backend must be running on `http://127.0.0.1:8000`
(see `../backend/README.md`). All API calls go to `127.0.0.1:8000`
(`frontend/src/app/services/api.service.ts`).

```bash
npm run build             # production build → dist/frontend
npm test                  # unit tests (Karma + Jasmine)
```

## What the UI does

The app is a two-view clinical-data workbench for one dataset (MIMIC-IV Demo v2.2,
100 deidentified patients, 866,848 unified events):

| View | Purpose |
|---|---|
| **Event timeline** | Day-grouped patient journey: labs, medications, diagnoses, procedures, transfers, ICU observations, admissions — color-coded by event type, with data-quality (DQ) badges |
| **Data quality dashboard** | Global KPIs (events / flags / flag rate), flags by rule × severity, coverage by source table, unit-variation scan, and the eval/rubric evidence panel |

Plus a right-hand **grounded Q&A panel** for natural-language questions about the
selected patient (answers with source-row citations, or explicit `not_found` /
`out_of_scope` states — never a memory-based answer).

## Project structure

```
frontend/src/app/
├── app.component.ts/.html/.css   # shell: topbar, patient search+dropdown, view toggle, theme
├── app.config.ts                 # application config (no routing — single page)
├── models.ts                     # TypeScript models mirroring backend schemas
├── services/api.service.ts       # HTTP client for all backend endpoints
└── components/
    ├── safety-banner/            # fixed research-only notice (required by challenge rules)
    ├── timeline/                 # day-grouped event timeline + vertical day rail
    ├── dq-dashboard/             # DQ KPIs, rules × severity, coverage, eval evidence
    ├── quality-badge/            # per-group DQ badge with rule tooltip (flip-aware)
    ├── event-detail/             # modal: raw source rows with provenance + per-row flags
    └── qa-panel/                 # grounded Q&A: citations w/ values, collapse, retry
```

## Key UX details

- **Patient search** — topbar search box (`Search by MRN… e.g. 1000xxxx`) with a Go
  button, plus a patient dropdown. Empty state prompts the user to select a patient;
  unknown MRNs produce an explicit error (no silent fallback).
- **Sticky navigation** — the topbar sticks to the top while the safety banner scrolls
  away; the timeline's vertical day rail is offset so it stays aligned under the topbar.
- **Day rail** — sticky left rail with a day ruler (every day ticked, major labeled
  ticks sampled, `Day n/N` readout) and a position hairline that tracks the scroll
  position; clicking a tick jumps to that day.
- **DQ badges** — tooltips explain each rule (`missing_value`, `duplicate`,
  `implausible_range`, `temporal_misalignment`, `chronology_violation`,
  `bp_relationship_invalid`) and flip to avoid viewport clipping.
- **Timeline groups** — events are grouped per day by `(event_type, event_subtype,
  source_table, encounter_id)`; numeric groups summarize as min/max/mean, text groups
  as mode; clicking a group opens the expand modal with full source provenance.
- **Grounded Q&A** — questions asked against the selected patient; answers carry
  highlighted value chips, citation chips (`field · table · event_id · timestamp`),
  a "Show all N records" toggle (collapsed by default), the executed SQL, a Retry
  button on errors, and distinct `not_found` / `out_of_scope` / error states.
- **Eval & rubric evidence** — on the dashboard's Overall tab, the latest
  `eval/report.json` is shown: score, four track metrics (fact / order / provenance /
  abstention), and a per-question PASS/FAIL table (collapsed by default). The 404
  "no report yet" state explains how to generate it.
- **Theme toggle** — dark (default) / light, persisted in `localStorage`.

## Data flow

```
Angular components
   │  api.service.ts (HttpClient, base http://127.0.0.1:8000)
   ▼
FastAPI backend
   ├─ GET  /api/patients            → patient dropdown + meta (gender, age, admissions)
   ├─ GET  /api/timeline/{patient_id}  → day-grouped timeline + flag counts
   ├─ GET  /api/group/{patient_id}  → raw source rows for one group (modal)
   ├─ GET  /api/quality/summary     → DQ dashboard payload (global or per-patient)
   ├─ GET  /api/eval/report         → latest eval report (or 404 → hint state)
   └─ POST /api/ask                 → grounded Q&A (scope guard → SQL guard → rows → citations)
```

## Testing

```bash
npm test     # Karma + Jasmine unit tests
```

The eval evidence panel is refreshed by regenerating the backend report:

```bash
cd ../backend
.venv\Scripts\python ..\eval\run_eval.py   # writes eval/report.json
```

## Styling

Design tokens live in `app.component.css` (`:root` custom properties — surfaces, ink
tones, event-type colors `--c-lab/--c-med/--c-dx/…`, radii, motion). IBM Plex Sans /
Mono via `@fontsource`; Phosphor icons via `@phosphor-icons/web`. Component styles
consume the same tokens, so theme toggling is a single class switch.
