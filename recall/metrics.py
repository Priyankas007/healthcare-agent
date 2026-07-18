"""metrics — recall, clean-note flag rate (FP upper bound), injection specificity."""

from __future__ import annotations

from collections import defaultdict


def compute_metrics(injection_records: list[dict], eval_results: list[dict]) -> dict:
    injected = [e for e in eval_results if e["injected_fact_id"] is not None]
    clean = [e for e in eval_results if e["injected_fact_id"] is None]
    severity_by_injection = {r["injection_id"]: r["severity"] for r in injection_records}
    type_by_injection = {r["injection_id"]: r["type"] for r in injection_records}

    # --- Recall (primary), overall and by severity / type
    caught = [e for e in injected if e["caught"]]
    recall_overall = len(caught) / len(injected) if injected else None

    by_severity: dict[str, dict] = defaultdict(lambda: {"caught": 0, "total": 0})
    by_type: dict[str, dict] = defaultdict(lambda: {"caught": 0, "total": 0})
    for e in injected:
        sev = severity_by_injection.get(e["note_version_id"], "?")
        typ = type_by_injection.get(e["note_version_id"], "?")
        by_severity[sev]["total"] += 1
        by_type[typ]["total"] += 1
        if e["caught"]:
            by_severity[sev]["caught"] += 1
            by_type[typ]["caught"] += 1
    for d in (*by_severity.values(), *by_type.values()):
        d["recall"] = d["caught"] / d["total"] if d["total"] else None

    # --- Clean-note flag rate (FP UPPER BOUND — some flags are genuine
    # natural omissions in the provided notes, not judge errors)
    clean_flags = [len(e["detected_absent_fact_ids"]) for e in clean]
    clean_flag_rate = sum(clean_flags) / len(clean_flags) if clean_flags else None

    # --- Injection specificity: when we delete X, do OTHER present facts stay present?
    total_flips = sum(len(e["collateral_flips"]) for e in injected)
    flip_opportunities = sum(max(e["n_present_on_provided"] - 1, 0) for e in injected)
    flip_rate = total_flips / flip_opportunities if flip_opportunities else None
    notes_with_flips = sum(1 for e in injected if e["collateral_flips"])

    return {
        "n_injections": len(injected),
        "n_caught": len(caught),
        "recall_overall": recall_overall,
        "recall_by_severity": dict(by_severity),
        "recall_by_type": dict(by_type),
        "n_clean_notes": len(clean),
        "clean_flag_counts": clean_flags,
        "clean_flag_rate_mean": clean_flag_rate,
        "collateral_flips_total": total_flips,
        "collateral_flip_rate": flip_rate,
        "degraded_notes_with_flips": notes_with_flips,
    }
