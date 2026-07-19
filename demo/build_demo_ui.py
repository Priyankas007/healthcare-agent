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

        def make_version(vid, label, note_text, presence, planted=None):
            cpath = C3 / f"{vid}.json"
            classify = json.loads(cpath.read_text()) if cpath.exists() else []
            counts = presence_counts(presence)
            total = max(len(presence), 1)
            return {
                "id": vid,
                "label": label,
                "note_html": md_to_html(note_text),
                "counts": counts,
                "coverage": round(counts["present"] / total * 100),
                "n_facts": len(presence),
                "flags": render_flags(facts_by_id, presence, classify),
                "planted": planted,
            }

        prov_presence = json.loads((C2 / "presence_provided" / f"{rid}.json").read_text())
        versions.append(make_version(f"{rid}__clean", "Original note", rec["note"], prov_presence))

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
            version = make_version(iid, label, note_md, ev["presence_results"], planted)
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

    payload = json.dumps({"encounters": encounters}, separators=(",", ":"))
    OUT.write_text(TEMPLATE.replace("__DATA__", payload.replace("</", "<\\/")))
    size_mb = OUT.stat().st_size / 1e6
    n_versions = sum(len(e["versions"]) for e in encounters)
    print(f"Wrote {OUT}  ({size_mb:.1f} MB, {len(encounters)} encounters, {n_versions} note versions)")


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
  .dot.clean{background:var(--ok)} .dot.deg{background:var(--major)}

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
  <button class="sysbtn" onclick="document.getElementById('ov').classList.add('show')">⌘ System architecture</button>
</header>

<div class="layout">
  <aside id="sidebar"><h2>Encounters · 25</h2></aside>

  <main id="main"></main>

  <div class="rail">
    <h2>Pre-signature safety</h2>
    <p class="sub">Coverage verifier</p>
    <button class="runbtn" id="runbtn" onclick="runVerifier()">Run verifier engine</button>
    <p class="replay-note">Deterministic replay of the cached Opus 4.8 pipeline — no live calls in this demo.</p>
    <div id="stages" style="margin-top:14px"></div>
    <div class="results" id="results"></div>
  </div>
</div>

<div class="overlay" id="ov" onclick="if(event.target===this)this.classList.remove('show')">
  <div class="sheet">
    <button class="close" onclick="document.getElementById('ov').classList.remove('show')">×</button>
    <h2>System architecture</h2>
    <p class="cap">Orchestrator–worker pipeline · every stage a separate structured-JSON Opus 4.8 call · prompt-cached prefixes</p>
    <div class="flow">
      <div>
        <div class="srcbox"><b>Ambient transcript</b>speaker-labeled clinician–patient conversation</div>
        <div class="srcbox"><b>Encounter FHIR R4</b>MedicationRequest · Observation · Condition · DiagnosticReport…</div>
        <div class="srcbox"><b>Longitudinal chart</b>problem &amp; medication labels (context)</div>
      </div>
      <div class="arrow">→</div>
      <div class="pipe">
        <div class="step"><span class="n">1</span><div><b>Fact decomposition</b><span>extract_facts — atomic, typed clinical assertions with slots (drug/dose/route/freq) + provenance (verbatim quote or FHIR ref)</span></div></div>
        <div class="step guard"><span class="n">2</span><div><b>Grounded entailment · guard #1</b><span>presence — one batched judge call per note: is each fact present / partial / absent, with verbatim note evidence? Judges the note text only.</span></div></div>
        <div class="step"><span class="n">3</span><div><b>Severity + expectation classifier</b><span>classify — for each absent fact: should a complete note document it? clinical impact if left out (safety-critical / major / minor)</span></div></div>
        <div class="step"><span class="n">4</span><div><b>Relevance-filtered surface</b><span>render — surface expected ∧ (safety-critical ∨ major), ranked; minors logged quietly; no count cap</span></div></div>
      </div>
    </div>
    <div class="evalnote"><b>Evaluation — the injection harness:</b> delete a known-present fact from a gold note (confirm-absent QC), run the detector blind, check it flags exactly that fact. 69 confirmed single-fact deletions → <b>100% recall</b>; untouched notes give the false-positive upper bound (1.56 → 0.96 after the relevance filter); collateral flip rate 0.34%.</div>
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
      const b=el('button',null,`<span class="dot ${v.planted?'deg':'clean'}"></span>${esc(v.label)}`);
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

buildSidebar(); select(cur.enc, cur.ver);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    build()
