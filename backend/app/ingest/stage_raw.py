"""Stage 1: load every CSV verbatim into raw_* tables.

No column-name guessing: each CSV becomes a table named raw_{stem} with the
exact columns of the file. All values are kept as TEXT (dtype=str) so nothing
is reformatted or lost before the transform stage.
"""
import gzip
import os

import pandas as pd

from ..db import engine

SUBDIRS = ("hosp", "icu")


def csv_files(csv_dir: str) -> list[str]:
    found = []
    for sub in SUBDIRS:
        folder = os.path.join(csv_dir, sub)
        if not os.path.isdir(folder):
            continue
        for fname in sorted(os.listdir(folder)):
            if fname.endswith(".csv.gz"):
                found.append((sub, fname))
    return found


def stage_raw(csv_dir: str, verbose: bool = True) -> dict:
    counts: dict[str, int] = {}
    for sub, fname in csv_files(csv_dir):
        table = "raw_" + fname.replace(".csv.gz", "")
        path = os.path.join(csv_dir, sub, fname)
        df = pd.read_csv(path, dtype=str, keep_default_na=True)
        df.to_sql(table, engine, if_exists="replace", index=False)
        counts[table] = int(len(df))
        if verbose:
            print(f"  staged {table}: {len(df)} rows")
    return counts


def gz_line_count(path: str) -> int:
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        return sum(1 for _ in fh) - 1


def verify_counts(csv_dir: str, counts: dict) -> list[str]:
    """Stage 1 check: every raw_* row count matches the gzip line count minus header."""
    failures = []
    for table, n in counts.items():
        stem = table[len("raw_"):]
        rel = None
        for sub in SUBDIRS:
            candidate = os.path.join(csv_dir, sub, f"{stem}.csv.gz")
            if os.path.isfile(candidate):
                rel = candidate
                break
        if rel is None:
            failures.append(f"{table}: source file not found")
            continue
        expected = gz_line_count(rel)
        if n != expected:
            failures.append(f"{table}: staged {n} vs source {expected}")
    return failures
