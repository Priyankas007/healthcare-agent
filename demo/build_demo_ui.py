"""Build the RECALL demo UI — a single self-contained HTML file.

Reads ONLY cached artifacts (dataset, checkpoint2_cache, checkpoint3_cache,
injections) and bakes them into demo/index.html. Zero LLM calls at build or
view time; the "Run verifier engine" button replays cached pipeline output.

Rebuild:  .venv/bin/python demo/build_demo_ui.py
"""

from __future__ import annotations

import html as html_mod
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "synthetic-ambient-fhir-25" / "synthetic-ambient-fhir-25.jsonl"
C2 = REPO / "checkpoint2_cache"
C3 = REPO / "checkpoint3_cache" / "classify"
C4 = REPO / "checkpoint4_cache"
INJ = REPO / "injections"
OUT = REPO / "demo" / "index.html"

SECTION_HEADERS = {
    "Subjective": "**Subjective:**",
    "Objective": "**Objective:**",
    "Assessment and Plan": "**Assessment and Plan:**",
}


def apply_patch_md(note_md: str, section: str, insert_text: str) -> str:
    """Insert the patch at the end of the target SOAP section, wrapped in
    highlight markers (resolved to <span class='ins'> after md rendering)."""
    marked = f"@@INS@@{insert_text}@@ENDINS@@"
    lines = note_md.splitlines()
    header = SECTION_HEADERS.get(section)
    start = next((i for i, l in enumerate(lines) if header and l.strip().startswith(header)), None)
    if start is None:
        return note_md + "\n\n" + marked
    end = next(
        (j for j in range(start + 1, len(lines))
         if any(lines[j].strip().startswith(h) for h in SECTION_HEADERS.values())),
        len(lines),
    )
    # walk back over trailing blank lines of the section
    while end - 1 > start and lines[end - 1].strip() == "":
        end -= 1
    return "\n".join(lines[:end] + [marked] + lines[end:])


def load_patch(injection_id: str) -> dict | None:
    loop_path = C4 / "patch_loop" / f"{injection_id}.json"
    if not loop_path.exists():
        return None
    loop = json.loads(loop_path.read_text())
    if loop.get("unpatchable") or not loop.get("patch"):
        return {"unpatchable": True}
    restore_path = C4 / "restore" / f"{injection_id}.json"
    restored = None
    if restore_path.exists():
        restored = json.loads(restore_path.read_text())[0]["status"]
    p = loop["patch"]
    v = loop.get("verify", {})
    return {
        "unpatchable": False,
        "section": p.get("section", "Assessment and Plan"),
        "insert_text": p.get("insert_text", ""),
        "mode": p.get("mode", "append"),
        "iterations": loop.get("iterations", 1),
        "verify": {
            "grounded": bool(v.get("grounded")),
            "non_redundant": bool(v.get("non_redundant")),
            "correctly_placed": bool(v.get("correctly_placed")),
        },
        "restored": restored,
    }

SEVERITY_RANK = {"safety_critical": 0, "major": 1, "minor": 2}
TYPE_PRIORITY = {"medication": 0, "observation": 1, "red_flag_screen": 2, "order": 3, "referral": 4}


def md_to_html(md: str) -> str:
    """Tiny markdown renderer for the SOAP notes (headers, bold, lists)."""
    out = []
    for line in md.splitlines():
        raw = line.rstrip()
        esc = html_mod.escape(raw)
        esc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
        if raw.startswith("### "):
            out.append(f"<h4>{esc[4:]}</h4>")
        elif raw.startswith("## "):
            out.append(f"<h3>{esc[3:]}</h3>")
        elif raw.startswith("# "):
            out.append(f"<h2>{esc[2:]}</h2>")
        elif raw.startswith(("- ", "* ")):
            out.append(f"<li>{esc[2:]}</li>")
        elif raw.strip() == "":
            out.append("<br>")
        else:
            out.append(f"<p>{esc}</p>")
    return "\n".join(out)


def render_flags(facts_by_id: dict, presence: list[dict], classify: list[dict]) -> dict:
    """Mirror recall.render: relevance filter + severity sort (no cap)."""
    status = {r["fact_id"]: r for r in presence}
    surfaced, minor, suppressed = [], [], []
    for c in classify:
        f = facts_by_id.get(c["fact_id"])
        if not f:
            continue
        flag = {
            "fact_id": f["id"],
            "text": f["text"],
            "type": f.get("type", "other"),
            "severity": c["severity"],
            "why": c["why_it_matters"],
            "quote": f.get("transcript_quote"),
            "fhir": f.get("fhir_ref"),
            "rationale": status.get(f["id"], {}).get("rationale", ""),
        }
        if not c["expected"]:
            suppressed.append(flag)
        elif c["severity"] == "minor":
            minor.append(flag)
        else:
            surfaced.append(flag)
    surfaced.sort(key=lambda x: (SEVERITY_RANK[x["severity"]], TYPE_PRIORITY.get(x["type"], 5), x["fact_id"]))
    return {"surfaced": surfaced, "minor": minor, "suppressed": suppressed}


def presence_counts(presence: list[dict]) -> dict:
    counts = {"present": 0, "partial": 0, "absent": 0}
    for r in presence:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts


def build() -> None:
    records = {r["id"]: r for r in (json.loads(l) for l in open(DATA))}
    injection_records = [json.loads(l) for l in (INJ / "records.jsonl").read_text().splitlines() if l]
    inj_by_note: dict[str, list[dict]] = {}
    for rec in injection_records:
        inj_by_note.setdefault(rec["note_id"], []).append(rec)

    encounters = []
    for rid, rec in records.items():
        facts = json.loads((C2 / "facts" / f"{rid}.json").read_text())
        facts_by_id = {f["id"]: f for f in facts}
        versions = []

        def make_version(vid, label, note_text, presence, planted=None, kind="clean", classify_path=None):
            cpath = classify_path or (C3 / f"{vid}.json")
            classify = json.loads(cpath.read_text()) if cpath.exists() else []
            counts = presence_counts(presence)
            total = max(len(presence), 1)
            return {
                "id": vid,
                "label": label,
                "kind": kind,
                "note_html": md_to_html(note_text),
                "counts": counts,
                "coverage": round(counts["present"] / total * 100),
                "n_facts": len(presence),
                "flags": render_flags(facts_by_id, presence, classify),
                "planted": planted,
            }

        prov_presence = json.loads((C2 / "presence_provided" / f"{rid}.json").read_text())
        versions.append(make_version(f"{rid}__clean", "Original note", rec["note"], prov_presence))

        # Generated (B0) note with REAL detection results, when the b0 run has
        # cached this encounter (rebuild after run_b0_detection.py for all 25).
        b0_pres_path = REPO / "b0_cache" / "presence" / f"{rid}.json"
        b0_cls_path = REPO / "b0_cache" / "classify" / f"{rid}.json"
        gen_note_path = REPO / "generated_notes" / f"{rid}.md"
        if b0_pres_path.exists() and b0_cls_path.exists() and gen_note_path.exists():
            versions.append(
                make_version(
                    f"{rid}__b0",
                    "Generated note (B0 scribe)",
                    gen_note_path.read_text(),
                    json.loads(b0_pres_path.read_text()),
                    kind="b0",
                    classify_path=b0_cls_path,
                )
            )

        for inj in sorted(inj_by_note.get(rid, []), key=lambda r: r["injection_id"]):
            iid = inj["injection_id"]
            ev = json.loads((C2 / "eval" / f"{iid}.json").read_text())
            fact = inj["fact"]
            label = f"Degraded — {fact['type']} removed"
            planted = {
                "fact_id": fact["id"],
                "text": fact["text"],
                "type": fact["type"],
                "caught": fact["id"] in ev["detected_absent_fact_ids"],
            }
            note_md = (INJ / f"{iid}.md").read_text()
            version = make_version(iid, label, note_md, ev["presence_results"], planted, kind="deg")
            patch = load_patch(iid)
            if patch and not patch["unpatchable"]:
                patched_html = md_to_html(
                    apply_patch_md(note_md, patch["section"], patch["insert_text"])
                ).replace("@@INS@@", '<span class="ins">').replace("@@ENDINS@@", "</span>")
                version["patch"] = patch
                version["note_patched_html"] = patched_html
            versions.append(version)

        encounters.append(
            {
                "id": rid,
                "title": rec["metadata"]["visit_title"],
                "date": rec["metadata"]["date"][:10],
                "transcript": rec["transcript"],
                "n_fhir": sum(len(v) for v in rec["encounter_fhir"].get("related_resources", {}).values()),
                "versions": versions,
            }
        )

    # Hero encounters first (the med-rich ones), then the rest by title.
    hero_ids = json.loads((REPO / "hero_cases.json").read_text())
    encounters.sort(key=lambda e: (0 if e["id"] in hero_ids else 1, e["title"]))

    payload = json.dumps(
        {"encounters": encounters, "writeback": build_writeback(records)},
        separators=(",", ":"),
    )
    OUT.write_text(TEMPLATE.replace("__DATA__", payload.replace("</", "<\\/")))
    size_mb = OUT.stat().st_size / 1e6
    n_versions = sum(len(e["versions"]) for e in encounters)
    print(f"Wrote {OUT}  ({size_mb:.1f} MB, {len(encounters)} encounters, {n_versions} note versions)")


WRITEBACK_RID = (
    "1be66dc9-cf0b-cb78-e88e-ada9a9a5405b::1be66dc9-cf0b-cb78-ee14-c92f2fe041a4"
)


def build_writeback(records: dict) -> dict:
    """Embed the chart write-back demo data: coverage gaps + pre-authored FHIR
    resources for the SNF-admission encounter (patient-stated allergies that
    exist nowhere in the coded chart). Live POSTs happen from the browser."""
    import sys
    sys.path.insert(0, str(REPO))
    from recall.writeback import select_coverage_gaps

    rec = records[WRITEBACK_RID]
    facts = json.loads((C2 / "facts" / f"{WRITEBACK_RID}.json").read_text())
    presence = json.loads((C2 / "presence_provided" / f"{WRITEBACK_RID}.json").read_text())
    gaps, skipped = select_coverage_gaps(facts, presence)

    gap_cards = []
    for g in gaps:
        f = g["fact"]
        authored = REPO / "checkpoint6_cache" / "authored" / f"{WRITEBACK_RID}__{f['id']}.json"
        if not authored.exists():
            continue
        resource = json.loads(authored.read_text())
        resource.pop("encounter", None)  # browser demo scaffolds only a Patient
        gap_cards.append(
            {
                "fact_id": f["id"],
                "text": f["text"],
                "type": f.get("type"),
                "quote": f.get("transcript_quote"),
                "fhir_type": g["fhir_type"],
                "resource": resource,
            }
        )

    patient = dict(rec["patient_context"]["patient"])
    patient.pop("id", None)  # server assigns a fresh id per demo session
    return {
        "encounter_id": WRITEBACK_RID,
        "title": rec["metadata"]["visit_title"],
        "patient_resource": patient,
        "gaps": gap_cards,
        "n_skipped": len(skipped),
        "skipped_sample": [
            {"text": s["text"][:80], "type": s["type"], "reason": s["reason"][:110]}
            for s in skipped[:6]
        ],
        "base_url": "http://localhost:8080/fhir",
    }


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RECALL — Pre-Signature Coverage Agent</title>
<style>
  :root {
    --ground:#fafbfa; --panel:#ffffff; --wash:#eef3f1; --ink:#152420; --ink2:#47605a;
    --faint:#7d928c; --line:#dde6e3; --pine:#0b6b5d; --pine-deep:#08503f; --pine-wash:#e2efec;
    --crit:#b3261e; --crit-wash:#fbe9e7; --major:#a35c00; --major-wash:#f9efdf;
    --minor:#5b7a94; --ok:#1b7f4d; --ok-wash:#e3f2e9;
    --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
    --sans:"Avenir Next",Seravek,"Gill Sans",Calibri,sans-serif;
    --mono:"SF Mono",Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box} html,body{height:100%}
  body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.55}
  ::selection{background:var(--pine-wash)}

  header.top{display:flex;align-items:center;gap:14px;padding:10px 22px;background:var(--panel);
    border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
  .brand{font-family:var(--serif);font-size:21px;font-weight:700;letter-spacing:.02em;color:var(--pine-deep)}
  .brand small{font-family:var(--sans);font-weight:500;font-size:10.5px;letter-spacing:.22em;color:var(--faint);
    text-transform:uppercase;margin-left:12px;vertical-align:2px}
  .top .stats{margin-left:auto;display:flex;gap:22px;font-size:12px;color:var(--ink2)}
  .top .stats b{font-family:var(--serif);font-size:16px;color:var(--pine-deep)}
  .sysbtn{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:6px 13px;cursor:pointer;
    font-family:var(--sans);font-size:12.5px;color:var(--ink2)}
  .sysbtn:hover{border-color:var(--pine);color:var(--pine-deep)}

  .layout{display:grid;grid-template-columns:295px 1fr 415px;height:calc(100vh - 53px)}

  /* sidebar */
  aside{border-right:1px solid var(--line);overflow-y:auto;background:var(--panel);padding:14px 10px}
  aside h2{font-size:10.5px;letter-spacing:.2em;text-transform:uppercase;color:var(--faint);margin:6px 8px 10px}
  .enc{border-radius:10px;margin-bottom:4px}
  .enc>button{all:unset;display:block;width:100%;padding:9px 12px;border-radius:10px;cursor:pointer}
  .enc>button:hover{background:var(--wash)}
  .enc.open>button{background:var(--pine-wash)}
  .enc .t{font-weight:600;font-size:13.5px;line-height:1.35}
  .enc .d{font-size:11.5px;color:var(--faint);margin-top:1px}
  .vers{padding:2px 4px 6px 14px;display:none}
  .enc.open .vers{display:block}
  .vers button{all:unset;display:flex;align-items:center;gap:7px;width:100%;padding:5.5px 9px;border-radius:7px;
    font-size:12.5px;color:var(--ink2);cursor:pointer}
  .vers button:hover{background:var(--wash)}
  .vers button.sel{background:var(--pine);color:#fff}
  .dot{width:7px;height:7px;border-radius:50%;flex:none}
  .dot.clean{background:var(--ok)} .dot.deg{background:var(--major)} .dot.b0{background:var(--minor)}
  .b0-banner{margin:14px 0 0;border:1px dashed var(--pine);background:var(--pine-wash);border-radius:10px;
    padding:10px 14px;font-size:13px}
  .b0-banner b{color:var(--pine-deep)}

  /* center */
  main{overflow-y:auto;padding:26px 34px}
  .pt-head h1{font-family:var(--serif);font-size:27px;font-weight:700;margin:0}
  .pt-head .meta{color:var(--faint);font-size:12.5px;margin-top:3px}
  .planted{margin:14px 0 0;border:1px dashed var(--major);background:var(--major-wash);border-radius:10px;
    padding:10px 14px;font-size:13px}
  .planted b{color:var(--major)}
  .tabs{display:flex;gap:2px;margin:18px 0 0;border-bottom:1.5px solid var(--line)}
  .tabs button{all:unset;padding:8px 16px;font-size:13.5px;color:var(--faint);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1.5px}
  .tabs button.on{color:var(--pine-deep);border-color:var(--pine);font-weight:600}
  .doc{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:28px 34px;margin-top:16px;
    max-width:760px;box-shadow:0 1px 3px rgba(21,36,32,.04)}
  .doc h2{font-family:var(--serif);font-size:19px;margin:2px 0 10px}
  .doc h3{font-size:14px;text-transform:uppercase;letter-spacing:.08em;color:var(--pine-deep);margin:20px 0 6px}
  .doc h4{font-size:13.5px;margin:14px 0 4px}
  .doc p{margin:0 0 8px;max-width:68ch} .doc li{margin:3px 0 3px 16px;max-width:66ch}
  .doc.transcript{font-size:14px;white-space:pre-wrap;color:var(--ink2);max-height:none}

  /* right rail */
  .rail{border-left:1px solid var(--line);overflow-y:auto;background:#f4f8f6;padding:20px}
  .rail h2{font-size:10.5px;letter-spacing:.2em;text-transform:uppercase;color:var(--faint);margin:0 0 4px}
  .rail .sub{font-family:var(--serif);font-size:19px;font-weight:700;margin:0 0 14px}
  .runbtn{all:unset;display:block;width:100%;text-align:center;background:var(--pine);color:#fff;font-weight:600;
    font-size:14.5px;padding:12px 0;border-radius:10px;cursor:pointer;letter-spacing:.02em;
    box-shadow:0 2px 8px rgba(11,107,93,.28);transition:transform .12s}
  .runbtn:hover{background:var(--pine-deep)} .runbtn:active{transform:scale(.985)}
  .runbtn[disabled]{opacity:.55;cursor:default}
  .replay-note{font-size:11px;color:var(--faint);text-align:center;margin:7px 0 0}

  .stage{display:flex;align-items:center;gap:10px;padding:7px 4px;font-size:13px;color:var(--faint);opacity:0;
    transform:translateY(4px);transition:all .3s}
  .stage.show{opacity:1;transform:none;color:var(--ink2)}
  .stage.done .spin{display:none}
  .stage .check{display:none;color:var(--ok);font-weight:700}
  .stage.done .check{display:inline}
  .spin{width:12px;height:12px;border:2px solid var(--line);border-top-color:var(--pine);border-radius:50%;
    animation:spin .7s linear infinite;flex:none}
  @keyframes spin{to{transform:rotate(360deg)}}
  .stage b{color:var(--pine-deep)}

  .results{display:none}
  .results.show{display:block}
  .covrow{display:flex;gap:12px;align-items:center;background:var(--panel);border:1px solid var(--line);
    border-radius:12px;padding:14px 16px;margin:16px 0 14px;animation:rise .4s both}
  .covnum{font-family:var(--serif);font-size:34px;font-weight:700;color:var(--pine-deep);line-height:1}
  .covnum small{font-size:16px}
  .covlab{font-size:12.5px;color:var(--ink2)} .covlab b{display:block;font-size:13px;color:var(--ink)}
  .catchband{border-radius:10px;padding:9px 13px;font-size:13px;margin:0 0 14px;animation:rise .4s .1s both}
  .catchband.ok{background:var(--ok-wash);color:var(--ok);border:1px solid #bfe3cd}
  .catchband.miss{background:var(--major-wash);color:var(--major);border:1px solid #ecd9b5}

  .flag{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--major);border-radius:10px;
    padding:13px 15px;margin-bottom:11px;opacity:0;animation:rise .45s both}
  .flag.safety_critical{border-left-color:var(--crit)}
  .flag .pill{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.08em;padding:2px 8px;border-radius:20px;margin-bottom:7px}
  .flag.major .pill{background:var(--major-wash);color:var(--major)}
  .flag.safety_critical .pill{background:var(--crit-wash);color:var(--crit)}
  .flag .ft{font-weight:600;font-size:13.8px;line-height:1.4}
  .flag .why{font-size:12.8px;color:var(--ink2);margin:6px 0 0}
  .ev{margin-top:9px;border-top:1px dashed var(--line);padding-top:8px;font-size:12px}
  .ev .src{color:var(--faint);letter-spacing:.1em;font-size:9.5px;text-transform:uppercase;font-weight:600}
  .ev .q{font-style:italic;color:var(--ink2)} .ev code{font-family:var(--mono);font-size:10.5px;color:var(--pine-deep);
    background:var(--pine-wash);border-radius:4px;padding:1px 5px}
  .minorbox{font-size:12px;color:var(--faint);background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:9px 13px;animation:rise .45s both}

  /* correction card */
  .fix{margin-top:11px;border-top:1px dashed var(--line);padding-top:10px}
  .fix .fixhead{font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;font-weight:700;color:var(--pine-deep)}
  .fix .badges{display:flex;gap:6px;margin:6px 0}
  .fix .badge{font-size:10px;padding:2px 8px;border-radius:20px;background:var(--ok-wash);color:var(--ok);font-weight:600}
  .fix .ins-preview{background:var(--pine-wash);border-left:3px solid var(--pine);border-radius:0 7px 7px 0;
    padding:8px 11px;font-size:12.8px;margin:7px 0}
  .fix .where{font-size:11px;color:var(--faint);margin-bottom:8px}
  .fix .btns{display:flex;gap:8px}
  .fix button{all:unset;font-size:12.5px;font-weight:600;padding:6px 14px;border-radius:8px;cursor:pointer}
  .fix .accept{background:var(--pine);color:#fff}
  .fix .accept:hover{background:var(--pine-deep)}
  .fix .accept.done{background:var(--ok-wash);color:var(--ok);cursor:default}
  .fix .dismiss{border:1px solid var(--line);color:var(--ink2);background:var(--panel)}
  .doc .ins{background:var(--pine-wash);border-bottom:2px solid var(--pine);padding:1px 3px;border-radius:3px;
    animation:insglow 1.6s ease-out}
  @keyframes insglow{0%{background:#bfe6dd}100%{background:var(--pine-wash)}}
  @keyframes rise{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:none}}
  .noflag{background:var(--ok-wash);border:1px solid #bfe3cd;color:var(--ok);border-radius:10px;padding:11px 14px;
    font-size:13px;animation:rise .4s both}

  /* flowchart overlay */
  .overlay{position:fixed;inset:0;background:rgba(21,36,32,.45);display:none;z-index:50;align-items:center;justify-content:center}
  .overlay.show{display:flex}
  .sheet{background:var(--ground);border-radius:16px;max-width:940px;width:92%;max-height:88vh;overflow-y:auto;padding:30px 36px;box-shadow:0 24px 60px rgba(0,0,0,.25)}
  .sheet h2{font-family:var(--serif);font-size:22px;margin:0 0 4px}
  .sheet .cap{color:var(--faint);font-size:13px;margin:0 0 20px}
  .flow{display:grid;grid-template-columns:150px 34px 1fr;gap:10px;align-items:stretch}
  .srcbox{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-size:12px;margin-bottom:8px}
  .srcbox b{display:block;font-size:12.5px;color:var(--pine-deep)}
  .arrow{display:flex;align-items:center;justify-content:center;color:var(--faint);font-size:20px}
  .pipe{display:flex;flex-direction:column;gap:8px}
  .step{display:grid;grid-template-columns:26px 1fr;gap:12px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
  .step .n{font-family:var(--serif);font-weight:700;color:#fff;background:var(--pine);border-radius:7px;width:24px;height:24px;
    display:grid;place-items:center;font-size:13px}
  .step b{font-size:13.5px} .step span{display:block;font-size:12px;color:var(--ink2)}
  .step.guard{border-left:3px solid var(--major)}
  .evalnote{margin-top:16px;background:var(--pine-wash);border-radius:10px;padding:12px 16px;font-size:12.5px;color:var(--pine-deep)}
  .close{all:unset;float:right;cursor:pointer;font-size:22px;color:var(--faint);line-height:1}

  /* write-back overlay */
  .wb-status{display:flex;gap:10px;align-items:center;font-size:13px;margin:0 0 16px;padding:10px 14px;
    border-radius:10px;background:var(--panel);border:1px solid var(--line)}
  .wb-status.err{background:var(--crit-wash);border-color:#e8c4c0;color:var(--crit)}
  .wb-live{width:9px;height:9px;border-radius:50%;background:var(--ok);flex:none;box-shadow:0 0 0 3px var(--ok-wash)}
  .wb-count{font-family:var(--serif);font-size:30px;font-weight:700;color:var(--pine-deep)}
  .wb-count.zero{color:var(--faint)}
  .wb-before{display:flex;gap:16px;align-items:center;background:var(--panel);border:1px solid var(--line);
    border-radius:12px;padding:14px 18px;margin-bottom:14px}
  .wb-before .lbl{font-size:12.5px;color:var(--ink2)} .wb-before .lbl b{display:block;color:var(--ink);font-size:13.5px}
  .wb-query{font-family:var(--mono);font-size:11px;color:var(--pine-deep);background:var(--pine-wash);
    border-radius:6px;padding:2px 8px}
  .gapcard{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--pine);
    border-radius:10px;padding:14px 16px;margin-bottom:12px}
  .gapcard .gt{font-weight:600;font-size:14px}
  .gapcard .gq{font-style:italic;font-size:12.5px;color:var(--ink2);margin:5px 0}
  .gapcard .rtype{font-family:var(--mono);font-size:10.5px;color:var(--pine-deep);background:var(--pine-wash);
    border-radius:5px;padding:1px 7px}
  .gapcard .unconf{font-size:11px;color:var(--major);font-weight:600}
  .rsc{background:linear-gradient(180deg,#f7faf9,#f1f6f4);border:1px solid var(--line);border-radius:10px;
    padding:12px 14px;margin:10px 0}
  .rsc .rschead{display:flex;align-items:center;gap:8px;margin-bottom:9px}
  .rsc .rtitle{font-family:var(--serif);font-weight:700;font-size:15px;color:var(--pine-deep)}
  .rsc .spill{font-size:9.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
    padding:2px 8px;border-radius:20px}
  .rsc .spill.active{background:var(--ok-wash);color:var(--ok)}
  .rsc .spill.unconfirmed{background:var(--major-wash);color:var(--major)}
  .rsc .rrow{display:grid;grid-template-columns:96px 1fr;gap:10px;padding:4px 0;font-size:12.5px;
    border-top:1px dashed var(--line)}
  .rsc .rrow .rl{color:var(--faint);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;padding-top:2px}
  .rsc .codechip{font-family:var(--mono);font-size:10.5px;background:var(--panel);border:1px solid var(--line);
    border-radius:5px;padding:1px 6px;color:var(--pine-deep)}
  .rsc .prov{font-style:italic;color:var(--ink2)}
  .gapcard .gbtns{display:flex;gap:8px;margin-top:9px;align-items:center}
  .gapcard .gbtns button{all:unset;font-size:12.5px;font-weight:600;padding:6px 15px;border-radius:8px;cursor:pointer}
  .gapcard .approve{background:var(--pine);color:#fff} .gapcard .approve:hover{background:var(--pine-deep)}
  .gapcard .reject{border:1px solid var(--line);color:var(--ink2)}
  .gapcard .result{font-size:12.5px;font-weight:600}
  .gapcard.written{border-left-color:var(--ok);background:linear-gradient(to right,var(--ok-wash),var(--panel) 40%)}
  .gapcard.rejected{opacity:.55;border-left-color:var(--faint)}
  .wb-skips{font-size:12px;color:var(--faint);background:var(--panel);border:1px solid var(--line);
    border-radius:10px;padding:10px 14px;margin-top:4px}
  .wb-skips summary{cursor:pointer;font-weight:600;color:var(--ink2)}
  .wb-skips li{margin:4px 0 4px 14px}
</style>
</head>
<body>
<header class="top">
  <span class="brand">RECALL<small>Pre-signature coverage agent</small></span>
  <div class="stats">
    <span><b>100%</b> injection recall (69/69)</span>
    <span><b>0.96</b> clean-note flags (upper bound)</span>
    <span><b>2</b> median flags/note</span>
    <span><b>96.5%</b> patch faithfulness</span>
  </div>
  <button class="sysbtn" onclick="document.getElementById('ov').classList.add('show')">⌘ How it works</button>
  <button class="sysbtn" onclick="openWriteback()">⚡ Chart write-back</button>
</header>

<div class="layout">
  <aside id="sidebar"><h2>Encounters · 25</h2></aside>

  <main id="main"></main>

  <div class="rail">
    <h2>Pre-signature safety</h2>
    <p class="sub">Coverage verifier</p>
    <button class="runbtn" id="runbtn" onclick="runVerifier()">Run verifier engine</button>
    <p class="replay-note">Replays the pipeline's pre-computed analysis — deterministic, no live calls in this demo.</p>
    <div id="stages" style="margin-top:14px"></div>
    <div class="results" id="results"></div>
  </div>
</div>

<div class="overlay" id="ov" onclick="if(event.target===this)this.classList.remove('show')">
  <div class="sheet">
    <button class="close" onclick="document.getElementById('ov').classList.remove('show')">×</button>
    <h2>How it works</h2>
    <p class="cap">A pipeline of independent steps — checking is always kept separate from writing, and every claim must cite its source</p>
    <div class="flow">
      <div>
        <div class="srcbox"><b>The conversation</b>the full recorded visit — everything the clinician and patient actually said</div>
        <div class="srcbox"><b>This visit's chart data</b>coded medications, lab results, diagnoses &amp; reports recorded for the encounter</div>
        <div class="srcbox"><b>Patient history</b>ongoing problems &amp; medications for context</div>
      </div>
      <div class="arrow">→</div>
      <div class="pipe">
        <div class="step"><span class="n">1</span><div><b>Break the visit into facts</b><span>Every clinically important statement — symptoms, medication changes, results, follow-ups — becomes one discrete fact, linked to its source: the exact words spoken, or the chart entry.</span></div></div>
        <div class="step guard"><span class="n">2</span><div><b>Check the note against every fact</b><span>An independent checker reads the note and asks, for each fact: is it documented — fully, partially, or not at all? Every verdict must quote the note's own words as evidence.</span></div></div>
        <div class="step"><span class="n">3</span><div><b>Judge what matters</b><span>For each missing fact: should a complete note for <i>this</i> visit include it? And how serious is the gap if left uncorrected — safety-critical, major, or minor?</span></div></div>
        <div class="step"><span class="n">4</span><div><b>Show only what matters</b><span>Clinicians see the important, relevant gaps, ranked by severity. Minor items are logged but not surfaced — thoroughness without alarm fatigue.</span></div></div>
      </div>
    </div>
    <div class="evalnote"><b>How we grade it:</b> there's no existing answer key for omissions, so we make one — remove a single known fact from a complete note, then test whether the system finds it, blind. Across <b>69 planted omissions it caught every one (100%)</b>. On untouched notes it raises fewer than one flag per note — and deleting one fact doesn't disturb the rest of the analysis.</div>
  </div>
</div>

<div class="overlay" id="wbov" onclick="if(event.target===this)this.classList.remove('show')">
  <div class="sheet">
    <button class="close" onclick="document.getElementById('wbov').classList.remove('show')">×</button>
    <h2>Chart write-back <span style="font-size:12px;color:var(--major);font-weight:600">STRETCH · sandbox only</span></h2>
    <p class="cap" id="wb-cap"></p>
    <div id="wb-body"></div>
  </div>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
let cur = {enc: DATA.encounters[0], ver: null, tab: 'note', hasRun: false};
cur.ver = cur.enc.versions.find(v=>v.planted) || cur.enc.versions[0];

function el(tag, cls, html){const e=document.createElement(tag); if(cls)e.className=cls; if(html!=null)e.innerHTML=html; return e;}
function esc(s){const d=document.createElement('div'); d.textContent=s??''; return d.innerHTML;}

function buildSidebar(){
  const sb=document.getElementById('sidebar');
  DATA.encounters.forEach(enc=>{
    const box=el('div','enc'); box.dataset.id=enc.id;
    const head=el('button',null,`<div class="t">${esc(enc.title)}</div><div class="d">${enc.date} · ${enc.n_fhir} FHIR resources · ${enc.versions.length-1} degraded cop${enc.versions.length-1===1?'y':'ies'}</div>`);
    head.onclick=()=>{document.querySelectorAll('.enc').forEach(x=>x!==box&&x.classList.remove('open')); box.classList.toggle('open');};
    box.appendChild(head);
    const vers=el('div','vers');
    enc.versions.forEach(v=>{
      const b=el('button',null,`<span class="dot ${v.kind||'clean'}"></span>${esc(v.label)}`);
      b.onclick=(e)=>{e.stopPropagation(); select(enc,v);};
      b.dataset.vid=v.id;
      vers.appendChild(b);
    });
    box.appendChild(vers); sb.appendChild(box);
  });
}

function select(enc,ver){
  cur={enc,ver,tab:'note',hasRun:false};
  document.querySelectorAll('.vers button').forEach(b=>b.classList.toggle('sel',b.dataset.vid===ver.id));
  document.querySelectorAll('.enc').forEach(x=>x.classList.toggle('open',x.dataset.id===enc.id));
  resetRail(); renderMain();
}

function renderMain(){
  const m=document.getElementById('main'); m.innerHTML='';
  const head=el('div','pt-head',`<h1>${esc(cur.enc.title)}</h1><div class="meta">${cur.enc.date} · synthetic encounter · ${esc(cur.ver.label)} · ${cur.ver.n_facts} candidate facts tracked</div>`);
  m.appendChild(head);
  if(cur.ver.planted){
    m.appendChild(el('div','planted',`<b>Eval harness ground truth:</b> the fact “${esc(cur.ver.planted.text)}” <b>was deleted</b> from this note copy. Run the verifier to see if it catches the omission blind.`));
  }
  if(cur.ver.kind==='b0'){
    m.appendChild(el('div','b0-banner',`<b>Scribe output — real detection:</b> this note was generated from the transcript alone by a naive ambient scribe. Any flags below are <b>authentic omissions</b> — nothing was planted.`));
  }
  const tabs=el('div','tabs');
  [['note','Clinical note'],['transcript','Transcript']].forEach(([k,label])=>{
    const b=el('button',cur.tab===k?'on':'',label);
    b.onclick=()=>{cur.tab=k; renderMain();};
    tabs.appendChild(b);
  });
  m.appendChild(tabs);
  if(cur.tab==='note'){
    const body = (cur.ver.accepted && cur.ver.note_patched_html) ? cur.ver.note_patched_html : cur.ver.note_html;
    m.appendChild(el('div','doc',body));
  }
  else { m.appendChild(el('div','doc transcript',esc(cur.enc.transcript))); }
}

function resetRail(){
  document.getElementById('stages').innerHTML='';
  const r=document.getElementById('results'); r.innerHTML=''; r.classList.remove('show');
  document.getElementById('runbtn').disabled=false;
}

function runVerifier(){
  if(cur.hasRun){resetRail();}
  cur.hasRun=true;
  const btn=document.getElementById('runbtn'); btn.disabled=true;
  const stages=document.getElementById('stages'); stages.innerHTML='';
  const c=cur.ver.counts;
  const steps=[
    [`Decomposing transcript + FHIR into atomic facts… <b>${cur.ver.n_facts} facts</b>`, 950],
    [`Grounded entailment vs. note… <b>${c.present} present · ${c.partial} partial · ${c.absent} absent</b>`, 1350],
    [`Classifying severity &amp; expectation for absent facts…`, 1050],
    [`Applying relevance filter, ranking…`, 700],
  ];
  let t=120;
  steps.forEach(([txt,dur],i)=>{
    const s=el('div','stage',`<span class="spin"></span><span class="check">✓</span><span>${txt}</span>`);
    stages.appendChild(s);
    setTimeout(()=>s.classList.add('show'), t);
    t+=dur;
    setTimeout(()=>s.classList.add('done'), t);
  });
  setTimeout(showResults, t+250);
}

function showResults(){
  const r=document.getElementById('results'); r.innerHTML='';
  const v=cur.ver, fl=v.flags;
  r.appendChild(el('div','covrow',`<div class="covnum">${v.coverage}<small>%</small></div><div class="covlab"><b>Note coverage</b>${v.counts.absent} fact(s) absent · ${v.counts.partial} partial · ${fl.surfaced.length} flag(s) surfaced</div>`));
  if(v.planted){
    const caughtAndSurfaced = fl.surfaced.some(f=>f.fact_id===v.planted.fact_id);
    if(caughtAndSurfaced) r.appendChild(el('div','catchband ok',`✓ Planted omission <b>caught and surfaced</b> — the deleted ${esc(v.planted.type)} fact is flagged below.`));
    else if(v.planted.caught) r.appendChild(el('div','catchband miss',`◐ Detected as absent, but classified below the surfacing bar (logged as minor) — a severity-calibration case, not a detection miss.`));
    else r.appendChild(el('div','catchband miss',`✗ Not detected — a genuine miss.`));
  }
  if(v.kind==='b0' && fl.surfaced.length>0){
    r.appendChild(el('div','catchband ok',`● <b>${fl.surfaced.length} authentic omission(s)</b> in the scribe's own output — nothing planted, no answer key.`));
  }
  if(fl.surfaced.length===0){
    r.appendChild(el('div','noflag','No safety-critical or major omissions to review. Note is clear to sign.'));
  }
  fl.surfaced.forEach((f,i)=>{
    const sev=f.severity==='safety_critical'?'SAFETY-CRITICAL':'MAJOR';
    let ev='';
    if(f.quote) ev+=`<div class="ev"><span class="src">Transcript</span><div class="q">“${esc(f.quote)}”</div></div>`;
    if(f.fhir) ev+=`<div class="ev"><span class="src">Patient chart</span> <code>${esc(f.fhir)}</code></div>`;
    let fix='';
    const p = (v.planted && f.fact_id===v.planted.fact_id) ? v.patch : null;
    if(p){
      const iters = p.iterations>1 ? ` · revised ×${p.iterations-1} by verifier` : '';
      fix=`<div class="fix"><div class="fixhead">Proposed correction${iters}</div>
        <div class="badges"><span class="badge">✓ grounded</span><span class="badge">✓ non-redundant</span><span class="badge">✓ placed</span></div>
        <div class="ins-preview">${esc(p.insert_text)}</div>
        <div class="where">→ ${esc(p.section)} · ${esc(p.mode)}</div>
        <div class="btns"><button class="accept" onclick="acceptPatch(this)">✓ Accept insertion</button>
        <button class="dismiss" onclick="this.closest('.fix').style.display='none'">Dismiss</button></div></div>`;
    }
    const box=el('div',`flag ${f.severity}`,`<span class="pill">${sev} · ${esc(f.type)}</span><div class="ft">${esc(f.text)}</div><div class="why">${esc(f.why)}</div>${ev}${fix}`);
    box.style.animationDelay=(i*0.14)+'s';
    r.appendChild(box);
  });
  if(fl.minor.length){
    r.appendChild(el('div','minorbox',`${fl.minor.length} minor flag(s) logged, not surfaced: ${fl.minor.map(f=>esc(f.text.slice(0,60))).join(' · ')}`));
  }
  if(fl.suppressed.length){
    r.appendChild(el('div','minorbox',`${fl.suppressed.length} candidate(s) suppressed as not-expected for this visit.`));
  }
  r.classList.add('show');
  document.getElementById('runbtn').disabled=false;
  document.getElementById('runbtn').textContent='Re-run verifier engine';
}

function acceptPatch(btn){
  if(!cur.ver.note_patched_html) return;
  btn.textContent='✓ Insertion accepted'; btn.classList.add('done');
  btn.parentElement.querySelector('.dismiss').style.display='none';
  cur.ver.accepted=true;
  cur.tab='note';
  renderMain();
  const ins=document.querySelector('#main .doc .ins');
  if(ins) ins.scrollIntoView({behavior:'smooth', block:'center'});
}

/* ---------------- chart write-back (live FHIR sandbox) ---------------- */
const WB = DATA.writeback;
let wbPatient = null;  // fresh Patient id per session

async function fhir(method, path, body){
  const res = await fetch(WB.base_url + path, {
    method, headers: {'Content-Type':'application/fhir+json'},
    body: body ? JSON.stringify(body) : undefined,
  });
  if(!res.ok && res.status !== 201) throw new Error(method+' '+path+' → HTTP '+res.status);
  return res.status === 204 ? null : res.json();
}

async function allergyCount(){
  const b = await fhir('GET', `/AllergyIntolerance?patient=${wbPatient}&_summary=count`);
  return b.total ?? 0;
}

async function openWriteback(){
  document.getElementById('wbov').classList.add('show');
  document.getElementById('wb-cap').textContent =
    `${esc0(WB.title)} — patient-stated facts with NO coded FHIR counterpart. Each write requires explicit approval; resources are verificationStatus=unconfirmed with the transcript quote as provenance.`;
  const body = document.getElementById('wb-body');
  body.innerHTML = '<div class="wb-status"><span class="spin"></span>Connecting to sandbox FHIR server…</div>';
  try{
    await fhir('GET', '/metadata?_summary=true');
    if(!wbPatient){
      const created = await fhir('POST', '/Patient', WB.patient_resource);
      wbPatient = created.id;
    }
    renderWriteback();
  }catch(e){
    body.innerHTML = `<div class="wb-status err">Sandbox unreachable (${esc0(e.message)}). Start it with:
      <code style="font-family:var(--mono)">docker start hapi-fhir</code> — writes are refused for any non-localhost host.</div>`;
  }
}
function esc0(s){const d=document.createElement('div'); d.textContent=s??''; return d.innerHTML;}

const NICE_TYPE = {AllergyIntolerance:'Allergy record', MedicationStatement:'Medication record',
  Condition:'Condition record', FamilyMemberHistory:'Family history record', Observation:'Observation record'};

function resourcePreview(r, ftype){
  const cc = r.code || {};
  const coding = (cc.coding||[])[0] || {};
  const display = cc.text || coding.display || '—';
  const statusPills = [];
  const clin = r.clinicalStatus?.coding?.[0]?.display || r.clinicalStatus?.coding?.[0]?.code;
  if(clin) statusPills.push(`<span class="spill active">${esc0(clin)}</span>`);
  statusPills.push(`<span class="spill unconfirmed">Unconfirmed — needs clinician verification</span>`);
  const rows = [];
  rows.push(['What', esc0(display.replace(/\s*\(provisional[^)]*\)/i,''))]);
  const reactions = (r.reaction||[]).flatMap(x=>(x.manifestation||[]).map(m=>m.text||m.coding?.[0]?.display)).filter(Boolean);
  if(reactions.length) rows.push(['Reaction', esc0(reactions.join(', '))]);
  if(r.criticality) rows.push(['Criticality', esc0(r.criticality)]);
  if(coding.code) rows.push(['Coding', `<span class="codechip">${esc0(coding.system?.includes('snomed')?'SNOMED':'code')} ${esc0(coding.code)}</span> <span style="font-size:11px;color:var(--faint)">provisional — needs verification</span>`]);
  const note = (r.note||[])[0]?.text;
  if(note) rows.push(['Provenance', `<span class="prov">${esc0(note)}</span>`]);
  return `<div class="rsc">
    <div class="rschead"><span class="rtitle">${esc0(NICE_TYPE[ftype]||ftype)}</span>${statusPills.join('')}</div>
    ${rows.map(([l,v])=>`<div class="rrow"><span class="rl">${l}</span><span>${v}</span></div>`).join('')}
  </div>`;
}

async function renderWriteback(){
  const body = document.getElementById('wb-body');
  const n = await allergyCount();
  let html = `
    <div class="wb-status"><span class="wb-live"></span>Live sandbox · HAPI FHIR R4 · <span class="wb-query">${esc0(WB.base_url)}</span> · Patient/${esc0(wbPatient)} (fresh this session)</div>
    <div class="wb-before">
      <div class="wb-count ${n===0?'zero':''}" id="wb-n">${n}</div>
      <div class="lbl"><b>Coded allergies on the chart</b>
      <span class="wb-query">GET /AllergyIntolerance?patient=${esc0(wbPatient)}</span></div>
    </div>`;
  WB.gaps.forEach((g,i)=>{
    html += `<div class="gapcard" id="gap${i}">
      <div class="gt">${esc0(g.text)}</div>
      <div class="gq">Said in the visit: “${esc0(g.quote||'')}”</div>
      ${resourcePreview(g.resource, g.fhir_type)}
      <div class="gbtns">
        <button class="approve" onclick="approveGap(${i}, this)">✓ Approve &amp; write to chart</button>
        <button class="reject" onclick="rejectGap(${i}, this)">Reject</button>
        <span class="result"></span>
      </div>
    </div>`;
  });
  html += `<div class="wb-skips"><details><summary>${WB.n_skipped} candidates auto-excluded by safety screens — never auto-coded</summary><ul>`
    + WB.skipped_sample.map(s=>`<li><b>${esc0(s.type)}</b> “${esc0(s.text)}…” — ${esc0(s.reason)}</li>`).join('')
    + `</ul></details></div>`;
  body.innerHTML = html;
}

async function approveGap(i, btn){
  const card = document.getElementById('gap'+i);
  const resEl = card.querySelector('.result');
  btn.disabled = true; resEl.textContent = 'Writing…';
  try{
    const resource = JSON.parse(JSON.stringify(WB.gaps[i].resource));
    resource.patient = {reference: 'Patient/'+wbPatient};
    const created = await fhir('POST', '/'+WB.gaps[i].fhir_type, resource);
    card.classList.add('written');
    card.querySelector('.gbtns .reject').style.display='none';
    btn.style.display='none';
    resEl.innerHTML = `✅ 201 Created — <span class="wb-query">${esc0(WB.gaps[i].fhir_type)}/${esc0(created.id)}</span> confirmed on chart`;
    const n = await allergyCount();
    const cnt = document.getElementById('wb-n');
    cnt.textContent = n; cnt.classList.remove('zero');
  }catch(e){
    btn.disabled = false; resEl.textContent = '⚠ write failed: '+e.message;
  }
}
function rejectGap(i, btn){
  const card = document.getElementById('gap'+i);
  card.classList.add('rejected');
  card.querySelector('.gbtns').innerHTML = '<span class="result">✗ Rejected by clinician — nothing written</span>';
}

buildSidebar(); select(cur.enc, cur.ver);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    build()
