"""verify_patch — independent patch verifier (Checkpoint 4).

The evaluator side of the evaluator-optimizer loop: a SEPARATE call from
patch (never the same prompt) that judges a proposed insertion on grounding,
redundancy, and placement. `pass` is recomputed in code as the conjunction of
the three component verdicts — the model's own pass value is never trusted
over its components, and a missing/invalid verdict conservatively fails.

VerifyResult = {
  "patch_id": "f4",
  "grounded": true|false,
  "non_redundant": true|false,
  "correctly_placed": true|false,
  "pass": true|false,
  "reasons": ["..."]
}
"""

from __future__ import annotations

import json

from .llm import call_json

# Split for prompt caching: rules + ORIGINAL NOTE are stable across every
# patch (and every loop iteration) verified against the same note (cached
# prefix); the proposed insertion + evidence vary and come last.
RULES_AND_NOTE = """You are a patch verifier. Given the ORIGINAL note, a PROPOSED insertion, and the EVIDENCE, judge three things:
1. grounded: is every claim in the insertion supported by the evidence? (no unsupported or invented claims)
2. non_redundant: does the insertion avoid duplicating content already present in the note?
3. correctly_placed: is the target SOAP section correct for this fact?
Give short reasons. pass = all three true. Return ONLY {{"grounded","non_redundant","correctly_placed","pass","reasons":[...]}}.
ORIGINAL NOTE: {note}"""

PATCH_AND_EVIDENCE = """PROPOSED insertion — target section: {section} (mode: {mode})
INSERT TEXT: {insert_text}
ADDED CLAIMS: {claims}
EVIDENCE (transcript span / FHIR ref): {evidence}"""

_JUDGMENTS = ("grounded", "non_redundant", "correctly_placed")


def verify_patch(patch: dict, evidence: str, note: str, model: str | None = None) -> dict:
    """Judge one proposed patch against the original note + evidence."""
    result = call_json(
        [
            {"text": RULES_AND_NOTE.format(note=note), "cache": True},
            {
                "text": PATCH_AND_EVIDENCE.format(
                    section=patch["section"],
                    mode=patch.get("mode", "append"),
                    insert_text=patch["insert_text"],
                    claims=json.dumps(patch.get("added_claims", [])),
                    evidence=evidence,
                )
            },
        ],
        max_tokens=8000,
        model=model,
    )
    if isinstance(result, list):  # tolerate a single-element list wrapper
        result = next((r for r in result if isinstance(r, dict)), None)
    if not isinstance(result, dict):
        raise ValueError(f"verify_patch: expected a JSON object, got {type(result)}")

    reasons = result.get("reasons")
    if isinstance(reasons, str):
        reasons = [reasons]
    if not isinstance(reasons, list):
        reasons = []
    reasons = [str(r).strip() for r in reasons if str(r).strip()]

    out: dict = {"patch_id": patch.get("flag_id")}
    for key in _JUDGMENTS:
        value = result.get(key)
        if not isinstance(value, bool):
            reasons.append(
                f"Missing/invalid {key} verdict {value!r} — conservatively treated as false."
            )
            value = False
        out[key] = value
    out["pass"] = all(out[k] for k in _JUDGMENTS)  # recomputed, never trusted
    out["reasons"] = reasons
    return out
