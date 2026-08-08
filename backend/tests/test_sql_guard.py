"""Guard unit tests. Run: pytest tests/ from backend/."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.llm.sql_guard import validate  # noqa: E402

GOOD = [
    ("SELECT value FROM events WHERE patient_id = '10000032' AND event_type='lab' LIMIT 5", True),
    ("SELECT COUNT(*) FROM events WHERE patient_id='10000032'", True),
    ("SELECT e.event_subtype, COUNT(*) FROM events e WHERE e.patient_id = 10000032 GROUP BY e.event_subtype LIMIT 10", True),
    ("SELECT value_numeric FROM events WHERE patient_id='10000032' AND event_subtype='Creatinine' AND value_numeric > 2 ORDER BY event_timestamp LIMIT 100", True),
    ("SELECT * FROM events WHERE patient_id='10000032'", True),
    ("SELECT CAST(value_numeric AS REAL) FROM events WHERE patient_id='1'", True),
    ("SELECT COUNT(*) AS n, event_type FROM events WHERE patient_id='1' GROUP BY event_type ORDER BY n DESC LIMIT 20", True),
    ("SELECT COUNT(*) FROM quality_flags qf JOIN events e ON qf.event_id = e.event_id WHERE e.patient_id='1' AND qf.rule_id='duplicate'", True),
]

BAD = [
    ("SELECT * FROM raw_labevents WHERE subject_id='10000032'", "unknown identifier"),
    ("INSERT INTO events VALUES (1,2,3)", "not SELECT"),
    ("DELETE FROM events WHERE patient_id=1", "not SELECT"),
    ("PRAGMA table_info(events)", "not SELECT"),
    ("SELECT * FROM events -- comment", "comments"),
    ("SELECT * FROM events /* x */", "comments"),
    ("SELECT * FROM events WHERE patient_id=1 UNION SELECT * FROM quality_flags", "forbidden keyword"),
    ("SELECT * FROM events", "patient_id"),
    ("SELECT * FROM events WHERE patient_id=1 LIMIT 500", "exceeds 100"),
    ("SELECT evil_column FROM events WHERE patient_id=1", "unknown identifier"),
    ("SELECT * FROM events WHERE patient_id=1 LIMIT 10; DROP TABLE events", "multiple statements"),
    # SQA BUG #1: patient_id must appear in a WHERE clause, not just anywhere.
    ("SELECT COUNT(*) FROM events GROUP BY patient_id LIMIT 100", "patient_id"),
    ("SELECT patient_id, COUNT(*) FROM events GROUP BY patient_id LIMIT 100", "patient_id"),
    ("SELECT COUNT(DISTINCT patient_id) FROM events LIMIT 100", "patient_id"),
    ("SELECT patient_id FROM events LIMIT 100", "patient_id"),
    ("SELECT COUNT(*) FROM events GROUP BY patient_id HAVING COUNT(*) > 1 LIMIT 100", "patient_id"),
    # patient_id in a JOIN ON clause is not a filter either.
    ("SELECT COUNT(*) FROM events e JOIN quality_flags qf ON e.patient_id = qf.event_id LIMIT 100", "patient_id"),
]


def test_good_queries_pass():
    for sql, _ in GOOD:
        ok, cleaned, reason = validate(sql)
        assert ok, f"should pass: {sql} ({reason})"
        assert cleaned is not None


def test_bad_queries_rejected():
    for sql, why in BAD:
        ok, cleaned, reason = validate(sql)
        assert not ok, f"should be rejected: {sql}"
        assert reason is not None


def test_limit_appended_when_missing():
    ok, cleaned, _ = validate("SELECT * FROM events WHERE patient_id='1'")
    assert ok and cleaned.endswith("LIMIT 100")


def test_where_scoped_patient_filter_accepted():
    # SQA BUG #1 regression: subquery WHERE filters and aggregate queries that
    # DO filter at the outer level must still pass.
    good = [
        "SELECT COUNT(*) FROM events WHERE patient_id='10000032'",
        "SELECT e.event_subtype, COUNT(*) FROM events e WHERE e.patient_id = 10000032 GROUP BY e.event_subtype LIMIT 10",
        "SELECT COUNT(DISTINCT encounter_id) AS n, event_type FROM events WHERE patient_id='10000032' GROUP BY event_type LIMIT 100",
        "SELECT e.event_id, e.event_timestamp FROM events e WHERE e.patient_id = '10000032' AND e.event_type = 'lab' AND e.event_timestamp < (SELECT MIN(event_timestamp) FROM events WHERE patient_id = '10000032' AND event_type = 'icu_stay') LIMIT 100",
        "SELECT gender FROM raw_patients WHERE subject_id = '10000032'",
    ]
    for sql in good:
        ok, cleaned, reason = validate(sql)
        assert ok, f"should pass: {sql} ({reason})"
        assert cleaned is not None
