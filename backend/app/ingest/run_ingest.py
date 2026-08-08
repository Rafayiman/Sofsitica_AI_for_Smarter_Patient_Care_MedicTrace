"""One-shot pipeline: stage raw CSVs -> unified events -> quality flags -> summary.

Run from backend/:  python -m app.ingest.run_ingest [--csv-dir PATH]
"""
import argparse
import os
import sys

from ..db import engine, init_db
from . import quality_rules
from .stage_raw import stage_raw, verify_counts
from .transform_events import transform_events
from sqlalchemy import text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv-dir", default=os.getenv("CSV_DIR", "demo_data/mimic-iv-clinical-database-demo-2.2"))
    parser.add_argument("--skip-stage", action="store_true")
    args = parser.parse_args()

    init_db()
    print("[1/3] staging raw CSVs ...")
    counts = {} if args.skip_stage else stage_raw(args.csv_dir)
    if not counts and not args.skip_stage:
        print(f"Stage 1 FAIL: no CSVs found under {args.csv_dir} (expected hosp/ and icu/ subfolders)")
        return 1
    if counts:
        failures = verify_counts(args.csv_dir, counts)
        if failures:
            print("Stage 1 FAILURES:")
            for f in failures:
                print("  -", f)
            return 1
        print(f"Stage 1 OK: {len(counts)} raw tables, all row counts verified")

    print("[2/3] transforming to unified events ...")
    report = transform_events()
    total = sum(v["inserted"] for v in report.values())
    with engine.connect() as conn:
        db_total = conn.execute(text("SELECT COUNT(*) FROM events")).scalar()
    print(f"Stage 2 OK: {total} mapped, {db_total} rows in events table")

    print("[3/3] running quality rules ...")
    flag_counts = quality_rules.run_quality_rules()
    print("Stage 3 OK: flags by rule:")
    for rule, n in sorted(flag_counts.items()):
        print(f"  {rule}: {n}")
    print("Pipeline complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
