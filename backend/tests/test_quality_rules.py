"""Quality-rule unit tests on an in-memory SQLite DB.

Verifies the chronology_violation split and the bp_relationship_invalid rule
fire correctly on synthetic data — the demo dataset happens to contain zero
instances of both, so this test is the proof the logic works.
Run: pytest tests/ from backend/.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text  # noqa: E402

from app.ingest.quality_rules import (  # noqa: E402
    rule_bp_relationship_invalid,
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


def _mem_conn():
    engine = create_engine("sqlite://")
    conn = engine.connect()
    conn.execute(text("PRAGMA foreign_keys=OFF"))
    for stmt in SCHEMA.split(";"):
        if stmt.strip():
            conn.execute(text(stmt))
    return conn


def _insert_event(conn, event_id, subtype, val, ts, enc="1", table="chartevents", patient="1"):
    conn.execute(
        text(
            "INSERT INTO events (event_id, patient_id, encounter_id, event_type, event_subtype, value, value_numeric, event_timestamp, source_table, source_row_id) "
            "VALUES (:id, :pid, :enc, 'icu_observation', :sub, :val, :num, :ts, :tbl, '1')"
        ),
        {"id": event_id, "pid": patient, "enc": enc, "sub": subtype, "val": str(val), "num": val, "ts": ts, "tbl": table},
    )


def _flags(conn):
    return conn.execute(
        text("SELECT rule_id, event_id, severity FROM quality_flags ORDER BY event_id")
    ).fetchall()


def test_bp_relationship_flags_both_events():
    conn = _mem_conn()
    _insert_event(conn, "e_sys", "Non Invasive Blood Pressure systolic", 95, "2111-01-01T10:00:00")
    _insert_event(conn, "e_dia", "Non Invasive Blood Pressure diastolic", 110, "2111-01-01T10:00:00")
    _insert_event(conn, "e_ok_sys", "Non Invasive Blood Pressure systolic", 120, "2111-01-01T11:00:00")
    _insert_event(conn, "e_ok_dia", "Non Invasive Blood Pressure diastolic", 70, "2111-01-01T11:00:00")
    n = rule_bp_relationship_invalid(conn)
    assert n == 2, "exactly two flags (both events of the one bad pair)"
    assert [f[1] for f in _flags(conn)] == ["e_dia", "e_sys"]
    assert _flags(conn)[0][2] == "severe"


def test_bp_relationship_ignores_different_timestamps_and_patients():
    conn = _mem_conn()
    # same encounter, same timestamp, VALID relationship (120 > 70) -> no flag
    _insert_event(conn, "a1", "Non Invasive Blood Pressure systolic", 120, "2111-01-01T10:00:00")
    _insert_event(conn, "a2", "Non Invasive Blood Pressure diastolic", 70, "2111-01-01T10:00:00")
    # same timestamp, INVALID relationship, but different patients -> no match
    _insert_event(conn, "b1", "Non Invasive Blood Pressure systolic", 95, "2111-01-01T11:00:00", patient="2")
    _insert_event(conn, "b2", "Non Invasive Blood Pressure diastolic", 110, "2111-01-01T11:00:00")
    n = rule_bp_relationship_invalid(conn)
    assert n == 0, "no match across different timestamps/patients"


def test_chronology_violation_split_rule_id():
    conn = _mem_conn()
    conn.execute(text("INSERT INTO raw_icustays VALUES ('9', '1', '99', '2111-01-02 08:00:00', '2111-01-01 08:00:00')"))
    conn.execute(text("INSERT INTO raw_admissions VALUES ('99', '1', '2111-01-03 09:00:00', '2111-01-01 09:00:00')"))
    rule_temporal_misalignment(conn)
    chrono = [f[1] for f in _flags(conn)]
    assert chrono == ["admissions_99", "icustays_9_start"]
    assert all(f[0] == "chronology_violation" and f[2] == "severe" for f in _flags(conn))
    temporal = conn.execute(text("SELECT COUNT(*) FROM quality_flags WHERE rule_id='temporal_misalignment'")).scalar()
    assert temporal == 0, "window checks find nothing in this synthetic data"
