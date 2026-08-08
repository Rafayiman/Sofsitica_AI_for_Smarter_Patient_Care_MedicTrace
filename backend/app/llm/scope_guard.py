"""Scope pre-check for /api/ask.

Classifies a question as DATA (factual about the structured record) or CLINICAL
(diagnosis / treatment / triage / prognosis / any "what should be done" judgment).
CLINICAL questions are refused before SQL generation ever happens — the question
never reaches the text-to-SQL context.
"""
from ..llm import client as llm

SCOPE_CHECK_PROMPT = """\
Classify the following question about a patient's clinical data record.
Answer with exactly one word: DATA or CLINICAL.

DATA = asks what the structured record contains (facts, values, timelines, counts).
CLINICAL = asks for a diagnosis, treatment recommendation, triage priority, prognosis,
or any judgment call about what should be done for the patient.

Examples:
- "What diagnoses did the patient receive?" -> DATA
- "What medications was the patient given?" -> DATA
- "What treatment should this patient receive for their diagnosis?" -> CLINICAL
- "Should this patient be triaged as urgent?" -> CLINICAL
- "Is this patient going to survive?" -> CLINICAL
- "What medication dose should I give next?" -> CLINICAL

Question: {question}
"""

OUT_OF_SCOPE_SUMMARY = (
    "This tool answers factual questions about the structured record only. "
    "It does not provide diagnosis, treatment, triage, or clinical recommendations. "
    "Please consult a qualified clinician."
)


def classify_scope(question: str) -> str | None:
    """Returns 'DATA', 'CLINICAL', or None when the model is unavailable/unparseable.

    Unparseable responses default to 'DATA' (proceed to SQL generation): the SQL
    guard and grounding still protect against fabrication; the scope guard is a
    pre-filter, not the last line of defense.
    """
    answer = llm.chat("You are a question-scope classifier.", SCOPE_CHECK_PROMPT.format(question=question))
    if not answer:
        return None
    verdict = answer.strip().upper().split()[0] if answer.strip() else ""
    return verdict if verdict in ("DATA", "CLINICAL") else None
