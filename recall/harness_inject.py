"""harness_inject — manufacture ground truth by deleting known-present facts.

Design rules (locked):
- Inject into the PROVIDED note only (gold reference). Never the generated note.
- Targets must be grounded AND present (per presence on the original note).
- One injection per degraded copy.
- Confirm-absent QC: presence(degraded, [fact]) must say absent, else retry once,
  else discard.

InjectionRecord = {
  "note_id", "injection_id", "fact": {CandidateFact}, "type", "severity",
  "deletion_method": "llm_edit", "confirmed_absent": true
}
"""

from __future__ import annotations

from .llm import call_text
from .presence import presence

# Split for prompt caching: rules + NOTE are identical across the ~3 edit
# calls per encounter (cached prefix); the fact to remove varies and comes
# last. The retry suffix rides on the varying block so retries still hit
# the cached prefix.
EDIT_RULES_AND_NOTE = """You are editing a clinical note. Remove every mention of the fact given at the end from the NOTE, and lightly smooth the surrounding text so it still reads naturally. Do NOT add any new clinical information. Do NOT remove or alter anything else. Return the FULL edited note only.
NOTE: {note}"""

FACT_BLOCK = "FACT TO REMOVE: {fact_text}"

RETRY_SUFFIX = """

IMPORTANT: A previous attempt left traces of this fact in the note. Be thorough — remove EVERY mention, restatement, or paraphrase of the fact anywhere in the note (all sections, including Assessment & Plan), while changing nothing else."""

# Interim severity heuristic from fact type (real classifier is Checkpoint 3).
SEVERITY_BY_TYPE = {
    "medication": "major",
    "observation": "major",       # abnormal/actionable observations
    "red_flag_screen": "major",
    "order": "major",
    "referral": "major",
    "followup": "minor",          # major if safety-relevant — classifier's job later
    "symptom": "minor",
    "sdoh": "minor",
    "counseling": "minor",
}
DEFAULT_SEVERITY = "minor"  # condition/procedure/relieving_factor/other
# NOTE: nothing maps to safety_critical yet — the dataset has no usable
# AllergyIntolerance resources; allergy scenarios need labeled synthetic
# injection in a later checkpoint.

TARGET_PRIORITY = {"medication": 0, "observation": 1, "red_flag_screen": 2, "order": 3, "referral": 4}


def severity_for(fact: dict) -> str:
    return SEVERITY_BY_TYPE.get(fact.get("type", "other"), DEFAULT_SEVERITY)


def select_targets(facts: list[dict], presence_results: list[dict], k: int = 3) -> list[dict]:
    """Grounded-and-present facts, medication/observation types weighted first."""
    status = {r["fact_id"]: r["status"] for r in presence_results}
    candidates = [
        f
        for f in facts
        if status.get(f["id"]) == "present"
        and f.get("source") in ("transcript", "fhir", "both")
    ]
    candidates.sort(key=lambda f: TARGET_PRIORITY.get(f.get("type", "other"), 5))
    return candidates[:k]


def make_degraded_note(provided_note: str, fact: dict, retry: bool = False) -> str:
    fact_text = FACT_BLOCK.format(fact_text=fact["text"])
    if retry:
        fact_text += RETRY_SUFFIX
    return call_text(
        [
            {"text": EDIT_RULES_AND_NOTE.format(note=provided_note), "cache": True},
            {"text": fact_text},
        ],
        max_tokens=8000,
    )


def inject_one(provided_note: str, fact: dict, note_id: str, k: int) -> tuple[dict | None, dict | None]:
    """Create one degraded note + record; returns (result, discarded).

    result = {"injection_record": ..., "degraded_note": ...} on success.
    discarded = {"note_id", "fact_id", "reason"} on failure.
    """
    last_failure = "edit returned degenerate output (too short) twice"
    for retry in (False, True):
        degraded = make_degraded_note(provided_note, fact, retry=retry)
        # Basic sanity: the edit must return a real note, not an apology/fragment.
        if len(degraded) < 0.5 * len(provided_note):
            last_failure = "edit returned degenerate output (too short)"
            continue
        verdict = presence(degraded, [fact])[0]
        if verdict["status"] == "absent":
            injection_id = f"{note_id}__inj_{k}"
            record = {
                "note_id": note_id,
                "injection_id": injection_id,
                "fact": fact,
                "type": fact.get("type", "other"),
                "severity": severity_for(fact),
                "deletion_method": "llm_edit",
                "confirmed_absent": True,
            }
            return {"injection_record": record, "degraded_note": degraded}, None
        last_failure = f"fact survived deletion (status={verdict['status']})"
    return None, {
        "note_id": note_id,
        "fact_id": fact["id"],
        "fact_text": fact["text"],
        "reason": last_failure + " after retry",
    }
