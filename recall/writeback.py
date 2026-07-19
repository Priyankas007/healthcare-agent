"""writeback — Checkpoint 6 STRETCH demo: chart coverage gaps → sandbox FHIR write-back.

Concept: transcript-only facts absent from the structured chart (source ==
"transcript", no fhir_ref) are chart COVERAGE GAPS — e.g. a stated aspirin or
peanut allergy, an uncoded OTC med, family history. The agent structures each
gap as a FHIR R4 resource and, with MANDATORY clinician approval, writes it to
a sandbox FHIR server.

SAFETY RULES (non-negotiable, enforced in code, not just documented):
1. Human-in-the-loop: NO resource is written without explicit per-resource
   approval (interactive prompt). The --approve-all bypass is DEMO ONLY and
   is loudly labeled as such wherever it appears.
2. Nothing authored here is verified truth: AllergyIntolerance/Condition get
   verificationStatus=unconfirmed; every other type gets its most conservative
   legal status; EVERY resource gets an "unconfirmed" meta.tag plus a
   provenance note[] carrying the verbatim transcript quote and a
   codes-are-provisional warning.
3. Sensitive social/safety disclosures (IPV, substance use, mental health) are
   NEVER auto-structured — a type + keyword screen routes them to a
   skipped-with-reason list. The screen deliberately over-excludes.
4. Negative findings ("no known allergies", "denies X") are never authored as
   positive resources — negation screen routes them to skipped.
5. Sandbox only: write/read helpers refuse any base URL whose host is not on
   the allowlist (localhost, 127.0.0.1, hapi.fhir.org). Default is a local
   HAPI container; the public HAPI fallback requires a uniquely-named
   synthetic patient (runner's job).

Mapping (fact → FHIR R4): allergy→AllergyIntolerance, patient-reported
medication→MedicationStatement, stated diagnosis→Condition, family
history→FamilyMemberHistory, stated measurement→Observation.

Optional dependency: `pip install fhir.resources` upgrades validate_resource
from structural checks to full schema validation. Not required.

This is a demo, NOT a core eval metric — chart-coverage-gap counts never fold
into headline recall numbers.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .llm import call_json

# ---------------------------------------------------------------- selection

DEFAULT_BASE_URL = "http://localhost:8080/fhir"  # docker run -p 8080:8080 hapiproject/hapi
FALLBACK_BASE_URL = "https://hapi.fhir.org/baseR4"  # public sandbox — unique patient names only
ALLOWED_HOSTS = ("localhost", "127.0.0.1", "hapi.fhir.org")

FHIR_TYPE_BY_FACT_TYPE = {
    "allergy": "AllergyIntolerance",
    "medication": "MedicationStatement",
    "condition": "Condition",
    "family_history": "FamilyMemberHistory",
    "observation": "Observation",
}
# Keyword remap only for substantive fact types — never process types
# (order/counseling/followup), where the fact is about workflow, not the
# allergy/history itself.
KEYWORD_REMAP_TYPES = ("condition", "symptom", "observation", "other")

# Sensitive social/safety disclosures — never auto-structured. Deliberately
# broad; over-exclusion is the safe failure mode ("drinking water" gets
# skipped, and that is fine for a demo).
SENSITIVE_FACT_TYPES = ("sdoh",)
SENSITIVE_KEYWORDS = (
    # intimate partner violence / safety
    "violence", "abuse", "abusive", "assault", "unsafe at home", "afraid of",
    "hurt you", "hit you", "weapon",
    # substance use
    "alcohol", "etoh", "drink", "binge", "cannabis", "marijuana", "cocaine",
    "heroin", "opioid misuse", "methamphetamine", "substance", "tobacco",
    "smok", "vape", "vaping", "nicotine", "recreational drug", "overdose",
    # mental health
    "depress", "anxiety", "anxious", "panic", "suicid", "self-harm",
    "self harm", "psych", "mental health", "ptsd", "bipolar", "schizo",
    "hallucin", "trauma",
)

# Negative findings must not become positive chart entries. Like the
# sensitive screen, this deliberately over-excludes (a mixed fact that also
# carries a positive component gets skipped — safe failure mode).
NEGATION_MARKERS = (
    "no known", "denies", "denied", "no recent", "no history of", "never had",
    "no prior", "without any", "negative for", "none reported", "no current",
    "not taking", "takes no",
)

GAP_PRIORITY = {
    "AllergyIntolerance": 0,
    "MedicationStatement": 1,
    "Condition": 2,
    "FamilyMemberHistory": 3,
    "Observation": 4,
}


def _fact_haystack(fact: dict) -> str:
    parts = [str(fact.get("text") or ""), str(fact.get("transcript_quote") or "")]
    parts += [str(v) for v in (fact.get("slots") or {}).values()]
    return " ".join(parts).lower()


def sensitivity_reason(fact: dict) -> str | None:
    """Non-None => this fact is a sensitive social/safety disclosure."""
    if fact.get("type") in SENSITIVE_FACT_TYPES:
        return (
            f"sensitive fact type {fact.get('type')!r} — social/safety context is "
            "never auto-structured into the chart"
        )
    hay = _fact_haystack(fact)
    for kw in SENSITIVE_KEYWORDS:
        if kw in hay:
            return (
                f"sensitive keyword {kw!r} (possible IPV/substance/mental-health "
                "disclosure — never auto-structured; over-exclusion is deliberate)"
            )
    return None


def negation_reason(fact: dict) -> str | None:
    hay = (fact.get("text") or "").lower()
    for marker in NEGATION_MARKERS:
        if marker in hay:
            return (
                f"negative finding ({marker!r}) — not writable as a positive "
                "FHIR resource"
            )
    return None


def target_fhir_type(fact: dict) -> str | None:
    """FHIR R4 resource type this fact safely maps to, or None."""
    hay = (fact.get("text") or "").lower()
    if fact.get("type") in KEYWORD_REMAP_TYPES:
        if "allerg" in hay or "anaphyla" in hay:
            return "AllergyIntolerance"
        if "family history" in hay or "family hx" in hay:
            return "FamilyMemberHistory"
    return FHIR_TYPE_BY_FACT_TYPE.get(fact.get("type"))


def select_coverage_gaps(
    facts: list[dict], presence_results: list[dict] | None = None
) -> tuple[list[dict], list[dict]]:
    """Chart coverage gaps: transcript-only facts (not in FHIR) of safely-
    codeable types, sensitive/negated facts excluded.

    Returns (gaps, skipped):
      gap     = {"fact", "fhir_type", "note_status"}  (note_status from the
                provided-note presence results, informational only)
      skipped = {"fact_id", "text", "type", "reason"}  — gap candidates
                excluded by a safety screen or unmapped type.
    """
    status = {r["fact_id"]: r.get("status") for r in (presence_results or [])}
    gaps, skipped = [], []
    for f in facts:
        if f.get("source") != "transcript":
            continue  # already in FHIR (or partly) — not a chart coverage gap
        reason = sensitivity_reason(f) or negation_reason(f)
        if reason is None:
            ft = target_fhir_type(f)
            if ft is None:
                reason = (
                    f"fact type {f.get('type')!r} is not in the safe-to-code "
                    "mapping (allergy/medication/condition/family history/"
                    "observation only)"
                )
        if reason:
            skipped.append(
                {"fact_id": f["id"], "text": f["text"], "type": f.get("type"), "reason": reason}
            )
            continue
        gaps.append({"fact": f, "fhir_type": ft, "note_status": status.get(f["id"])})
    gaps.sort(key=lambda g: (GAP_PRIORITY.get(g["fhir_type"], 9), g["fact"]["id"]))
    return gaps, skipped


# ---------------------------------------------------------------- authoring

# Split for prompt caching (mirrors presence.py): rules + patient/encounter
# refs are stable across every gap of the same encounter and form the cached
# prefix; the target type + fact vary per call and come last.
AUTHOR_RULES = """You are authoring ONE FHIR R4 resource from a patient-reported fact captured in an ambient clinical transcript. The fact appears nowhere in the structured chart — you are drafting a PROVISIONAL entry for clinician review. It must never look like verified data.
Rules:
1. Return ONLY one JSON object: the FHIR R4 resource itself. No Bundle, no prose, no markdown fences.
2. `resourceType` MUST be exactly the TARGET RESOURCE TYPE given at the end.
3. Reference the patient using PATIENT REF below (field `patient` for AllergyIntolerance/FamilyMemberHistory, else `subject`). Reference the encounter using ENCOUNTER REF below (field `context` for MedicationStatement, `encounter` otherwise; FamilyMemberHistory takes no encounter reference — omit it there). If ENCOUNTER REF is "none", omit the encounter reference entirely.
4. Verification is UNCONFIRMED: set verificationStatus to unconfirmed (AllergyIntolerance: system http://terminology.hl7.org/CodeSystem/allergyintolerance-verification; Condition: system http://terminology.hl7.org/CodeSystem/condition-ver-status). Types without verificationStatus use their most conservative legal status: Observation "preliminary", FamilyMemberHistory "partial", MedicationStatement "active" only if the fact clearly states current use, else "unknown".
5. Codings are PROVISIONAL: RxNorm for medications, SNOMED CT for conditions/allergies/family history, LOINC for observations. Give your best code and append " (provisional — needs verification)" to every coding display. If unsure of the code, use only a `text` value with no coding array.
6. Add a note[] entry (Annotation) containing the verbatim transcript quote from the fact.
7. Include ONLY what the fact states — never invent dosages, dates, severities, reaction details, or onset times.
PATIENT REF: {patient_ref}
ENCOUNTER REF: {encounter_ref}"""

FACT_BLOCK = """TARGET RESOURCE TYPE: {fhir_type}
FACT: {fact_json}"""

# Per-type reference field names (defaults: subject / encounter).
SUBJECT_FIELD = {"AllergyIntolerance": "patient", "FamilyMemberHistory": "patient"}
ENCOUNTER_FIELD = {"MedicationStatement": "context", "FamilyMemberHistory": None}

VERIFICATION_SYSTEMS = {
    "AllergyIntolerance": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
    "Condition": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
}
# resource type -> (legal status codes, conservative fallback)
LEGAL_STATUS = {
    "MedicationStatement": (
        ("active", "completed", "intended", "stopped", "on-hold", "unknown", "not-taken"),
        "unknown",
    ),
    "FamilyMemberHistory": (("partial", "completed", "health-unknown"), "partial"),
}
UNCONFIRMED_TAG = {
    "system": "urn:recall:verification",
    "code": "unconfirmed",
    "display": "Unconfirmed — patient-reported ambient capture, pending clinician verification",
}


def _apply_safety_overlays(
    resource: dict, fact: dict, fhir_type: str, patient_ref: str, encounter_ref: str | None
) -> dict:
    """Force the safety invariants regardless of what the model emitted
    (defense in depth — the prompt asks for all of this too)."""
    resource["resourceType"] = fhir_type

    # Subject / encounter references.
    subject_field = SUBJECT_FIELD.get(fhir_type, "subject")
    resource[subject_field] = {"reference": patient_ref}
    for wrong in ("subject", "patient"):
        if wrong != subject_field:
            resource.pop(wrong, None)
    encounter_field = ENCOUNTER_FIELD.get(fhir_type, "encounter")
    for wrong in ("encounter", "context"):
        if wrong != encounter_field:
            resource.pop(wrong, None)
    if encounter_field:
        if encounter_ref:
            resource[encounter_field] = {"reference": encounter_ref}
        else:
            resource.pop(encounter_field, None)

    # Verification status / most conservative legal status.
    if fhir_type in VERIFICATION_SYSTEMS:
        resource.pop("status", None)  # no such element on these types in R4
        resource["verificationStatus"] = {
            "coding": [
                {
                    "system": VERIFICATION_SYSTEMS[fhir_type],
                    "code": "unconfirmed",
                    "display": "Unconfirmed",
                }
            ]
        }
    elif fhir_type == "Observation":
        resource["status"] = "preliminary"  # never final for ambient-captured data
    elif fhir_type in LEGAL_STATUS:
        legal, fallback = LEGAL_STATUS[fhir_type]
        if resource.get("status") not in legal:
            resource["status"] = fallback

    # Unconfirmed tag + provenance note with the transcript quote.
    meta = resource.setdefault("meta", {})
    tags = [t for t in meta.get("tag", []) if t.get("system") != UNCONFIRMED_TAG["system"]]
    tags.append(dict(UNCONFIRMED_TAG))
    meta["tag"] = tags
    quote = fact.get("transcript_quote") or fact.get("text", "")
    provenance = (
        "RECALL write-back demo: patient-reported fact captured from the ambient "
        "transcript; absent from the structured chart; all codings provisional and "
        f'pending clinician verification. Transcript: "{quote}"'
    )
    notes = resource.get("note")
    if not isinstance(notes, list):
        notes = []
    notes.append({"text": provenance})
    resource["note"] = notes

    resource.pop("id", None)  # server assigns the id
    return resource


def author_resource(
    fact: dict,
    patient_ref: str,
    encounter_ref: str | None,
    fhir_type: str,
    model: str | None = None,
) -> dict:
    """LLM-author one FHIR R4 resource for a coverage-gap fact, then force the
    safety overlays (unconfirmed status, refs, provenance note)."""
    fact_json = json.dumps(
        {
            "id": fact["id"],
            "text": fact["text"],
            "type": fact.get("type"),
            "slots": fact.get("slots", {}),
            "transcript_quote": fact.get("transcript_quote"),
        },
        indent=1,
    )
    result = call_json(
        [
            {
                "text": AUTHOR_RULES.format(
                    patient_ref=patient_ref, encounter_ref=encounter_ref or "none"
                ),
                "cache": True,
            },
            {"text": FACT_BLOCK.format(fhir_type=fhir_type, fact_json=fact_json)},
        ],
        max_tokens=8000,
        model=model,
    )
    # Reconcile defensively: unwrap a single-element list; require an object.
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
        result = result[0]
    if not isinstance(result, dict):
        raise ValueError(f"author_resource: expected a JSON object, got {type(result)}")
    if result.get("resourceType") == "Bundle":  # never accept a bundle
        entries = result.get("entry") or []
        inner = entries[0].get("resource") if entries and isinstance(entries[0], dict) else None
        if not isinstance(inner, dict):
            raise ValueError("author_resource: model returned an unusable Bundle")
        result = inner
    return _apply_safety_overlays(result, fact, fhir_type, patient_ref, encounter_ref)


# ---------------------------------------------------------------- validation

# Structural minimums per mapped type; inner tuple = alternatives (>=1 must
# be present). Used when fhir.resources is not installed.
REQUIRED_FIELDS = {
    "AllergyIntolerance": [("patient",)],
    "MedicationStatement": [("status",), ("subject",), ("medicationCodeableConcept", "medicationReference")],
    "Condition": [("subject",)],
    "FamilyMemberHistory": [("status",), ("patient",), ("relationship",)],
    "Observation": [("status",), ("code",)],
}


def validate_resource(resource: dict, expected_type: str) -> tuple[bool, list[str]]:
    """Validate an authored resource. Uses the optional fhir.resources library
    for full schema validation when installed; otherwise degrades gracefully
    to structural checks (resourceType + required fields for the mapped type).
    Returns (ok, issues)."""
    issues: list[str] = []
    if not isinstance(resource, dict):
        return False, ["resource is not a JSON object"]
    rt = resource.get("resourceType")
    if rt != expected_type:
        issues.append(f"resourceType is {rt!r}, expected {expected_type!r}")
    for alternatives in REQUIRED_FIELDS.get(expected_type, []):
        if not any(resource.get(field) for field in alternatives):
            issues.append(f"missing required field: {' or '.join(alternatives)}")
    try:  # optional strict pass — `pip install fhir.resources`
        import fhir.resources as _fr  # type: ignore

        construct = getattr(_fr, "construct_fhir_element", None)
        if construct is not None:
            construct(expected_type, resource)
        else:  # newer releases
            _fr.get_fhir_model_class(expected_type).parse_obj(resource)  # type: ignore[attr-defined]
    except ImportError:
        pass  # structural checks above are the (documented) fallback
    except Exception as exc:
        issues.append(f"fhir.resources schema validation: {exc}")
    return (not issues), issues


# ---------------------------------------------------------------- approval

def request_approval(
    gap: dict, resource: dict, approve_all: bool = False, input_fn=input
) -> bool:
    """MANDATORY human-in-the-loop gate before any write.

    approve_all=True bypasses the prompt and is DEMO ONLY — never acceptable
    in any real clinical context. `input_fn` is injectable for tests.
    """
    fact = gap["fact"]
    print(f"\n--- APPROVAL REQUIRED: {gap['fhir_type']} for fact {fact['id']} ---")
    print(f"  Fact: {fact['text']}")
    if fact.get("transcript_quote"):
        print(f'  Transcript: "{fact["transcript_quote"]}"')
    print(f"  Resource preview: {json.dumps(resource)[:400]}")
    if approve_all:
        print("  [--approve-all] AUTO-APPROVED — DEMO ONLY, never use with real data.")
        return True
    answer = input_fn("  Write this UNCONFIRMED resource to the sandbox? [y/N] ")
    return answer.strip().lower() in ("y", "yes")


# ---------------------------------------------------------------- sandbox HTTP

def check_base_url(base_url: str) -> None:
    """Refuse any FHIR base URL whose host is not on the sandbox allowlist."""
    host = urllib.parse.urlsplit(base_url).hostname
    if host not in ALLOWED_HOSTS:
        raise ValueError(
            f"Refusing FHIR base URL {base_url!r}: host {host!r} is not on the "
            f"sandbox allowlist {ALLOWED_HOSTS}. This demo only ever writes to a "
            "local HAPI container or the public HAPI test server."
        )


def _http(method: str, url: str, body: dict | None = None, timeout: int = 20):
    """Minimal FHIR JSON request via urllib (no new deps). Returns
    (parsed_json_or_None, headers_dict). Raises on transport/HTTP errors."""
    headers = {"Accept": "application/fhir+json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/fhir+json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode()
        resp_headers = dict(resp.headers)
    parsed = json.loads(raw) if raw.strip() else None
    return parsed, resp_headers


def server_alive(base_url: str) -> bool:
    check_base_url(base_url)
    try:
        _http("GET", f"{base_url}/metadata?_summary=true")
        return True
    except Exception:
        return False


def write_resource(base_url: str, resource: dict) -> dict:
    """POST one approved resource to the sandbox, then confirm via GET.

    Only ever called AFTER request_approval. Returns
    {"created_id", "confirmed", "resource"}.
    """
    check_base_url(base_url)
    rt = resource["resourceType"]
    created, headers = _http("POST", f"{base_url}/{rt}", body=resource)
    rid = (created or {}).get("id")
    if not rid:  # some servers return an empty body + Location header
        location = headers.get("Location") or headers.get("Content-Location") or ""
        parts = [p for p in location.split("/") if p]
        if rt in parts and parts.index(rt) + 1 < len(parts):
            rid = parts[parts.index(rt) + 1]
    confirmed_resource = None
    if rid:
        try:
            confirmed_resource, _ = _http("GET", f"{base_url}/{rt}/{rid}")
        except Exception:
            confirmed_resource = None
    return {
        "created_id": rid,
        "confirmed": confirmed_resource is not None,
        "resource": confirmed_resource or created,
    }


def get_resource(base_url: str, resource_type: str, resource_id: str) -> dict | None:
    check_base_url(base_url)
    parsed, _ = _http("GET", f"{base_url}/{resource_type}/{resource_id}")
    return parsed


def count_patient_resources(base_url: str, patient_ref: str) -> dict:
    """Count per-type resources for a patient — the before/after snapshot.
    Returns {resource_type: count | None (query failed)}."""
    check_base_url(base_url)
    counts: dict[str, int | None] = {}
    for rt in sorted(set(GAP_PRIORITY)):
        try:
            bundle, _ = _http(
                "GET",
                f"{base_url}/{rt}?patient={urllib.parse.quote(patient_ref)}&_summary=count",
            )
            counts[rt] = (bundle or {}).get("total")
        except Exception:
            counts[rt] = None
    return counts
