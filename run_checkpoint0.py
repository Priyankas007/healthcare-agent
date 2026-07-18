"""Checkpoint 0 — data inventory + hero shortlist + 25 baseline note generations.

Outputs:
  - generated_notes/{id}.md  (25 baseline SOAP notes, transcript-only, B0)
  - checkpoint_0.md          (inventory table + hero shortlist + confirmation)

Run:  .venv/bin/python run_checkpoint0.py [--inventory-only]
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parent
DATA_PATH = Path(
    os.environ.get(
        "DATA_PATH", REPO / "synthetic-ambient-fhir-25" / "synthetic-ambient-fhir-25.jsonl"
    )
)
NOTES_DIR = REPO / "generated_notes"
CHECKPOINT_MD = REPO / "checkpoint_0.md"


def load_records() -> list[dict]:
    with open(DATA_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------- inventory

def med_request_label_count(record: dict) -> tuple[int, int]:
    """(total MedicationRequests, those with a resolvable inline drug label)."""
    reqs = record["encounter_fhir"].get("related_resources", {}).get("MedicationRequest", [])
    total = len(reqs)
    labeled = 0
    for r in reqs:
        mcc = r.get("medicationCodeableConcept", {})
        if mcc.get("text") or any(c.get("display") for c in mcc.get("coding", [])):
            labeled += 1
    return total, labeled


def obs_with_value_count(record: dict) -> tuple[int, int]:
    """(Observations with a value present, those explicitly flagged abnormal)."""
    obs = record["encounter_fhir"].get("related_resources", {}).get("Observation", [])
    with_value = 0
    flagged_abnormal = 0
    for o in obs:
        has_value = any(
            k in o for k in ("valueQuantity", "valueCodeableConcept", "valueString", "component")
        )
        if has_value:
            with_value += 1
        interps = o.get("interpretation") or []
        if isinstance(interps, dict):
            interps = [interps]
        for interp in interps:
            codes = {c.get("code") for c in interp.get("coding", [])}
            if codes - {"N", None}:  # anything besides Normal
                flagged_abnormal += 1
                break
    return with_value, flagged_abnormal


def resource_type_counts(record: dict) -> dict[str, int]:
    related = record["encounter_fhir"].get("related_resources", {})
    return {rtype: len(resources) for rtype, resources in related.items()}


def allergy_count(record: dict) -> int:
    """AllergyIntolerance appears ONLY as a longitudinal count — no usable resources."""
    counts = record.get("patient_context", {}).get("longitudinal_summary", {}).get(
        "resource_counts", {}
    )
    return counts.get("AllergyIntolerance", 0)


def build_inventory(records: list[dict]) -> list[dict]:
    rows = []
    for rec in records:
        total_mr, labeled_mr = med_request_label_count(rec)
        obs_val, obs_flagged = obs_with_value_count(rec)
        rows.append(
            {
                "id": rec["id"],
                "visit_title": rec["metadata"]["visit_title"],
                "transcript_words": len(rec["transcript"].split()),
                "resource_counts": resource_type_counts(rec),
                "medreq_total": total_mr,
                "medreq_labeled": labeled_mr,
                "obs_with_value": obs_val,
                "obs_flagged_abnormal": obs_flagged,
                "allergy_count": allergy_count(rec),
            }
        )
    return rows


def pick_heroes(rows: list[dict], n: int = 3) -> list[dict]:
    """Rank by real ground-truth substrate: labeled MedicationRequests first,
    then Observations with values."""
    ranked = sorted(
        rows, key=lambda r: (r["medreq_labeled"], r["obs_with_value"]), reverse=True
    )
    return ranked[:n]


# ---------------------------------------------------------------- generation

def generate_all_notes(records: list[dict]) -> dict[str, str]:
    """Generate baseline notes for all records (skips ones already on disk)."""
    from recall.generate_note import generate_note

    NOTES_DIR.mkdir(exist_ok=True)
    results: dict[str, str] = {}
    todo = []
    for rec in records:
        out = NOTES_DIR / f"{rec['id']}.md"
        if out.exists() and out.stat().st_size > 0:
            results[rec["id"]] = str(out)
        else:
            todo.append(rec)

    def _one(rec: dict) -> tuple[str, str]:
        note = generate_note(rec["transcript"])
        out = NOTES_DIR / f"{rec['id']}.md"
        out.write_text(note)
        return rec["id"], str(out)

    if todo:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_one, rec): rec["id"] for rec in todo}
            for fut in as_completed(futures):
                rid, path = fut.result()
                results[rid] = path
                print(f"  generated {rid} ({len(results)}/{len(records)})")
    return results


# ---------------------------------------------------------------- report

RTYPE_ORDER = [
    "Condition", "Observation", "Procedure", "DiagnosticReport",
    "MedicationRequest", "Immunization", "ImagingStudy",
]


def write_checkpoint_md(
    rows: list[dict], heroes: list[dict], notes: dict[str, str] | None
) -> None:
    lines: list[str] = []
    total_labeled = sum(r["medreq_labeled"] for r in rows)
    encounters_with_labeled = sum(1 for r in rows if r["medreq_labeled"] > 0)
    total_obs = sum(r["obs_with_value"] for r in rows)

    hero_names = "; ".join(h["visit_title"] for h in heroes)
    lines.append("# Checkpoint 0 — Data inventory & baseline notes")
    lines.append("")
    lines.append(
        f"**Takeaway:** The data supports the plan — Observations with values are the richest "
        f"ground-truth substrate ({total_obs} across 25 encounters) while labeled MedicationRequests "
        f"are sparse ({total_labeled} labeled, in {encounters_with_labeled}/25 encounters), and "
        f"AllergyIntolerance exists only as counts (allergy scenarios must be labeled synthetic "
        f"injections). Demo anchors: {hero_names}."
    )
    lines.append("")

    lines.append("## Inventory (one row per encounter)")
    lines.append("")
    header = (
        "| Visit title | Transcript words | "
        + " | ".join(RTYPE_ORDER)
        + " | MedReq w/ label | Obs w/ value (flagged abn.) | AllergyIntolerance (count only) |"
    )
    lines.append(header)
    lines.append("|" + "---|" * (len(RTYPE_ORDER) + 5))
    for r in rows:
        rc = r["resource_counts"]
        type_cells = " | ".join(str(rc.get(t, 0)) for t in RTYPE_ORDER)
        lines.append(
            f"| {r['visit_title']} | {r['transcript_words']} | {type_cells} "
            f"| {r['medreq_labeled']}/{r['medreq_total']} "
            f"| {r['obs_with_value']} ({r['obs_flagged_abnormal']}) "
            f"| {r['allergy_count']} |"
        )
    lines.append("")
    lines.append(
        "*Notes: `MedReq w/ label` = MedicationRequests with a resolvable inline drug label / total "
        "(reference-based entries have no usable label). `Obs w/ value` counts Observations carrying an "
        "actual value (valueQuantity/CodeableConcept/String/components); the dataset rarely sets "
        "`interpretation`, so flagged-abnormal is shown in parentheses where present. "
        "**AllergyIntolerance is a longitudinal count only — the dataset contains no usable allergy "
        "resources (no substance/code); allergy scenarios require labeled synthetic injection.***"
    )
    lines.append("")

    lines.append("## Hero-case shortlist")
    lines.append("")
    for i, h in enumerate(heroes, 1):
        lines.append(
            f"{i}. **{h['visit_title']}** (`{h['id']}`) — "
            f"{h['medreq_labeled']} labeled MedicationRequests, "
            f"{h['obs_with_value']} Observations with values. "
        )
    lines.append("")
    lines.append(
        "*Why: ranked by labeled MedicationRequests (the highest-value, scarcest injection substrate "
        "— med/dose omissions are the top severe-error category), then by Observations with values "
        "(the most abundant substrate for actionable-result omissions). These encounters give the "
        "injection harness the most real, structured ground truth to delete from and verify against.*"
    )
    lines.append("")

    lines.append("## Baseline note generation (B0)")
    lines.append("")
    if notes is None:
        lines.append(
            "**NOT YET RUN** — inventory-only mode (no API key at time of writing). "
            "Re-run `run_checkpoint0.py` without `--inventory-only` to generate."
        )
    else:
        lines.append(
            f"**{len(notes)}/25 baseline notes generated** from transcripts only "
            f"(model: Opus 4.8, adaptive thinking) and saved to `generated_notes/{{id}}.md`. "
            "The provided `note` field was not used or modified — it remains the gold reference "
            "for the later injection harness."
        )
    lines.append("")
    CHECKPOINT_MD.write_text("\n".join(lines))
    print(f"Wrote {CHECKPOINT_MD}")


def main() -> None:
    inventory_only = "--inventory-only" in sys.argv
    records = load_records()
    assert len(records) == 25, f"Expected 25 records, got {len(records)}"
    rows = build_inventory(records)
    heroes = pick_heroes(rows)
    notes = None
    if not inventory_only:
        notes = generate_all_notes(records)
        missing = [r["id"] for r in records if r["id"] not in notes]
        assert not missing, f"Missing generated notes for: {missing}"
    write_checkpoint_md(rows, heroes, notes)
    # Persist hero ids for checkpoint 1.
    (REPO / "hero_cases.json").write_text(json.dumps([h["id"] for h in heroes], indent=1))
    print("Hero cases:", [h["visit_title"] for h in heroes])


if __name__ == "__main__":
    main()
