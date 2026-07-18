"""contradiction — Checkpoint 5: the SEPARATE note-vs-FHIR failure class.

detect_contradiction: LLM judge — claims in the note that directly conflict
with a coded FHIR value. inject_contradiction: LLM edit that alters exactly
ONE note claim to conflict with a coded value (the labeled planted set,
~15–20 across encounters, cached by the runner under
checkpoint5_cache/contradictions/).

Contradiction gets its OWN metric — it is NEVER folded into omission recall.
An omission (absence) is NOT a contradiction; the detect prompt says so
explicitly.
"""

from __future__ import annotations

from .extract_facts import condense_fhir
from .llm import call_json

# Prompt split for caching (mirrors presence.py): rules + condensed FHIR are
# stable per encounter (shared by the planted-note and clean-note detection
# calls, and by inject); the note varies and comes last.
DETECT_RULES_AND_FHIR = """You are auditing a clinical NOTE against the encounter's coded FHIR data. Find every claim in the note that DIRECTLY CONFLICTS with a coded FHIR value — a different number, different drug or dose, opposite finding, or wrong status.
Rules:

A contradiction requires the note to ASSERT something the FHIR contradicts. A fact missing from the note is an OMISSION, not a contradiction — never report absences.
Compare only against the FHIR shown below; no outside knowledge, no plausibility judgments.
Quote the conflicting note claim verbatim in `claim`, cite the FHIR resource in `fhir_ref` (ResourceType/id), and describe the conflict in one sentence.
Each result is an object: {{"claim": "<verbatim note span>", "fhir_ref": "ResourceType/id", "conflict_description": "<one sentence>"}}.
Return ONLY a JSON list — [] if the note conflicts with nothing.
ENCOUNTER FHIR (condensed): {fhir_summary}"""

DETECT_NOTE_BLOCK = "NOTE: {note}"

INJECT_RULES_AND_FHIR = """You are manufacturing a labeled test case for a note-auditing system. Edit the clinical NOTE so that EXACTLY ONE existing claim now CONFLICTS with a coded value in the encounter FHIR shown below (e.g. change a documented lab value, vital sign, medication dose, or status so it disagrees with the coded resource).
Rules:

Alter ONE claim only; change nothing else. Keep the note natural and plausible — a reader without the FHIR should notice nothing.
The altered claim must conflict with a SPECIFIC coded resource shown below; cite it.
Do not add or remove any other clinical content.
Return ONLY a JSON object: {{"contradicted_note": "<the FULL edited note>", "altered_claim": "<the new conflicting claim, verbatim as it appears in the edited note>", "fhir_ref": "ResourceType/id"}}.
ENCOUNTER FHIR (condensed): {fhir_summary}"""

INJECT_NOTE_BLOCK = "NOTE: {note}"

# Rides on the varying block so retries still hit the cached prefix.
INJECT_RETRY_SUFFIX = """

IMPORTANT: The previous attempt was invalid (missing fields, truncated note, or altered_claim not present verbatim in the edited note). Follow the output contract exactly: full note, one altered claim quoted verbatim from the edited note, one fhir_ref."""


def detect_contradiction(
    note: str, encounter_fhir: dict, model: str | None = None
) -> list[dict]:
    """LLM judge: [{claim, fhir_ref, conflict_description}] — [] when clean.
    Normalized defensively: only dict entries with a non-empty claim survive."""
    results = call_json(
        [
            {
                "text": DETECT_RULES_AND_FHIR.format(fhir_summary=condense_fhir(encounter_fhir)),
                "cache": True,
            },
            {"text": DETECT_NOTE_BLOCK.format(note=note)},
        ],
        max_tokens=16000,
        model=model,
    )
    if isinstance(results, dict):  # tolerate a single-object return
        results = [results]
    if not isinstance(results, list):
        raise ValueError(f"detect_contradiction: expected a JSON list, got {type(results)}")
    normalized = []
    for r in results:
        if not isinstance(r, dict) or not r.get("claim"):
            continue
        normalized.append(
            {
                "claim": str(r["claim"]),
                "fhir_ref": r.get("fhir_ref"),
                "conflict_description": str(r.get("conflict_description", "")),
            }
        )
    return normalized


def _valid_injection(result, note: str) -> bool:
    if not isinstance(result, dict):
        return False
    contradicted = result.get("contradicted_note")
    claim = result.get("altered_claim")
    ref = result.get("fhir_ref")
    if not (isinstance(contradicted, str) and isinstance(claim, str) and claim.strip()):
        return False
    if not (isinstance(ref, str) and ref.strip()):
        return False
    # The edit must return a real note, not an apology/fragment (mirrors
    # harness_inject's sanity check), and the claim must actually be in it.
    if len(contradicted) < 0.5 * len(note):
        return False
    return claim in contradicted


def inject_contradiction(
    note: str, encounter_fhir: dict, model: str | None = None
) -> dict:
    """LLM edit: alter ONE note claim to conflict with a coded FHIR value.

    Returns {contradicted_note, altered_claim, fhir_ref}. One retry with a
    stricter reminder (riding the varying block), then ValueError — the
    runner's per-item error isolation treats that as a discarded plant.
    """
    fhir_summary = condense_fhir(encounter_fhir)
    for retry in (False, True):
        note_block = INJECT_NOTE_BLOCK.format(note=note)
        if retry:
            note_block += INJECT_RETRY_SUFFIX
        result = call_json(
            [
                {"text": INJECT_RULES_AND_FHIR.format(fhir_summary=fhir_summary), "cache": True},
                {"text": note_block},
            ],
            max_tokens=16000,
            model=model,
        )
        if _valid_injection(result, note):
            return {
                "contradicted_note": result["contradicted_note"],
                "altered_claim": result["altered_claim"],
                "fhir_ref": result["fhir_ref"],
            }
    raise ValueError("inject_contradiction: no valid single-claim edit after retry")


def _tokens(text: str) -> set[str]:
    return {t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if t}


def detection_matches_planted(detection: dict, planted: dict) -> bool:
    """Does a detected contradiction correspond to the planted one?
    Primary: same fhir_ref. Fallback: >=60% of the planted claim's tokens
    appear in the detected claim (paraphrase-tolerant, pure Python)."""
    d_ref = (detection.get("fhir_ref") or "").strip()
    p_ref = (planted.get("fhir_ref") or "").strip()
    if d_ref and p_ref and d_ref == p_ref:
        return True
    planted_tokens = _tokens(planted.get("altered_claim", ""))
    if not planted_tokens:
        return False
    overlap = len(planted_tokens & _tokens(detection.get("claim", ""))) / len(planted_tokens)
    return overlap >= 0.6


def planted_was_detected(detections: list[dict], planted: dict) -> bool:
    return any(detection_matches_planted(d, planted) for d in detections)
