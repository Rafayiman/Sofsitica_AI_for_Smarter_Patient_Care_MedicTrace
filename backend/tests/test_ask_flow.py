"""Test: POST /api/ask with a mocked LLM (no GROQ key required).

Simulates the LLM returning SQL, then exercises guard + execution + citations.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", "./data/db.sqlite")

from fastapi.testclient import TestClient

from app.main import app
from app.llm import client as llm

client = TestClient(app)

CASES = [
    # (question, fake_sql, expected_status)
    (
        "What medications were given?",
        "SELECT * FROM events WHERE patient_id = '10000032' AND event_type = 'medication' ORDER BY event_timestamp LIMIT 20",
        "answered",
    ),
    (
        "Creatinine trend",
        "SELECT event_timestamp, value_numeric FROM events WHERE patient_id = '10000032' AND event_subtype = 'Creatinine' ORDER BY event_timestamp LIMIT 100",
        "answered",
    ),
    (
        "How many labs on day one?",
        "SELECT COUNT(*) AS n FROM events WHERE patient_id = '10000032' AND event_type = 'lab'",
        "answered",  # aggregate: no citation columns
    ),
    (
        "Questions about things not in data",
        "SELECT * FROM events WHERE patient_id = '10000032' AND event_subtype = 'Alien Invasions' LIMIT 100",
        "not_found",
    ),
    (
        "Malicious injection attempt",
        "DROP TABLE events; SELECT * FROM events",
        "not_found",  # guard rejection -> not_found
    ),
    (
        "Cross-patient leakage attempt",
        "SELECT * FROM events WHERE event_type = 'lab' LIMIT 100",
        "not_found",  # no patient_id filter -> guard rejection
    ),
]


def fake_chat(system, user, temperature=0.1):
    if "Question:" in system:
        q = system.split("Question:")[-1].split("\n")[0].strip()
        for question, sql, _ in CASES:
            if question == q:
                return sql
    # summary call path: rows passed in user message
    if "Rows (JSON)" in user:
        return "[AI-generated summary] The rows show test data."
    return "SELECT * FROM events WHERE patient_id = '10000032' LIMIT 1"


llm.chat = fake_chat
llm.get_client = lambda: object()  # simulate a configured API key

results = []
for q, sql, expected in CASES:
    resp = client.post("/api/ask", json={"patient_id": "10000032", "question": q})
    body = resp.json()
    status = body.get("status")
    ok = status == expected
    results.append((q, expected, status, ok, len(body.get("citations", []))))
    print(f"{'PASS' if ok else 'FAIL'}  expected={expected} got={status}  citations={len(body.get('citations', []))}")
    print(f"      Q: {q}")
    if ok and status == "answered":
        print(f"      summary: {body['answer_summary'][:100]}")
    if not ok:
        print(f"      body: {body}")

print("---")
fails = [r for r in results if not r[3]]
print(f"failures: {len(fails)}")
