"""Checkpoint 5 — FHIR ablation (the research spine): rungs B0–R6.

The honest question: when does longitudinal FHIR context help or harm
omission detection? Targeted vs full-chart is an explicit comparison — NOT
rigged; checkpoint_5.md states whichever way it falls.

Fixed eval set: injections/records.jsonl + checkpoint2_cache (the answer key
is never regenerated here). Every rung's incremental cost is cached per item
under checkpoint5_cache/<rung>/ so the run is resumable; R2 is free (pure
reads of checkpoint-2 caches).

Rungs (nominal cumulative stack; ablation config =
{checklist_in_gen, presence_guard, fhir: off|targeted|full, patch,
contradiction, normalizer}):
  B0  generation only                        (generated_notes/ + a presence pass)
  R1  checklist in gen prompt                (prompt-time reduction)
  R2  presence guard                         (== checkpoint-2 cached results, free)
  R3  + targeted FHIR                        (evidence patterns, severity boosts)
  R4  + patch/verifier                       (requires recall/patch.py — CP4, parallel session)
  R5  + contradiction class + full-chart arm (the honest FHIR finding)
  R6  + normalizer/tuning                    (OPTIONAL stub — underspecified, marked TODO)

B0/R1 are generation-side rungs (metric: absent facts per GENERATED note);
R2+ are detection-side rungs over the FIXED injected/clean provided-note set
— the two halves share the ablation table with n/a cells, per the scoping doc.

Run:  .venv/bin/python run_checkpoint5.py [--rungs B0,R2,R3] [--workers N]
                                          [--contradictions N] [--model MODEL]
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from recall.contradiction import (
    detect_contradiction,
    inject_contradiction,
    planted_was_detected,
)
from recall.evidence_pattern import (
    boost_severity,
    classify_evidence,
    corroborate,
    flatten_evidence,
)
from recall.render import render
from recall.retrieve_fhir import (
    decide_resource_types,
    full_chart_context,
    retrieve_fhir_batch,
)

REPO = Path(__file__).resolve().parent
DATA_PATH = Path(
    os.environ.get(
        "DATA_PATH", REPO / "synthetic-ambient-fhir-25" / "synthetic-ambient-fhir-25.jsonl"
    )
)
C2 = REPO / "checkpoint2_cache"
FACTS_DIR, EVAL_DIR, PRESENCE_DIR = C2 / "facts", C2 / "eval", C2 / "presence_provided"
C3_CLASSIFY = REPO / "checkpoint3_cache" / "classify"
INJ_DIR = REPO / "injections"
RECORDS_PATH = INJ_DIR / "records.jsonl"
GEN_NOTES_DIR = REPO / "generated_notes"
# Overridable for offline smoke tests so mocked runs never pollute the real cache.
C5 = Path(os.environ.get("CHECKPOINT5_CACHE", REPO / "checkpoint5_cache"))
CHECKPOINT_MD = Path(os.environ.get("CHECKPOINT5_MD", REPO / "checkpoint_5.md"))

WORKERS = int(next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--workers"), 5))
MODEL = next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--model"), None)
N_CONTRADICTIONS = int(
    next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--contradictions"), 18)
)


# ---------------------------------------------------------------- config

@dataclass(frozen=True)
class AblationConfig:
    """One rung of the ablation stack (spec: §10 ablation config)."""

    name: str
    adds: str
    checklist_in_gen: bool = False
    presence_guard: bool = False
    fhir: str = "off"  # off | targeted | full
    patch: bool = False
    contradiction: bool = False
    normalizer: bool = False
    optional: bool = False


RUNGS = [
    AblationConfig("B0", adds="generation only"),
    AblationConfig("R1", adds="checklist in gen prompt", checklist_in_gen=True),
    AblationConfig(
        "R2", adds="presence guard (free — checkpoint-2 cache)",
        checklist_in_gen=True, presence_guard=True,
    ),
    AblationConfig(
        "R3", adds="targeted FHIR (evidence patterns)",
        checklist_in_gen=True, presence_guard=True, fhir="targeted",
    ),
    AblationConfig(
        "R4", adds="patch + verifier (CP4 modules)",
        checklist_in_gen=True, presence_guard=True, fhir="targeted", patch=True,
    ),
    AblationConfig(
        "R5", adds="contradiction class + full-chart arm",
        checklist_in_gen=True, presence_guard=True, fhir="targeted",
        patch=True, contradiction=True,
    ),
    AblationConfig(
        "R6", adds="normalizer / tuning (OPTIONAL stub)",
        checklist_in_gen=True, presence_guard=True, fhir="targeted",
        patch=True, contradiction=True, normalizer=True, optional=True,
    ),
]


# ---------------------------------------------------------------- shared plumbing

def load_records() -> list[dict]:
    with open(DATA_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def _atomic_write(path: Path, text: str) -> None:
    """Concurrent-safe cache write: same-encounter versions share cache files
    (e.g. the per-encounter retrieval decision), so a plain write_text lets a
    parallel reader observe a partial file. Write-to-temp + os.replace is
    atomic on POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}-{threading.get_ident()}")
    tmp.write_text(text)
    os.replace(tmp, path)


def _cached(path: Path, compute):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass  # partial/corrupt file (interrupted or concurrent writer) — recompute
    value = compute()
    _atomic_write(path, json.dumps(value, indent=1))
    return value


def _cached_text(path: Path, compute):
    if path.exists() and path.stat().st_size > 0:
        return path.read_text()
    value = compute()
    _atomic_write(path, value)
    return value


def run_pool(items: dict, fn, label: str) -> dict:
    """Run fn over items concurrently with per-item error isolation."""
    results, failures = {}, {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fn, item): key for key, item in items.items()}
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                results[key] = fut.result()
                print(f"  [{label}] done {key} ({len(results)}/{len(items)})")
            except Exception as exc:  # isolate: one failure shouldn't kill the run
                failures[key] = repr(exc)
                print(f"  [{label}] FAILED {key}: {exc!r}")
    if failures:
        print(f"  [{label}] {len(failures)} failures (resumable — rerun to retry): {list(failures)}")
    return results


def load_versions(records: dict) -> list[dict]:
    """Every note version in the FIXED eval set (injected + clean), with the
    checkpoint-2 detected-absent answer key attached."""
    injection_records = [json.loads(l) for l in RECORDS_PATH.read_text().splitlines() if l]
    versions = []
    for rec in injection_records:
        injection_id = rec["injection_id"]
        ev = json.loads((EVAL_DIR / f"{injection_id}.json").read_text())
        versions.append(
            {
                "note_version_id": injection_id,
                "note_id": rec["note_id"],
                "note_text": (INJ_DIR / f"{injection_id}.md").read_text(),
                "injected_fact_id": rec["fact"]["id"],
                "injected_severity": rec["severity"],
                "detected_absent_fact_ids": ev["detected_absent_fact_ids"],
            }
        )
    for rid, rec in records.items():
        prov = json.loads((PRESENCE_DIR / f"{rid}.json").read_text())
        versions.append(
            {
                "note_version_id": f"{rid}__clean",
                "note_id": rid,
                "note_text": rec["note"],
                "injected_fact_id": None,
                "injected_severity": None,
                "detected_absent_fact_ids": [
                    r["fact_id"] for r in prov if r["status"] == "absent"
                ],
            }
        )
    return versions


def _absent_rate_metrics(presence_by_note: dict) -> dict:
    counts = sorted(
        sum(1 for r in results if r["status"] == "absent")
        for results in presence_by_note.values()
    )
    if not counts:
        return {"n_notes": 0, "gen_absent_mean": None, "gen_absent_median": None}
    return {
        "n_notes": len(counts),
        "gen_absent_mean": sum(counts) / len(counts),
        "gen_absent_median": statistics.median(counts),
        "gen_absent_max": counts[-1],
        "gen_absent_histogram": {str(c): counts.count(c) for c in sorted(set(counts))},
    }


# ---------------------------------------------------------------- B0 / R1 (generation-side)

def run_B0(ctx: dict, cfg: AblationConfig, prior: dict) -> dict:
    """Baseline 'before': absent facts per transcript-only generated note.
    Reuses generated_notes/ (checkpoint 0) + one cached presence pass each."""
    from recall.presence import presence

    records = ctx["records"]
    missing = [rid for rid in records if not (GEN_NOTES_DIR / f"{rid}.md").exists()]
    assert not missing, (
        f"B0 needs generated_notes/ for all encounters (run run_checkpoint0.py); "
        f"missing {len(missing)}, e.g. {missing[:3]}"
    )

    def one(rid: str):
        return _cached(
            C5 / "B0" / "presence_generated" / f"{rid}.json",
            lambda: presence(
                (GEN_NOTES_DIR / f"{rid}.md").read_text(),
                ctx["facts_by_note"][rid],
                model=MODEL,
            ),
        )

    pres = run_pool({rid: rid for rid in sorted(records)}, one, "B0")
    return {**_absent_rate_metrics(pres), "adds": cfg.adds}


CHECKLIST_RULES = """You are an ambient clinical scribe. Given the visit transcript, write a clinical note in SOAP format (Subjective, Objective, Assessment and Plan) in markdown. Document only what the transcript supports; do not invent findings, vitals, or results that were not stated. Be complete but not redundant.
Before finalizing, check the note against this documentation-completeness checklist and capture every applicable item the transcript supports:
- Medications started, changed, or stopped — with drug, dose, route, frequency
- Pertinent positives AND pertinent negatives (red-flag and ROS screens actually asked)
- Relieving/aggravating factors
- Abnormal or actionable results that were discussed
- Orders, tests, and referrals placed or planned
- Follow-up interval and return precautions
- Counseling or education given
- Clinically relevant social determinants (SDOH)
Do NOT invent content to satisfy the checklist — only document what the transcript supports."""

R1_TRANSCRIPT_BLOCK = "TRANSCRIPT: {transcript}"


def run_R1(ctx: dict, cfg: AblationConfig, prior: dict) -> dict:
    """Checklist in the generation prompt: regenerate each note (cached) and
    measure the prompt-time reduction in absent facts vs B0."""
    from recall.llm import call_text
    from recall.presence import presence

    records = ctx["records"]

    def one(rid: str):
        note = _cached_text(
            C5 / "R1" / "notes" / f"{rid}.md",
            lambda: call_text(
                [
                    {"text": CHECKLIST_RULES, "cache": True},
                    {"text": R1_TRANSCRIPT_BLOCK.format(transcript=records[rid]["transcript"])},
                ],
                max_tokens=8000,
                model=MODEL,
            ),
        )
        return _cached(
            C5 / "R1" / "presence" / f"{rid}.json",
            lambda: presence(note, ctx["facts_by_note"][rid], model=MODEL),
        )

    pres = run_pool({rid: rid for rid in sorted(records)}, one, "R1")
    metrics = {**_absent_rate_metrics(pres), "adds": cfg.adds}
    b0 = prior.get("B0") or {}
    if metrics.get("gen_absent_mean") is not None and b0.get("gen_absent_mean") is not None:
        metrics["gen_absent_delta_vs_B0"] = metrics["gen_absent_mean"] - b0["gen_absent_mean"]
    return metrics


# ---------------------------------------------------------------- R2 (free)

def run_R2(ctx: dict, cfg: AblationConfig, prior: dict) -> dict:
    """Presence guard on the fixed eval set — identical to checkpoint 2's
    cached results, zero API calls."""
    from recall.eval_runner import eval_clean
    from recall.metrics import compute_metrics

    injected_results = []
    for rec in ctx["injection_records"]:
        ev = json.loads((EVAL_DIR / f"{rec['injection_id']}.json").read_text())
        injected_results.append(ev)
    clean_results = []
    for rid in ctx["records"]:
        prov = json.loads((PRESENCE_DIR / f"{rid}.json").read_text())
        clean_results.append(eval_clean(rid, prov))
    m = compute_metrics(ctx["injection_records"], injected_results + clean_results)
    total_flags = sum(len(e["detected_absent_fact_ids"]) for e in injected_results)
    return {
        "adds": cfg.adds,
        "recall_detected": m["recall_overall"],
        "recall_by_severity": m["recall_by_severity"],
        "clean_flag_rate": m["clean_flag_rate_mean"],
        # Lower bound: every non-injected flag counted as FP even though many
        # are genuine natural omissions of the provided notes.
        "precision_lb": (m["n_caught"] / total_flags) if total_flags else None,
        "n_injections": m["n_injections"],
    }


# ---------------------------------------------------------------- R3 / R5 shared FHIR arm

def _encounter_decisions(ctx: dict, rid: str) -> list[dict]:
    """Targeted retrieval decisions for ALL of an encounter's facts — one
    router call per encounter, reused across its ~4 note versions."""
    rec = ctx["records"][rid]
    return _cached(
        C5 / "retrieval" / f"{rid}.json",
        lambda: decide_resource_types(
            ctx["facts_by_note"][rid],
            rec["encounter_fhir"],
            rec["patient_context"].get("longitudinal_summary"),
            model=MODEL,
        ),
    )


def run_fhir_arm(ctx: dict, arm: str) -> dict:
    """Evidence-pattern pass over every note version — `targeted` (R3) or
    `full` (R5 contrast arm). Severity boosts apply ONLY upward; detection
    itself is untouched (FHIR never suppresses — asserted per version)."""
    assert arm in ("targeted", "full")
    assert C3_CLASSIFY.exists(), (
        "R3/R5 need checkpoint3_cache/classify (severity verdicts) — run run_checkpoint3.py first."
    )
    missing = [
        v["note_version_id"]
        for v in ctx["versions"]
        if not (C3_CLASSIFY / f"{v['note_version_id']}.json").exists()
    ]
    assert not missing, (
        f"checkpoint-3 classify cache missing for {len(missing)} note versions, "
        f"e.g. {missing[:3]} — finish run_checkpoint3.py first."
    )
    arm_dir = C5 / ("R3/targeted" if arm == "targeted" else "R5/full")
    records, facts_by_note = ctx["records"], ctx["facts_by_note"]

    def one(v: dict) -> dict:
        rid = v["note_id"]
        rec = records[rid]
        enc = rec["encounter_fhir"]
        ls = rec["patient_context"].get("longitudinal_summary")
        facts = {f["id"]: f for f in facts_by_note[rid]}
        absent = [facts[fid] for fid in v["detected_absent_fact_ids"] if fid in facts]

        def compute():
            if not absent:
                return {"retrievals": [], "corroboration": []}
            if arm == "targeted":
                decisions = _encounter_decisions(ctx, rid)
                retrievals = retrieve_fhir_batch(absent, enc, ls, decisions=decisions)
                items = [
                    {
                        "fact_id": f["id"],
                        "text": f["text"],
                        "transcript_quote": f.get("transcript_quote"),
                        "evidence": r["evidence"],
                    }
                    for f, r in zip(absent, retrievals)
                ]
                corr = corroborate(items, model=MODEL)
            else:
                chart = full_chart_context(enc, ls)
                retrievals = [
                    {
                        "fact_id": f["id"],
                        "resource_types": ["(full chart)"],
                        "rationale": "full-chart arm — no retrieval decision",
                        "evidence": "(shared full-chart context)",
                    }
                    for f in absent
                ]
                items = [
                    {
                        "fact_id": f["id"],
                        "text": f["text"],
                        "transcript_quote": f.get("transcript_quote"),
                    }
                    for f in absent
                ]
                corr = corroborate(items, chart_context=chart, model=MODEL)
            return {"retrievals": retrievals, "corroboration": corr}

        cached = _cached(arm_dir / f"{v['note_version_id']}.json", compute)
        retrievals, corr = cached["retrievals"], cached["corroboration"]
        evidence = classify_evidence(absent, corr, retrievals)
        entries = {e["fact_id"]: e for e in flatten_evidence(evidence)}

        cls_results = json.loads(
            (C3_CLASSIFY / f"{v['note_version_id']}.json").read_text()
        )
        scored, baseline_scored, boosted = [], [], []
        for c in cls_results:
            if c["fact_id"] not in facts:
                continue
            e = entries.get(c["fact_id"])
            c2 = dict(c)
            if e and e.get("severity_boost"):
                new_sev = boost_severity(c2["severity"])
                if new_sev != c2["severity"]:
                    boosted.append(c["fact_id"])
                c2["severity"] = new_sev
            scored.append({"fact": facts[c["fact_id"]], "classify_result": c2})
            baseline_scored.append({"fact": facts[c["fact_id"]], "classify_result": c})
        rendered = render(scored)
        baseline_rendered = render(baseline_scored)
        surfaced = [f["fact_id"] for f in rendered["surfaced"]]
        inj = v["injected_fact_id"]
        return {
            "note_version_id": v["note_version_id"],
            "note_id": rid,
            "injected_fact_id": inj,
            "injected_severity": v["injected_severity"],
            "surfaced_fact_ids": surfaced,
            "baseline_surfaced_fact_ids": [
                f["fact_id"] for f in baseline_rendered["surfaced"]
            ],
            "caught": (inj in surfaced) if inj else None,
            "baseline_caught": (
                inj in [f["fact_id"] for f in baseline_rendered["surfaced"]]
            )
            if inj
            else None,
            "boosted_fact_ids": boosted,
            "pattern_by_fact": {fid: e["evidence_pattern"] for fid, e in entries.items()},
            "evidence_by_fact": {r["fact_id"]: r.get("evidence") for r in retrievals},
            "rationale_by_fact": {
                fid: e.get("corroboration_rationale", "") for fid, e in entries.items()
            },
            "n_coverage": len(evidence["coverage_candidates"]),
            "n_reconciliation": len(evidence["reconciliation_needed"]),
        }

    per_version = run_pool(
        {
            v["note_version_id"]: v
            for v in sorted(ctx["versions"], key=lambda v: v["note_id"])
        },
        one,
        f"fhir-{arm}",
    )
    return _arm_metrics(per_version, ctx, arm)


def _arm_metrics(per_version: dict, ctx: dict, arm: str) -> dict:
    res = list(per_version.values())
    injected = [r for r in res if r["injected_fact_id"]]
    clean = [r for r in res if not r["injected_fact_id"]]

    by_sev: dict[str, dict] = {}
    for r in injected:
        d = by_sev.setdefault(r["injected_severity"], {"caught": 0, "total": 0})
        d["total"] += 1
        if r["caught"]:
            d["caught"] += 1
    n_caught = sum(1 for r in injected if r["caught"])
    n_baseline_caught = sum(1 for r in injected if r["baseline_caught"])
    total_surfaced_injected = sum(len(r["surfaced_fact_ids"]) for r in injected)

    pattern_dist = Counter()
    for r in res:
        pattern_dist.update(r["pattern_by_fact"].values())

    # Annotated-example candidates (fact text resolved from the facts cache).
    facts_by_note = ctx["facts_by_note"]
    examples = []
    for r in injected:
        if r["injected_fact_id"] in r["boosted_fact_ids"]:
            fact = next(
                f for f in facts_by_note[r["note_id"]] if f["id"] == r["injected_fact_id"]
            )
            examples.append(
                {
                    "kind": "corroborated boost",
                    "note_version_id": r["note_version_id"],
                    "fact_text": fact["text"],
                    "detail": r["rationale_by_fact"].get(r["injected_fact_id"], ""),
                    "outcome": "surfaced" if r["caught"] else "not surfaced",
                }
            )
            break
    for r in res:
        cov = [fid for fid, p in r["pattern_by_fact"].items() if p == "fhir_only"]
        if cov:
            fact = next(f for f in facts_by_note[r["note_id"]] if f["id"] == cov[0])
            examples.append(
                {
                    "kind": "chart-critical coverage candidate",
                    "note_version_id": r["note_version_id"],
                    "fact_text": fact["text"],
                    "detail": r["rationale_by_fact"].get(cov[0], ""),
                    "outcome": "separate coverage list (never folded into omission recall)",
                }
            )
            break

    return {
        "arm": arm,
        "n_versions": len(res),
        "surfaced_recall": (n_caught / len(injected)) if injected else None,
        "surfaced_recall_by_severity": by_sev,
        "baseline_surfaced_recall": (n_baseline_caught / len(injected)) if injected else None,
        "precision_lb": (n_caught / total_surfaced_injected) if total_surfaced_injected else None,
        "clean_surfaced_rate": (
            sum(len(r["surfaced_fact_ids"]) for r in clean) / len(clean) if clean else None
        ),
        "baseline_clean_surfaced_rate": (
            sum(len(r["baseline_surfaced_fact_ids"]) for r in clean) / len(clean)
            if clean
            else None
        ),
        "n_boosted": sum(len(r["boosted_fact_ids"]) for r in res),
        "n_boosted_clean": sum(len(r["boosted_fact_ids"]) for r in clean),
        "n_coverage": sum(r["n_coverage"] for r in res),
        "n_reconciliation": sum(r["n_reconciliation"] for r in res),
        "pattern_dist": dict(pattern_dist),
        "examples": examples,
        "per_version": per_version,
    }


def run_R3(ctx: dict, cfg: AblationConfig, prior: dict) -> dict:
    m = run_fhir_arm(ctx, "targeted")
    r2 = prior.get("R2") or {}
    return {
        "adds": cfg.adds,
        # Detection is untouched by FHIR (it never suppresses): detected
        # recall carries over from R2 by construction.
        "recall_detected": r2.get("recall_detected"),
        "surfaced_recall": m["surfaced_recall"],
        "surfaced_recall_by_severity": m["surfaced_recall_by_severity"],
        "baseline_surfaced_recall": m["baseline_surfaced_recall"],
        "precision_lb": m["precision_lb"],
        "clean_surfaced_rate": m["clean_surfaced_rate"],
        "baseline_clean_surfaced_rate": m["baseline_clean_surfaced_rate"],
        "n_boosted": m["n_boosted"],
        "n_boosted_clean": m["n_boosted_clean"],
        "n_coverage": m["n_coverage"],
        "n_reconciliation": m["n_reconciliation"],
        "pattern_dist": m["pattern_dist"],
        "examples": m["examples"],
        "per_version": m["per_version"],
    }


# ---------------------------------------------------------------- R4 (patch — CP4 modules)

MAX_PATCH_ITERATIONS = 3  # mirrors run_checkpoint4's evaluator-optimizer loop


def _repeated_ngram_rate(text: str, n: int = 5) -> float:
    """Share of word n-grams that are repeats — the redundancy proxy
    (kept locally so this runner never imports another run_checkpoint script)."""
    words = text.lower().split()
    grams = [tuple(words[i : i + n]) for i in range(len(words) - n + 1)]
    if not grams:
        return 0.0
    return 1 - len(set(grams)) / len(grams)


def run_R4(ctx: dict, cfg: AblationConfig, prior: dict) -> dict:
    """Patch + verifier (evaluator-optimizer loop) over every surfaced flag.
    Gated on the CP4 modules; uses their real contract:
    patch(fact, evidence, note, feedback) / verify_patch(patch, evidence, note)."""
    try:
        from recall.patch import apply_patch, evidence_for
        from recall.patch import patch as propose_patch
        from recall.verify_patch import verify_patch
    except ImportError as exc:
        raise AssertionError(
            "R4 requires checkpoint-4 modules recall/patch.py + recall/verify_patch.py "
            f"(built in a parallel session) — not importable yet: {exc}"
        )

    r3 = prior.get("R3")
    if not r3 or "per_version" not in r3:  # R3 not run or skipped — recompute
        r3 = run_fhir_arm(ctx, "targeted")  # asserts its own prerequisites
    records, facts_by_note = ctx["records"], ctx["facts_by_note"]
    versions_by_id = {v["note_version_id"]: v for v in ctx["versions"]}

    def one(nvid: str) -> list[dict]:
        pv = r3["per_version"][nvid]
        v = versions_by_id[nvid]
        if not pv["surfaced_fact_ids"]:
            return []

        def compute():
            facts = {f["id"]: f for f in facts_by_note[v["note_id"]]}
            enc = records[v["note_id"]]["encounter_fhir"]
            note = v["note_text"]
            out = []
            for fid in pv["surfaced_fact_ids"]:
                if pv["pattern_by_fact"].get(fid) == "reconciliation_needed":
                    out.append(
                        {"fact_id": fid, "verified": False,
                         "skipped": "reconciliation_needed — never auto-patched"}
                    )
                    continue
                fact = facts[fid]
                evidence = evidence_for(fact, enc)
                fhir_ev = pv["evidence_by_fact"].get(fid)
                if fhir_ev and fhir_ev != "(shared full-chart context)":
                    evidence += "\nTargeted FHIR evidence:\n" + fhir_ev
                try:
                    feedback = None
                    p = verdict = None
                    iterations = 0
                    for iterations in range(1, MAX_PATCH_ITERATIONS + 1):
                        p = propose_patch(fact, evidence, note, feedback=feedback, model=MODEL)
                        verdict = verify_patch(p, evidence, note, model=MODEL)
                        if verdict["pass"]:
                            break
                        feedback = verdict["reasons"]
                    verified = bool(verdict and verdict["pass"])
                    entry = {
                        "fact_id": fid,
                        "verified": verified,
                        "grounded": bool(verdict and verdict.get("grounded")),
                        "iterations": iterations,
                        "patch": p,
                        "verify": verdict,
                        "redundancy_delta": None,
                    }
                    if verified:
                        patched = apply_patch(note, p)
                        entry["redundancy_delta"] = (
                            _repeated_ngram_rate(patched) - _repeated_ngram_rate(note)
                        )
                    out.append(entry)
                except Exception as exc:  # per-flag isolation
                    out.append({"fact_id": fid, "verified": False, "error": repr(exc)})
            return out

        return _cached(C5 / "R4" / f"{nvid}.json", compute)

    results = run_pool(
        {nvid: nvid for nvid in sorted(r3["per_version"])}, one, "R4-patch"
    )
    flat = [p for patches in results.values() for p in patches]
    attempted = [p for p in flat if "skipped" not in p]
    verified = [p for p in attempted if p.get("verified")]
    errors = [p for p in attempted if p.get("error")]
    deltas = [p["redundancy_delta"] for p in verified if p.get("redundancy_delta") is not None]
    return {
        "adds": cfg.adds,
        "n_flags": len(flat),
        "n_attempted": len(attempted),
        "n_verified": len(verified),
        "n_errors": len(errors),
        "n_skipped_reconciliation": len(flat) - len(attempted),
        "patch_success": (len(verified) / len(attempted)) if attempted else None,
        # Faithfulness = verifier-grounded share (no unsupported claims added).
        "patch_faithfulness": (
            sum(1 for p in attempted if p.get("grounded")) / len(attempted)
            if attempted
            else None
        ),
        "redundancy_delta_mean": (sum(deltas) / len(deltas)) if deltas else None,
        "surfaced_recall": r3["surfaced_recall"],
        "clean_surfaced_rate": r3["clean_surfaced_rate"],
    }


# ---------------------------------------------------------------- R5 (contradiction + full arm)

def _has_coded_values(rec: dict) -> bool:
    related = rec["encounter_fhir"].get("related_resources", {})
    for o in related.get("Observation", []):
        if any(k in o for k in ("valueQuantity", "valueCodeableConcept", "component")):
            return True
    for mr in related.get("MedicationRequest", []):
        mcc = mr.get("medicationCodeableConcept", {})
        if mcc.get("text") or any(c.get("display") for c in mcc.get("coding", [])):
            return True
    return False


def run_contradictions(ctx: dict) -> dict:
    """Plant ~N labeled contradictions (one per eligible encounter, provided
    note) + detect on planted and clean notes. OWN metric — never folded
    into omission recall."""
    records = ctx["records"]
    eligible = [rid for rid in sorted(records) if _has_coded_values(records[rid])]
    targets = eligible[:N_CONTRADICTIONS]
    if len(targets) < 15:
        print(
            f"  [contradiction] WARNING: only {len(targets)} eligible encounters "
            f"(spec wants ~15–20 plants)"
        )

    def plant(rid: str) -> dict:
        return _cached(
            C5 / "contradictions" / f"{rid}.json",
            lambda: inject_contradiction(
                records[rid]["note"], records[rid]["encounter_fhir"], model=MODEL
            ),
        )

    planted = run_pool({rid: rid for rid in targets}, plant, "contradiction-plant")

    def detect_planted(rid: str) -> list[dict]:
        return _cached(
            C5 / "R5" / "detect_planted" / f"{rid}.json",
            lambda: detect_contradiction(
                planted[rid]["contradicted_note"], records[rid]["encounter_fhir"], model=MODEL
            ),
        )

    det_planted = run_pool(
        {rid: rid for rid in sorted(planted)}, detect_planted, "contradiction-detect"
    )

    def detect_clean(rid: str) -> list[dict]:
        return _cached(
            C5 / "R5" / "detect_clean" / f"{rid}.json",
            lambda: detect_contradiction(
                records[rid]["note"], records[rid]["encounter_fhir"], model=MODEL
            ),
        )

    det_clean = run_pool({rid: rid for rid in sorted(records)}, detect_clean, "contradiction-clean")

    matched = {
        rid: planted_was_detected(det_planted.get(rid, []), planted[rid]) for rid in planted
    }
    n_detected = sum(matched.values())
    example = None
    for rid, ok in matched.items():
        if ok:
            hit = next(
                d for d in det_planted[rid]
                if planted_was_detected([d], planted[rid])
            )
            example = {
                "note_id": rid,
                "altered_claim": planted[rid]["altered_claim"],
                "fhir_ref": planted[rid]["fhir_ref"],
                "detected_claim": hit["claim"],
                "conflict_description": hit["conflict_description"],
            }
            break
    return {
        "n_planted": len(planted),
        "n_detected": n_detected,
        "detection_rate": (n_detected / len(planted)) if planted else None,
        "extra_detections_per_planted_note": (
            sum(max(len(det_planted.get(rid, [])) - 1, 0) for rid in planted) / len(planted)
            if planted
            else None
        ),
        "clean_contradiction_rate": (
            sum(len(d) for d in det_clean.values()) / len(det_clean) if det_clean else None
        ),
        "missed": [rid for rid, ok in matched.items() if not ok],
        "example": example,
    }


def _tvf_verdict(t: dict, f: dict) -> str:
    """Honest targeted-vs-full verdict — computed from the numbers, whichever
    way they fall."""
    parts = []
    if t.get("surfaced_recall") is not None and f.get("surfaced_recall") is not None:
        dr = f["surfaced_recall"] - t["surfaced_recall"]
        parts.append(
            f"full-chart surfaced recall {f['surfaced_recall']:.1%} vs targeted "
            f"{t['surfaced_recall']:.1%} (Δ {dr:+.1%})"
        )
    else:
        dr = 0.0
    if t.get("clean_surfaced_rate") is not None and f.get("clean_surfaced_rate") is not None:
        dc = f["clean_surfaced_rate"] - t["clean_surfaced_rate"]
        parts.append(
            f"clean-note surfaced-flag rate {f['clean_surfaced_rate']:.2f} vs "
            f"{t['clean_surfaced_rate']:.2f}/note (Δ {dc:+.2f}; higher = precision harm)"
        )
    else:
        dc = 0.0
    if dc > 0.05 and dr <= 0:
        verdict = "targeted helps, full-chart hurts (dragged-in history costs precision without recall gain)"
    elif dr > 0.02 and dc <= 0:
        verdict = "full-chart helped here — the extra context raised recall without a precision cost"
    elif abs(dr) <= 0.02 and abs(dc) <= 0.05:
        verdict = "no meaningful targeted-vs-full difference on this eval set"
    else:
        verdict = "mixed: full-chart trades recall and precision — see deltas"
    return "; ".join(parts) + f". Verdict: {verdict}."


def run_R5(ctx: dict, cfg: AblationConfig, prior: dict) -> dict:
    r3 = prior.get("R3")
    if not r3 or "per_version" not in r3:  # R3 not run or skipped — recompute
        r3 = run_fhir_arm(ctx, "targeted")  # asserts its own prerequisites
    full = run_fhir_arm(ctx, "full")
    contr = run_contradictions(ctx)
    tvf = {
        "targeted": {k: r3.get(k) for k in (
            "surfaced_recall", "clean_surfaced_rate", "n_boosted", "n_boosted_clean",
            "pattern_dist", "precision_lb",
        )},
        "full": {k: full.get(k) for k in (
            "surfaced_recall", "clean_surfaced_rate", "n_boosted", "n_boosted_clean",
            "pattern_dist", "precision_lb",
        )},
        "verdict": _tvf_verdict(r3, full),
    }
    return {
        "adds": cfg.adds,
        # R5's detection stack stays targeted; full-chart is the contrast arm.
        "surfaced_recall": r3.get("surfaced_recall"),
        "clean_surfaced_rate": r3.get("clean_surfaced_rate"),
        "precision_lb": r3.get("precision_lb"),
        "contradiction": contr,
        "targeted_vs_full": tvf,
        "full_arm_examples": full.get("examples", []),
    }


# ---------------------------------------------------------------- R6 (optional stub)

def run_R6(ctx: dict, cfg: AblationConfig, prior: dict) -> dict:
    # TODO(R6 — optional rung, underspecified by the scoping doc): a
    # terminology normalizer (merge fact variants pre-presence) and
    # threshold tuning for precision/FP. No normalizer module exists yet;
    # this rung deliberately reports itself as skipped rather than faking
    # a number.
    return {
        "adds": cfg.adds,
        "skipped": True,
        "notes": "normalizer/tuning not built — optional rung, see TODO in run_R6",
    }


RUNNERS = {
    "B0": run_B0, "R1": run_R1, "R2": run_R2, "R3": run_R3,
    "R4": run_R4, "R5": run_R5, "R6": run_R6,
}


# ---------------------------------------------------------------- report

def _fmt(value, kind: str = "raw") -> str:
    if value is None:
        return "—"
    if kind == "pct":
        return f"{value:.1%}"
    if kind == "f2":
        return f"{value:.2f}"
    return str(value)


def write_report(results: dict, ctx: dict) -> None:
    lines = ["# Checkpoint 5 — FHIR ablation (targeted vs full-chart)", ""]

    # --- Top line: what helped / harmed + the FHIR verdict.
    top = []
    b0, r1 = results.get("B0"), results.get("R1")
    if r1 and r1.get("gen_absent_delta_vs_B0") is not None:
        d = r1["gen_absent_delta_vs_B0"]
        top.append(
            f"checklist-in-prompt changed generated-note absent facts by {d:+.2f}/note "
            f"({'helped' if d < 0 else 'did not help'})"
        )
    r2, r3 = results.get("R2"), results.get("R3")
    if r3 and r3.get("surfaced_recall") is not None and r3.get("baseline_surfaced_recall") is not None:
        d = r3["surfaced_recall"] - r3["baseline_surfaced_recall"]
        dc = (r3.get("clean_surfaced_rate") or 0) - (r3.get("baseline_clean_surfaced_rate") or 0)
        top.append(
            f"targeted FHIR corroboration moved surfaced recall by {d:+.1%} "
            f"and clean-note surfaced flags by {dc:+.2f}/note"
        )
    r5 = results.get("R5")
    if r5 and r5.get("targeted_vs_full"):
        top.append(r5["targeted_vs_full"]["verdict"])
    if r5 and r5.get("contradiction", {}).get("detection_rate") is not None:
        c = r5["contradiction"]
        top.append(
            f"contradiction detection (separate metric) {c['n_detected']}/{c['n_planted']} "
            f"= {c['detection_rate']:.0%} with {c['clean_contradiction_rate']:.2f} "
            f"contradiction flags/clean note"
        )
    lines.append("**Top line:** " + ("; ".join(top) if top else
                 "run incomplete — rungs below reflect only what has been computed so far."))
    lines.append("")

    # --- Ablation table (rows = rungs, cols = metrics).
    lines.append("## Ablation table")
    lines.append("")
    lines.append(
        "| Rung | Adds | Gen absent/note | Recall (detected) | Recall (surfaced) | "
        "Precision (lower bound) | Clean-note flag rate | Patch success | Contradiction detect |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for cfg in RUNGS:
        r = results.get(cfg.name)
        if r is None:
            continue
        if r.get("skipped"):
            lines.append(
                f"| {cfg.name} | {cfg.adds} | — | — | — | — | — | — | "
                f"_{r.get('notes', 'skipped')}_ |"
            )
            continue
        contr = (r.get("contradiction") or {}).get("detection_rate")
        lines.append(
            f"| {cfg.name} | {cfg.adds} "
            f"| {_fmt(r.get('gen_absent_mean'), 'f2')} "
            f"| {_fmt(r.get('recall_detected'), 'pct')} "
            f"| {_fmt(r.get('surfaced_recall'), 'pct')} "
            f"| {_fmt(r.get('precision_lb'), 'pct')} "
            f"| {_fmt(r.get('clean_flag_rate', r.get('clean_surfaced_rate')), 'f2')} "
            f"| {_fmt(r.get('patch_success'), 'pct')} "
            f"| {_fmt(contr, 'pct')} |"
        )
    lines.append("")
    lines.append(
        "_B0/R1 measure the GENERATED note (absent facts/note — lower is better); R2+ "
        "measure detection on the fixed injected/clean provided-note answer key. "
        "Precision is a lower bound: non-injected flags counted against it even though "
        "many are genuine natural omissions. Contradiction has its own column and is "
        "never folded into omission recall._"
    )
    lines.append("")

    # --- Targeted vs full-chart (the headline).
    lines.append("## Targeted vs full-chart (the honest FHIR question)")
    lines.append("")
    if r5 and r5.get("targeted_vs_full"):
        tvf = r5["targeted_vs_full"]
        lines.append(tvf["verdict"])
        lines.append("")
        lines.append("| Metric | Targeted (R3) | Full-chart (R5 arm) |")
        lines.append("|---|---|---|")
        t, f = tvf["targeted"], tvf["full"]
        lines.append(
            f"| Surfaced recall | {_fmt(t.get('surfaced_recall'), 'pct')} | {_fmt(f.get('surfaced_recall'), 'pct')} |"
        )
        lines.append(
            f"| Clean-note surfaced-flag rate | {_fmt(t.get('clean_surfaced_rate'), 'f2')} | {_fmt(f.get('clean_surfaced_rate'), 'f2')} |"
        )
        lines.append(
            f"| Precision (lower bound) | {_fmt(t.get('precision_lb'), 'pct')} | {_fmt(f.get('precision_lb'), 'pct')} |"
        )
        lines.append(
            f"| Severity boosts (all / clean notes) | {t.get('n_boosted')} / {t.get('n_boosted_clean')} | {f.get('n_boosted')} / {f.get('n_boosted_clean')} |"
        )
        lines.append(
            f"| Evidence patterns | {t.get('pattern_dist')} | {f.get('pattern_dist')} |"
        )
    else:
        lines.append("_R5 not run yet — the comparison lands here._")
    lines.append("")

    # --- Evidence-pattern distribution.
    lines.append("## Evidence-pattern distribution (targeted arm)")
    lines.append("")
    if r3 and r3.get("pattern_dist"):
        total = sum(r3["pattern_dist"].values())
        lines.append("| Pattern | n | share |")
        lines.append("|---|---|---|")
        for pat in ("transcript_only", "transcript_fhir", "fhir_only", "reconciliation_needed"):
            n = r3["pattern_dist"].get(pat, 0)
            lines.append(f"| {pat} | {n} | {n / total:.0%} |" if total else f"| {pat} | 0 | — |")
        lines.append("")
        lines.append(
            "_fhir_only = chart-critical coverage candidates (separate list); "
            "reconciliation_needed = transcript-vs-FHIR conflicts (flagged, never "
            "auto-patched). FHIR never suppresses: every absent fact appears in "
            "exactly one bucket — asserted per note version._"
        )
    else:
        lines.append("_R3 not run yet._")
    lines.append("")

    # --- Contradiction results (separate class).
    lines.append("## Contradiction results (separate failure class)")
    lines.append("")
    if r5 and r5.get("contradiction"):
        c = r5["contradiction"]
        lines.append(
            f"- Planted: {c['n_planted']} · detected: {c['n_detected']} "
            f"({_fmt(c['detection_rate'], 'pct')}) · missed: {c['missed'] or 'none'}"
        )
        lines.append(
            f"- Extra (non-planted) detections on contradicted notes: "
            f"{_fmt(c['extra_detections_per_planted_note'], 'f2')}/note · "
            f"clean-note contradiction flags: {_fmt(c['clean_contradiction_rate'], 'f2')}/note "
            f"(false-alarm signal)"
        )
    else:
        lines.append("_R5 not run yet._")
    lines.append("")

    # --- Component attribution.
    lines.append("## Component attribution (marginal change per rung, harms included)")
    lines.append("")
    attributed = False
    if b0 and r1 and r1.get("gen_absent_delta_vs_B0") is not None:
        d = r1["gen_absent_delta_vs_B0"]
        tag = "helped" if d < 0 else ("no effect" if d == 0 else "HARMED (more omissions)")
        lines.append(f"- **B0→R1 (checklist):** generated-note absent rate {d:+.2f}/note — {tag}.")
        attributed = True
    if r2:
        lines.append(
            f"- **R2 (presence guard):** detection recall {_fmt(r2.get('recall_detected'), 'pct')} on the "
            f"fixed answer key at {_fmt(r2.get('clean_flag_rate'), 'f2')} raw flags/clean note — the floor "
            f"everything below modulates."
        )
        attributed = True
    if r3 and r3.get("baseline_surfaced_recall") is not None:
        d = (r3.get("surfaced_recall") or 0) - r3["baseline_surfaced_recall"]
        dc = (r3.get("clean_surfaced_rate") or 0) - (r3.get("baseline_clean_surfaced_rate") or 0)
        harm = " — HARM: boosts surfaced extra clean-note flags" if dc > 0 else ""
        lines.append(
            f"- **R3 (targeted FHIR):** severity boosts moved surfaced recall {d:+.1%} "
            f"({r3.get('n_boosted')} boosts, {r3.get('n_boosted_clean')} on clean notes; "
            f"clean surfaced rate {dc:+.2f}/note{harm})."
        )
        attributed = True
    r4 = results.get("R4")
    if r4 and not r4.get("skipped"):
        lines.append(
            f"- **R4 (patch+verify):** {r4.get('n_verified')}/{r4.get('n_attempted')} patches verified "
            f"({_fmt(r4.get('patch_success'), 'pct')}); faithfulness (verifier-grounded) "
            f"{_fmt(r4.get('patch_faithfulness'), 'pct')}; redundancy delta "
            f"{_fmt(r4.get('redundancy_delta_mean'), 'f2')} (self-overlap after−before, ≤0 is good); "
            f"{r4.get('n_skipped_reconciliation')} reconciliation-needed flags never auto-patched; "
            f"{r4.get('n_errors')} errors."
        )
        attributed = True
    if r5 and r5.get("targeted_vs_full"):
        lines.append(f"- **R5 (full-chart arm):** {r5['targeted_vs_full']['verdict']}")
        attributed = True
    if not attributed:
        lines.append("_No rungs computed yet._")
    lines.append("")

    # --- Annotated examples.
    lines.append("## Annotated examples")
    lines.append("")
    shown = 0
    candidates = ((r3 or {}).get("examples") or []) + (
        (r5 or {}).get("full_arm_examples") or []
    )
    for ex in candidates:
        if shown >= 3:
            break
        lines.append(
            f"- **{ex['kind']}** (`{ex['note_version_id']}`): “{ex['fact_text']}” — "
            f"{ex['detail'] or 'no judge rationale'} → {ex['outcome']}"
        )
        shown += 1
    if r5 and r5.get("contradiction", {}).get("example") and shown < 3:
        ex = r5["contradiction"]["example"]
        lines.append(
            f"- **planted contradiction caught** (`{ex['note_id']}`): planted “{ex['altered_claim']}” "
            f"vs `{ex['fhir_ref']}` → detector quoted “{ex['detected_claim']}” — "
            f"{ex['conflict_description']}"
        )
        shown += 1
    if shown == 0:
        lines.append("_No examples available yet (run R3/R5)._")
    lines.append("")

    CHECKPOINT_MD.write_text("\n".join(lines))
    print(f"Wrote {CHECKPOINT_MD}")


# ---------------------------------------------------------------- main

def main() -> None:
    # --- Gate: the fixed answer key must exist; we never regenerate it here.
    assert RECORDS_PATH.exists() and FACTS_DIR.exists() and PRESENCE_DIR.exists() and EVAL_DIR.exists(), (
        "Checkpoint 5 requires the FIXED checkpoint-2 answer key "
        "(injections/records.jsonl + checkpoint2_cache/{facts,presence_provided,eval}) — "
        "run run_checkpoint2.py first."
    )
    records = {r["id"]: r for r in load_records()}
    facts_by_note = {p.stem: json.loads(p.read_text()) for p in FACTS_DIR.glob("*.json")}
    missing_facts = sorted(set(records) - set(facts_by_note))
    assert not missing_facts, f"checkpoint2_cache/facts incomplete — missing {missing_facts[:3]}"
    injection_records = [json.loads(l) for l in RECORDS_PATH.read_text().splitlines() if l]
    versions = load_versions(records)
    ctx = {
        "records": records,
        "facts_by_note": facts_by_note,
        "injection_records": injection_records,
        "versions": versions,
    }

    rung_arg = next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--rungs"), None)
    if rung_arg:
        selected = [r.strip() for r in rung_arg.split(",") if r.strip()]
        unknown = [r for r in selected if r not in RUNNERS]
        assert not unknown, f"Unknown rungs {unknown}; valid: {list(RUNNERS)}"
    else:
        selected = [cfg.name for cfg in RUNGS if not cfg.optional]
    print(
        f"Ablation over {len(versions)} note versions ({len(injection_records)} injected + "
        f"{len(records)} clean); rungs: {selected}; model: {MODEL or 'default'}"
    )

    results: dict[str, dict] = {}
    for cfg in RUNGS:
        if cfg.name not in selected:
            continue
        print(f"— Rung {cfg.name}: {cfg.adds}")
        try:
            results[cfg.name] = RUNNERS[cfg.name](ctx, cfg, results)
        except AssertionError as exc:
            # A rung whose prerequisites are missing is skipped, not fatal —
            # the report says so honestly.
            print(f"  [{cfg.name}] SKIPPED — {exc}")
            results[cfg.name] = {"adds": cfg.adds, "skipped": True, "notes": str(exc)}

    write_report(results, ctx)
    from recall.llm import usage_summary
    print("API usage:", usage_summary())


if __name__ == "__main__":
    main()
