"""retrieve_fhir — Checkpoint 5: agentic targeted FHIR retrieval + full-chart arm.

Retrieval-as-decision (agentic pocket #1): ONE batched LLM call per encounter
decides WHICH resource categories each candidate fact needs — medications /
conditions / observations / procedures / diagnostic_reports — then pure
Python pulls ONLY those resources, condensed via extract_facts.condense_fhir
(never raw FHIR JSON in a prompt).

`full_chart_context` is the explicit contrast arm: dump ALL chart context
(longitudinal summary + every encounter resource, condensed), no decision.
Targeted-vs-full is an honest comparison — run_checkpoint5.py reports
whichever way it falls.

RetrievalDecision = {"fact_id", "resource_types": [...], "rationale"}
Retrieval         = RetrievalDecision + {"evidence": "<condensed text>"}
"""

from __future__ import annotations

import json

from .extract_facts import condense_fhir
from .llm import call_json

# Spec categories -> FHIR resource types present in this dataset.
# Immunization rides with procedures (administered interventions) and
# ImagingStudy with diagnostic_reports — nothing maps outside the spec's
# five categories.
RESOURCE_TYPE_MAP = {
    "medications": ("MedicationRequest", "Medication"),
    "conditions": ("Condition",),
    "observations": ("Observation",),
    "procedures": ("Procedure", "Immunization"),
    "diagnostic_reports": ("DiagnosticReport", "ImagingStudy"),
}
VALID_CATEGORIES = tuple(RESOURCE_TYPE_MAP)

# Conservative fallback when the router returns no verdict for a fact:
# guess minimally from the fact type rather than dumping everything.
DEFAULT_BY_FACT_TYPE = {
    "medication": ["medications"],
    "observation": ["observations"],
    "condition": ["conditions"],
    "procedure": ["procedures"],
    "order": ["diagnostic_reports", "observations"],
    "red_flag_screen": ["observations"],
    "referral": ["conditions"],
}

# Prompt split for caching (mirrors presence.py): rules + CHART INVENTORY are
# stable per encounter (identical across every note version / absent-fact
# subset of the same encounter) and form the cached prefix; the candidate
# facts vary and come last.
RULES_AND_INVENTORY = """You are a clinical retrieval router for a note-omission auditor. For EACH candidate fact below, decide which structured-chart resource categories (if any) could corroborate or conflict with the fact — i.e. would change how confident or severe an omission of this fact would be.
Rules:

Choose ONLY from: medications, conditions, observations, procedures, diagnostic_reports.
Choose the MINIMAL set that could actually bear on the fact. An empty list is correct when the chart cannot help (e.g. purely conversational counseling or lifestyle advice).
Retrieval NEVER decides whether something is an omission — it only gathers evidence. Do not reason about suppressing or dismissing facts.
Each result is an object: {{"fact_id": "<fact id>", "resource_types": ["<category>", ...], "rationale": "<one short sentence>"}}. Return one result per fact, in the same order.
Return ONLY a JSON list.
CHART INVENTORY (what is available to pull):
{inventory}"""

FACTS_BLOCK = "CANDIDATE FACTS: {facts_json}"


def chart_inventory(encounter_fhir: dict, longitudinal_summary: dict | None) -> str:
    """Pure-Python summary of what the chart HAS (counts + labels, no values) —
    enough for the router to decide, cheap enough to sit in the cached prefix."""
    related = encounter_fhir.get("related_resources", {})
    enc_counts = ", ".join(f"{t}×{len(rs)}" for t, rs in related.items() if rs)
    lines = [f"This encounter's coded resources: {enc_counts or 'none'}"]
    ls = longitudinal_summary or {}
    counts = ls.get("resource_counts") or {}
    if counts:
        lines.append(
            "Longitudinal chart resource counts: "
            + ", ".join(f"{t}×{n}" for t, n in sorted(counts.items()))
        )
    if ls.get("condition_labels"):
        lines.append("Longitudinal condition labels: " + "; ".join(ls["condition_labels"]))
    if ls.get("medication_labels"):
        lines.append("Longitudinal medication labels: " + "; ".join(ls["medication_labels"]))
    return "\n".join(lines)


def decide_resource_types(
    facts: list[dict],
    encounter_fhir: dict,
    longitudinal_summary: dict | None = None,
    model: str | None = None,
) -> list[dict]:
    """One batched LLM call: which categories does each fact need? Reconciled
    defensively (mirrors classify.py): every fact gets exactly one decision;
    invalid categories are dropped and flagged, missing verdicts fall back to
    a fact-type heuristic — never to a full-chart dump."""
    if not facts:
        return []
    facts_json = json.dumps(
        [
            {
                "id": f["id"],
                "text": f["text"],
                "type": f.get("type"),
                "source": f.get("source"),
                "fhir_ref": f.get("fhir_ref"),
            }
            for f in facts
        ],
        indent=1,
    )
    results = call_json(
        [
            {
                "text": RULES_AND_INVENTORY.format(
                    inventory=chart_inventory(encounter_fhir, longitudinal_summary)
                ),
                "cache": True,
            },
            {"text": FACTS_BLOCK.format(facts_json=facts_json)},
        ],
        max_tokens=16000,
        model=model,
    )
    if not isinstance(results, list):
        raise ValueError(f"decide_resource_types: expected a JSON list, got {type(results)}")

    by_id = {}
    for r in results:
        if isinstance(r, dict) and r.get("fact_id") is not None and r["fact_id"] not in by_id:
            by_id[r["fact_id"]] = r
    reconciled = []
    for f in facts:
        r = by_id.get(f["id"])
        if r is None:
            reconciled.append(
                {
                    "fact_id": f["id"],
                    "resource_types": list(
                        DEFAULT_BY_FACT_TYPE.get(f.get("type", "other"), [])
                    ),
                    "rationale": "No verdict returned by router; defaulted from fact type.",
                }
            )
            continue
        raw = r.get("resource_types") or []
        if not isinstance(raw, list):
            raw = [raw]
        valid, dropped, seen = [], [], set()
        for cat in raw:
            if cat in VALID_CATEGORIES and cat not in seen:
                valid.append(cat)
                seen.add(cat)
            elif cat not in VALID_CATEGORIES:
                dropped.append(cat)
        rationale = str(r.get("rationale") or "")
        if dropped:
            rationale = f"Invalid categories {dropped} dropped. " + rationale
        reconciled.append({"fact_id": f["id"], "resource_types": valid, "rationale": rationale})
    return reconciled


def pull_resources(
    resource_types: list[str],
    encounter_fhir: dict,
    longitudinal_summary: dict | None = None,
) -> str:
    """Pure Python: pull ONLY the selected categories, condensed. Longitudinal
    labels ride along only for the categories that were selected."""
    wanted: set[str] = set()
    for cat in resource_types:
        wanted.update(RESOURCE_TYPE_MAP.get(cat, ()))
    related = encounter_fhir.get("related_resources", {})
    filtered = {t: rs for t, rs in related.items() if t in wanted}
    lines = []
    if filtered:
        lines.append(condense_fhir({"related_resources": filtered}))
    else:
        lines.append("(no encounter resources in the selected categories)")
    ls = longitudinal_summary or {}
    if "conditions" in resource_types and ls.get("condition_labels"):
        lines.append("Longitudinal conditions: " + "; ".join(ls["condition_labels"]))
    if "medications" in resource_types and ls.get("medication_labels"):
        lines.append("Longitudinal medications: " + "; ".join(ls["medication_labels"]))
    return "\n".join(lines)


def retrieve_fhir_batch(
    facts: list[dict],
    encounter_fhir: dict,
    longitudinal_summary: dict | None = None,
    decisions: list[dict] | None = None,
    model: str | None = None,
) -> list[dict]:
    """Batched targeted retrieval for one note's candidate facts.

    `decisions` lets a runner reuse a per-encounter cached decide_resource_types
    result (decisions may cover MORE facts than requested — matched by id).
    """
    if not facts:
        return []
    if decisions is None:
        decisions = decide_resource_types(
            facts, encounter_fhir, longitudinal_summary, model=model
        )
    by_id = {d["fact_id"]: d for d in decisions if isinstance(d, dict)}
    out = []
    for f in facts:
        d = by_id.get(f["id"]) or {
            "fact_id": f["id"],
            "resource_types": list(DEFAULT_BY_FACT_TYPE.get(f.get("type", "other"), [])),
            "rationale": "No decision available; defaulted from fact type.",
        }
        out.append(
            {
                "fact_id": d["fact_id"],
                "resource_types": list(d.get("resource_types") or []),
                "rationale": d.get("rationale", ""),
                "evidence": pull_resources(
                    d.get("resource_types") or [], encounter_fhir, longitudinal_summary
                ),
            }
        )
    return out


def retrieve_fhir(
    candidate_fact: dict,
    encounter_fhir: dict,
    longitudinal_summary: dict | None = None,
    model: str | None = None,
) -> dict:
    """Single-fact convenience wrapper (spec signature); prefer
    retrieve_fhir_batch per note — one router call instead of N."""
    return retrieve_fhir_batch(
        [candidate_fact], encounter_fhir, longitudinal_summary, model=model
    )[0]


def full_chart_context(encounter_fhir: dict, longitudinal_summary: dict | None) -> str:
    """The full-chart arm: EVERYTHING, condensed — no retrieval decision.
    Deliberately indiscriminate; that is the point of the comparison."""
    lines = ["ALL ENCOUNTER RESOURCES (condensed):", condense_fhir(encounter_fhir)]
    ls = longitudinal_summary or {}
    counts = ls.get("resource_counts") or {}
    if counts:
        lines.append(
            "LONGITUDINAL CHART COUNTS: "
            + ", ".join(f"{t}×{n}" for t, n in sorted(counts.items()))
        )
    if ls.get("condition_labels"):
        lines.append("LONGITUDINAL CONDITIONS: " + "; ".join(ls["condition_labels"]))
    if ls.get("medication_labels"):
        lines.append("LONGITUDINAL MEDICATIONS: " + "; ".join(ls["medication_labels"]))
    return "\n".join(lines)
