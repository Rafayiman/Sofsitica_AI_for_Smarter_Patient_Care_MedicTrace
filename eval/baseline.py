"""Keyword/template baseline for the Q&A engine.

No LLM involved: a regex-to-SQL template map. Questions whose keywords match a
template become a single-table SELECT scoped to the patient; everything else
returns not_found. Run on the same 24-question set and scored with the same
checks as the LLM eval, so the two systems are comparable on the four metrics.

Usage:
    python eval/baseline.py [--db backend/data/db.sqlite] [--questions eval/questions.json]
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

from checks import evaluate

ROOT = Path(__file__).resolve().parent

BASELINE_TEMPLATES = [
    (re.compile(r"\bmedications?\b", re.I),
     "SELECT event_id, patient_id, event_type, event_subtype, value, unit, event_timestamp, source_table FROM events WHERE patient_id = :pid AND event_type = 'medication' LIMIT 100"),
    (re.compile(r"\bcreatinine\b|\bpotassium\b|\bsodium\b|\blab(s|oratory)?\b", re.I),
     "SELECT event_id, patient_id, event_type, event_subtype, value, unit, event_timestamp, source_table FROM events WHERE patient_id = :pid AND event_type = 'lab' LIMIT 100"),
    (re.compile(r"\bdiagnos", re.I),
     "SELECT event_id, patient_id, event_type, event_subtype, value, event_timestamp, source_table FROM events WHERE patient_id = :pid AND event_type = 'diagnosis' LIMIT 100"),
    (re.compile(r"\bprocedures?\b", re.I),
     "SELECT event_id, patient_id, event_type, event_subtype, value, event_timestamp, source_table FROM events WHERE patient_id = :pid AND event_type = 'procedure' LIMIT 100"),
    (re.compile(r"\btransfers?\b", re.I),
     "SELECT event_id, patient_id, event_type, event_subtype, value, event_timestamp, source_table FROM events WHERE patient_id = :pid AND event_type = 'transfer' LIMIT 100"),
    (re.compile(r"\bicu stays?\b|\bicu admission", re.I),
     "SELECT event_id, patient_id, event_type, event_subtype, value, event_timestamp, source_table FROM events WHERE patient_id = :pid AND event_type = 'icu_stay' LIMIT 100"),
    (re.compile(r"\bheart rate\b|\bblood pressure\b|\bvitals?\b", re.I),
     "SELECT event_id, patient_id, event_type, event_subtype, value, unit, event_timestamp, source_table FROM events WHERE patient_id = :pid AND event_type = 'icu_observation' LIMIT 100"),
]


def baseline_answer(conn: sqlite3.Connection, patient_id: str, question: str) -> dict:
    """Returns an AskResponse-shaped dict; only 'answered' and 'not_found' occur."""
    for pattern, sql in BASELINE_TEMPLATES:
        if pattern.search(question):
            try:
                rows = conn.execute(sql, {"pid": patient_id}).fetchall()
            except sqlite3.Error:
                return {"status": "not_found", "answer_summary": "", "citations": []}
            citations = [
                {"table": r["source_table"], "field": r["event_subtype"] or r["event_type"],
                 "event_id": r["event_id"], "timestamp": r["event_timestamp"]}
                for r in rows
            ]
            if rows:
                return {
                    "status": "answered",
                    "answer_summary": f"[baseline] {len(rows)} row(s) returned by keyword template.",
                    "citations": citations,
                    "query": None,
                }
            return {"status": "not_found", "answer_summary": "", "citations": []}
    return {"status": "not_found", "answer_summary": "", "citations": []}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.getenv("DB_PATH", "../backend/data/db.sqlite"))
    ap.add_argument("--questions", default=str(ROOT / "questions.json"))
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    patient_id = questions["patient_id"]
    results = []

    for q in questions["questions"]:
        resp = baseline_answer(conn, patient_id, q["question"])
        ok = evaluate(resp, q["check"], baseline_mode=True)
        results.append({"qid": q["qid"], "category": q["category"], "status": resp["status"],
                        "citations": len(resp["citations"]), "pass": ok})

    total = len(results)
    passed = sum(1 for r in results if r["pass"])

    def acc(cat: str) -> tuple[int, int]:
        rows = [r for r in results if r["category"] == cat]
        return sum(1 for r in rows if r["pass"]), len(rows)

    fact_n, fact_d = acc("fact")
    order_n, order_d = acc("order")
    answered_rows = [r for r in results if r["status"] == "answered"]
    prov_n = sum(1 for r in answered_rows if r["citations"] > 0)
    prov_d = len(answered_rows)
    abst_rows = [r for r in results if r["category"] in ("unanswerable", "out_of_scope")]
    abst_n = sum(1 for r in abst_rows if r["status"] == "not_found")
    abst_d = len(abst_rows)

    print(f"\nBaseline (keyword/template) report — patient {patient_id} — {passed}/{total} passed\n")
    for r in results:
        mark = "  " if r["pass"] else "!!"
        print(f"{mark} {r['qid']:>4} {r['category']:<13} {'PASS' if r['pass'] else 'FAIL':<5} "
              f"(status={r['status']}, citations={r['citations']})")

    print("\nBaseline track metrics:")
    print(f"  Structured-fact accuracy     : {fact_n}/{fact_d} = {fact_n / fact_d:.0%}")
    print(f"  Temporal-order accuracy      : {order_n}/{order_d} = {order_n / order_d:.0%}")
    print(f"  Source-provenance coverage   : {prov_n}/{prov_d} = {prov_n / prov_d:.0%}")
    print(f"  Abstention accuracy          : {abst_n}/{abst_d} = {abst_n / abst_d:.0%}")
    print(f"\nBaseline score: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
