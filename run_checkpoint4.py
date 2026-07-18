"""Checkpoint 4 — patch surfaced omissions + independent verifier loop.

Scope (locked): patch ONLY surfaced flags — degraded notes whose planted
omission was caught AND surfaced by Checkpoint 3. Surfacing is recomputed
here from cached data (checkpoint3_cache/classify + checkpoint2_cache via
recall.render) with no LLM calls. For each eligible note, run the
evaluator-optimizer loop:

  patch → verify_patch → revise-on-fail (reasons fed back), max 3 iterations,
  then mark unpatchable and surface without diff.

Accepted patches are applied deterministically (apply_patch), then judged:
  fact_restored  = presence(patched_note, [fact]) == present
  faithfulness   = grounded field of a FINAL post-hoc verify_patch call
                   (a fresh call, distinct from the loop's last verify)
  redundancy Δ   = pure-Python repeated-5-gram self-overlap, after − before

Plus a verifier-efficacy stress test: ~10 deliberately bad patches built
deterministically in code (ungrounded / redundant / misplaced) that
verify_patch must reject.

All LLM phases are cached per item under checkpoint4_cache/ (resumable).
`severity` in Checkpoint4Result is the CLASSIFIER severity the flag was
surfaced with (Checkpoint 3's judgment); the Checkpoint-2 heuristic severity
is kept alongside as injected_severity.

Run:  .venv/bin/python run_checkpoint4.py [--workers N]
"""

from __future__ import annotations

import difflib
import json
import os
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

from recall.patch import apply_patch, evidence_for, section_span
from recall.patch import patch as propose_patch
from recall.presence import presence
from recall.render import render
from recall.verify_patch import verify_patch

REPO = Path(__file__).resolve().parent
DATA_PATH = Path(
    os.environ.get(
        "DATA_PATH", REPO / "synthetic-ambient-fhir-25" / "synthetic-ambient-fhir-25.jsonl"
    )
)
C2 = REPO / "checkpoint2_cache"
FACTS_DIR, EVAL_DIR = C2 / "facts", C2 / "eval"
INJ_DIR = REPO / "injections"
RECORDS_PATH = INJ_DIR / "records.jsonl"
C3_CLASSIFY = REPO / "checkpoint3_cache" / "classify"
C4 = REPO / "checkpoint4_cache"
CHECKPOINT_MD = REPO / "checkpoint_4.md"

WORKERS = int(next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--workers"), 5))
MAX_ITERATIONS = 3
NGRAM_N = 5


def _cached(path: Path, compute):
    if path.exists():
        return json.loads(path.read_text())
    value = compute()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1))
    return value


def run_pool(items: dict, fn, label: str) -> dict:
    """Run fn over items concurrently with per-item error isolation."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

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


# ------------------------------------------------------- eligibility (no LLM)


def load_eligible() -> tuple[list[dict], dict]:
    """Degraded notes whose planted omission was caught AND surfaced.

    Detection comes from checkpoint2_cache/eval; surfacing is recomputed from
    checkpoint3_cache/classify via recall.render — pure Python, no LLM.
    """
    records = {json.loads(l)["id"]: json.loads(l) for l in open(DATA_PATH) if l.strip()}
    injection_records = [json.loads(l) for l in RECORDS_PATH.read_text().splitlines() if l]
    eligible, skipped = [], {"not_detected": 0, "not_surfaced": 0}
    for rec in injection_records:
        nvid, inj_fid = rec["injection_id"], rec["fact"]["id"]
        ev = json.loads((EVAL_DIR / f"{nvid}.json").read_text())
        if inj_fid not in ev["detected_absent_fact_ids"]:
            skipped["not_detected"] += 1
            continue
        facts = {f["id"]: f for f in json.loads((FACTS_DIR / f"{rec['note_id']}.json").read_text())}
        cls_results = json.loads((C3_CLASSIFY / f"{nvid}.json").read_text())
        rendered = render(
            [
                {"fact": facts[c["fact_id"]], "classify_result": c}
                for c in cls_results
                if c["fact_id"] in facts
            ]
        )
        surfaced_ids = [f["fact_id"] for f in rendered["surfaced"]]
        if inj_fid not in surfaced_ids:
            skipped["not_surfaced"] += 1
            continue
        cls_by_id = {c["fact_id"]: c for c in cls_results}
        eligible.append(
            {
                "note_version_id": nvid,
                "note_id": rec["note_id"],
                "fact": rec["fact"],
                "severity": cls_by_id[inj_fid]["severity"],  # surfaced (classifier) severity
                "injected_severity": rec["severity"],
                "note_text": (INJ_DIR / f"{nvid}.md").read_text(),
                "encounter_fhir": records[rec["note_id"]]["encounter_fhir"],
            }
        )
    return eligible, skipped


# ----------------------------------------------------- evaluator-optimizer loop


def run_loop(fact: dict, evidence: str, note: str) -> dict:
    """patch → verify_patch → revise-on-fail; max MAX_ITERATIONS, then unpatchable."""
    history: list[dict] = []
    feedback = None
    for i in range(1, MAX_ITERATIONS + 1):
        p = propose_patch(fact, evidence, note, feedback=feedback)
        v = verify_patch(p, evidence, note)
        history.append({"patch": p, "verify": v})
        if v["pass"]:
            return {"patch": p, "verify": v, "iterations": i, "unpatchable": False, "history": history}
        feedback = v["reasons"]
    last = history[-1]
    return {
        "patch": last["patch"],
        "verify": last["verify"],
        "iterations": MAX_ITERATIONS,
        "unpatchable": True,
        "history": history,
    }


def run_item(item: dict) -> dict:
    """Loop → apply → restore-check → post-hoc verify; each LLM phase cached."""
    fact, note, nvid = item["fact"], item["note_text"], item["note_version_id"]
    evidence = evidence_for(fact, item["encounter_fhir"])

    loop = _cached(C4 / "patch_loop" / f"{nvid}.json", lambda: run_loop(fact, evidence, note))

    result = {
        # Checkpoint4Result contract
        "note_version_id": nvid,
        "injected_fact_id": fact["id"],
        "severity": item["severity"],
        "patched": not loop["unpatchable"],
        "iterations": loop["iterations"],
        "unpatchable": loop["unpatchable"],
        "fact_restored": False,
        "verify_pass": loop["verify"]["pass"],
        # report extras
        "injected_severity": item["injected_severity"],
        "fact_text": fact["text"],
        "patch": loop["patch"],
        "history": loop["history"],
        "note_before": note,
        "note_after": None,
        "posthoc_grounded": None,
        "redundancy_delta": None,
    }
    if loop["unpatchable"]:
        return result

    patched_note = apply_patch(note, loop["patch"])
    result["note_after"] = patched_note
    restore = _cached(C4 / "restore" / f"{nvid}.json", lambda: presence(patched_note, [fact]))
    result["fact_restored"] = restore[0]["status"] == "present"
    # Fresh post-hoc grounding spot-check — a NEW verify call, distinct from
    # the loop's last verify (whose verdict gated acceptance).
    posthoc = _cached(
        C4 / "posthoc" / f"{nvid}.json", lambda: verify_patch(loop["patch"], evidence, note)
    )
    result["posthoc_grounded"] = posthoc["grounded"]
    result["redundancy_delta"] = repeated_ngram_rate(patched_note) - repeated_ngram_rate(note)
    return result


# ------------------------------------------------------- redundancy (no LLM)


def repeated_ngram_rate(text: str, n: int = NGRAM_N) -> float:
    """Token-level self-overlap: fraction of word n-grams that are repeats.

    A patch that restates existing content raises this; a minimal insertion
    barely moves it. Pure Python, no embeddings.
    """
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    if len(tokens) < n:
        return 0.0
    counts = Counter(tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1))
    total = sum(counts.values())
    repeated = sum(c for c in counts.values() if c > 1)
    return repeated / total


# --------------------------------------------------- verifier stress test


STRESS_UNGROUNDED_TEXT = (
    "Symptoms have fully resolved since starting amiodarone 200 mg twice daily last month."
)


def _first_sentence(note: str, section: str = "Subjective") -> str:
    span = section_span(note, section)
    text = note[span[0] : span[1]].strip() if span else note.strip()
    m = re.search(r"[^.?!]*[.?!]", text)
    return (m.group(0) if m else text[:200]).strip()


def build_stress_jobs(eligible: list[dict]) -> dict:
    """~10 deliberately bad patches, built deterministically — the verifier
    must reject each. Kinds: ungrounded (invented claim), redundant (restates
    the note's own first Subjective sentence, with evidence supplied so ONLY
    redundancy is wrong), misplaced (real fact, wrong section)."""
    items = sorted(eligible, key=lambda x: x["note_version_id"])
    jobs: dict[str, dict] = {}
    for item in items[:4]:
        nvid, note, fact = item["note_version_id"], item["note_text"], item["fact"]
        evidence = evidence_for(fact, item["encounter_fhir"])
        jobs[f"ungrounded__{nvid}"] = {
            "id": f"ungrounded__{nvid}",
            "kind": "ungrounded",
            "target_field": "grounded",
            "note": note,
            "evidence": evidence,
            "patch": {
                "flag_id": "stress_ungrounded",
                "section": "Subjective",
                "insert_text": STRESS_UNGROUNDED_TEXT,
                "mode": "append",
                "added_claims": [
                    "Patient started amiodarone 200 mg twice daily last month",
                    "Symptoms have fully resolved",
                ],
            },
        }
        sent = _first_sentence(note)
        jobs[f"redundant__{nvid}"] = {
            "id": f"redundant__{nvid}",
            "kind": "redundant",
            "target_field": "non_redundant",
            "note": note,
            "evidence": f'transcript span: "{sent}"',  # grounded on purpose
            "patch": {
                "flag_id": "stress_redundant",
                "section": "Subjective",
                "insert_text": sent,
                "mode": "append",
                "added_claims": [sent],
            },
        }
    for item in items[:2]:
        nvid, note, fact = item["note_version_id"], item["note_text"], item["fact"]
        wrong = "Objective" if fact.get("type") != "observation" else "Subjective"
        jobs[f"misplaced__{nvid}"] = {
            "id": f"misplaced__{nvid}",
            "kind": "misplaced",
            "target_field": "correctly_placed",
            "note": note,
            "evidence": evidence_for(fact, item["encounter_fhir"]),
            "patch": {
                "flag_id": "stress_misplaced",
                "section": wrong,
                "insert_text": fact["text"],
                "mode": "append",
                "added_claims": [fact["text"]],
            },
        }
    return jobs


def run_stress_job(job: dict) -> dict:
    v = _cached(
        C4 / "stress" / f"{job['id']}.json",
        lambda: verify_patch(job["patch"], job["evidence"], job["note"]),
    )
    return {
        "kind": job["kind"],
        "target_field": job["target_field"],
        "rejected": not v["pass"],
        "field_caught": v.get(job["target_field"]) is False,
        "verify": v,
    }


# ---------------------------------------------------------------- report


def _section_tail(note: str, section: str, chars: int = 260) -> str:
    span = section_span(note, section)
    if span is None:
        return ""
    text = note[span[0] : span[1]].strip()
    return ("…" if len(text) > chars else "") + text[-chars:]


def _showcase(title: str, r: dict) -> list[str]:
    lines = [f"#### {title} — `{r['note_version_id']}` ({r['severity']})", ""]
    lines.append(f"- Missing fact: “{r['fact_text']}”")
    p = r["patch"]
    lines.append(
        f"- Patch → **{p['section']}** ({p['mode']}), iterations {r['iterations']}, "
        f"fact_restored: {'✅' if r['fact_restored'] else '❌'}"
        + (", **unpatchable**" if r["unpatchable"] else "")
    )
    if r["unpatchable"]:
        lines.append("- Surfaced WITHOUT diff — last rejection reasons:")
        for reason in r["history"][-1]["verify"]["reasons"][:4]:
            lines.append(f"  - {reason}")
        lines.append(f"- Last proposed insert (rejected): “{p['insert_text']}”")
        lines.append("")
        return lines
    if r["iterations"] > 1:
        lines.append("- First-round rejection reasons (fixed by the loop):")
        for reason in r["history"][0]["verify"]["reasons"][:4]:
            lines.append(f"  - {reason}")
    lines.append("")
    lines.append("Diff (degraded → patched):")
    lines.append("")
    lines.append("```diff")
    diff = difflib.unified_diff(
        r["note_before"].splitlines(),
        r["note_after"].splitlines(),
        lineterm="",
        n=0,
    )
    for dl in list(diff)[2:]:  # skip ---/+++ header
        lines.append(dl if len(dl) <= 400 else dl[:400] + " …")
    lines.append("```")
    lines.append("")
    lines.append(f"Section tail after patch: > {_section_tail(r['note_after'], p['section'])}")
    lines.append("")
    return lines


def write_report(results: list[dict], skipped: dict, stress: list[dict]) -> None:
    patched = [r for r in results if r["patched"]]
    restored = [r for r in patched if r["fact_restored"]]
    unpatchable = [r for r in results if r["unpatchable"]]

    by_sev: dict[str, dict] = {}
    for r in patched:
        d = by_sev.setdefault(r["severity"], {"restored": 0, "patched": 0})
        d["patched"] += 1
        if r["fact_restored"]:
            d["restored"] += 1

    success = len(restored) / len(patched) if patched else 0.0
    faithful = [r for r in patched if r["posthoc_grounded"] is not None]
    faithfulness = (
        sum(1 for r in faithful if r["posthoc_grounded"]) / len(faithful) if faithful else None
    )
    deltas = [r["redundancy_delta"] for r in patched if r["redundancy_delta"] is not None]
    mean_delta = statistics.mean(deltas) if deltas else None
    mean_iters = statistics.mean(r["iterations"] for r in results) if results else 0.0
    iter_hist = Counter(r["iterations"] for r in results)

    n_stress = len(stress)
    stress_rejected = sum(1 for s in stress if s["rejected"])
    stress_field = sum(1 for s in stress if s["field_caught"])
    stress_by_kind: dict[str, list[dict]] = {}
    for s in stress:
        stress_by_kind.setdefault(s["kind"], []).append(s)

    lines = ["# Checkpoint 4 — Patch + independent verifier loop", ""]
    verdict = (
        "patches close the gap without unsupported claims or bloat"
        if patched
        and success >= 0.8
        and (faithfulness is None or faithfulness >= 0.9)
        and (mean_delta is None or mean_delta < 0.02)
        else "patching needs attention before building further rungs"
    )
    lines.append(
        f"**Top line:** {len(restored)}/{len(patched)} accepted patches restored the missing fact "
        f"({success:.0%}); post-hoc grounding "
        f"{f'{faithfulness:.0%}' if faithfulness is not None else '—'}; "
        f"mean redundancy Δ {f'{mean_delta:+.4f}' if mean_delta is not None else '—'} "
        f"(repeated {NGRAM_N}-gram rate); verifier stress test rejected "
        f"{stress_rejected}/{n_stress} bad patches — {verdict}."
    )
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(
        f"| Eligible degraded notes (omission caught AND surfaced) | {len(results)} "
        f"(skipped: {skipped['not_detected']} not detected, {skipped['not_surfaced']} not surfaced) |"
    )
    lines.append(
        f"| Patched (verifier accepted within {MAX_ITERATIONS} iterations) | "
        f"{len(patched)}/{len(results)} |"
    )
    lines.append(
        f"| Unpatchable rate | {len(unpatchable)}/{len(results)}"
        + (f" = {len(unpatchable)/len(results):.1%}" if results else "")
        + " |"
    )
    lines.append(
        f"| **Patch success (fact restored ÷ patched) — HEADLINE** | "
        f"**{len(restored)}/{len(patched)} = {success:.1%}** |"
    )
    for sev in ("safety_critical", "major", "minor"):
        if sev in by_sev:
            d = by_sev[sev]
            lines.append(
                f"| Patch success — {sev} | {d['restored']}/{d['patched']} = "
                f"{d['restored']/d['patched']:.1%} |"
            )
    lines.append(
        f"| Patch faithfulness (fresh post-hoc `grounded`) | "
        + (
            f"{sum(1 for r in faithful if r['posthoc_grounded'])}/{len(faithful)} = {faithfulness:.1%}"
            if faithfulness is not None
            else "—"
        )
        + " |"
    )
    if deltas:
        lines.append(
            f"| Redundancy Δ (repeated {NGRAM_N}-gram rate, after − before) | "
            f"mean {mean_delta:+.4f} · max {max(deltas):+.4f} |"
        )
    lines.append(
        f"| Loop stats | mean iterations {mean_iters:.2f} · "
        f"hist {dict(sorted(iter_hist.items()))} · unpatchable {len(unpatchable)} |"
    )
    lines.append(
        f"| Verifier efficacy (stress test) | rejected {stress_rejected}/{n_stress}; "
        f"correct field caught it {stress_field}/{n_stress} |"
    )
    lines.append("")

    lines.append("## Verifier stress test detail")
    lines.append("")
    lines.append("| Kind | Rejected | Target field caught |")
    lines.append("|---|---|---|")
    for kind, ss in sorted(stress_by_kind.items()):
        lines.append(
            f"| {kind} | {sum(1 for s in ss if s['rejected'])}/{len(ss)} | "
            f"{sum(1 for s in ss if s['field_caught'])}/{len(ss)} |"
        )
    lines.append("")

    lines.append("## Before/after diffs (picked from actual results)")
    lines.append("")
    clean = next(
        (r for r in results if r["patched"] and r["iterations"] == 1 and r["fact_restored"]), None
    )
    revised = next(
        (r for r in results if r["patched"] and r["iterations"] > 1 and r["fact_restored"]),
        next((r for r in results if r["patched"] and r["iterations"] > 1), None),
    )
    rejected = next((r for r in results if r["unpatchable"]), None)
    for title, r in (
        ("Clean accept (first-try pass)", clean),
        ("Revised by the loop (rejected → fixed)", revised),
        ("Rejected / unpatchable (surfaced without diff)", rejected),
    ):
        if r is None:
            lines.append(f"#### {title}")
            lines.append("")
            lines.append("_No case of this kind occurred in this run._")
            lines.append("")
        else:
            lines.extend(_showcase(title, r))

    CHECKPOINT_MD.write_text("\n".join(lines))
    print(f"Wrote {CHECKPOINT_MD}")


# ------------------------------------------------------------------ main


def main() -> None:
    # --- Gates: Checkpoints 2 + 3 artifacts must exist before patching.
    assert RECORDS_PATH.exists(), (
        "Checkpoint 2 injections missing — run run_checkpoint2.py first."
    )
    assert FACTS_DIR.is_dir() and EVAL_DIR.is_dir(), (
        "checkpoint2_cache/facts + eval missing — run run_checkpoint2.py first."
    )
    assert C3_CLASSIFY.is_dir(), (
        "checkpoint3_cache/classify missing — run run_checkpoint3.py first."
    )
    injection_ids = [
        json.loads(l)["injection_id"] for l in RECORDS_PATH.read_text().splitlines() if l
    ]
    missing = [i for i in injection_ids if not (C3_CLASSIFY / f"{i}.json").exists()]
    assert not missing, (
        f"Checkpoint 3 classify cache incomplete ({len(missing)} missing, e.g. {missing[:3]}) — "
        "finish run_checkpoint3.py first."
    )

    eligible, skipped = load_eligible()
    print(
        f"{len(eligible)} eligible degraded notes (caught AND surfaced); "
        f"skipped {skipped['not_detected']} not-detected, {skipped['not_surfaced']} not-surfaced"
    )

    # Sort by note so same-note items run close together — their patch/verify
    # prompts share a cached rules+NOTE prefix (5-min TTL).
    print("Phase 1: patch → verify loop + apply + restore-check…")
    ordered = sorted(eligible, key=lambda x: (x["note_id"], x["note_version_id"]))
    results = run_pool({v["note_version_id"]: v for v in ordered}, run_item, "patch")

    print("Phase 2: verifier stress test…")
    stress_jobs = build_stress_jobs(eligible)
    stress = run_pool(stress_jobs, run_stress_job, "stress")

    write_report(
        [results[k] for k in sorted(results)], skipped, [stress[k] for k in sorted(stress)]
    )
    from recall.llm import usage_summary

    print("API usage:", usage_summary())


if __name__ == "__main__":
    main()
