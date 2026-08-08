# References

Log of every external source and version used in this project (required by the challenge brief).

## Dataset

 **MIMIC-IV Clinical Database Demo (version 2.2)** [Data set]. PhysioNet.
  https://doi.org/10.13026/dp1f-ex47
  - Local copy: `backend/demo_data/mimic-iv-clinical-database-demo-2.2/` (CSVs, unmodified)
  - Files used: `patients.csv`, `admissions.csv`, `transfers.csv`, `diagnoses_icd.csv`,
    `procedures_icd.csv`, `prescriptions.csv`, `d_labitems.csv`, `labevents.csv`,
    `icustays.csv`, `chartevents.csv`, `procedureevents.csv`, `d_icd_diagnoses.csv`,
    `d_icd_procedures.csv`
  - License: PhysioNet credentialed access; research/educational use only.
  - **Note:** dates in this dataset are shifted; timestamps are meaningful only within one
    patient's timeline. Event labels and units come directly from the dataset files.

## Model / inference service

- Llama 3.3 70B, "versatile" endpoint, accessed via the Groq API (`groq` Python SDK).
  - Used for text-to-SQL generation and row summarization only (see `AI_DISCLOSURE.md`).

## Software

- FastAPI / Uvicorn — HTTP backend
- SQLAlchemy — DB layer; SQLite — storage
- sqlparse — SQL parsing/validation
- pandas — CSV ingestion
- python-dotenv — configuration
- Angular (latest CLI scaffold) — frontend framework
- pytest + httpx — API tests

## Reference-range sources for quality rules

- Adult reference ranges for the ~11 most common lab/vital subtypes were taken from standard
  clinical reference-range conventions (e.g. creatinine 0.6–1.3 mg/dL, potassium 3.5–5.0
  mmol/L, sodium 135–145 mmol/L, SpO₂ 90–100%, temperature 35.5–39.0 °C, heart rate
  30–220 bpm as a *plausibility* bound, not a clinical alert). Exact constants and the
  per-rule rationale are inline in `backend/app/ingest/quality_rules.py`. These are
  plausibility bounds for data-quality flagging — **not** clinical thresholds or alerts.

## Temporal-tolerance rationale for the temporal_misalignment rule

- MIMIC chartevents timestamps are *documentation* times: they routinely precede ICU bed
  transfer (`intime`) by minutes and can lag discharge (`outtime`) by a short window,
  because staff document events as of observed time while the patient is being moved.
  See the MIMIC-IV documentation on chartevents timestamps (PhysioNet MIMIC-IV docs,
  chartevents table description) and the common ICU-research convention of allowing a
  tolerance around the ICU-stay window for charted data.
- The rule therefore flags an event only when it falls **more than 2 hours** outside its
  ICU stay or hospital admission window (`TEMPORAL_TOLERANCE = "120"` minutes in
  `backend/app/ingest/quality_rules.py`, the single source of truth for the SQL modifiers
  and flag descriptions). Severity bands: ≤12h = `minor`, 12–24h = `moderate`, >24h =
  `severe` (see `backend/app/ingest/quality_rules.py`). The structural checks — ICU stay or hospital
  discharge time preceding admission time — remain strict (no tolerance) and are counted
  separately under `rule_id = "chronology_violation"`. The BP pair relationship check
  (`bp_relationship_invalid`) flags readings where systolic < diastolic in the same
  (patient, encounter, timestamp, source) reading.
