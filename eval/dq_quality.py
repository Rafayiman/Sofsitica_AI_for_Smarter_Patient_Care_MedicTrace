"""Precision / recall of the quality-rule engine against SEEDED (synthetic) data.

The real MIMIC-IV demo subset contains 0 rows violating the chronology or
BP-relationship rules, so those rules can never be "shown" on real data. This
script builds an in-memory SQLite database seeded with rows whose quality
state is KNOWN BY CONSTRUCTION, runs the exact rule functions used at ingest,
and compares their flags against the ground-truth labels:

    * 12+ clean events (must produce 0 flags)
    * 5  events missing required fields          -> missing_value
    * 3  duplicate pairs                         -> duplicate (only dup rows)
    * 4  events outside plausible ranges         -> implausible_range
    * 4  events outside the 2h tolerance window  -> temporal_misalignment
    * 2  events inside tolerance                 -> 0 flags
    * 1  ICU stay + 1 admission with reversed times -> chronology_violation
    * 2  systolic<diastolic same-reading pairs   -> bp_relationship_invalid

Output: per-rule precision / recall / F1 + overall micro scores.
Every number here is a claim about SYNTHETIC data, labelled as such.

Usage:  python eval/dq_quality.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import create_engine, text  # noqa: E402

from app.ingest.quality_rules import (  # noqa: E402
    rule_bp_relationship_invalid,
    rule_duplicate,
    rule_implausible_range,
    rule_missing_value,
    rule_temporal_misalignment,
)

SCHEMA = """
CREATE TABLE events (
  event_id TEXT PRIMARY KEY, patient_id TEXT, encounter_id TEXT,
  event_type TEXT, event_subtype TEXT, value TEXT, value_numeric REAL,
  unit TEXT, event_timestamp TEXT, source_table TEXT, source_row_id TEXT
);
CREATE TABLE raw_icustays (
  stay_id TEXT, subject_id TEXT, hadm_id TEXT, intime TEXT, outtime TEXT
);
CREATE TABLE raw_admissions (
  hadm_id TEXT, subject_id TEXT, admittime TEXT, dischtime TEXT
);
CREATE TABLE quality_flags (
  flag_id TEXT PRIMARY KEY, event_id TEXT, flag_type TEXT, rule_id TEXT,
  description TEXT, reversible INTEGER, severity TEXT
);
"""

# Stay 1 window: 2111-01-01 08:00 -> 2111-01-05 08:00
# Admission 10 window: 2111-01-01 09:00 -> 2111-01-06 09:00
STAY1_IN, STAY1_OUT = "2111-01-01 08:00:00", "2111-01-05 08:00:00"
ADM10_IN, ADM10_OUT = "2111-01-01 09:00:00", "2111-01-06 09:00:00"


def build_db() -> object:
    engine = create_engine("sqlite://")
    conn = engine.connect()
    conn.execute(text("PRAGMA foreign_keys=OFF"))
    for stmt in SCHEMA.split(";"):
        if stmt.strip():
            conn.execute(text(stmt))

    conn.execute(text("INSERT INTO raw_icustays VALUES ('1','1','10',:i,:o)"), {"i": STAY1_IN, "o": STAY1_OUT})
    conn.execute(text("INSERT INTO raw_icustays VALUES ('9','9','99',:i,:o)"),
                 {"i": "2111-01-02 08:00:00", "o": "2111-01-01 08:00:00"})
    conn.execute(text("INSERT INTO raw_admissions VALUES ('10','1',:i,:o)"), {"i": ADM10_IN, "o": ADM10_OUT})
    conn.execute(text("INSERT INTO raw_admissions VALUES ('99','9',:i,:o)"),
                 {"i": "2111-01-03 09:00:00", "o": "2111-01-01 09:00:00"})

    def ev(id_, subtype, val, ts, etype="lab", enc="1", patient="1", unit=None):
        conn.execute(
            text(
                "INSERT INTO events (event_id, patient_id, encounter_id, event_type, event_subtype, "
                "value, value_numeric, unit, event_timestamp, source_table, source_row_id) "
                "VALUES (:id, :pid, :enc, :etype, :sub, :val, :num, :unit, :ts, 'chartevents', :id)"
            ),
            {
                "id": id_, "pid": patient, "enc": enc, "etype": etype, "sub": subtype,
                "val": None if val is None else str(val), "num": val, "unit": unit, "ts": ts,
            },
        )

    # --- Clean events: must never be flagged ---------------------------------
    clean = [
        ("e_clean_01", "Potassium", 4.2, "2111-01-02T08:00:00"),
        ("e_clean_02", "Glucose", 95.0, "2111-01-02T09:00:00"),
        ("e_clean_03", "Sodium", 138.0, "2111-01-02T10:00:00"),
        ("e_clean_04", "Creatinine", 1.1, "2111-01-03T08:00:00"),
        ("e_clean_05", "Hemoglobin", 14.2, "2111-01-03T09:00:00"),
        ("e_clean_06", "Platelet Count", 220.0, "2111-01-03T10:00:00"),
        ("e_clean_07", "Heart Rate", 74.0, "2111-01-04T08:00:00", "icu_observation"),
        ("e_clean_08", "Respiratory Rate", 16.0, "2111-01-04T09:00:00", "icu_observation"),
        ("e_clean_09", "O2 saturation pulseoxymetry", 97.0, "2111-01-04T10:00:00", "icu_observation"),
        ("e_clean_10", "Temperature Fahrenheit", 98.6, "2111-01-04T11:00:00", "icu_observation"),
        ("e_clean_11", "Non Invasive Blood Pressure systolic", 120.0, "2111-01-04T12:00:00", "icu_observation"),
        ("e_clean_12", "Non Invasive Blood Pressure diastolic", 70.0, "2111-01-04T12:00:00", "icu_observation"),
        ("e_clean_13", "Non Invasive Blood Pressure systolic", 118.0, "2111-01-03T10:00:00", "icu_observation"),
        ("e_clean_14", "Non Invasive Blood Pressure diastolic", 68.0, "2111-01-03T10:00:00", "icu_observation"),
    ]
    for id_, sub, val, ts, *rest in clean:
        if rest:
            ev(id_, sub, val, ts, etype=rest[0])
        else:
            ev(id_, sub, val, ts)

    # --- Rule 1: missing required field --------------------------------------
    for i in range(1, 6):
        ev(f"e_miss_{i}", "Potassium", None, f"2111-01-02T1{i}:00:00", etype="lab")

    # --- Rule 2: duplicates (identical rows; only the second copy is flagged) --
    dup_specs = [
        ("e_dup_1a", "e_dup_1b", "Glucose", 100.0, "2111-01-02T14:00:00", "1"),
        ("e_dup_2a", "e_dup_2b", "Heart Rate", 80.0, "2111-01-03T14:00:00", "2"),
        ("e_dup_3a", "e_dup_3b", "Potassium", 3.9, "2111-01-04T14:00:00", "3"),
    ]
    for a, b, sub, val, ts, pid in dup_specs:
        ev(a, sub, val, ts, patient=pid)
        ev(b, sub, val, ts, patient=pid)

    # --- Rule 3: implausible ranges ------------------------------------------
    ev("e_imp_01", "Potassium", 15.0, "2111-01-02T15:00:00")
    ev("e_imp_02", "Glucose", 3000.0, "2111-01-02T16:00:00")
    ev("e_imp_03", "Heart Rate", 350.0, "2111-01-02T17:00:00", "icu_observation")
    ev("e_imp_04", "Temperature Fahrenheit", 60.0, "2111-01-02T18:00:00", "icu_observation")

    # --- Rule 4: temporal misalignment (2h tolerance) -------------------------
    ev("e_temp_pre_1", "Potassium", 4.0, "2110-12-31T05:00:00")  # 27h before intime -> severe
    ev("e_temp_pre_2", "Potassium", 4.1, "2111-01-01T04:00:00")  # 4h before intime -> minor
    ev("e_temp_post_1", "Glucose", 90.0, "2111-01-06T20:00:00")  # >2h after outtime
    ev("e_temp_post_2", "Glucose", 91.0, "2111-01-05T10:30:00")  # 2.5h after outtime
    # Inside tolerance -> must NOT flag
    ev("e_temp_ok_1", "Potassium", 4.3, "2111-01-01T08:30:00")
    ev("e_temp_ok_2", "Potassium", 4.4, "2111-01-05T08:45:00")

    # --- Rule 5 (chronology) via raw tables: expected synthetic event ids ----
    # icustays_9_start, admissions_99

    # --- Rule 6: systolic < diastolic in same reading -------------------------
    ev("e_bp_1s", "Non Invasive Blood Pressure systolic", 95.0, "2111-01-03T12:00:00", "icu_observation")
    ev("e_bp_1d", "Non Invasive Blood Pressure diastolic", 110.0, "2111-01-03T12:00:00", "icu_observation")
    ev("e_bp_2s", "Non Invasive Blood Pressure systolic", 85.0, "2111-01-03T10:30:00", "icu_observation", "10")
    ev("e_bp_2d", "Non Invasive Blood Pressure diastolic", 120.0, "2111-01-03T10:30:00", "icu_observation", "10")

    return conn


GROUND_TRUTH = {
    "missing_value": {f"e_miss_{i}" for i in range(1, 6)},
    "duplicate": {"e_dup_1b", "e_dup_2b", "e_dup_3b"},
    "implausible_range": {"e_imp_01", "e_imp_02", "e_imp_03", "e_imp_04"},
    "temporal_misalignment": {"e_temp_pre_1", "e_temp_pre_2", "e_temp_post_1", "e_temp_post_2"},
    "chronology_violation": {"icustays_9_start", "admissions_99"},
    "bp_relationship_invalid": {"e_bp_1s", "e_bp_1d", "e_bp_2s", "e_bp_2d"},
}

RULES = [
    ("missing_value", rule_missing_value),
    ("duplicate", rule_duplicate),
    ("implausible_range", rule_implausible_range),
    ("temporal_misalignment", rule_temporal_misalignment),
    ("bp_relationship_invalid", rule_bp_relationship_invalid),
]


def main() -> int:
    conn = build_db()
    for _name, fn in RULES:
        fn(conn)

    actual = {}
    for rule_id, event_id in conn.execute(
        text("SELECT rule_id, event_id FROM quality_flags")
    ).fetchall():
        actual.setdefault(rule_id, set()).add(event_id)

    print("Seeded precision/recall — [SYNTHETIC DATA, known-by-construction labels]\n")
    print(f"{'rule':<26} {'expected':>8} {'flagged':>8} {'TP':>4} {'FP':>4} {'FN':>4}  {'precision':>9} {'recall':>7} {'F1':>6}")
    ok = True
    tot_tp = tot_fp = tot_fn = 0
    for rule_id in sorted(GROUND_TRUTH):
        expected = GROUND_TRUTH[rule_id]
        predicted = actual.get(rule_id, set())
        tp = len(predicted & expected)
        fp = len(predicted - expected)
        fn = len(expected - predicted)
        tot_tp += tp
        tot_fp += fp
        tot_fn += fn
        prec = tp / (tp + fp) if (tp + fp) else 1.0
        rec = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        row_ok = tp == len(expected) and fp == 0 and fn == 0
        ok = ok and row_ok
        print(
            f"{rule_id:<26} {len(expected):>8} {len(predicted):>8} {tp:>4} {fp:>4} {fn:>4}  "
            f"{prec:>9.3f} {rec:>7.3f} {f1:>6.3f} {'OK' if row_ok else '!!'}"
        )
        if not row_ok:
            if fp:
                print(f"    unexpected flags: {sorted(predicted - expected)}")
            if fn:
                print(f"    missed flags:     {sorted(expected - predicted)}")

    prec = tot_tp / (tot_tp + tot_fp) if (tot_tp + tot_fp) else 1.0
    rec = tot_tp / (tot_tp + tot_fn) if (tot_tp + tot_fn) else 1.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    print(f"{'MICRO (all rules)':<26} {'':>8} {'':>8} {tot_tp:>4} {tot_fp:>4} {tot_fn:>4}  {prec:>9.3f} {rec:>7.3f} {f1:>6.3f}")
    print("\nResult: " + ("ALL RULES EXACT — precision = recall = 1.000" if ok else "MISMATCHES FOUND (see above)"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
