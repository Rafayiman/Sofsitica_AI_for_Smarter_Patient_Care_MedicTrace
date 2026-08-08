"""Shared per-question pass/fail logic for the LLM eval and the keyword baseline.

Check types (see eval/questions.json):
  - status_not_found            : expect status == 'not_found'
  - status_out_of_scope         : expect status == 'out_of_scope'
  - citations_present           : answered + >= 1 citation
  - citations_from_events       : answered + citations from the events table
  - citations_from_prescriptions: answered + a prescription citation
  - citations_present_or_not_found : either answered+citations or not_found
  - answer_contains_age_or_gender : answered and summary mentions female/F/52
  - answer_contains:<a|b|...>   : answered and summary contains any alternative
                                 (case-insensitive)
  - labs_before_icu              : answered + labevents citations + the executed
                                 query (response "query" field) compares event
                                 timestamps against icu_stay rows (temporal claim
                                 verified at the SQL level, not by summary wording)
For the keyword baseline (no refusal concept), status_out_of_scope checks are
scored as "abstained" when the baseline returns not_found (see EVAL.md).
"""


def _tables(resp: dict) -> set[str]:
    return {c.get("table") for c in (resp.get("citations") or [])}


def _summary(resp: dict) -> str:
    return (resp.get("answer_summary") or "").lower()


def evaluate(resp: dict, check: str, baseline_mode: bool = False) -> bool:
    status = resp.get("status")
    citations = resp.get("citations") or []

    if check == "status_not_found":
        return status == "not_found"
    if check == "status_out_of_scope":
        if baseline_mode:
            return status == "not_found"  # baseline abstains instead of refusing
        return status == "out_of_scope"
    if check == "citations_present":
        return status == "answered" and len(citations) > 0
    if check == "citations_from_events":
        # citations carry the source_table (labevents, chartevents, ...), never
        # the literal table name "events"; anything other than raw_patients counts.
        return status == "answered" and any(t not in ("raw_patients", None) for t in _tables(resp))
    if check == "citations_from_prescriptions":
        return status == "answered" and "prescriptions" in _tables(resp)
    if check == "citations_present_or_not_found":
        return status == "not_found" or (status == "answered" and len(citations) > 0)
    if check == "answer_contains_age_or_gender":
        s = _summary(resp)
        return status == "answered" and ("female" in s or "gender" in s or "52" in s)
    if check == "labs_before_icu":
        # o3: "any lab results before the first ICU admission?". The LLM's
        # summary wording is not part of the ground truth (it answered a
        # correct list without the words yes/before/prior in run 3); verify
        # the evidence instead: labevents citations AND a query that compares
        # event_timestamp against icu_stay rows.
        if status != "answered":
            return False
        if "labevents" not in _tables(resp):
            return False
        q = (resp.get("query") or "").lower()
        return "icu_stay" in q and "<" in q
    if check.startswith("answer_contains:"):
        if status != "answered":
            return False
        s = _summary(resp)
        alternatives = [alt.strip().lower() for alt in check.split(":", 1)[1].split("|")]
        return any(alt in s for alt in alternatives if alt)
    return False
