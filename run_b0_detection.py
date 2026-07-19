"""Job 2 — REAL detection: the full detect→classify→render chain on the
GENERATED (B0, transcript-only) notes. No injection — these are omissions the
naive scribe actually made.

Reuses cached facts (note-independent). Adds: presence(generated_note, facts)
and classify(absent) per encounter. Caches under b0_cache/.

Run:  .venv/bin/python run_b0_detection.py [--workers N]
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from recall.classify import classify
from recall.presence import presence
from recall.render import render

REPO = Path(__file__).resolve().parent
DATA_PATH = Path(
    os.environ.get(
        "DATA_PATH", REPO / "synthetic-ambient-fhir-25" / "synthetic-ambient-fhir-25.jsonl"
    )
)
FACTS_DIR = REPO / "checkpoint2_cache" / "facts"
NOTES_DIR = REPO / "generated_notes"
CACHE = REPO / "b0_cache"
OUT_MD = REPO / "b0_detection.md"

WORKERS = int(next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--workers"), 5))


def _cached(path: Path, compute):
    if path.exists():
        return json.loads(path.read_text())
    value = compute()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1))
    return value


def run_encounter(rec: dict) -> dict:
    rid = rec["id"]
    facts = json.loads((FACTS_DIR / f"{rid}.json").read_text())
    facts_by_id = {f["id"]: f for f in facts}
    gen_note = (NOTES_DIR / f"{rid}.md").read_text()

    pres = _cached(CACHE / "presence" / f"{rid}.json", lambda: presence(gen_note, facts))
    absent = [facts_by_id[r["fact_id"]] for r in pres if r["status"] == "absent" and r["fact_id"] in facts_by_id]
    cls = _cached(CACHE / "classify" / f"{rid}.json", lambda: classify(absent, gen_note))
    scored = [{"fact": facts_by_id[c["fact_id"]], "classify_result": c} for c in cls if c["fact_id"] in facts_by_id]
    rendered = render(scored)

    counts = {"present": 0, "partial": 0, "absent": 0}
    for r in pres:
        counts[r["status"]] += 1
    return {
        "id": rid,
        "title": rec["metadata"]["visit_title"],
        "n_facts": len(facts),
        "counts": counts,
        "surfaced": rendered["surfaced"],
        "minor": rendered["logged_minor"],
        "suppressed": rendered["suppressed"],
    }


def main() -> None:
    assert FACTS_DIR.exists() and NOTES_DIR.exists(), "need checkpoint2_cache/facts + generated_notes"
    records = [json.loads(l) for l in open(DATA_PATH) if l.strip()]
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(run_encounter, r): r["id"] for r in records}
        for fut in as_completed(futures):
            rid = futures[fut]
            try:
                results[rid] = fut.result()
                print(f"  done {rid} ({len(results)}/{len(records)})")
            except Exception as exc:
                print(f"  FAILED {rid}: {exc!r}")

    rows = sorted(results.values(), key=lambda r: -len(r["surfaced"]))
    surfaced_counts = [len(r["surfaced"]) for r in rows]
    absent_counts = [r["counts"]["absent"] for r in rows]
    sev = {"safety_critical": 0, "major": 0}
    type_hist: dict[str, int] = {}
    for r in rows:
        for f in r["surfaced"]:
            sev[f["severity"]] = sev.get(f["severity"], 0) + 1
            type_hist[f["type"]] = type_hist.get(f["type"], 0) + 1

    lines = ["# B0 real detection — generated (transcript-only) notes, no injection", ""]
    lines.append(
        f"**Top line:** the naive scribe's own notes miss real content — mean "
        f"{statistics.mean(absent_counts):.1f} absent facts/note, of which "
        f"{statistics.mean(surfaced_counts):.1f}/note survive the relevance filter "
        f"({sev.get('safety_critical', 0)} safety-critical + {sev.get('major', 0)} major across 25 notes). "
        f"These are AUTHENTIC omissions — nothing was planted."
    )
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Notes audited | {len(rows)} generated (B0) notes |")
    lines.append(f"| Absent facts/note | mean {statistics.mean(absent_counts):.1f} · median {statistics.median(absent_counts)} · max {max(absent_counts)} |")
    lines.append(f"| Surfaced flags/note | mean {statistics.mean(surfaced_counts):.1f} · median {statistics.median(surfaced_counts)} · max {max(surfaced_counts)} |")
    lines.append(f"| Surfaced by severity | {sev.get('safety_critical', 0)} safety_critical · {sev.get('major', 0)} major |")
    lines.append(f"| Surfaced by type | " + " · ".join(f"{k} {v}" for k, v in sorted(type_hist.items(), key=lambda x: -x[1])) + " |")
    lines.append("")
    lines.append("## Per-note surfaced flags (worst first)")
    lines.append("")
    for r in rows:
        lines.append(f"### {r['title']} — {len(r['surfaced'])} surfaced ({r['counts']['absent']} absent of {r['n_facts']})")
        for f in r["surfaced"][:4]:
            icon = "🔴" if f["severity"] == "safety_critical" else "🟠"
            lines.append(f"- {icon} **[{f['severity']}]** {f['text']} — _{f['why_it_matters'][:140]}_")
        lines.append("")
    OUT_MD.write_text("\n".join(lines))
    print(f"Wrote {OUT_MD}")
    from recall.llm import usage_summary
    print("API usage:", usage_summary())


if __name__ == "__main__":
    main()
