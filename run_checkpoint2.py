"""Checkpoint 2 — injection harness + detection-only eval + first numbers.

Phases (all cached/resumable; only presence re-runs per note version):
  1. extract_facts once per encounter        -> checkpoint2_cache/facts/{id}.json
  2. presence on each provided note          -> checkpoint2_cache/presence_provided/{id}.json
  3. harness_inject (~3 targets/encounter)   -> injections/{injection_id}.md + records.jsonl
  4. eval injected (full presence/degraded)  -> checkpoint2_cache/eval/{injection_id}.json
     eval clean (reuses phase-2 cache)
  5. metrics + checkpoint_2.md
  6. optional --benchmark: presence-judge model comparison on labeled pairs

Run:  .venv/bin/python run_checkpoint2.py [--benchmark] [--workers N]
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from recall.eval_runner import eval_clean, eval_injected
from recall.extract_facts import extract_facts
from recall.harness_inject import inject_one, select_targets
from recall.metrics import compute_metrics
from recall.presence import presence

REPO = Path(__file__).resolve().parent
DATA_PATH = Path(
    os.environ.get(
        "DATA_PATH", REPO / "synthetic-ambient-fhir-25" / "synthetic-ambient-fhir-25.jsonl"
    )
)
CACHE = REPO / "checkpoint2_cache"
FACTS_DIR = CACHE / "facts"
PRESENCE_DIR = CACHE / "presence_provided"
EVAL_DIR = CACHE / "eval"
INJ_DIR = REPO / "injections"
RECORDS_PATH = INJ_DIR / "records.jsonl"
DISCARDED_PATH = INJ_DIR / "discarded.jsonl"
EVAL_RESULTS_PATH = REPO / "eval_results.jsonl"
CHECKPOINT_MD = REPO / "checkpoint_2.md"

WORKERS = int(next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--workers"), 5))
TARGETS_PER_NOTE = 3


def load_records() -> list[dict]:
    with open(DATA_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def _cached(path: Path, compute):
    if path.exists():
        return json.loads(path.read_text())
    value = compute()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1))
    return value


def run_pool(items, fn, label: str) -> dict:
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


def main() -> None:
    records = {r["id"]: r for r in load_records()}

    # Phase 1+2 — facts + presence(provided) per encounter, cached.
    print("Phase 1/2: extract_facts + presence(provided) per encounter…")

    def facts_and_presence(rec: dict) -> dict:
        rid = rec["id"]
        facts = _cached(
            FACTS_DIR / f"{rid}.json",
            lambda: extract_facts(rec["transcript"], rec["encounter_fhir"]),
        )
        prov = _cached(
            PRESENCE_DIR / f"{rid}.json", lambda: presence(rec["note"], facts)
        )
        return {"facts": facts, "presence_provided": prov}

    base = run_pool(records, facts_and_presence, "base")

    # Phase 3 — injections.
    print("Phase 3: harness_inject…")
    INJ_DIR.mkdir(exist_ok=True)
    existing_records = []
    if RECORDS_PATH.exists():
        existing_records = [json.loads(l) for l in RECORDS_PATH.read_text().splitlines() if l]
    done_ids = {r["injection_id"] for r in existing_records}

    inject_jobs = {}
    for rid, b in base.items():
        targets = select_targets(b["facts"], b["presence_provided"], k=TARGETS_PER_NOTE)
        for k, fact in enumerate(targets):
            injection_id = f"{rid}__inj_{k}"
            if injection_id not in done_ids:
                inject_jobs[injection_id] = (rid, fact, k)

    def do_inject(job):
        rid, fact, k = job
        result, discarded = inject_one(records[rid]["note"], fact, rid, k)
        if result:
            (INJ_DIR / f"{result['injection_record']['injection_id']}.md").write_text(
                result["degraded_note"]
            )
            with open(RECORDS_PATH, "a") as f:
                f.write(json.dumps(result["injection_record"]) + "\n")
        else:
            with open(DISCARDED_PATH, "a") as f:
                f.write(json.dumps(discarded) + "\n")
        return result is not None

    if inject_jobs:
        run_pool(inject_jobs, do_inject, "inject")

    injection_records = [json.loads(l) for l in RECORDS_PATH.read_text().splitlines() if l]
    discarded = (
        [json.loads(l) for l in DISCARDED_PATH.read_text().splitlines() if l]
        if DISCARDED_PATH.exists()
        else []
    )
    print(f"Injections: {len(injection_records)} confirmed, {len(discarded)} discarded")

    # Phase 4 — eval injected + clean.
    print("Phase 4: detection eval…")

    def do_eval(rec_record: dict) -> dict:
        rid = rec_record["note_id"]
        injection_id = rec_record["injection_id"]
        return _cached(
            EVAL_DIR / f"{injection_id}.json",
            lambda: eval_injected(
                (INJ_DIR / f"{injection_id}.md").read_text(),
                base[rid]["facts"],
                rec_record,
                base[rid]["presence_provided"],
            ),
        )

    # Sort by encounter so same-encounter evals run close together — their
    # presence prompts share a cached rules+FACTS prefix (5-min TTL).
    eval_injected_results = run_pool(
        {r["injection_id"]: r for r in sorted(injection_records, key=lambda r: r["note_id"])},
        do_eval,
        "eval",
    )
    eval_clean_results = {
        rid: eval_clean(rid, b["presence_provided"]) for rid, b in base.items()
    }
    all_results = list(eval_injected_results.values()) + list(eval_clean_results.values())
    with open(EVAL_RESULTS_PATH, "w") as f:
        for e in all_results:
            slim = {k: v for k, v in e.items() if k != "presence_results"}
            f.write(json.dumps(slim) + "\n")

    # Phase 5 — metrics + report.
    print("Phase 5: metrics…")
    m = compute_metrics(injection_records, all_results)
    benchmark = run_benchmark(records, base, injection_records) if "--benchmark" in sys.argv else None
    write_checkpoint_md(m, injection_records, discarded, eval_injected_results, eval_clean_results, base, benchmark)
    from recall.llm import usage_summary
    print("API usage:", usage_summary())


# ---------------------------------------------------------------- benchmark

BENCH_MODELS = ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-4-8"]
BENCH_SAMPLE = 25


def run_benchmark(records, base, injection_records) -> dict:
    """Presence-judge model comparison on free labeled pairs:
    each injected fact is present in the original note, absent in its degraded copy."""
    print("Phase 6 (optional): presence-judge model benchmark…")
    sample = injection_records[:BENCH_SAMPLE]
    jobs = {}
    for rec in sample:
        rid, fact = rec["note_id"], rec["fact"]
        degraded_note = (INJ_DIR / f"{rec['injection_id']}.md").read_text()
        for model in BENCH_MODELS:
            jobs[f"{rec['injection_id']}|{model}|present"] = (records[rid]["note"], fact, model, "present")
            jobs[f"{rec['injection_id']}|{model}|absent"] = (degraded_note, fact, model, "absent")

    def do_pair(job):
        note, fact, model, expected = job
        status = presence(note, [fact], model=model)[0]["status"]
        return {"model": model, "expected": expected, "got": status, "correct": status == expected}

    results = run_pool(jobs, do_pair, "bench")
    table: dict[str, dict] = {}
    for r in results.values():
        t = table.setdefault(r["model"], {"present_ok": 0, "present_n": 0, "absent_ok": 0, "absent_n": 0})
        side = r["expected"]
        t[f"{side}_n"] += 1
        if r["correct"]:
            t[f"{side}_ok"] += 1
    return table


# ---------------------------------------------------------------- report

def write_checkpoint_md(m, injection_records, discarded, eval_inj, eval_clean_map, base, benchmark) -> None:
    lines: list[str] = []
    r = m["recall_overall"]
    lines.append("# Checkpoint 2 — Injection harness + first detection numbers")
    lines.append("")
    verdict = (
        "detection works well enough to build on"
        if r is not None and r >= 0.8 and (m["clean_flag_rate_mean"] or 0) < 5
        else "detection needs attention before building further rungs"
    )
    lines.append(
        f"**Top line:** recall {r:.0%} on {m['n_injections']} confirmed single-fact deletions with a "
        f"clean-note flag rate of {m['clean_flag_rate_mean']:.2f} facts/note (upper bound) — {verdict}."
    )
    lines.append("")

    lines.append("## Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| **Recall (primary)** | **{m['n_caught']}/{m['n_injections']} = {r:.1%}** |")
    for sev in ("safety_critical", "major", "minor"):
        if sev in m["recall_by_severity"]:
            d = m["recall_by_severity"][sev]
            lines.append(f"| Recall — {sev} | {d['caught']}/{d['total']} = {d['recall']:.1%} |")
    for typ, d in sorted(m["recall_by_type"].items()):
        lines.append(f"| Recall — type: {typ} | {d['caught']}/{d['total']} = {d['recall']:.1%} |")
    lines.append(
        f"| Clean-note flag rate (**FP upper bound**) | {m['clean_flag_rate_mean']:.2f} facts/note "
        f"across {m['n_clean_notes']} untouched notes |"
    )
    lines.append(
        f"| Injection specificity (collateral present→absent flips) | {m['collateral_flips_total']} flips "
        f"/ {m['degraded_notes_with_flips']} of {m['n_injections']} degraded notes affected "
        f"(rate {m['collateral_flip_rate']:.2%}) |"
    )
    lines.append("")
    lines.append(
        "_The clean-note flag rate is explicitly an **upper bound** on false positives: some flags are "
        "genuine natural omissions in the provided notes, not judge errors. A physician pass converts "
        "this to a true estimate later._"
    )
    lines.append("")

    lines.append("## Injection counts")
    lines.append("")
    attempted = len(injection_records) + len(discarded)
    lines.append(f"- Attempted: {attempted}  ·  Confirmed absent: {len(injection_records)}  ·  Discarded: {len(discarded)}")
    if discarded:
        from collections import Counter
        for reason, n in Counter(d["reason"] for d in discarded).most_common():
            lines.append(f"  - discarded ({n}×): {reason}")
    per_note = {}
    for rec in injection_records:
        per_note[rec["note_id"]] = per_note.get(rec["note_id"], 0) + 1
    lines.append(
        f"- Coverage: {len(per_note)}/25 encounters have ≥1 injection "
        f"(mean {len(injection_records) / max(len(per_note), 1):.1f}/covered note; target was ≤3)."
    )
    lines.append("")

    # Example cases: ≥1 catch, ≥1 miss (if any), ≥1 clean-note flag.
    lines.append("## Example cases")
    lines.append("")
    ex: list[str] = []
    catches = [e for e in eval_inj.values() if e["caught"]]
    misses = [e for e in eval_inj.values() if not e["caught"]]
    rec_by_id = {r["injection_id"]: r for r in injection_records}

    def fact_line(e):
        rec = rec_by_id[e["note_version_id"]]
        pres = {p["fact_id"]: p for p in e["presence_results"]}
        verdict = pres.get(e["injected_fact_id"], {})
        return rec, verdict

    for e in catches[:2]:
        rec, v = fact_line(e)
        ex.append(
            f"- ✅ **Caught** (`{e['note_version_id']}`, {rec['severity']}/{rec['type']}): deleted "
            f"“{rec['fact']['text']}” → judge: `{v.get('status')}` — “{v.get('rationale', '')}”"
        )
    for e in misses[:2]:
        rec, v = fact_line(e)
        ex.append(
            f"- ❌ **Missed** (`{e['note_version_id']}`, {rec['severity']}/{rec['type']}): deleted "
            f"“{rec['fact']['text']}” → judge said `{v.get('status')}` with evidence "
            f"“{v.get('note_evidence') or '—'}” — “{v.get('rationale', '')}”"
        )
    if not misses:
        ex.append("- ❌ Missed: _none — every confirmed deletion was flagged absent._")
    for rid, e in list(eval_clean_map.items()):
        if e["detected_absent_fact_ids"]:
            facts_by_id = {f["id"]: f for f in base[rid]["facts"]}
            fid = e["detected_absent_fact_ids"][0]
            pres = {p["fact_id"]: p for p in e["presence_results"]}
            ex.append(
                f"- ⚠️ **Clean-note flag** (`{rid}__clean`): “{facts_by_id[fid]['text']}” flagged absent "
                f"on an untouched note — “{pres[fid].get('rationale', '')}” (natural omission or judge error — "
                f"exactly the ambiguity the physician pass resolves)"
            )
            break
    lines.extend(ex)
    lines.append("")

    if benchmark:
        lines.append("## Presence-judge model benchmark (free labels from the harness)")
        lines.append("")
        lines.append("| Model | Accuracy on PRESENT (originals) | Accuracy on ABSENT (degraded) |")
        lines.append("|---|---|---|")
        for model, t in benchmark.items():
            lines.append(
                f"| {model} | {t['present_ok']}/{t['present_n']} | {t['absent_ok']}/{t['absent_n']} |"
            )
        lines.append("")

    lines.append("## Interpretation guardrail")
    lines.append("")
    lines.append(
        "At this stage the detector is just `extract_facts` + `presence`, so recall here is partly a "
        "floor/sanity measure — it mostly confirms the presence judge reliably detects a clean deletion. "
        "Its real power is as a **fixed answer key** for the later ablation comparisons (same injected "
        "set, different rungs → meaningful deltas). The more revealing first signal is the clean-note "
        "flag rate. Don't over-claim from recall alone."
    )
    lines.append("")
    CHECKPOINT_MD.write_text("\n".join(lines))
    print(f"Wrote {CHECKPOINT_MD}")


if __name__ == "__main__":
    main()
