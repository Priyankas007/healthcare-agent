"""Checkpoint 6 — FHIR write-back STRETCH demo (chart coverage gaps).

Transcript-only facts absent from the structured chart (stated allergies,
uncoded OTC meds, family history, stated measurements) are structured as FHIR
R4 resources and — with MANDATORY per-resource clinician approval — written to
a SANDBOX FHIR server. Before/after chart snapshots go into checkpoint_6.md.

This is a demo, NOT a core eval metric: chart-coverage-gap counts are never
folded into headline recall numbers.

Safety posture (enforced in recall/writeback.py):
- human-in-the-loop approval before ANY write (--approve-all is DEMO ONLY)
- every authored resource: verificationStatus=unconfirmed (or the most
  conservative legal status), provisional codings, provenance note with the
  verbatim transcript quote
- sensitive social/safety disclosures (IPV, substance use, mental health) and
  negative findings are excluded up front, with reasons
- base-URL allowlist: localhost / 127.0.0.1 / hapi.fhir.org only

Prerequisites: checkpoint2_cache/facts + checkpoint2_cache/presence_provided
(run run_checkpoint2.py first) and a reachable sandbox server:
    docker run -p 8080:8080 hapiproject/hapi

Run:  .venv/bin/python run_checkpoint6.py [--base-url URL] [--encounter ID]
          [--max-gaps N] [--workers N] [--approve-all]   (--approve-all: DEMO ONLY)

Resumable: authored resources cache under checkpoint6_cache/authored/, write
receipts under checkpoint6_cache/written/ (a re-run never double-writes),
patient/encounter scaffolds under checkpoint6_cache/patient|encounter/.

Checkpoint6Result (one per selected gap) = {
  "fact_id", "text", "fhir_type", "note_status", "authored", "valid",
  "validation_issues", "approved", "written", "server_id", "error"
}
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from recall.writeback import (
    DEFAULT_BASE_URL,
    author_resource,
    check_base_url,
    count_patient_resources,
    request_approval,
    select_coverage_gaps,
    server_alive,
    validate_resource,
    write_resource,
    _http,
)

REPO = Path(__file__).resolve().parent
DATA_PATH = Path(
    os.environ.get(
        "DATA_PATH", REPO / "synthetic-ambient-fhir-25" / "synthetic-ambient-fhir-25.jsonl"
    )
)
C2 = REPO / "checkpoint2_cache"
FACTS_DIR, PRESENCE_DIR = C2 / "facts", C2 / "presence_provided"
C6 = REPO / "checkpoint6_cache"
CHECKPOINT_MD = REPO / "checkpoint_6.md"

BASE_URL = next(
    (sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--base-url"), DEFAULT_BASE_URL
)
ENCOUNTER_ID = next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--encounter"), None)
MAX_GAPS = int(next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--max-gaps"), 5))
WORKERS = int(next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--workers"), 4))
APPROVE_ALL = "--approve-all" in sys.argv  # DEMO ONLY — bypasses the human gate

DOCKER_HELP = """\
FHIR sandbox unreachable at {base_url}.
Start a local HAPI FHIR server with:
    docker run -p 8080:8080 hapiproject/hapi
(then wait ~1 min for startup), or point at the public test server with:
    --base-url https://hapi.fhir.org/baseR4
Only localhost / 127.0.0.1 / hapi.fhir.org are allowed — this demo never
writes anywhere else."""


def _cached(path: Path, compute):
    if path.exists():
        return json.loads(path.read_text())
    value = compute()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1))
    return value


def load_records() -> list[dict]:
    with open(DATA_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def load_gaps(rid: str) -> tuple[list[dict], list[dict]]:
    facts_path, presence_path = FACTS_DIR / f"{rid}.json", PRESENCE_DIR / f"{rid}.json"
    assert facts_path.exists(), f"{facts_path} missing — run run_checkpoint2.py first."
    assert presence_path.exists(), f"{presence_path} missing — run run_checkpoint2.py first."
    facts = json.loads(facts_path.read_text())
    presence = json.loads(presence_path.read_text())
    return select_coverage_gaps(facts, presence)


def choose_record(records: list[dict]) -> dict:
    """--encounter wins; else the encounter with the most non-Observation gaps
    (allergies/meds/conditions demo best), ties broken by total gaps then
    dataset order. Deterministic."""
    if ENCOUNTER_ID:
        for rec in records:
            if rec["id"] == ENCOUNTER_ID:
                return rec
        sys.exit(f"--encounter {ENCOUNTER_ID!r} not found in {DATA_PATH}")
    best, best_key = None, None
    for i, rec in enumerate(records):
        if not (
            (FACTS_DIR / f"{rec['id']}.json").exists()
            and (PRESENCE_DIR / f"{rec['id']}.json").exists()
        ):
            continue
        gaps, _ = load_gaps(rec["id"])
        key = (
            -sum(1 for g in gaps if g["fhir_type"] != "Observation"),
            -len(gaps),
            i,
        )
        if gaps and (best_key is None or key < best_key):
            best, best_key = rec, key
    if best is None:
        sys.exit("No encounter has any chart coverage gap — nothing to demo.")
    return best


# ---------------------------------------------------------------- scaffold

def ensure_patient(rec: dict) -> str:
    """Create (once, cached) the synthetic demo patient on the sandbox.
    On the public HAPI server the patient gets a uniquely-suffixed family name
    + demo identifier so it can never be confused with anyone real."""
    def create() -> dict:
        patient = {
            k: v for k, v in rec["patient_context"]["patient"].items() if k not in ("id", "meta")
        }
        token = uuid.uuid4().hex[:10]
        if "hapi.fhir.org" in BASE_URL:
            for name in patient.get("name", []):
                name["family"] = f"{name.get('family', 'Synthetic')}-RecallDemo-{token}"
        patient.setdefault("identifier", []).append(
            {"system": "urn:recall-demo", "value": token}
        )
        created, _ = _http("POST", f"{BASE_URL}/Patient", body=patient)
        assert created and created.get("id"), "Patient POST returned no id"
        return created

    created = _cached(C6 / "patient" / f"{rec['id']}.json", create)
    return f"Patient/{created['id']}"


def ensure_encounter(rec: dict, patient_ref: str) -> str | None:
    """Create (once, cached) a minimal Encounter scaffold (status/class/type/
    period + subject only — no practitioner/location refs, so it POSTs cleanly
    under referential-integrity checks). Returns None if creation fails; the
    authored resources then simply omit the encounter reference."""
    def create() -> dict:
        src = rec["encounter_fhir"]["encounter"]
        minimal: dict = {
            "resourceType": "Encounter",
            "status": src.get("status", "finished"),
            "class": src.get(
                "class", {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"}
            ),
            "subject": {"reference": patient_ref},
        }
        if src.get("type"):
            minimal["type"] = src["type"]
        if src.get("period"):
            minimal["period"] = src["period"]
        created, _ = _http("POST", f"{BASE_URL}/Encounter", body=minimal)
        assert created and created.get("id"), "Encounter POST returned no id"
        return created

    try:
        created = _cached(C6 / "encounter" / f"{rec['id']}.json", create)
        return f"Encounter/{created['id']}"
    except Exception as exc:
        print(f"  Encounter scaffold failed ({exc!r}) — authored resources will omit it.")
        return None


# ---------------------------------------------------------------- pipeline

def author_all(rid: str, gaps: list[dict], patient_ref: str, encounter_ref: str | None) -> dict:
    """Author each gap's resource concurrently, per-item cached + isolated."""
    authored: dict[str, dict] = {}
    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {
            pool.submit(
                _cached,
                C6 / "authored" / f"{rid}__{g['fact']['id']}.json",
                lambda g=g: author_resource(g["fact"], patient_ref, encounter_ref, g["fhir_type"]),
            ): g["fact"]["id"]
            for g in gaps
        }
        for fut in as_completed(futures):
            fid = futures[fut]
            try:
                authored[fid] = fut.result()
                print(f"  [author] done {fid} ({len(authored)}/{len(gaps)})")
            except Exception as exc:  # isolate: one failure shouldn't kill the demo
                failures[fid] = repr(exc)
                print(f"  [author] FAILED {fid}: {exc!r}")
    if failures:
        print(f"  [author] {len(failures)} failures (resumable — rerun to retry): {list(failures)}")
    return {"authored": authored, "failures": failures}


def main() -> None:
    # --- Gates: Checkpoint 2 caches must exist; sandbox must be reachable.
    assert FACTS_DIR.exists() and any(FACTS_DIR.glob("*.json")), (
        "checkpoint2_cache/facts is missing — run run_checkpoint2.py first."
    )
    assert PRESENCE_DIR.exists() and any(PRESENCE_DIR.glob("*.json")), (
        "checkpoint2_cache/presence_provided is missing — run run_checkpoint2.py first."
    )
    check_base_url(BASE_URL)  # allowlist before any network traffic
    if not server_alive(BASE_URL):
        sys.exit(DOCKER_HELP.format(base_url=BASE_URL))

    records = load_records()
    rec = choose_record(records)
    rid = rec["id"]
    gaps, skipped = load_gaps(rid)
    demo_gaps = gaps[:MAX_GAPS]
    print(f"Encounter {rid}: {len(gaps)} coverage gaps ({len(skipped)} skipped by safety screens); "
          f"demoing the top {len(demo_gaps)} (--max-gaps {MAX_GAPS}).")
    if APPROVE_ALL:
        print("WARNING: --approve-all is set — the human approval gate is bypassed. DEMO ONLY.")

    # --- Scaffold (patient + minimal encounter). The first write of any kind
    # gets an explicit go-ahead unless --approve-all.
    scaffold_cached = (C6 / "patient" / f"{rid}.json").exists()
    if not scaffold_cached and not APPROVE_ALL:
        answer = input(f"Create a synthetic demo Patient/Encounter on {BASE_URL}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            sys.exit("Aborted before any write — nothing was created.")
    patient_ref = ensure_patient(rec)
    encounter_ref = ensure_encounter(rec, patient_ref)
    print(f"Sandbox scaffold: {patient_ref}, encounter {encounter_ref or '(none)'}")

    before = count_patient_resources(BASE_URL, patient_ref)

    # --- Author (LLM, cached, concurrent) → validate → approve → write.
    authored_out = author_all(rid, demo_gaps, patient_ref, encounter_ref)
    authored = authored_out["authored"]

    results: list[dict] = []
    for gap in demo_gaps:  # sequential: the approval gate is interactive
        fid = gap["fact"]["id"]
        result = {
            "fact_id": fid,
            "text": gap["fact"]["text"],
            "fhir_type": gap["fhir_type"],
            "note_status": gap["note_status"],
            "authored": fid in authored,
            "valid": False,
            "validation_issues": [],
            "approved": False,
            "written": False,
            "server_id": None,
            "error": authored_out["failures"].get(fid),
        }
        if fid in authored:
            resource = authored[fid]
            ok, issues = validate_resource(resource, gap["fhir_type"])
            result["valid"], result["validation_issues"] = ok, issues
            if not ok:
                print(f"  [validate] {fid} REJECTED: {issues}")
            else:
                receipt_path = C6 / "written" / f"{rid}__{fid}.json"
                if receipt_path.exists():  # already written on a previous run
                    receipt = json.loads(receipt_path.read_text())
                    result["approved"] = True
                    result["written"] = bool(receipt.get("confirmed", True))
                    result["server_id"] = receipt.get("created_id")
                elif request_approval(gap, resource, approve_all=APPROVE_ALL):
                    result["approved"] = True
                    try:
                        receipt = write_resource(BASE_URL, resource)
                        result["written"] = receipt["confirmed"]
                        result["server_id"] = receipt["created_id"]
                        receipt_path.parent.mkdir(parents=True, exist_ok=True)
                        receipt_path.write_text(
                            json.dumps({k: receipt[k] for k in ("created_id", "confirmed")}, indent=1)
                        )
                        print(f"  [write] {gap['fhir_type']}/{receipt['created_id']} "
                              f"confirmed={receipt['confirmed']}")
                    except Exception as exc:
                        result["error"] = repr(exc)
                        print(f"  [write] FAILED {fid}: {exc!r}")
                else:
                    print(f"  [approve] {fid} declined — not written.")
        results.append(result)

    after = count_patient_resources(BASE_URL, patient_ref)
    write_report(rec, patient_ref, encounter_ref, results, skipped, before, after, authored)
    from recall.llm import usage_summary
    print("API usage:", usage_summary())


# ---------------------------------------------------------------- report

def write_report(rec, patient_ref, encounter_ref, results, skipped, before, after, authored) -> None:
    lines = ["# Checkpoint 6 — FHIR write-back demo (STRETCH)", ""]
    written = [r for r in results if r["written"]]
    lines.append(
        f"**Top line:** {len(written)}/{len(results)} selected chart coverage gaps written to the "
        f"sandbox as unconfirmed FHIR R4 resources for encounter `{rec['id']}` "
        f"({len(skipped)} gap candidates excluded by safety screens). "
        "**This is a demo, not an eval metric** — coverage-gap counts are never folded into "
        "headline recall numbers."
    )
    lines.append("")

    lines.append("## Safety framing")
    lines.append("")
    lines.append("- **Human-in-the-loop:** every resource required explicit approval before writing"
                 + (" _(bypassed this run via --approve-all — DEMO ONLY)_." if APPROVE_ALL else "."))
    lines.append("- **Nothing is verified truth:** AllergyIntolerance/Condition carry "
                 "`verificationStatus=unconfirmed`; other types use their most conservative legal "
                 "status; every resource carries an `unconfirmed` meta tag and a provenance note "
                 "with the verbatim transcript quote.")
    lines.append("- **Provisional codes:** RxNorm/SNOMED/LOINC codings are model-suggested and "
                 "explicitly marked needs-verification — a clinician must confirm before any "
                 "downstream use.")
    lines.append("- **Sensitive exclusions:** IPV, substance-use, and mental-health disclosures "
                 "(plus all SDOH-typed facts and negative findings) are screened out before "
                 "structuring; see the skipped list.")
    lines.append("- **Sandbox only:** writes are refused for any host other than "
                 "localhost / 127.0.0.1 / hapi.fhir.org.")
    lines.append("")

    lines.append("## Configuration")
    lines.append("")
    lines.append(f"- Base URL: `{BASE_URL}`")
    lines.append(f"- Patient: `{patient_ref}` (synthetic, from the encounter's patient_context)")
    lines.append(f"- Encounter scaffold: `{encounter_ref or 'none (omitted from resources)'}`")
    lines.append(f"- Gap cap: --max-gaps {MAX_GAPS}")
    lines.append("")

    lines.append("## Coverage gaps selected")
    lines.append("")
    lines.append("| Fact | Target FHIR type | In note? | Authored | Valid | Approved | Written | Server id |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in sorted(results, key=lambda r: r["fact_id"]):
        outcome_note = f" — {r['error']}" if r["error"] else ""
        lines.append(
            f"| {r['text'][:70]} (`{r['fact_id']}`) | {r['fhir_type']} | {r['note_status'] or '—'} "
            f"| {'✅' if r['authored'] else '❌'} | {'✅' if r['valid'] else '❌'} "
            f"| {'✅' if r['approved'] else '—'} | {'✅' if r['written'] else '—'} "
            f"| `{r['server_id'] or '—'}`{outcome_note} |"
        )
    lines.append("")

    lines.append("## Skipped by safety screens (with reasons)")
    lines.append("")
    if not skipped:
        lines.append("_No gap candidates were excluded._")
    for s in sorted(skipped, key=lambda s: s["fact_id"]):
        lines.append(f"- `{s['fact_id']}` ({s['type']}): “{s['text'][:80]}” — {s['reason']}")
    lines.append("")

    lines.append("## Before / after (sandbox resource counts for this patient)")
    lines.append("")
    lines.append("| Resource type | Before | After |")
    lines.append("|---|---|---|")
    for rt in sorted(set(before) | set(after)):
        b = before.get(rt); a = after.get(rt)
        lines.append(f"| {rt} | {b if b is not None else '?'} | {a if a is not None else '?'} |")
    lines.append("")

    lines.append("## Example authored resources")
    lines.append("")
    shown = 0
    for r in sorted(results, key=lambda r: r["fact_id"]):
        if shown >= 3 or r["fact_id"] not in authored:
            continue
        lines.append(f"### {r['fhir_type']} — “{r['text'][:70]}”")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(authored[r["fact_id"]], indent=1))
        lines.append("```")
        lines.append("")
        shown += 1
    if shown == 0:
        lines.append("_No resources were authored this run._")
        lines.append("")

    lines.append("## Caveats")
    lines.append("")
    lines.append("- Codings are provisional model suggestions, not terminology-service lookups — "
                 "every code needs human verification.")
    lines.append("- The approval gate here is a terminal prompt; a real deployment needs an EHR-"
                 "integrated review queue with audit trail.")
    lines.append("- Sensitive-disclosure screening is a keyword heuristic that deliberately "
                 "over-excludes; it is a floor, not a guarantee.")
    lines.append("- Sandbox-only by construction; nothing here touches a production system.")
    lines.append("- Stretch demo: results are illustrative and excluded from headline metrics.")
    lines.append("")

    CHECKPOINT_MD.write_text("\n".join(lines))
    print(f"Wrote {CHECKPOINT_MD}")


if __name__ == "__main__":
    main()
