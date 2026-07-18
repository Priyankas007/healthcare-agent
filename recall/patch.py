"""patch — minimal-edit proposer for surfaced omissions (Checkpoint 4).

Locked rules: augment, don't regenerate — propose the MINIMAL insertion that
documents a missing fact, grounded entirely in that fact's evidence
(transcript_quote / fhir_ref); no new clinical information. Verification is a
SEPARATE call (recall/verify_patch.py) — this module never judges its own
output. On verifier rejection the loop feeds reasons back via `feedback`,
appended to the VARYING block so the cached rules+NOTE prefix still hits.

Patch = {
  "flag_id": "f4",
  "section": "Subjective" | "Objective" | "Assessment and Plan",
  "insert_text": "...",
  "mode": "append|merge",
  "added_claims": ["..."]
}

Also home to the deterministic, pure-Python side: evidence_for (format the
fact's grounding evidence), section_span / normalize_section (the dataset's
notes all use exactly **Subjective:** / **Objective:** /
**Assessment and Plan:** headers), and apply_patch (insert the text into the
named section without touching anything else).
"""

from __future__ import annotations

import json
import re

from .llm import call_json

SECTIONS = ("Subjective", "Objective", "Assessment and Plan")

# Split for prompt caching: rules + NOTE are stable across every flag patched
# on the same note AND across revision iterations (cached prefix); the fact,
# evidence, and any revision guidance vary and come last.
RULES_AND_NOTE = """You are a clinical documentation assistant. A clinically important fact is MISSING from this note. Propose the MINIMAL edit to add it.
Output the SOAP section to edit, the exact text to insert, and whether to append a new line or merge into an existing sentence.
Add ONLY the missing fact — introduce no other clinical information, and do not restate content already in the note.
Ground every word in the provided EVIDENCE; do not infer beyond it.
Return ONLY {{"section","insert_text","mode","added_claims":[...]}}.
NOTE: {note}"""

FACT_AND_EVIDENCE = """MISSING FACT: {fact_text}
EVIDENCE (transcript span / FHIR ref): {evidence}"""

REVISION_SUFFIX = """

REVISION GUIDANCE: a previous version of this patch was rejected by an independent verifier for the reasons below. Fix these problems while keeping the edit minimal and grounded in the EVIDENCE.
{reasons}"""


def patch(
    fact: dict,
    evidence: str,
    note: str,
    feedback: list[str] | None = None,
    model: str | None = None,
) -> dict:
    """Propose the minimal insertion documenting `fact` — one call.

    `feedback` (verifier rejection reasons) rides on the varying block for
    revision rounds. Output is defensively normalized to the Patch contract.
    """
    varying = FACT_AND_EVIDENCE.format(fact_text=fact["text"], evidence=evidence)
    if feedback:
        varying += REVISION_SUFFIX.format(
            reasons="\n".join(f"- {r}" for r in feedback)
        )
    result = call_json(
        [
            {"text": RULES_AND_NOTE.format(note=note), "cache": True},
            {"text": varying},
        ],
        max_tokens=8000,
        model=model,
    )
    if isinstance(result, list):  # tolerate a single-element list wrapper
        result = next((r for r in result if isinstance(r, dict)), None)
    if not isinstance(result, dict):
        raise ValueError(f"patch: expected a JSON object, got {type(result)}")

    insert_text = str(result.get("insert_text") or "").strip()
    if not insert_text:
        raise ValueError("patch: model returned an empty insert_text")
    mode = str(result.get("mode") or "").strip().lower()
    if mode not in ("append", "merge"):
        mode = "append"
    claims = result.get("added_claims")
    if not isinstance(claims, list):
        claims = [claims] if claims else []
    claims = [str(c).strip() for c in claims if c is not None and str(c).strip()]
    if not claims:
        claims = [insert_text]
    return {
        "flag_id": fact["id"],
        "section": normalize_section(result.get("section")),
        "insert_text": insert_text,
        "mode": mode,
        "added_claims": claims,
    }


# ------------------------------------------------------------- pure Python


def evidence_for(fact: dict, encounter_fhir: dict | None = None) -> str:
    """Format the fact's grounding evidence (transcript span / FHIR ref).

    When `encounter_fhir` is given, the referenced resource is inlined in
    compact JSON so grounding can be judged against actual content, not just
    a reference string.
    """
    parts = []
    if fact.get("transcript_quote"):
        parts.append(f'transcript span: "{fact["transcript_quote"]}"')
    ref = fact.get("fhir_ref")
    if ref:
        line = f"FHIR ref: {ref}"
        resource = _resolve_fhir(ref, encounter_fhir) if encounter_fhir else None
        if resource is not None:
            compact = json.dumps(resource, separators=(",", ":"))
            if len(compact) > 1200:
                compact = compact[:1200] + "…(truncated)"
            line += f"\nFHIR resource: {compact}"
        parts.append(line)
    return "\n".join(parts) or "no recorded evidence for this fact"


def _resolve_fhir(ref: str, encounter_fhir: dict) -> dict | None:
    rtype, _, rid = str(ref).partition("/")
    for resource in (encounter_fhir.get("related_resources") or {}).get(rtype, []):
        if isinstance(resource, dict) and resource.get("id") == rid:
            return resource
    return None


def normalize_section(name) -> str:
    """Map model-provided section names onto the note's three headers."""
    s = re.sub(r"[^a-z&/ ]", "", str(name or "").lower()).strip()
    if "subject" in s or s == "s":
        return "Subjective"
    if "object" in s or s == "o":
        return "Objective"
    if "assess" in s or "plan" in s or s in ("a", "p", "ap", "a/p", "a&p"):
        return "Assessment and Plan"
    return "Assessment and Plan"  # conservative default bucket


_HEADER_RE = re.compile(r"^\*\*(Subjective|Objective|Assessment and Plan)\s*:?\*\*:?", re.M)


def section_span(note: str, section: str) -> tuple[int, int] | None:
    """(start, end) span of the section's CONTENT (header excluded), or None."""
    matches = list(_HEADER_RE.finditer(note))
    for i, m in enumerate(matches):
        if m.group(1) == section:
            end = matches[i + 1].start() if i + 1 < len(matches) else len(note)
            return m.end(), end
    return None


def apply_patch(note: str, patch: dict) -> str:
    """Deterministically insert patch["insert_text"] into the named section.

    append → the text goes on its own new line at the end of the section;
    merge  → the text is joined onto the section's final text with a space.
    Inter-section whitespace is preserved exactly; if the header is somehow
    missing, the text is appended as a new section at the end of the note.
    """
    section, text = patch["section"], patch["insert_text"].strip()
    span = section_span(note, section)
    if span is None:
        return note.rstrip() + f"\n\n**{section}:** {text}\n"
    start, end = span
    content = note[start:end]
    body = content.rstrip()
    trailing = content[len(body):] or "\n"
    sep = " " if patch.get("mode") == "merge" or not body else "\n"
    return note[:start] + body + sep + text + trailing + note[end:]
