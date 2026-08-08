"""Run the 24-question eval set against the live Q&A endpoint; report the four
named track metrics.

Usage:
    python eval/run_eval.py [--base http://127.0.0.1:8000] [--out eval/report.json]

The machine-readable report (score, track metrics, per-question rows, latency)
is written to --out for the dashboard's "Eval & rubric evidence" section
(GET /api/eval/report serves it).

Metrics (all reported with underlying counts):
  - Structured-fact accuracy : fact-category passes / fact total
  - Temporal-order accuracy  : order-category passes / order total
  - Source-provenance coverage: answered-with-citations / answered total
                               (prose-to-citation mapping spot-checked by hand,
                               see EVAL.md)
  - Abstention accuracy      : (unanswerable not_found + out_of_scope refusals)
                               / (unanswerable + out_of_scope total)

Latency (end-to-end request -> grounded answer, seconds) is reported per
question and as mean / p50 / p95 / max as supporting evidence only — it is
environment-dependent (this machine, Groq model), not a model-level claim.
"""

import argparse
import json
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from checks import evaluate

ROOT = Path(__file__).resolve().parent


def post(url: str, payload: dict, timeout: int = 180) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--questions", default=str(ROOT / "questions.json"))
    ap.add_argument("--out", default=str(ROOT / "report.json"))
    args = ap.parse_args()

    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    patient_id = questions["patient_id"]
    results = []
    latencies: list[float] = []

    for q in questions["questions"]:
        t0 = time.perf_counter()
        try:
            resp = post(f"{args.base}/api/ask", {"patient_id": patient_id, "question": q["question"]})
        except Exception as exc:  # noqa: BLE001
            resp = {"status": "error", "answer_summary": f"request failed: {exc}", "citations": []}
        elapsed = time.perf_counter() - t0
        latencies.append(elapsed)
        ok = evaluate(resp, q["check"])
        results.append(
            {
                "qid": q["qid"],
                "category": q["category"],
                "question": q["question"],
                "check": q["check"],
                "status": resp.get("status"),
                "citations": len(resp.get("citations") or []),
                "latency_s": round(elapsed, 2),
                "pass": ok,
            }
        )

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
    abst_n = sum(
        1
        for r in abst_rows
        if (r["category"] == "unanswerable" and r["status"] == "not_found")
        or (r["category"] == "out_of_scope" and r["status"] == "out_of_scope")
    )
    abst_d = len(abst_rows)

    print(f"\nEval report — patient {patient_id} — {passed}/{total} passed\n")
    for r in results:
        mark = "  " if r["pass"] else "!!"
        print(
            f"{mark} {r['qid']:>4} {r['category']:<13} {'PASS' if r['pass'] else 'FAIL':<5} "
            f"(check={r['check']}, status={r['status']}, citations={r['citations']}, "
            f"latency={r['latency_s']}s) {r['question']}"
        )

    print("\nTrack metrics:")
    print(f"  Structured-fact accuracy     : {fact_n}/{fact_d} = {fact_n / fact_d:.0%}" if fact_d else "  Structured-fact accuracy : n/a")
    print(f"  Temporal-order accuracy      : {order_n}/{order_d} = {order_n / order_d:.0%}" if order_d else "  Temporal-order accuracy : n/a")
    print(f"  Source-provenance coverage   : {prov_n}/{prov_d} = {prov_n / prov_d:.0%}" if prov_d else "  Source-provenance coverage : n/a")
    print(f"  Abstention accuracy          : {abst_n}/{abst_d} = {abst_n / abst_d:.0%}" if abst_d else "  Abstention accuracy : n/a")

    # End-to-end latency (request -> grounded answer), reported as supporting info.
    if latencies:
        ans = [l for r, l in zip(results, latencies) if r["status"] == "answered"]
        print("\nLatency (end-to-end, seconds):")
        print(f"  all requests   : mean={statistics.mean(latencies):.2f} p50={statistics.median(latencies):.2f} "
              f"p95={sorted(latencies)[int(0.95 * (len(latencies) - 1))]:.2f} max={max(latencies):.2f}")
        if ans:
            print(f"  answered only  : mean={statistics.mean(ans):.2f} p50={statistics.median(ans):.2f} "
                  f"p95={sorted(ans)[int(0.95 * (len(ans) - 1))]:.2f} max={max(ans):.2f}")

    print(f"\nScore: {passed}/{total}")

    if ans:
        latency = {
            "all": {
                "mean": round(statistics.mean(latencies), 2),
                "p50": round(statistics.median(latencies), 2),
                "p95": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 2),
                "max": round(max(latencies), 2),
            },
            "answered": {
                "mean": round(statistics.mean(ans), 2),
                "p50": round(statistics.median(ans), 2),
                "p95": round(sorted(ans)[int(0.95 * (len(ans) - 1))], 2),
                "max": round(max(ans), 2),
            },
        }
    else:
        latency = {"all": None, "answered": None}

    report = {
        "patient_id": patient_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "total": total,
        "metrics": {
            "fact": [fact_n, fact_d],
            "order": [order_n, order_d],
            "provenance": [prov_n, prov_d],
            "abstention": [abst_n, abst_d],
        },
        "questions": results,
        "latency": latency,
    }
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport written to {args.out}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
