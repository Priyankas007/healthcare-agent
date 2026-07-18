"""extract_facts — Checkpoint 1 core: transcript + encounter FHIR -> CandidateFacts.

CandidateFact = {
  "id": "f1",
  "text": "Start lisinopril 10 mg daily",
  "type": "medication|symptom|red_flag_screen|relieving_factor|observation|condition|procedure|order|referral|followup|counseling|sdoh|other",
  "slots": {"drug": "lisinopril", "dose": "10 mg", "route": "oral", "freq": "daily"},
  "source": "transcript|fhir|both",
  "transcript_quote": "start you on a low-dose lisinopril",
  "fhir_ref": "MedicationRequest/abc"
}
"""

from __future__ import annotations

from .llm import call_json

PROMPT = """You are a clinical fact extractor. Given a visit TRANSCRIPT and the encounter's structured FHIR resources, list the discrete, clinically important facts that a COMPLETE note for THIS visit should contain.
Rules:

One clinical assertion per fact. Do NOT split a medication into separate drug/dose/frequency facts — keep them in one fact with slots.
Include: patient-reported symptoms/HPI, pertinent positives and negatives (e.g. red-flag/ROS screens), relieving/aggravating factors, medications started/changed/stopped, orders/tests, referrals, follow-up instructions, counseling given, and clinically relevant social determinants (SDOH).
Draw from BOTH the transcript (what was said/decided) and the encounter FHIR (coded meds, conditions, procedures, abnormal observations, diagnostic reports).
Do NOT invent facts unsupported by the transcript or FHIR.
For each fact set source (transcript|fhir|both) and provenance (transcript_quote verbatim if applicable, fhir_ref = ResourceType/id if applicable).
Each fact is an object: {{"id": "f<N>", "text": "<one clinical assertion>", "type": "medication|symptom|red_flag_screen|relieving_factor|observation|condition|procedure|order|referral|followup|counseling|sdoh|other", "slots": {{...typed slots, e.g. drug/dose/route/freq for medications...}}, "source": "transcript|fhir|both", "transcript_quote": "<verbatim>" or null, "fhir_ref": "ResourceType/id" or null}}.
Return ONLY a JSON list of CandidateFact objects.
TRANSCRIPT: {transcript}
ENCOUNTER_FHIR (related_resources, condensed to type/code/display/value): {fhir_summary}"""


def _value_str(resource: dict) -> str | None:
    """Human-readable value for an Observation-like resource."""
    if "valueQuantity" in resource:
        q = resource["valueQuantity"]
        return f"{q.get('value')} {q.get('unit', '')}".strip()
    if "valueCodeableConcept" in resource:
        return _code_display(resource["valueCodeableConcept"])
    if "valueString" in resource:
        return str(resource["valueString"])
    if "component" in resource:
        parts = []
        for comp in resource["component"]:
            label = _code_display(comp.get("code", {})) or "component"
            sub = _value_str(comp)
            if sub:
                parts.append(f"{label}={sub}")
        return "; ".join(parts) if parts else None
    return None


def _code_display(codeable: dict) -> str | None:
    if not isinstance(codeable, dict):
        return None
    if codeable.get("text"):
        return codeable["text"]
    for coding in codeable.get("coding", []):
        if coding.get("display"):
            return coding["display"]
    return None


def condense_fhir(encounter_fhir: dict) -> str:
    """Condense related_resources to readable one-liners: type/code/display/value.

    Never dump raw FHIR JSON into the prompt.
    """
    lines: list[str] = []
    related = encounter_fhir.get("related_resources", {})
    for rtype, resources in related.items():
        for r in resources:
            rid = r.get("id", "?")
            ref = f"{rtype}/{rid}"
            display = (
                _code_display(r.get("code", {}))
                or _code_display(r.get("medicationCodeableConcept", {}))
                or _code_display(r.get("vaccineCode", {}))
                or "?"
            )
            parts = [f"{ref}: {display}"]
            value = _value_str(r)
            if value:
                parts.append(f"value={value}")
            if r.get("interpretation"):
                interp = _code_display(r["interpretation"][0]) if isinstance(r["interpretation"], list) else _code_display(r["interpretation"])
                if interp:
                    parts.append(f"interpretation={interp}")
            if rtype == "MedicationRequest":
                dosages = r.get("dosageInstruction", [])
                if dosages:
                    di = dosages[0]
                    if di.get("text"):
                        parts.append(f"dosage={di['text']}")
                    # Dose quantity + frequency usually live in doseAndRate /
                    # timing.repeat, not dosageInstruction.text, in this dataset.
                    dar = di.get("doseAndRate", [])
                    if dar and "doseQuantity" in dar[0]:
                        q = dar[0]["doseQuantity"]
                        parts.append(f"dose={q.get('value')} {q.get('unit', '')}".strip())
                    repeat = (di.get("timing") or {}).get("repeat", {})
                    if repeat.get("frequency"):
                        parts.append(
                            f"freq={repeat['frequency']}x per {repeat.get('period', 1)}"
                            f"{repeat.get('periodUnit', '')}"
                        )
                if "medicationReference" in r and "medicationCodeableConcept" not in r:
                    parts.append("(medication by reference — label unresolved)")
            status = r.get("status") or r.get("clinicalStatus", {}).get("coding", [{}])[0].get("code") if isinstance(r.get("clinicalStatus"), dict) else r.get("status")
            if status:
                parts.append(f"status={status}")
            lines.append("  " + " | ".join(parts))
    return "\n".join(lines) if lines else "(no structured resources recorded for this encounter)"


def extract_facts(transcript: str, encounter_fhir: dict) -> list[dict]:
    """Extract CandidateFacts from the transcript + condensed encounter FHIR."""
    fhir_summary = condense_fhir(encounter_fhir)
    facts = call_json(
        PROMPT.format(transcript=transcript, fhir_summary=fhir_summary),
        max_tokens=16000,
    )
    if not isinstance(facts, list):
        raise ValueError(f"extract_facts: expected a JSON list, got {type(facts)}")
    # Normalize: dicts only, required keys guaranteed, ids unique.
    facts = [f for f in facts if isinstance(f, dict) and f.get("text")]
    seen_ids: set[str] = set()
    for i, fact in enumerate(facts):
        fid = str(fact.get("id") or f"f{i + 1}")
        while fid in seen_ids:  # dedupe model-supplied ids
            fid += "x"
        seen_ids.add(fid)
        fact["id"] = fid
        fact.setdefault("slots", {})
        fact.setdefault("source", "transcript")
        fact.setdefault("transcript_quote", None)
        fact.setdefault("fhir_ref", None)
        fact.setdefault("type", "other")
    return facts
