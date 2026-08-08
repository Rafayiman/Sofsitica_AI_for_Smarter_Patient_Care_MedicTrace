"""GET /api/timeline/{patient_id} + GET /api/group/{patient_id}.

Timeline returns events grouped by day + (type, subtype, source_table,
encounter_id). Groups with count > 1 carry a numeric summary (min/max/mean)
or the most common text value; clicking a group expands to the raw source
rows via the /group endpoint, with full provenance + quality flags.
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from ..db import engine
from ..schemas import (
    EventGroupOut,
    FlagOut,
    GroupExpandResponse,
    GroupFlagOut,
    RawEventOut,
    TimelineDayOut,
    TimelineResponse,
)

router = APIRouter()

GROUP_COLS = ("event_type", "event_subtype", "source_table", "encounter_id")

GROUP_SQL = text(
    """
    SELECT date(e.event_timestamp) AS d,
           e.event_type, e.event_subtype, e.source_table, e.encounter_id,
           COUNT(*) AS cnt,
           MIN(e.value_numeric) AS vmin, MAX(e.value_numeric) AS vmax, AVG(e.value_numeric) AS vmean,
           MAX(e.unit) AS unit,
           MIN(e.event_timestamp) AS first_ts, MAX(e.event_timestamp) AS last_ts
    FROM events e
    WHERE e.patient_id = :pid
    GROUP BY d, e.event_type, e.event_subtype, e.source_table, e.encounter_id
    ORDER BY d, e.event_type, e.event_subtype, e.source_table
    """
)

UNIT_MODE_SQL = text(
    """
    SELECT date(e.event_timestamp) AS d, e.event_type, e.event_subtype,
           e.source_table, e.encounter_id, e.unit, COUNT(*) AS c
    FROM events e
    WHERE e.patient_id = :pid AND e.unit IS NOT NULL AND e.unit != ''
    GROUP BY d, e.event_type, e.event_subtype, e.source_table, e.encounter_id, e.unit
    """
)

MODE_SQL = text(
    """
    WITH g AS (
      SELECT date(e.event_timestamp) AS d, e.event_type, e.event_subtype,
             e.source_table, e.encounter_id, e.value, e.unit, COUNT(*) AS c
      FROM events e
      WHERE e.patient_id = :pid AND e.value IS NOT NULL
      GROUP BY d, e.event_type, e.event_subtype, e.source_table, e.encounter_id, e.value, e.unit
    ),
    rn AS (
      SELECT g.*, ROW_NUMBER() OVER (
        PARTITION BY d, event_type, event_subtype, source_table, encounter_id
        ORDER BY c DESC, value
      ) AS r
      FROM g
    )
    SELECT d, event_type, event_subtype, source_table, encounter_id, value, unit, c
    FROM rn WHERE r = 1
    """
)

GROUP_FLAGS_SQL = text(
    """
    SELECT date(e.event_timestamp) AS d, e.event_type, e.event_subtype,
           e.source_table, e.encounter_id, qf.rule_id, COUNT(*) AS c
    FROM quality_flags qf JOIN events e ON e.event_id = qf.event_id
    WHERE e.patient_id = :pid
    GROUP BY d, e.event_type, e.event_subtype, e.source_table, e.encounter_id, qf.rule_id
    """
)

EXPAND_SQL = text(
    """
    SELECT * FROM events
    WHERE patient_id = :pid
      AND date(event_timestamp) = :d
      AND event_type = :etype
      AND (event_subtype = :stype OR ((:stype = '' OR :stype = 'null') AND event_subtype IS NULL))
      AND source_table = :stbl
      AND (encounter_id = :enc OR :enc IS NULL OR :enc = '')
    ORDER BY event_timestamp, event_id
    """
)

EXPAND_FLAGS_SQL = text(
    """
    SELECT qf.event_id, qf.rule_id, qf.description, qf.severity
    FROM quality_flags qf JOIN events e ON e.event_id = qf.event_id
    WHERE e.patient_id = :pid
      AND date(e.event_timestamp) = :d
      AND e.event_type = :etype
      AND (e.event_subtype = :stype OR ((:stype = '' OR :stype = 'null') AND e.event_subtype IS NULL))
      AND e.source_table = :stbl
      AND (e.encounter_id = :enc OR :enc IS NULL OR :enc = '')
    """
)


def _round2(x):
    return round(float(x), 2) if x is not None else None


@router.get("/api/timeline/{patient_id}", response_model=TimelineResponse)
def timeline(patient_id: str) -> TimelineResponse:
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT COUNT(*) FROM events WHERE patient_id = :pid"), {"pid": patient_id}
        ).scalar()
        if not exists:
            raise HTTPException(status_code=404, detail="Patient not found in events")

        groups = conn.execute(GROUP_SQL, {"pid": patient_id}).fetchall()
        modes = conn.execute(MODE_SQL, {"pid": patient_id}).fetchall()
        unit_modes = conn.execute(UNIT_MODE_SQL, {"pid": patient_id}).fetchall()
        group_flags = conn.execute(GROUP_FLAGS_SQL, {"pid": patient_id}).fetchall()

    mode_map = {}
    for d, etype, stype, stbl, enc, value, unit, c in modes:
        mode_map[(d, etype, stype, stbl, str(enc))] = (value, unit, int(c))

    # Most-common unit per group (ties broken alphabetically for determinism),
    # replacing the old arbitrary MAX(e.unit) fallback (SQA BUG #3).
    unit_map: dict[tuple, tuple] = {}
    for d, etype, stype, stbl, enc, unit, c in unit_modes:
        key = (d, etype, stype, stbl, str(enc))
        n = int(c)
        cur = unit_map.get(key)
        if cur is None or n > cur[1] or (n == cur[1] and unit < cur[0]):
            unit_map[key] = (unit, n)

    flag_map: dict[tuple, list[GroupFlagOut]] = {}
    for d, etype, stype, stbl, enc, rule_id, c in group_flags:
        flag_map.setdefault((d, etype, stype, stbl, str(enc)), []).append(
            GroupFlagOut(rule_id=rule_id, count=int(c))
        )

    days: dict[str, list[EventGroupOut]] = {}
    for d, etype, stype, stbl, enc, cnt, vmin, vmax, vmean, unit, first_ts, last_ts in groups:
        key = (d, etype, stype, stbl, str(enc))
        summary = None
        value = None
        group_unit = None
        mode_value, mode_unit, mode_count = mode_map.get(key, (None, None, None))
        unit_mode, _ = unit_map.get(key, (None, 0))
        if vmin is not None:
            summary = {"kind": "numeric", "min": _round2(vmin), "max": _round2(vmax), "mean": _round2(vmean)}
            if cnt == 1:
                value = None if mode_value is None else str(mode_value)
                group_unit = unit_mode or mode_unit or unit
            else:
                group_unit = unit_mode or mode_unit or unit
        else:
            if mode_value is not None:
                value = mode_value
                group_unit = unit_mode or mode_unit or unit
                if cnt > 1:
                    summary = {"kind": "text", "mode": mode_value, "mode_count": mode_count}

        days.setdefault(d, []).append(
            EventGroupOut(
                date=d,
                event_type=etype,
                event_subtype=stype,
                source_table=stbl,
                encounter_id=None if enc is None else str(enc),
                count=int(cnt),
                value=value,
                unit=group_unit,
                summary=summary,
                first_timestamp=first_ts,
                last_timestamp=last_ts,
                flags=flag_map.get(key, []),
            )
        )

    return TimelineResponse(
        patient_id=patient_id,
        days=[TimelineDayOut(date=d, groups=days[d]) for d in sorted(days)],
    )


@router.get("/api/group/{patient_id}", response_model=GroupExpandResponse)
def group_expand(
    patient_id: str,
    date: str,
    event_type: str,
    event_subtype: str,
    source_table: str,
    encounter_id: str | None = None,
) -> GroupExpandResponse:
    with engine.connect() as conn:
        rows = conn.execute(
            EXPAND_SQL,
            {"pid": patient_id, "d": date, "etype": event_type, "stype": event_subtype,
             "stbl": source_table, "enc": encounter_id},
        ).fetchall()
        flags = {}
        if rows:
            flag_rows = conn.execute(
                EXPAND_FLAGS_SQL,
                {"pid": patient_id, "d": date, "etype": event_type, "stype": event_subtype,
                 "stbl": source_table, "enc": encounter_id},
            ).fetchall()
            for event_id, rule_id, description, severity in flag_rows:
                flags.setdefault(event_id, []).append(FlagOut(rule_id=rule_id, description=description, severity=severity))

    events = [
        RawEventOut(
            event_id=r.event_id,
            patient_id=r.patient_id,
            encounter_id=r.encounter_id,
            event_type=r.event_type,
            event_subtype=r.event_subtype,
            value=r.value,
            value_numeric=r.value_numeric,
            unit=r.unit,
            event_timestamp=r.event_timestamp,
            source_table=r.source_table,
            source_row_id=r.source_row_id,
            flags=flags.get(r.event_id, []),
        )
        for r in rows
    ]
    return GroupExpandResponse(patient_id=patient_id, event_count=len(events), events=events)
