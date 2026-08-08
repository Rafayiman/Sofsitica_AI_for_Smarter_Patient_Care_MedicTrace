"""GET /api/quality/summary — global or patient-scoped data-quality dashboard (Track 2 support).

Aggregates the additive, reversible quality_flags table plus unit-variation
scan into one payload the frontend dashboard renders. Read-only.

Optional query param `patient_id` scopes every metric to one patient, so the
same endpoint powers both the "overall dataset" and "current patient" tabs.
"""
from fastapi import APIRouter
from sqlalchemy import text

from ..db import engine
from ..ingest.quality_rules import RULE_ORDER

router = APIRouter()


@router.get("/api/quality/summary")
def quality_summary(patient_id: str | None = None) -> dict:
    conds: list[str] = []
    params: dict[str, str] = {}
    if patient_id:
        conds.append("e.patient_id = :pid")
        params["pid"] = patient_id
    where = ("WHERE " + " AND ".join(conds)) if conds else ""

    with engine.connect() as conn:
        total_events = int(
            conn.execute(text("SELECT COUNT(*) FROM events e " + where), params).scalar()
        )
        total_flags = int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM quality_flags f "
                    "JOIN events e ON e.event_id = f.event_id " + where
                ),
                params,
            ).scalar()
        )

        # Per rule + severity, including zero-count rows for every defined rule
        # so the dashboard honestly shows "0 flags" for e.g. chronology_violation.
        stored = {
            (r, s): int(c)
            for r, s, c in conn.execute(
                text(
                    "SELECT f.rule_id, f.severity, COUNT(*) "
                    "FROM quality_flags f "
                    "JOIN events e ON e.event_id = f.event_id "
                    + where + " GROUP BY f.rule_id, f.severity"
                ),
                params,
            ).fetchall()
        }
        per_rule = []
        for rule in RULE_ORDER:
            sev_counts = [
                {"severity": sev, "count": n}
                for (r, sev), n in stored.items()
                if r == rule
            ]
            if not sev_counts:
                sev_counts = [{"severity": None, "count": 0}]
            per_rule.append({"rule_id": rule, "severity_counts": sev_counts})

        # Coverage per source table: rows ingested vs events flagged.
        # Definition (documented, SQA BUG #6): flagged_events counts DISTINCT
        # events carrying at least one flag, not the number of flag rows —
        # an event with 3 missing-value flags contributes 1.
        rows_by_table = dict(
            conn.execute(
                text(
                    "SELECT e.source_table, COUNT(*) FROM events e " + where
                    + " GROUP BY e.source_table"
                ),
                params,
            ).fetchall()
        )
        flagged_by_table = dict(
            conn.execute(
                text(
                    "SELECT e.source_table, COUNT(DISTINCT f.event_id) "
                    "FROM quality_flags f JOIN events e ON e.event_id = f.event_id "
                    + where + " GROUP BY e.source_table"
                ),
                params,
            ).fetchall()
        )
        per_table = [
            {
                "source_table": table,
                "rows": int(rows),
                "flagged_events": int(flagged_by_table.get(table, 0)),
            }
            for table, rows in sorted(
                rows_by_table.items(), key=lambda kv: kv[1], reverse=True
            )
        ]

        # Unit-variation scan: event subtypes observed with more than one
        # distinct unit (only units actually present, "" excluded).
        uv_conds = ["e.unit IS NOT NULL", "e.unit != ''"]
        uv_conds.extend(conds)
        uv_where = "WHERE " + " AND ".join(uv_conds)
        unit_variation = [
            {
                "event_subtype": st,
                "unit_count": int(n),
                "units": [u for u in units.split(",") if u],
            }
            for st, n, units in conn.execute(
                text(
                    "SELECT e.event_subtype, COUNT(DISTINCT e.unit), "
                    "GROUP_CONCAT(DISTINCT e.unit) "
                    "FROM events e "
                    + uv_where
                    + " GROUP BY e.event_subtype HAVING COUNT(DISTINCT e.unit) > 1 "
                    "ORDER BY COUNT(DISTINCT e.unit) DESC LIMIT 12"
                ),
                params,
            ).fetchall()
        ]

    return {
        "patient_id": patient_id,
        "total_events": total_events,
        "total_flags": total_flags,
        "per_rule": per_rule,
        "per_table": per_table,
        "unit_variation": unit_variation,
    }
