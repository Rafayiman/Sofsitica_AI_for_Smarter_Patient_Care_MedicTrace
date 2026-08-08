"""Stage 2: raw_* -> unified events table.

One mapper per domain. Every mapper reports rows inserted vs rows expected;
a mismatch raises (silent data loss breaks the "trace back to source"
guarantee). ICU tables (chartevents etc.) have no row-id column, so the
surrogate source_row_id is the 1-based row position within the source file.

Design decisions (see README.md):
- inputevents / ingredientevents are deliberately NOT mapped as medication
  events (they duplicate infusions already covered by emar/prescriptions).
- microbiologyevents, hcpcsevents, pharmacy, poe, poe_detail, drgcodes,
   services, provider, caregiver, d_hcpcs are not mapped (no timeline events
   per project scope).
- diagnoses have no timestamp in the source; their event time is set to the
  admission time and documented as approximate.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from ..db import engine, init_db

BATCH = 10000
INSERT_SQL = text(
    """
    INSERT OR IGNORE INTO events
      (event_id, patient_id, encounter_id, event_type, event_subtype,
       value, value_numeric, unit, event_timestamp, source_table, source_row_id)
    VALUES
      (:event_id, :patient_id, :encounter_id, :event_type, :event_subtype,
       :value, :value_numeric, :unit, :event_timestamp, :source_table, :source_row_id)
    """
)


def _norm_ts(v) -> str | None:
    """Normalize 'YYYY-MM-DD HH:MM:SS' (space separator) to ISO 'YYYY-MM-DDTHH:MM:SS'."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    if " " in s:
        s = s.replace(" ", "T", 1)
    if len(s) == 10:
        s += "T00:00:00"
    return s


def _to_float(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    if "<" in s or ">" in s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _clean_str(v):
    if v is None or pd.isna(v):
        return None
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return None
    return s


def _ev(row_id: str, patient_id, encounter_id, etype, subtype, value, value_numeric, unit, ts, table):
    return {
        "event_id": f"{table}_{row_id}",
        "patient_id": str(patient_id),
        "encounter_id": None if pd.isna(encounter_id) else str(encounter_id),
        "event_type": etype,
        "event_subtype": _clean_str(subtype),
        "value": _clean_str(value),
        "value_numeric": value_numeric,
        "unit": _clean_str(unit),
        "event_timestamp": _norm_ts(ts),
        "source_table": table,
        "source_row_id": str(row_id),
    }


def _insert(rows: list[dict]) -> int:
    inserted = 0
    for i in range(0, len(rows), BATCH):
        with engine.begin() as conn:
            res = conn.execute(INSERT_SQL, rows[i : i + BATCH])
            inserted += int(res.rowcount)
    return inserted


def _read(table: str) -> pd.DataFrame:
    return pd.read_sql(f"SELECT * FROM raw_{table}", engine)


def _dict_of(df: pd.DataFrame, key_cols: list[str], val_cols: list[str], sep: str = "_") -> dict:
    """First-wins dict for id -> human label lookups (keys are tuples).
    NaN values are normalized to None (never the string 'nan')."""
    out = {}

    def clean(v):
        if v is None or pd.isna(v):
            return None
        return str(v)

    for row in df.itertuples(index=False):
        key = tuple(clean(getattr(row, c)) for c in key_cols)
        if key not in out:
            out[key] = tuple(clean(getattr(row, c)) for c in val_cols)
    return out


# --------------------------------------------------------------------------
# Domain mappers
# --------------------------------------------------------------------------

def map_admissions() -> int:
    df = _read("admissions")
    rows = []
    for r in df.itertuples(index=False):
        hadm = r.hadm_id
        rows.append(_ev(hadm, r.subject_id, hadm, "admission", "admission",
                        r.admission_type, None, None, r.admittime, "admissions"))
        if not pd.isna(r.dischtime):
            rows.append(_ev(f"{hadm}_discharge", r.subject_id, hadm, "admission", "discharge",
                            r.discharge_location, None, None, r.dischtime, "admissions"))
        if not pd.isna(r.deathtime):
            rows.append(_ev(f"{hadm}_death", r.subject_id, hadm, "admission", "death",
                            None, None, None, r.deathtime, "admissions"))
    n = _insert(rows)
    expected = int(df.admittime.notna().sum() + df.dischtime.notna().sum() + df.deathtime.notna().sum())
    return n, expected


def map_transfers() -> int:
    df = _read("transfers")
    rows = []
    for idx, r in enumerate(df.itertuples(index=False)):
        ts = r.intime if not pd.isna(r.intime) else r.outtime
        if pd.isna(ts):
            continue
        subtype = r.eventtype if not pd.isna(r.eventtype) else "transfer"
        rows.append(_ev(f"{idx}", r.subject_id, r.hadm_id, "transfer", subtype,
                        r.careunit, None, None, ts, "transfers"))
    n = _insert(rows)
    return n, len(df)


def map_icustays() -> int:
    df = _read("icustays")
    rows = []
    for r in df.itertuples(index=False):
        rows.append(_ev(f"{r.stay_id}_start", r.subject_id, r.stay_id, "icu_stay", "start",
                        r.first_careunit, None, None, r.intime, "icustays"))
        if not pd.isna(r.outtime):
            rows.append(_ev(f"{r.stay_id}_end", r.subject_id, r.stay_id, "icu_stay", "end",
                            r.last_careunit, None, None, r.outtime, "icustays"))
    n = _insert(rows)
    expected = int(len(df) + df.outtime.notna().sum())
    return n, expected


def map_diagnoses() -> int:
    d = _read("d_icd_diagnoses")
    title = _dict_of(d, ["icd_code", "icd_version"], ["long_title"])
    adm = pd.read_sql("SELECT hadm_id, admittime FROM raw_admissions", engine)
    admit_time = {str(r.hadm_id): r.admittime for r in adm.itertuples(index=False)}
    df = _read("diagnoses_icd")
    rows, skipped = [], 0
    for idx, r in enumerate(df.itertuples(index=False)):
        key = (str(r.icd_code), str(r.icd_version))
        ts = admit_time.get(str(r.hadm_id))
        if pd.isna(ts):
            skipped += 1
            continue
        label = title.get(key, (str(r.icd_code),))[0]
        rows.append(_ev(f"{idx}", r.subject_id, r.hadm_id, "diagnosis", label,
                        r.icd_code, None, None, ts, "diagnoses_icd"))
    n = _insert(rows)
    return n, len(df) - skipped, skipped


def map_procedures() -> int:
    d = _read("d_icd_procedures")
    title = _dict_of(d, ["icd_code", "icd_version"], ["long_title"])
    adm = pd.read_sql("SELECT hadm_id, admittime FROM raw_admissions", engine)
    admit_time = {str(r.hadm_id): r.admittime for r in adm.itertuples(index=False)}
    df = _read("procedures_icd")
    rows, skipped = [], 0
    for idx, r in enumerate(df.itertuples(index=False)):
        key = (str(r.icd_code), str(r.icd_version))
        ts = r.chartdate if not pd.isna(r.chartdate) else admit_time.get(str(r.hadm_id))
        if pd.isna(ts):
            skipped += 1
            continue
        label = title.get(key, (str(r.icd_code),))[0]
        rows.append(_ev(f"{idx}", r.subject_id, r.hadm_id, "procedure", label,
                        r.icd_code, None, None, ts, "procedures_icd"))
    n = _insert(rows)
    return n, len(df) - skipped, skipped


def map_labevents() -> int:
    d = _read("d_labitems")
    items = _dict_of(d, ["itemid"], ["label", "category"])
    df = _read("labevents")
    rows, skipped = [], 0
    for r in df.itertuples(index=False):
        ts = r.charttime if not pd.isna(r.charttime) else r.storetime
        if pd.isna(ts):
            skipped += 1
            continue
        label, _cat = items.get((str(r.itemid),), (str(r.itemid), ""))
        value = r.value if not pd.isna(r.value) else None
        vnum = _to_float(r.valuenum)
        if vnum is None and value is not None:
            vnum = _to_float(value)
        rows.append(_ev(r.labevent_id, r.subject_id, r.hadm_id, "lab", label,
                        value, vnum, r.valueuom, ts, "labevents"))
    n = _insert(rows)
    return n, len(df) - skipped, skipped


def map_prescriptions() -> int:
    df = _read("prescriptions")
    rows, skipped = [], 0
    for idx, r in enumerate(df.itertuples(index=False)):
        ts = r.starttime if not pd.isna(r.starttime) else r.stoptime
        if pd.isna(ts):
            skipped += 1
            continue
        value = r.dose_val_rx if not pd.isna(r.dose_val_rx) else (r.prod_strength if not pd.isna(r.prod_strength) else None)
        rows.append(_ev(f"{idx}", r.subject_id, r.hadm_id, "medication", r.drug,
                        value, None, r.dose_unit_rx, ts, "prescriptions"))
    n = _insert(rows)
    return n, len(df) - skipped, skipped


def map_emar() -> int:
    df = _read("emar")
    rows, skipped = [], 0
    for r in df.itertuples(index=False):
        ts = r.charttime
        if pd.isna(ts):
            ts = r.scheduletime
        if pd.isna(ts):
            ts = r.storetime
        if pd.isna(ts):
            skipped += 1
            continue
        rows.append(_ev(r.emar_id, r.subject_id, r.hadm_id, "medication", r.medication,
                        r.event_txt if not pd.isna(r.event_txt) else None, None, None, ts, "emar"))
    n = _insert(rows)
    return n, len(df) - skipped, skipped


def map_omr() -> int:
    df = _read("omr")
    rows = []
    for idx, r in enumerate(df.itertuples(index=False)):
        rows.append(_ev(f"{idx}", r.subject_id, None, "measurement", r.result_name,
                        r.result_value, _to_float(r.result_value), None, r.chartdate, "omr"))
    n = _insert(rows)
    return n, len(df)


def _icu_map(df, d_items, etype: str, table: str) -> tuple[list, int]:
    items = _dict_of(d_items, ["itemid"], ["label", "unitname"])
    rows, skipped = [], 0
    for idx, r in enumerate(df.itertuples(index=False)):
        ts = r.charttime if not pd.isna(r.charttime) else r.storetime
        if pd.isna(ts):
            skipped += 1
            continue
        label, unitname = items.get((str(r.itemid),), (str(r.itemid), ""))
        value = r.value
        v = value if not pd.isna(value) else None
        unit = r.valueuom
        if (unit is None or pd.isna(unit)) and unitname:
            unit = unitname
        rows.append(_ev(f"{idx}", r.subject_id, r.stay_id, etype, label,
                        v, _to_float(v), unit, ts, table))
    return rows, skipped


def map_chartevents() -> int:
    d = _read("d_items")
    df = _read("chartevents")
    rows, skipped = _icu_map(df, d, "icu_observation", "chartevents")
    n = _insert(rows)
    return n, len(df) - skipped, skipped


def map_datetimeevents() -> int:
    d = _read("d_items")
    df = _read("datetimeevents")
    rows, skipped = _icu_map(df, d, "icu_observation", "datetimeevents")
    n = _insert(rows)
    return n, len(df) - skipped, skipped


def map_outputevents() -> int:
    d = _read("d_items")
    df = _read("outputevents")
    rows, skipped = _icu_map(df, d, "icu_observation", "outputevents")
    n = _insert(rows)
    return n, len(df) - skipped, skipped


def map_procedureevents() -> int:
    d = _read("d_items")
    df = _read("procedureevents")
    items = _dict_of(d, ["itemid"], ["label", "unitname"])
    rows, skipped = [], 0
    for idx, r in enumerate(df.itertuples(index=False)):
        ts = r.starttime
        if pd.isna(ts):
            ts = r.endtime
        if pd.isna(ts):
            ts = r.storetime
        if pd.isna(ts):
            skipped += 1
            continue
        label, unitname = items.get((str(r.itemid),), (str(r.itemid), ""))
        value = r.value if not pd.isna(r.value) else None
        unit = r.valueuom if not pd.isna(r.valueuom) else unitname
        rows.append(_ev(f"{idx}", r.subject_id, r.stay_id, "icu_procedure", label,
                        value, _to_float(value), unit, ts, "procedureevents"))
    n = _insert(rows)
    return n, len(df) - skipped, skipped


MAPPERS = [
    ("admissions", map_admissions),
    ("transfers", map_transfers),
    ("icustays", map_icustays),
    ("diagnoses_icd", map_diagnoses),
    ("procedures_icd", map_procedures),
    ("labevents", map_labevents),
    ("prescriptions", map_prescriptions),
    ("emar", map_emar),
    ("omr", map_omr),
    ("chartevents", map_chartevents),
    ("datetimeevents", map_datetimeevents),
    ("outputevents", map_outputevents),
    ("procedureevents", map_procedureevents),
]


def transform_events(verbose: bool = True) -> dict:
    """Run all mappers (rebuild semantics: events + flags are wiped first).
    Returns {domain: (inserted, expected)}. Raises on mismatch."""
    init_db()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM quality_flags"))
        conn.execute(text("DELETE FROM events"))
    report = {}
    for name, fn in MAPPERS:
        res = fn()
        if len(res) == 2:
            inserted, expected = res
            skipped = 0
        else:
            inserted, expected, skipped = res
        report[name] = {"inserted": inserted, "expected": expected, "skipped": skipped}
        if verbose:
            print(f"  {name}: inserted={inserted} expected={expected} skipped={skipped}")
        if inserted != expected:
            raise RuntimeError(
                f"Stage 2 FAIL {name}: inserted {inserted} != expected {expected} "
                f"(skipped {skipped}). Silent data loss — refusing to continue."
            )
    if verbose:
        total = sum(v["inserted"] for v in report.values())
        print(f"  TOTAL events: {total}")
    return report
