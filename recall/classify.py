"""classify — severity + expectation judge for ABSENT facts (Checkpoint 3).

Separate call from presence (never mix judgment types). Batched per note
version for cost (same pattern as presence); the per-fact judgment contract
matches the spec exactly.

ClassifyResult = {
  "fact_id": "f1",
  "expected": true|false,     # false => suppressed (non-pertinent negative, incidental normal, irrelevant background)
  "severity": "safety_critical|major|minor",
  "why_it_matters": "one sentence"
}
"""

from __future__ import annotations

import json

from .llm import call_json

PROMPT = """You are a clinical documentation reviewer. Given facts that are MISSING from a clinical note and the note's context, judge two things for EACH fact.
1. `expected`: should a complete note for THIS visit document this fact? (true/false — false for non-pertinent negatives, incidental normals, or chart background irrelevant to this visit).
2. `severity`: if omitted and left uncorrected, the clinical impact — `safety_critical` (contraindication, red-flag symptom, actionable abnormal result, critical follow-up), `major` (could change management or documentation completeness), or `minor`.
Give a one-sentence `why_it_matters`. Base the judgment only on the fact and the provided note context.
Judge each fact independently. Return ONLY a JSON list, one object per fact, in the same order: {{"fact_id": "...", "expected": true|false, "severity": "safety_critical|major|minor", "why_it_matters": "..."}}.
NOTE CONTEXT: {note}
MISSING FACTS: {facts_json}"""

VALID_SEVERITIES = ("safety_critical", "major", "minor")


def classify(facts: list[dict], note_context: str, model: str | None = None) -> list[dict]:
    """Judge expected + severity for each absent fact — one batched call per note."""
    if not facts:
        return []
    facts_json = json.dumps(
        [
            {"id": f["id"], "text": f["text"], "type": f.get("type"), "slots": f.get("slots", {})}
            for f in facts
        ],
        indent=1,
    )
    results = call_json(
        PROMPT.format(note=note_context, facts_json=facts_json),
        max_tokens=16000,
        model=model,
    )
    if not isinstance(results, list):
        raise ValueError(f"classify: expected a JSON list, got {type(results)}")

    # Reconcile: every input fact gets exactly one result; invalid values are
    # conservatively kept-and-flagged (expected=true, severity=minor) rather
    # than silently dropped.
    by_id = {}
    for r in results:
        if isinstance(r, dict) and r.get("fact_id") is not None and r["fact_id"] not in by_id:
            by_id[r["fact_id"]] = r
    reconciled = []
    for f in facts:
        r = by_id.get(
            f["id"],
            {
                "fact_id": f["id"],
                "expected": True,
                "severity": "minor",
                "why_it_matters": "No verdict returned by classifier; kept conservatively as minor.",
            },
        )
        r["expected"] = bool(r.get("expected", True))
        if r.get("severity") not in VALID_SEVERITIES:
            r["why_it_matters"] = (
                f"Invalid severity {r.get('severity')!r} normalized to minor. "
                + str(r.get("why_it_matters", ""))
            )
            r["severity"] = "minor"
        r.setdefault("why_it_matters", "")
        reconciled.append(r)
    return reconciled
