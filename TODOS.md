# RECALL — Task Tracker

Legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked

## Checkpoint 0 — Data prep + baseline note generation
- [x] Scaffold repo (venv, TODOS.md, LOGS.md, .gitignore)
- [x] `recall/llm.py` — shared Anthropic client + robust JSON parsing (Opus 4.8, adaptive thinking)
- [x] `recall/generate_note.py` — transcript → SOAP note (B0 baseline)
- [x] `recall/extract_facts.py` — transcript + encounter FHIR → CandidateFact list
- [x] `recall/presence.py` — note + facts → PresenceResult list (one batched call/note)
- [x] `run_checkpoint0.py` — inventory + hero shortlist + generate 25 baseline notes
- [x] Inventory smoke test passed (811 obs w/ values; 9 labeled MedReqs in 4/25; heroes picked)
- [x] Multi-agent code review (ultracode) — 0/23 findings confirmed; 4 rejected-but-useful fixes applied anyway (see LOGS.md)
- [x] Obtain `ANTHROPIC_API_KEY` (via `.env`) — verified with live call
- [x] Run checkpoint 0 → `generated_notes/{id}.md` × 25 + `checkpoint_0.md` ✅ 25/25

## Checkpoint 1 — Detection core (extract_facts + presence)
- [x] `run_checkpoint1.py` — 3 hero cases: extract_facts → presence vs **provided** note
- [x] Run checkpoint 1 → `checkpoint_1.md` ✅ 3 cases: 30/53/40 facts; 26+3+1 · 49+0+4 · 33+6+1 (present·partial·absent)
- [x] Multi-agent audit (ultracode) — 9 agents, all claims source-vetted: **0 invented facts**; over-bundling + judge-strictness issues written into checkpoint_1.md
- [x] ~~Human (clinician) eyeball pass~~ — **skipped for time** (user call); AGREE? column removed; audit serves as the quality gate

## Checkpoint 2 — Injection harness + first numbers
- [x] `recall/harness_inject.py` — target selection, LLM note edit, confirm-absent QC, InjectionRecords
- [x] `recall/eval_runner.py` — detection-only eval on injected + clean sets → EvalResults
- [x] `recall/metrics.py` — recall (overall/by severity), clean-note flag rate, injection specificity
- [x] `run_checkpoint2.py` — orchestration w/ caching (extract_facts once per encounter) + checkpoint_2.md
- [x] Dry-run: target selection (meds-first ✓) + metrics math ✓ (no API)
- [x] Run: **DONE — recall 100% (69/69)**, clean-note flag rate 1.56/note (FP upper bound), collateral flip rate 0.34%; 25/25 encounters covered; checkpoint_2.md written
- [x] Prompt caching added mid-run (presence + inject prompts restructured; verified 1,737-token prefix hit live)
- [ ] Optional: presence-judge model benchmark (Haiku vs Sonnet vs Opus) — incremental `--benchmark` rerun, caches make it cheap

## Checkpoint 3 — Severity classification + relevance-filtered surface
- [x] `recall/classify.py` — expected + severity judge (batched per note; separate from presence)
- [x] `recall/render.py` — relevance filter (expected ∧ major/safety) + severity sort, **no cap**; minor logged quietly
- [x] `run_checkpoint3.py` — reuses checkpoint-2 caches (zero new presence calls); gated on checkpoint-2 completion
- [x] Render logic unit-tested (sort/filter/suppress ✓, demo markdown ✓)
- [x] Gates read from checkpoint_2.md: flag rate LOW (1.56 ≲ 3 → build straight through); 0 misses (no presence fix needed); classify model = Opus 4.8 (user override stands)
- [x] Run full chain on injected + clean sets → **DONE: 57/69 = 82.6% detected-AND-surfaced**; clean surfaced-flag rate 0.96/note (vs 1.56 raw); flags/note median 2, max 4 — surface economical with no cap
- [ ] Suppression spot-check + severity calibration review — **12 "misses" are all severity-tier disagreements** (classifier downgraded heuristic-major → minor ×11, expected=false ×1), not detection failures; needs eyeball: is the classifier right and the heuristic answer key wrong (e.g. PHQ-2 score 2 → minor looks correct)?

## Checkpoints 4–6 (scaffolds DONE — ultracode workflow, 6 agents, all reviews passed)
- [x] CP4 scaffold: ready (49/49 mock tests; reviewer added eval-cache gate); 57 eligible flags (69 − 12 not-surfaced)
- [x] CP4 RUN **DONE** (274 calls, 32% cache-read): 57/57 patched, 0 unpatchable, mean 1.32 iterations; **restore 37/57 = 64.9% strict / 54/57 = 94.7% substance** (17 partials = slot-truncation, 3 true failures); faithfulness 96.5%; redundancy Δ ≈ 0; verifier stress 10/10 rejected w/ correct field. Diagnosis appended to checkpoint_4.md
- [ ] Optional prompt fix (require all slots in insert_text) + rerun 20 non-restored — **user decision** (changes reported numbers)
- [x] CP5 scaffold: ready (reviewer fixed skipped-R3 crash path + report key mismatch); **run deferred** (user call)
- [x] CP6 scaffold: ready (reviewer extended negation screening, tightened gates); **HAPI FHIR server UP** (R4, localhost:8080)
- [ ] CP6: run the write-back demo (interactive approval gate) when user is ready to film it
- [ ] Post-run: fold CP4 metrics into demo assets; optional CP2 `--benchmark`

## Demo assets
- [x] `demo/build_demo_ui.py` → `demo/index.html` — self-contained UI, cached data only (25 encounters, 94 note versions), "Run verifier engine" staged replay, architecture flowchart + sources, planted-omission ground-truth banner
- [x] Served at http://localhost:8765 (background `http.server`); page + data + JS verified
- [x] `demo/DEMO_SCRIPT.md` — ~2-min technical narration + Q&A one-liners
- [ ] User: film pass 1 (detection story); pass 2 (patch before/after) once CP4 run lands

## Later checkpoints (DO NOT BUILD YET)
- retrieve_fhir (targeted/full-chart arms) · patch + verify_patch · contradiction class · run_ablation
