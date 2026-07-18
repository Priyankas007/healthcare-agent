"""eval_runner — detection-only eval over injected + clean note sets.

The detector at this stage = extract_facts (cached per encounter) + presence.

EvalResult = {
  "note_version_id": "<id>__inj_<k>" | "<id>__clean",
  "injected_fact_id": "..." | null,
  "detected_absent_fact_ids": [...],
  "caught": true|false|null,          # null for clean notes
  "collateral_flips": [...],          # facts present on provided note but absent here (excl. injected)
}
"""

from __future__ import annotations

from .presence import presence


def eval_injected(
    degraded_note: str,
    facts: list[dict],
    injection_record: dict,
    provided_presence: list[dict],
) -> dict:
    results = presence(degraded_note, facts)
    detected_absent = [r["fact_id"] for r in results if r["status"] == "absent"]
    injected_id = injection_record["fact"]["id"]
    present_on_provided = {r["fact_id"] for r in provided_presence if r["status"] == "present"}
    collateral = [
        fid for fid in detected_absent if fid != injected_id and fid in present_on_provided
    ]
    return {
        "note_version_id": injection_record["injection_id"],
        "injected_fact_id": injected_id,
        "detected_absent_fact_ids": detected_absent,
        "caught": injected_id in detected_absent,
        "collateral_flips": collateral,
        "n_present_on_provided": len(present_on_provided),
        "presence_results": results,
    }


def eval_clean(note_id: str, provided_presence: list[dict]) -> dict:
    """Clean-set eval reuses the cached presence run on the provided note."""
    detected_absent = [r["fact_id"] for r in provided_presence if r["status"] == "absent"]
    return {
        "note_version_id": f"{note_id}__clean",
        "injected_fact_id": None,
        "detected_absent_fact_ids": detected_absent,
        "caught": None,
        "collateral_flips": [],
        "n_present_on_provided": sum(1 for r in provided_presence if r["status"] == "present"),
        "presence_results": provided_presence,
    }
