"""presence — Checkpoint 1 core: grounded entailment judge (note vs facts).

One batched call per note over the full fact list. Judges ONLY against the
note text — never the transcript. No severity, no fixes, no quality rating.

PresenceResult = {
  "fact_id": "f1",
  "status": "present|partial|absent",
  "note_evidence": "verbatim note quote or null",
  "rationale": "one short sentence"
}
"""

from __future__ import annotations

import json

from .llm import call_json

# Prompt is split into two blocks for prompt caching: the rules + FACTS are
# stable across every note version of the same encounter (provided note,
# degraded copies) and form the cached prefix; the NOTE varies per call and
# comes last. Same judgment rules, reordered only.
RULES_AND_FACTS = """You are a grounded entailment judge. Given a clinical NOTE and a list of candidate FACTS, judge for EACH fact whether the note documents it.
Rules:

Judge each fact independently against the FULL note (any section, any phrasing — clinical paraphrase counts, e.g. "no numbness or tingling" ≈ "no focal neuro deficits").
present = the note states or clearly entails the fact. partial = the note captures part but drops a clinically meaningful component (e.g. the drug but not the dose). absent = not present or entailed.
Base the verdict ONLY on the note text provided — do NOT use the transcript or outside knowledge.
For present/partial, quote the exact supporting note span in note_evidence.
Do NOT rate quality, assign severity, or suggest fixes. Only the present/partial/absent judgment + evidence.
Each result is an object: {{"fact_id": "<fact id>", "status": "present|partial|absent", "note_evidence": "<verbatim note quote>" or null, "rationale": "<one short sentence>"}}. Return one result per fact, in the same order.
Return ONLY a JSON list of PresenceResult objects.
FACTS: {facts_json}"""

NOTE_BLOCK = "NOTE: {note}"


def presence(note: str, facts: list[dict], model: str | None = None) -> list[dict]:
    """Judge presence of every fact in the note — one batched call."""
    facts_json = json.dumps(
        [
            {"id": f["id"], "text": f["text"], "type": f.get("type"), "slots": f.get("slots", {})}
            for f in facts
        ],
        indent=1,
    )
    results = call_json(
        [
            {"text": RULES_AND_FACTS.format(facts_json=facts_json), "cache": True},
            {"text": NOTE_BLOCK.format(note=note)},
        ],
        max_tokens=16000,
        model=model,
    )
    if not isinstance(results, list):
        raise ValueError(f"presence: expected a JSON list, got {type(results)}")

    # Reconcile against the input facts: every fact gets exactly one result.
    by_id = {}
    for r in results:
        fid = r.get("fact_id")
        if fid is not None and fid not in by_id:
            by_id[fid] = r
    reconciled = []
    for f in facts:
        r = by_id.get(
            f["id"],
            {"fact_id": f["id"], "status": "absent", "note_evidence": None,
             "rationale": "No verdict returned by judge; defaulted to absent."},
        )
        r.setdefault("status", "absent")
        r.setdefault("note_evidence", None)
        r.setdefault("rationale", "")
        if r["status"] not in ("present", "partial", "absent"):
            r["rationale"] = f"Invalid status {r['status']!r} normalized to absent. " + r["rationale"]
            r["status"] = "absent"
        reconciled.append(r)
    return reconciled
