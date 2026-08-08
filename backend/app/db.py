"""SQLite engine + DDL for the unified events model."""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "./data/db.sqlite")
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", future=True)

EVENTS_DDL = [
    """CREATE TABLE IF NOT EXISTS events (
      event_id        TEXT PRIMARY KEY,
      patient_id      TEXT NOT NULL,
      encounter_id    TEXT,
      event_type      TEXT NOT NULL,
      event_subtype   TEXT,
      value           TEXT,
      value_numeric   REAL,
      unit            TEXT,
      event_timestamp TEXT NOT NULL,
      source_table    TEXT NOT NULL,
      source_row_id   TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_events_patient ON events(patient_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_encounter ON events(encounter_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)",
    "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(event_timestamp)",
]

QUALITY_FLAGS_DDL = [
    """CREATE TABLE IF NOT EXISTS quality_flags (
      flag_id     TEXT PRIMARY KEY,
      event_id    TEXT NOT NULL,
      flag_type   TEXT NOT NULL,
      rule_id     TEXT NOT NULL,
      description TEXT NOT NULL,
      reversible  INTEGER DEFAULT 1
    )""",
    "CREATE INDEX IF NOT EXISTS idx_flags_event ON quality_flags(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_flags_rule ON quality_flags(rule_id)",
]


def init_db() -> None:
    with engine.begin() as conn:
        for stmt in EVENTS_DDL + QUALITY_FLAGS_DDL:
            conn.execute(text(stmt))
        # Idempotent migration: severity band for temporal flags.
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(quality_flags)"))}
        if "severity" not in cols:
            conn.execute(text("ALTER TABLE quality_flags ADD COLUMN severity TEXT"))
