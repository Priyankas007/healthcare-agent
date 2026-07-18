"""evidence_pattern — Checkpoint 5: evidence-pattern routing for absent facts.

Pure-Python classification plus ONE optional batched LLM corroboration judge:

  transcript only                 -> omission, baseline confidence
  transcript + corroborating FHIR -> omission, HIGH confidence (severity raised)
  FHIR only, clinically relevant  -> chart-critical coverage candidate (SEPARATE list)
  transcript conflicts with FHIR  -> reconciliation_needed (never auto-patched)

Note-vs-FHIR conflicts are a different failure class entirely — see
recall/contradiction.py; they are never folded in here.

INVARIANT (FHIR never suppresses): every input fact lands in exactly one
bucket and none is dropped. Corroboration can only RAISE confidence/severity;
it can never lower a severity or remove a flag.
"""

from __future__ import annotations

import json

from .llm import call_json

VALID_RELATIONS = ("corroborates", "conflicts", "unrelated")

# Deliberate: corroboration promotes minor -> major only. It never mints
# safety_critical — that tier stays a clinical-semantics call (classify.py),
# not a mechanical bonus for having a matching coded resource.
SEVERITY_BOOST = {"minor": "major"}

# Prompt split for caching (mirrors presence.py): rules (+ the shared chart
# context in the full-chart arm, stable per encounter) form the cached
# prefix; the candidate facts (with per-fact targeted evidence) vary and
# come last.
CORROBORATE_RULES = """You are a clinical evidence judge. Each candidate fact below is MISSING from a clinical note. For EACH fact, judge how the structured FHIR evidence relates to the fact itself.
Rules:

relation = "corroborates" when the FHIR evidence supports the fact (same medication/result/condition, consistent values); "conflicts" when the FHIR evidence contradicts what the fact asserts (different dose, different value, opposite status); "unrelated" when the evidence neither supports nor contradicts it.
Judge ONLY the fact-vs-FHIR relation. You are NOT judging whether the note should contain the fact, and no relation can ever suppress a fact.
Base the judgment only on the evidence provided — no outside knowledge.
Each result is an object: {{"fact_id": "<fact id>", "relation": "corroborates|conflicts|unrelated", "rationale": "<one short sentence>"}}. Return one result per fact, in the same order.
Return ONLY a JSON list.{chart_block}"""

CHART_BLOCK = "\nSHARED CHART CONTEXT (applies to every fact below):\n{chart}"

ITEMS_BLOCK = "CANDIDATE FACTS (with per-fact FHIR evidence where retrieved): {items_json}"


def corroborate(
    items: list[dict],
    chart_context: str | None = None,
    model: str | None = None,
) -> list[dict]:
    """One batched corroboration call per note version.

    items: [{"fact_id", "text", "transcript_quote", "evidence"?}] — targeted
    arm passes per-item `evidence`; full-chart arm passes `chart_context`
    (stable per encounter -> cached prefix) and no per-item evidence.

    Reconciled defensively: every item gets exactly one result; missing or
    invalid relations become "unrelated" (conservative — no boost, no
    conflict route, and never a suppression).
    """
    if not items:
        return []
    items_json = json.dumps(
        [
            {
                "fact_id": it["fact_id"],
                "text": it["text"],
                "transcript_quote": it.get("transcript_quote"),
                "evidence": it.get("evidence"),
            }
            for it in items
        ],
        indent=1,
    )
    chart_block = CHART_BLOCK.format(chart=chart_context) if chart_context else ""
    results = call_json(
        [
            {"text": CORROBORATE_RULES.format(chart_block=chart_block), "cache": True},
            {"text": ITEMS_BLOCK.format(items_json=items_json)},
        ],
        max_tokens=16000,
        model=model,
    )
    if not isinstance(results, list):
        raise ValueError(f"corroborate: expected a JSON list, got {type(results)}")

    by_id = {}
    for r in results:
        if isinstance(r, dict) and r.get("fact_id") is not None and r["fact_id"] not in by_id:
            by_id[r["fact_id"]] = r
    reconciled = []
    for it in items:
        r = by_id.get(
            it["fact_id"],
            {
                "fact_id": it["fact_id"],
                "relation": "unrelated",
                "rationale": "No verdict returned by judge; defaulted to unrelated (no boost).",
            },
        )
        r.setdefault("rationale", "")
        if r.get("relation") not in VALID_RELATIONS:
            r["rationale"] = (
                f"Invalid relation {r.get('relation')!r} normalized to unrelated. "
                + str(r["rationale"])
            )
            r["relation"] = "unrelated"
        reconciled.append(r)
    return reconciled


def classify_evidence(
    facts: list[dict],
    corroborations: list[dict] | None = None,
    retrievals: list[dict] | None = None,
) -> dict:
    """Pure Python: route each absent fact to exactly one evidence-pattern
    bucket. Returns {"omissions", "coverage_candidates", "reconciliation_needed"}.

    - omissions: transcript_only (baseline) or transcript_fhir (high
      confidence, severity_boost=True)
    - coverage_candidates: fhir_only — SEPARATE class, never folded into
      omission recall
    - reconciliation_needed: transcript-vs-FHIR conflict — still flagged
      (never suppressed) but auto_patch_ok=False

    Invariant enforced: every input fact appears in exactly one bucket.
    """
    corr_by_id = {c["fact_id"]: c for c in (corroborations or []) if isinstance(c, dict)}
    retr_by_id = {r["fact_id"]: r for r in (retrievals or []) if isinstance(r, dict)}
    omissions, coverage, reconciliation = [], [], []
    for f in facts:
        c = corr_by_id.get(f["id"], {})
        relation = c.get("relation")
        if relation not in VALID_RELATIONS:
            relation = "unrelated"
        has_transcript = bool(f.get("transcript_quote")) or f.get("source") in (
            "transcript",
            "both",
        )
        entry = {
            "fact_id": f["id"],
            "confidence": "baseline",
            "severity_boost": False,
            "auto_patch_ok": True,
            "corroboration_rationale": c.get("rationale", ""),
            "fhir_evidence": (retr_by_id.get(f["id"]) or {}).get("evidence"),
        }
        if not has_transcript:
            entry["evidence_pattern"] = "fhir_only"
            coverage.append(entry)
        elif relation == "conflicts":
            entry["evidence_pattern"] = "reconciliation_needed"
            entry["auto_patch_ok"] = False  # do NOT auto-patch a conflicted fact
            reconciliation.append(entry)
        elif relation == "corroborates":
            entry["evidence_pattern"] = "transcript_fhir"
            entry["confidence"] = "high"
            entry["severity_boost"] = True
            omissions.append(entry)
        else:
            entry["evidence_pattern"] = "transcript_only"
            omissions.append(entry)

    result = {
        "omissions": omissions,
        "coverage_candidates": coverage,
        "reconciliation_needed": reconciliation,
    }
    # FHIR never suppresses: every fact routed, none dropped, none duplicated.
    routed = [e["fact_id"] for e in flatten_evidence(result)]
    assert sorted(routed) == sorted(f["id"] for f in facts), (
        "classify_evidence invariant violated: input facts and routed facts differ "
        f"({sorted(f['id'] for f in facts)} vs {sorted(routed)})"
    )
    return result


def flatten_evidence(result: dict) -> list[dict]:
    """All pattern entries across the three buckets (order: omissions,
    coverage, reconciliation)."""
    return (
        list(result.get("omissions", []))
        + list(result.get("coverage_candidates", []))
        + list(result.get("reconciliation_needed", []))
    )


def boost_severity(severity: str) -> str:
    """Corroborated omission -> one-tier raise (minor -> major). Never lowers,
    never mints safety_critical, and unknown severities pass through."""
    return SEVERITY_BOOST.get(severity, severity)


def pattern_distribution(evidence_results: list[dict]) -> dict[str, int]:
    """Aggregate evidence-pattern counts across classify_evidence outputs."""
    dist: dict[str, int] = {}
    for res in evidence_results:
        for e in flatten_evidence(res):
            dist[e["evidence_pattern"]] = dist.get(e["evidence_pattern"], 0) + 1
    return dist
