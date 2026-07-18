"""Checkpoint 1 — detection core on 3 hero cases: extract_facts -> presence.

For each hero case: extract CandidateFacts from transcript + encounter FHIR,
then judge presence of each fact against the PROVIDED note (record["note"]).
Writes checkpoint_1.md with a human-reviewable table per note (AGREE? left
blank for the clinician) and raw JSON artifacts for the audit step.

Run:  .venv/bin/python run_checkpoint1.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from recall.extract_facts import extract_facts
from recall.presence import presence

REPO = Path(__file__).resolve().parent
DATA_PATH = Path(
    os.environ.get(
        "DATA_PATH", REPO / "synthetic-ambient-fhir-25" / "synthetic-ambient-fhir-25.jsonl"
    )
)
CHECKPOINT_MD = REPO / "checkpoint_1.md"
ARTIFACTS_DIR = REPO / "checkpoint1_artifacts"


def load_records() -> dict[str, dict]:
    with open(DATA_PATH) as f:
        return {r["id"]: r for r in (json.loads(line) for line in f if line.strip())}


def md_cell(value: object, limit: int = 160) -> str:
    """Escape a value for a markdown table cell."""
    if value is None:
        return "—"
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def run_case(record: dict) -> dict:
    rid = record["id"]
    artifact = ARTIFACTS_DIR / f"{rid}.json"
    if artifact.exists():  # resume: don't re-spend completed LLM calls
        print(f"[{rid}] using cached artifact")
        cached = json.loads(artifact.read_text())
        return {"record": record, "facts": cached["facts"], "presence": cached["presence"]}
    print(f"[{rid}] extracting facts…")
    facts = extract_facts(record["transcript"], record["encounter_fhir"])
    print(f"[{rid}] {len(facts)} facts; judging presence vs provided note…")
    results = presence(record["note"], facts)
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    artifact.write_text(json.dumps({"facts": facts, "presence": results}, indent=1))
    return {"record": record, "facts": facts, "presence": results}


def write_checkpoint_md(cases: list[dict]) -> None:
    lines: list[str] = []
    lines.append("# Checkpoint 1 — extract_facts + presence (3 hero cases, vs provided note)")
    lines.append("")
    lines.append(
        "**Takeaway:** _[fill after review]_ — do the extracted facts and present/partial/absent "
        "calls match clinical judgment? yes/no + what to fix."
    )
    lines.append("")
    lines.append(
        "_Presence is judged against the **provided** note (`record[\"note\"]`), which was "
        "co-generated with the transcript — so most facts should be `present`; `absent` calls "
        "deserve extra scrutiny (real gap vs. judge error). Quality gate is the multi-agent "
        "audit (clinician review skipped for time)._"
    )
    lines.append("")

    for case in cases:
        rec = case["record"]
        by_id = {r["fact_id"]: r for r in case["presence"]}
        counts = {"present": 0, "partial": 0, "absent": 0}
        for r in case["presence"]:
            counts[r["status"]] += 1
        lines.append(f"## {rec['metadata']['visit_title']}")
        lines.append(f"`{rec['id']}`")
        lines.append("")
        lines.append(
            f"{len(case['facts'])} facts — {counts['present']} present · "
            f"{counts['partial']} partial · {counts['absent']} absent"
        )
        lines.append("")
        lines.append("| # | fact.text | type | source | status | note_evidence |")
        lines.append("|---|---|---|---|---|---|")
        for f in case["facts"]:
            r = by_id[f["id"]]
            status = r["status"]
            marker = {"present": "present", "partial": "**partial**", "absent": "**ABSENT**"}[status]
            lines.append(
                f"| {f['id']} | {md_cell(f['text'])} | {f.get('type', '?')} | {f.get('source', '?')} "
                f"| {marker} | {md_cell(r.get('note_evidence'))} |"
            )
        lines.append("")
        lines.append("### Issues observed")
        lines.append("")
        lines.append("- Granularity too fine/coarse: _[fill]_")
        lines.append("- Invented facts (unsupported by transcript or FHIR): _[fill]_")
        lines.append("- Present-vs-absent mis-calls: _[fill]_")
        lines.append("- Other notes: _[fill]_")
        lines.append("")

    CHECKPOINT_MD.write_text("\n".join(lines))
    print(f"Wrote {CHECKPOINT_MD}")


def main() -> None:
    records = load_records()
    hero_ids = json.loads((REPO / "hero_cases.json").read_text())
    cases = [run_case(records[rid]) for rid in hero_ids]
    write_checkpoint_md(cases)


if __name__ == "__main__":
    main()
