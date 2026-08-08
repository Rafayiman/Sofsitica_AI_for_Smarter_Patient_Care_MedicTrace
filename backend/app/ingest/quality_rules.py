"""Rule-based data quality engine.

Four rules, all additive: rows in `events` are never modified or deleted.
Every flag row has flag_type = "data_quality" — never a clinical label.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from ..db import engine, init_db

# ---------------------------------------------------------------------------
# Rule 3 thresholds: hardcoded plausible ranges for the most common numeric
# lab/vital subtypes found in the demo data. Thresholds are extreme
# physiological plausibility bounds (values outside = almost certainly data
# error), NOT clinical-alert ranges. Sources: standard adult clinical
# reference ranges; see references.md for full citations.
#   Glucose mg/dL          normal 70-100 fasting; bounds 10-2000
#   Potassium mEq/L        normal 3.5-5.0;       bounds 1.0-10.0
#   Sodium mEq/L           normal 135-145;       bounds 100-180
#   Creatinine mg/dL       normal 0.6-1.3;       bounds 0.05-25
#   Hemoglobin g/dL        normal 12-17.5;       bounds 1.0-25
#   Platelet Count K/uL    normal 150-450;       bounds 1-2000
#   White Blood Cells K/uL normal 4.5-11;        bounds 0.1-500
#   Heart Rate bpm         normal 60-100;        bounds 0-300
#   Respiratory Rate       normal 12-20;         bounds 0-100
#   O2 saturation %        normal 95-100;        bounds 0-100
#   Temperature Fahrenheit normal 97-99;         bounds 80-112
#   NIBP systolic mmHg     normal 90-140;        bounds 40-300
#   NIBP diastolic mmHg    normal 60-90;         bounds 20-200
#   NIBP mean mmHg         normal 70-105;        bounds 25-250
# ---------------------------------------------------------------------------
PLAUSIBLE_RANGES: dict[str, tuple[float, float, str]] = {
    "Glucose": (10.0, 2000.0, "plausible range for glucose, mg/dL (ref: standard adult range, normal 70-100)"),
    "Potassium": (1.0, 10.0, "plausible range for potassium, mEq/L (normal 3.5-5.0)"),
    "Sodium": (100.0, 180.0, "plausible range for sodium, mEq/L (normal 135-145)"),
    "Creatinine": (0.05, 25.0, "plausible range for creatinine, mg/dL (normal 0.6-1.3)"),
    "Hemoglobin": (1.0, 25.0, "plausible range for hemoglobin, g/dL (normal 12-17.5)"),
    "Platelet Count": (1.0, 2000.0, "plausible range for platelet count, K/uL (normal 150-450)"),
    "White Blood Cells": (0.1, 500.0, "plausible range for WBC, K/uL (normal 4.5-11)"),
    "Heart Rate": (0.0, 300.0, "plausible range for heart rate, bpm (normal 60-100)"),
    "Respiratory Rate": (0.0, 100.0, "plausible range for respiratory rate, /min (normal 12-20)"),
    "O2 saturation pulseoxymetry": (0.0, 100.0, "plausible range for SpO2, % (normal 95-100)"),
    "Temperature Fahrenheit": (80.0, 112.0, "plausible range for temperature, F (normal 97-99)"),
    "Non Invasive Blood Pressure systolic": (40.0, 300.0, "plausible range for NIBP systolic, mmHg (normal 90-140)"),
    "Non Invasive Blood Pressure diastolic": (20.0, 200.0, "plausible range for NIBP diastolic, mmHg (normal 60-90)"),
    "Non Invasive Blood Pressure mean": (25.0, 250.0, "plausible range for NIBP mean, mmHg (normal 70-105)"),
    "Arterial Blood Pressure systolic": (40.0, 300.0, "plausible range for ABP systolic, mmHg (normal 90-140)"),
    "Arterial Blood Pressure diastolic": (20.0, 200.0, "plausible range for ABP diastolic, mmHg (normal 60-90)"),
    "Arterial Blood Pressure mean": (25.0, 250.0, "plausible range for ABP mean, mmHg (normal 70-105)"),
}

MISSING_REQUIRED = {"lab", "icu_observation", "medication", "measurement"}

# MIMIC-style placeholder texts that mean "no value" (e.g. "___") — these are
# missing even though the column is not SQL NULL.
PLACEHOLDER_VALUES = ("___", "", "unknown", "n/a", "na", "none", "-", "null", "nan")

RULE_ORDER = [
    "missing_value",
    "duplicate",
    "implausible_range",
    "temporal_misalignment",
    "chronology_violation",
    "bp_relationship_invalid",
]

# Rule 4: temporal tolerance. chartevents timestamps are documentation times,
# which routinely precede ICU bed transfer (intime) by minutes or trail
# discharge by a short lag in MIMIC data. Only events > TEMPORAL_TOLERANCE
# minutes outside the encounter window are flagged. All SQL modifier strings
# and flag descriptions are derived from this single constant.
TEMPORAL_TOLERANCE = "120"  # minutes
_TEMPORAL_BEFORE = f"-{TEMPORAL_TOLERANCE} minutes"
_TEMPORAL_AFTER = f"+{TEMPORAL_TOLERANCE} minutes"
_TEMPORAL_LABEL = f"{int(TEMPORAL_TOLERANCE) // 60}h" if int(TEMPORAL_TOLERANCE) % 60 == 0 else f"{TEMPORAL_TOLERANCE}min"

# Severity bands for the tolerance-window checks.
# Band edges in hours outside the window.
def temporal_severity(hours_outside: float) -> str:
    if hours_outside <= 12:
        return "minor"  # likely documentation lag
    if hours_outside <= 24:
        return "moderate"
    return "severe"


def _flag(rows: list[dict], conn, rule_id: str, description: str, severity: str | None = None) -> int:
    """Insert flags for event ids, returns count. `rows` may be (event_id, description)
    or (event_id, description, severity). `severity` overrides per-row severities."""
    batch = []
    for row in rows:
        event_id, desc = row[0], row[1]
        sev = severity if severity is not None else (row[2] if len(row) > 2 else None)
        batch.append(
            {
                "flag_id": f"{rule_id}_{event_id}",
                "event_id": event_id,
                "flag_type": "data_quality",
                "rule_id": rule_id,
                "description": desc,
                "reversible": 1,
                "severity": sev,
            }
        )
    if not batch:
        return 0
    conn.execute(
        text(
            "INSERT OR IGNORE INTO quality_flags "
            "(flag_id, event_id, flag_type, rule_id, description, reversible, severity) "
            "VALUES (:flag_id, :event_id, :flag_type, :rule_id, :description, :reversible, :severity)"
        ),
        batch,
    )
    return len(batch)


def rule_missing_value(conn) -> int:
    placeholders = ", ".join(f":p{i}" for i in range(len(PLACEHOLDER_VALUES)))
    params = {f"p{i}": v for i, v in enumerate(PLACEHOLDER_VALUES)}
    rows = conn.execute(
        text(
            "SELECT event_id, event_type FROM events "
            f"WHERE value IS NULL OR LOWER(TRIM(value)) IN ({placeholders}) OR event_timestamp IS NULL"
        ),
        params,
    ).fetchall()
    flags = []
    for event_id, etype in rows:
        if etype in MISSING_REQUIRED:
            flags.append((event_id, "Required field (value or event_timestamp) is missing on this row"))
    return _flag(flags, conn, "missing_value", "Required field (value or event_timestamp) is missing on this row")


def rule_duplicate(conn) -> int:
    rows = conn.execute(
        text(
            "WITH ranked AS ("
            "  SELECT event_id, ROW_NUMBER() OVER ("
            "    PARTITION BY patient_id, event_type, event_subtype, event_timestamp, value"
            "    ORDER BY event_id) AS rn"
            "  FROM events WHERE value IS NOT NULL"
            ") SELECT event_id FROM ranked WHERE rn > 1"
        )
    ).fetchall()
    flags = [(r[0], "Identical event (same patient, type, subtype, timestamp, value) appears more than once") for r in rows]
    return _flag(flags, conn, "duplicate", "Identical event (same patient, type, subtype, timestamp, value) appears more than once")


def rule_implausible_range(conn) -> int:
    if not PLAUSIBLE_RANGES:
        return 0
    parts = []
    params = {}
    notes = {}
    for i, (subtype, (lo, hi, note)) in enumerate(PLAUSIBLE_RANGES.items()):
        parts.append(f"(event_subtype = :s{i} AND (value_numeric < :lo{i} OR value_numeric > :hi{i}))")
        params[f"s{i}"] = subtype
        params[f"lo{i}"] = lo
        params[f"hi{i}"] = hi
        notes[subtype] = note
    where = " OR ".join(parts)
    sql = f"SELECT event_id, event_subtype, value_numeric FROM events WHERE value_numeric IS NOT NULL AND ({where})"
    rows = conn.execute(text(sql), params).fetchall()
    flags = []
    for event_id, subtype, v in rows:
        lo, hi, note = PLAUSIBLE_RANGES[subtype]
        flags.append((event_id, f"Value {v} outside plausible range [{lo}, {hi}] for {subtype} ({note})"))
    return _flag(flags, conn, "implausible_range", "Value outside hardcoded plausible range (see quality_rules.py PLAUSIBLE_RANGES)")


def rule_temporal_misalignment(conn) -> int:
    flags = []
    # Window timestamps in raw_* are space-separated; events use 'T'. Normalize
    # both sides via replace() so lexicographic comparison is correct. The
    # shifted boundaries are computed with datetime(col, :t_before/:t_after),
    # where the modifiers are built from TEMPORAL_TOLERANCE (single source of
    # truth for the tolerance). datetime() emits space-separated output, so the
    # shifted boundaries are normalized to 'T' as well.
    norm = "replace({col}, ' ', 'T')"
    shift = "replace(datetime({col}, :{mod}), ' ', 'T')"
    TS_FMT = "%Y-%m-%dT%H:%M:%S"

    def _hours_between(ts: str, boundary: str) -> float | None:
        """Hours between an event timestamp and a (raw) boundary; negative = outside."""
        try:
            t = datetime.strptime(ts, TS_FMT)
            b = datetime.strptime(str(boundary).replace(" ", "T"), TS_FMT)
            return (t - b).total_seconds() / 3600.0
        except (ValueError, TypeError):
            return None

    def _sev_for(ts: str, boundary: str) -> str | None:
        h = _hours_between(ts, boundary)
        if h is None:
            return None
        return temporal_severity(abs(h))

    # Event outside its ICU stay window (encounter_id == stay_id), > tolerance
    stay_rows = conn.execute(
        text(
            f"SELECT e.event_id, e.event_timestamp, {norm.format(col='s.intime')} AS intime, "
            f"{norm.format(col='s.outtime')} AS outtime, "
            f"{shift.format(col='s.intime', mod='t_before')} AS intime_lo, "
            f"{shift.format(col='s.outtime', mod='t_after')} AS outtime_hi "
            f"FROM events e JOIN raw_icustays s ON e.encounter_id = s.stay_id "
            "WHERE e.event_timestamp IS NOT NULL AND (s.intime IS NOT NULL OR s.outtime IS NOT NULL)"
        ),
        {"t_before": _TEMPORAL_BEFORE, "t_after": _TEMPORAL_AFTER},
    ).fetchall()
    for event_id, ts, intime, outtime, intime_lo, outtime_hi in stay_rows:
        if intime is not None and intime_lo is not None and ts < intime_lo:
            flags.append((event_id, f"Event timestamp {ts} is >{_TEMPORAL_LABEL} before ICU stay start {intime}", _sev_for(ts, intime)))
        elif outtime is not None and outtime_hi is not None and ts > outtime_hi:
            flags.append((event_id, f"Event timestamp {ts} is >{_TEMPORAL_LABEL} after ICU stay end {outtime}", _sev_for(ts, outtime)))

    # Event outside its admission window (encounter_id == hadm_id), > tolerance
    adm_rows = conn.execute(
        text(
            f"SELECT e.event_id, e.event_timestamp, {norm.format(col='a.admittime')} AS admittime, "
            f"{norm.format(col='a.dischtime')} AS dischtime, "
            f"{shift.format(col='a.admittime', mod='t_before')} AS admittime_lo, "
            f"{shift.format(col='a.dischtime', mod='t_after')} AS dischtime_hi "
            f"FROM events e JOIN raw_admissions a ON e.encounter_id = a.hadm_id "
            "WHERE e.event_timestamp IS NOT NULL AND (a.admittime IS NOT NULL OR a.dischtime IS NOT NULL)"
        ),
        {"t_before": _TEMPORAL_BEFORE, "t_after": _TEMPORAL_AFTER},
    ).fetchall()
    for event_id, ts, admittime, dischtime, admittime_lo, dischtime_hi in adm_rows:
        if admittime is not None and admittime_lo is not None and ts < admittime_lo:
            flags.append((event_id, f"Event timestamp {ts} is >{_TEMPORAL_LABEL} before admission {admittime}", _sev_for(ts, admittime)))
        elif dischtime is not None and dischtime_hi is not None and ts > dischtime_hi:
            flags.append((event_id, f"Event timestamp {ts} is >{_TEMPORAL_LABEL} after discharge {dischtime}", _sev_for(ts, dischtime)))

    n = _flag(flags, conn, "temporal_misalignment", f"Event timestamp outside its encounter window by more than {_TEMPORAL_LABEL}")

    # Structural checks (impossible chronology, NO tolerance): true anomalies,
    # counted separately under rule_id = "chronology_violation".
    bad_stays = conn.execute(
        text("SELECT stay_id FROM raw_icustays WHERE intime IS NOT NULL AND outtime IS NOT NULL AND outtime < intime")
    ).fetchall()
    for (stay_id,) in bad_stays:
        _flag([(f"icustays_{stay_id}_start", f"ICU stay discharge time precedes admission time (stay {stay_id})")],
              conn, "chronology_violation", "ICU stay discharge time precedes admission time", severity="severe")

    bad_adms = conn.execute(
        text("SELECT hadm_id FROM raw_admissions WHERE admittime IS NOT NULL AND dischtime IS NOT NULL AND dischtime < admittime")
    ).fetchall()
    for (hadm_id,) in bad_adms:
        _flag([(f"admissions_{hadm_id}", f"Hospital discharge time precedes admission time (hadm {hadm_id})")],
              conn, "chronology_violation", "Hospital discharge time precedes admission time", severity="severe")

    return n


# ---------------------------------------------------------------------------
# Rule 5: BP pair relationship.
# Systolic/diastolic can each sit inside plausible bounds while the pair is
# nonsensical (systolic < diastolic). Flags BOTH events of the pair.
# ---------------------------------------------------------------------------
BP_PAIRS = [
    ("Non Invasive Blood Pressure systolic", "Non Invasive Blood Pressure diastolic"),
    ("Arterial Blood Pressure systolic", "Arterial Blood Pressure diastolic"),
]


def rule_bp_relationship_invalid(conn) -> int:
    flags = []
    for sys_label, dia_label in BP_PAIRS:
        rows = conn.execute(
            text(
                "SELECT s.event_id AS sys_id, d.event_id AS dia_id, "
                "s.value_numeric AS sys_val, d.value_numeric AS dia_val "
                "FROM events s JOIN events d "
                "  ON s.patient_id = d.patient_id "
                " AND s.encounter_id = d.encounter_id "
                " AND s.event_timestamp = d.event_timestamp "
                " AND s.source_table = d.source_table "
                "WHERE s.event_subtype = :sys_label AND d.event_subtype = :dia_label "
                "  AND s.value_numeric IS NOT NULL AND d.value_numeric IS NOT NULL "
                "  AND s.value_numeric < d.value_numeric"
            ),
            {"sys_label": sys_label, "dia_label": dia_label},
        ).fetchall()
        for sys_id, dia_id, sys_val, dia_val in rows:
            desc = f"Systolic ({sys_val}) is lower than diastolic ({dia_val}) for the same reading"
            flags.append((sys_id, desc))
            flags.append((dia_id, desc))
    return _flag(flags, conn, "bp_relationship_invalid", "Systolic lower than diastolic in the same reading", severity="severe")


def run_quality_rules() -> dict[str, int]:
    init_db()  # ensures severity column migration before INSERTs
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM quality_flags"))
        rule_missing_value(conn)
        rule_duplicate(conn)
        rule_implausible_range(conn)
        rule_temporal_misalignment(conn)
        rule_bp_relationship_invalid(conn)
        counts = {
            rule: int(n)
            for rule, n in conn.execute(
                text("SELECT rule_id, COUNT(*) FROM quality_flags GROUP BY rule_id")
            ).fetchall()
        }
    return counts
