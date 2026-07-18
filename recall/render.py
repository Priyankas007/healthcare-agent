"""render — the relevance-filtered clinician surface (Checkpoint 3).

Filter: expected=true AND severity in {safety_critical, major} are surfaced;
minor flags are logged quietly (kept in the result, not surfaced by default).
Sort: severity rank; tie-break by fact-type priority then fact id, stable.
NO count truncation — flag volume is an output we measure, not a limit we
impose (≤3-flag cap dropped 2026-07-18).

Note: presence emits no numeric confidence, so the spec's "tie-break by
presence confidence" is approximated with fact-type priority (medication/
observation first) until a confidence signal exists.
"""

from __future__ import annotations

SEVERITY_RANK = {"safety_critical": 0, "major": 1, "minor": 2}
TYPE_PRIORITY = {"medication": 0, "observation": 1, "red_flag_screen": 2, "order": 3, "referral": 4}


def render(scored_flags: list[dict]) -> dict:
    """scored_flags: [{fact, classify_result}] for each absent fact.

    Returns {"surfaced": [flag...], "logged_minor": [...], "suppressed": [...]}
    where each flag = {fact_id, text, type, severity, why_it_matters,
    transcript_quote, fhir_ref}.
    """
    surfaced, logged_minor, suppressed = [], [], []
    for item in scored_flags:
        fact, cls = item["fact"], item["classify_result"]
        flag = {
            "fact_id": fact["id"],
            "text": fact["text"],
            "type": fact.get("type", "other"),
            "severity": cls["severity"],
            "why_it_matters": cls["why_it_matters"],
            "transcript_quote": fact.get("transcript_quote"),
            "fhir_ref": fact.get("fhir_ref"),
        }
        if not cls["expected"]:
            suppressed.append(flag)
        elif cls["severity"] == "minor":
            logged_minor.append(flag)
        else:
            surfaced.append(flag)

    surfaced.sort(
        key=lambda f: (
            SEVERITY_RANK[f["severity"]],
            TYPE_PRIORITY.get(f["type"], 5),
            f["fact_id"],
        )
    )
    return {"surfaced": surfaced, "logged_minor": logged_minor, "suppressed": suppressed}


def render_markdown(note_title: str, rendered: dict) -> str:
    """Human-readable surface preview for checkpoint_3.md demo sections."""
    lines = [f"#### Pre-signature flags — {note_title}", ""]
    if not rendered["surfaced"]:
        lines.append("_No safety-critical or major omissions flagged._")
    for i, f in enumerate(rendered["surfaced"], 1):
        icon = "🔴" if f["severity"] == "safety_critical" else "🟠"
        lines.append(f"{i}. {icon} **[{f['severity'].upper()}] {f['text']}**")
        lines.append(f"   - _Why it matters:_ {f['why_it_matters']}")
        if f["transcript_quote"]:
            lines.append(f"   - _Transcript:_ “{f['transcript_quote']}”")
        if f["fhir_ref"]:
            lines.append(f"   - _FHIR:_ `{f['fhir_ref']}`")
    if rendered["logged_minor"]:
        lines.append("")
        lines.append(
            f"<sub>{len(rendered['logged_minor'])} minor flag(s) logged, not surfaced: "
            + "; ".join(f["text"][:60] for f in rendered["logged_minor"])
            + "</sub>"
        )
    return "\n".join(lines)
