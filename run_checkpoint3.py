"""Checkpoint 3 — severity classification + relevance-filtered surface.

Reuses Checkpoint 2's FIXED answer key and caches (no new injections, no new
presence calls): absent facts per note version come from checkpoint2_cache/eval
and checkpoint2_cache/presence_provided. Adds one batched classify call per
note version that has absent facts, then pure-Python render + metrics.

Run:  .venv/bin/python run_checkpoint3.py [--workers N] [--model MODEL]
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path

from recall.classify import classify
from recall.render import render, render_markdown

REPO = Path(__file__).resolve().parent
DATA_PATH = Path(
    os.environ.get(
        "DATA_PATH", REPO / "synthetic-ambient-fhir-25" / "synthetic-ambient-fhir-25.jsonl"
    )
)
C2 = REPO / "checkpoint2_cache"
FACTS_DIR, EVAL_DIR, PRESENCE_DIR = C2 / "facts", C2 / "eval", C2 / "presence_provided"
INJ_DIR = REPO / "injections"
RECORDS_PATH = INJ_DIR / "records.jsonl"
C3 = REPO / "checkpoint3_cache"
CHECKPOINT_MD = REPO / "checkpoint_3.md"

WORKERS = int(next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--workers"), 5))
CLASSIFY_MODEL = next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--model"), None)

SURFACED_SEVERITIES = ("safety_critical", "major")


def load_note_versions() -> list[dict]:
    """Every note version to run through classify → render.

    Injected versions: absent facts from checkpoint2_cache/eval/{injection_id}.json.
    Clean versions:    absent facts from checkpoint2_cache/presence_provided/{id}.json.
    """
    records = {json.loads(l)["id"]: json.loads(l) for l in open(DATA_PATH) if l.strip()}
    injection_records = [json.loads(l) for l in RECORDS_PATH.read_text().splitlines() if l]
    versions = []
    for rec in injection_records:
        rid, injection_id = rec["note_id"], rec["injection_id"]
        ev = json.loads((EVAL_DIR / f"{injection_id}.json").read_text())
        versions.append(
            {
                "note_version_id": injection_id,
                "note_id": rid,
                "note_text": (INJ_DIR / f"{injection_id}.md").read_text(),
                "injected_fact_id": rec["fact"]["id"],
                "injected_severity": rec["severity"],
                "detected_absent_fact_ids": ev["detected_absent_fact_ids"],
            }
        )
    for rid in records:
        prov = json.loads((PRESENCE_DIR / f"{rid}.json").read_text())
        versions.append(
            {
                "note_version_id": f"{rid}__clean",
                "note_id": rid,
                "note_text": records[rid]["note"],
                "injected_fact_id": None,
                "injected_severity": None,
                "detected_absent_fact_ids": [
                    r["fact_id"] for r in prov if r["status"] == "absent"
                ],
            }
        )
    return versions


def run_version(v: dict, facts_by_note: dict) -> dict:
    """classify absent facts (cached) → render → Checkpoint3Result."""
    facts = {f["id"]: f for f in facts_by_note[v["note_id"]]}
    absent = [facts[fid] for fid in v["detected_absent_fact_ids"] if fid in facts]

    cache_path = C3 / "classify" / f"{v['note_version_id']}.json"
    if cache_path.exists():
        cls_results = json.loads(cache_path.read_text())
    else:
        cls_results = classify(absent, v["note_text"], model=CLASSIFY_MODEL)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cls_results, indent=1))

    scored = [
        {"fact": facts[c["fact_id"]], "classify_result": c}
        for c in cls_results
        if c["fact_id"] in facts
    ]
    rendered = render(scored)
    surfaced_ids = [f["fact_id"] for f in rendered["surfaced"]]

    inj = v["injected_fact_id"]
    cls_by_id = {c["fact_id"]: c for c in cls_results}
    suppressed_by_expected_false = bool(
        inj and inj in cls_by_id and not cls_by_id[inj]["expected"]
    )
    return {
        "note_version_id": v["note_version_id"],
        "injected_fact_id": inj,
        "injected_severity": v["injected_severity"],
        "detected_absent_fact_ids": v["detected_absent_fact_ids"],
        "surfaced_flag_fact_ids": surfaced_ids,
        "caught": (inj in surfaced_ids) if inj else None,
        "suppressed_by_expected_false": suppressed_by_expected_false,
        "surfaced_flag_count": len(surfaced_ids),
        "classifier_severity_of_injected": cls_by_id.get(inj, {}).get("severity") if inj else None,
        "rendered": rendered,
    }


def main() -> None:
    # --- Gate: read Checkpoint 2 before ranking a leaky list.
    assert RECORDS_PATH.exists(), (
        "Checkpoint 2 has not produced injections yet — run run_checkpoint2.py first, "
        "then READ checkpoint_2.md (miss rate + clean-note flag rate) before this."
    )
    from concurrent.futures import ThreadPoolExecutor, as_completed

    versions = load_note_versions()
    facts_by_note = {
        p.stem: json.loads(p.read_text()) for p in FACTS_DIR.glob("*.json")
    }
    print(f"{len(versions)} note versions (injected + clean); classify model: {CLASSIFY_MODEL or 'default'}")

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {
            pool.submit(run_version, v, facts_by_note): v["note_version_id"] for v in versions
        }
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                results[key] = fut.result()
                print(f"  done {key} ({len(results)}/{len(versions)})")
            except Exception as exc:
                print(f"  FAILED {key}: {exc!r}")

    write_report(list(results.values()))
    from recall.llm import usage_summary
    print("API usage:", usage_summary())


def write_report(results: list[dict]) -> None:
    injected = [r for r in results if r["injected_fact_id"]]
    clean = [r for r in results if not r["injected_fact_id"]]

    # 1. Recall by severity (headline): detected AND surfaced.
    by_sev: dict[str, dict] = {}
    for r in injected:
        d = by_sev.setdefault(r["injected_severity"], {"caught": 0, "total": 0})
        d["total"] += 1
        if r["caught"]:
            d["caught"] += 1
    overall_caught = sum(1 for r in injected if r["caught"])

    # 2. Flags-per-note distribution (injected + clean separately).
    def dist(rs):
        counts = sorted(r["surfaced_flag_count"] for r in rs)
        if not counts:
            return None
        return {
            "min": counts[0],
            "median": statistics.median(counts),
            "max": counts[-1],
            "histogram": {str(c): counts.count(c) for c in sorted(set(counts))},
        }

    inj_dist, clean_dist = dist(injected), dist(clean)
    clean_surfaced_rate = (
        sum(r["surfaced_flag_count"] for r in clean) / len(clean) if clean else None
    )
    clean_raw_rate = (
        sum(len(r["detected_absent_fact_ids"]) for r in clean) / len(clean) if clean else None
    )

    # 5. Severity calibration matrix (injected heuristic vs classifier).
    calib: dict[tuple, int] = {}
    for r in injected:
        key = (r["injected_severity"], r["classifier_severity_of_injected"] or "n/a")
        calib[key] = calib.get(key, 0) + 1

    # Misses shown in full.
    misses = [r for r in injected if not r["caught"]]

    # Suppression spot-check sample.
    suppressed_sample = []
    for r in results:
        for f in r["rendered"]["suppressed"][:1]:
            suppressed_sample.append((r["note_version_id"], f))
        if len(suppressed_sample) >= 6:
            break

    lines = ["# Checkpoint 3 — Severity classification + relevance-filtered surface", ""]
    rec = overall_caught / len(injected) if injected else 0
    lines.append(
        f"**Top line:** {overall_caught}/{len(injected)} injected omissions detected AND surfaced "
        f"({rec:.0%}); clean-note surfaced-flag rate {clean_surfaced_rate:.2f}/note "
        f"(vs {clean_raw_rate:.2f} raw absent-rate in Checkpoint 2 — the relevance filter's effect); "
        f"flags-per-note median {inj_dist['median'] if inj_dist else '—'} (injected set), no cap applied."
    )
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| **Recall (detected AND surfaced), overall** | **{overall_caught}/{len(injected)} = {rec:.1%}** |")
    for sev in ("safety_critical", "major", "minor"):
        if sev in by_sev:
            d = by_sev[sev]
            note = " _(minor injections are logged, not surfaced — low recall here is by design)_" if sev == "minor" else ""
            lines.append(f"| Recall — injected {sev} | {d['caught']}/{d['total']} = {d['caught']/d['total']:.1%}{note} |")
    if inj_dist:
        lines.append(
            f"| Flags/note (injected set) | min {inj_dist['min']} · median {inj_dist['median']} · max {inj_dist['max']} · hist {inj_dist['histogram']} |"
        )
    if clean_dist:
        lines.append(
            f"| Flags/note (clean set) | min {clean_dist['min']} · median {clean_dist['median']} · max {clean_dist['max']} · hist {clean_dist['histogram']} |"
        )
    lines.append(f"| Clean-note surfaced-flag rate | {clean_surfaced_rate:.2f}/note (raw absent-rate was {clean_raw_rate:.2f}) |")
    lines.append("")

    lines.append("## Severity calibration (injected heuristic → classifier)")
    lines.append("")
    lines.append("| Injected (heuristic) | Classifier | n |")
    lines.append("|---|---|---|")
    for (inj_sev, cls_sev), n in sorted(calib.items()):
        lines.append(f"| {inj_sev} | {cls_sev} | {n} |")
    lines.append("")

    lines.append("## Missed injected omissions (shown in full)")
    lines.append("")
    if not misses:
        lines.append("_None — every injected omission was detected and surfaced (or see minor-by-design note above)._")
    for r in misses:
        detected = r["injected_fact_id"] in r["detected_absent_fact_ids"]
        stage = (
            "suppressed by expected=false" if r["suppressed_by_expected_false"]
            else ("classified minor → logged, not surfaced" if detected else "NOT DETECTED by presence")
        )
        lines.append(
            f"- `{r['note_version_id']}` (injected {r['injected_severity']}): **{stage}** — "
            f"classifier said `{r['classifier_severity_of_injected']}`"
        )
    lines.append("")

    lines.append("## Rendered surfaces — hero cases (demo preview)")
    lines.append("")
    hero_ids = json.loads((REPO / "hero_cases.json").read_text())
    shown = 0
    for r in results:
        if shown >= 3:
            break
        if r["injected_fact_id"] and any(r["note_version_id"].startswith(h) for h in hero_ids):
            lines.append(render_markdown(r["note_version_id"], r["rendered"]))
            lines.append("")
            shown += 1

    lines.append("## Suppression spot-check (expected=false drops — verify by hand)")
    lines.append("")
    for nvid, f in suppressed_sample:
        lines.append(f"- `{nvid}`: “{f['text']}” ({f['type']}) — _{f['why_it_matters']}_  → OK to omit? ☐")
    if not suppressed_sample:
        lines.append("_No facts were suppressed by expected=false._")
    lines.append("")

    CHECKPOINT_MD.write_text("\n".join(lines))
    print(f"Wrote {CHECKPOINT_MD}")


if __name__ == "__main__":
    main()
