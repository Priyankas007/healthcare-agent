# RECALL — Working Log / Scratchpad

## 2026-07-18 — Session: Checkpoints 0 & 1

### Decisions
- **Model:** `claude-opus-4-8` for **everything** (user override 2026-07-18, supersedes the checkpoint spec's Sonnet default). Adaptive thinking enabled explicitly (`thinking: {"type": "adaptive"}`) — on Opus 4.8, omitting the field runs WITHOUT thinking, unlike Sonnet 5. Override with `RECALL_MODEL` env var if needed.
- **Env:** Python 3.13 venv at `.venv/`, `anthropic` 0.117.0. API key loaded from `.env` (gitignored) since no env var / `ant` profile exists on this machine.
- **Data path:** `synthetic-ambient-fhir-25/synthetic-ambient-fhir-25.jsonl` (copy inside this repo). Override with `DATA_PATH` env var.
- **Two notes kept straight:** `record["note"]` = provided note (gold for later injection — never modified). Generated notes (B0) go to `generated_notes/{id}.md`.
- **JSON robustness:** all LLM calls prompt for JSON-only; parser strips fences/prose, one retry with a stricter reminder on failure.
- **Concurrency:** ThreadPoolExecutor(4) for the 25 note generations; SDK auto-retries 429s.
- **Token budgets:** thinking tokens count toward `max_tokens`, so budgets are generous (8k notes / 16k extract & presence).
- **"Abnormal Observations" column:** dataset Observations rarely carry `interpretation`, so we count Observations *with a value present* (valueQuantity/CodeableConcept/String/components) as the ground-truth-substrate proxy, and separately count flagged-abnormal where `interpretation` exists.
- **Ultracode:** user opted in mid-session — multi-agent workflows for code review (pre-run) and checkpoint-1 quality audit (post-run).

### Questions (open)
- Hero-case final pick: computed programmatically (rank by labeled MedicationRequests, then obs-with-values) — sanity-check against scoping doc's expectation (SNF/COVID admissions richest).
- COVID admission has 22 MedicationRequests but reference-based (no inline drug label) per scoping doc — verify in inventory; if labels unresolvable it should rank below SNF cases.

### Design changes (user decisions)
- **2026-07-18: ≤3-flag cap DROPPED.** The review surface shows ALL flags, ranked severity → evidence-confidence, no top-3 collapse. Scoping doc updated in 6 places (§1, §4, §6.7, §7 locked table, §9 metric now "flag ranking quality: true major ranked at/near the top", §12). No checkpoint-2 code impact (rendering is a later checkpoint); the injection cap of ≤3/note is unrelated and stands.

### Prompt caching (added mid-checkpoint-2, verified live)
- **Where it pays (shared prefixes across single-turn calls):** presence — same encounter's fact list judged against ~4 note versions → prompt reordered to `[rules+FACTS]` (cached block) + `[NOTE]` (varying, last); injection edit — same note edited 3× → `[rules+NOTE]` (cached) + `[FACT]`, retry suffix rides the varying block so retries still hit. extract_facts/generate_note/classify skipped — no reusable prefix ≥1024-token Opus 4.8 minimum.
- **Mechanics:** `llm.call_text/call_json` accept block lists with `cache: True` → `cache_control: {"type":"ephemeral"}` breakpoints; JSON-retry reminder appended as a new block AFTER the cached prefix; eval jobs sorted by encounter for 5-min-TTL locality; USAGE counters + `usage_summary()` printed at end of runs.
- **Verified:** paired presence test — call 1 wrote 1,737 prefix tokens, call 2 read 1,737 from cache (0.1× price). Confirm-absent single-fact calls fall under the 1,024-token minimum → silently uncached, harmless.
- **Consistency note:** the in-flight checkpoint-2 process uses the OLD prompt order (loaded before the edit — not stopped, per user). Its cached eval JSONs remain the fixed answer key; new prompt order applies from checkpoint 3 / benchmark / reruns onward. Prompt reorder does not change judgment rules.

### Checkpoint 3 scaffolding decisions (built while checkpoint 2 runs)
- **Zero new presence calls needed:** checkpoint-2's eval cache stores full presence results per degraded note, and presence_provided covers the clean set — checkpoint 3 only adds ~1 batched classify call per note version with absent facts (~100 calls total), plus pure-Python render/metrics.
- **classify is batched per note** (list in/list out) like presence, for cost — the spec's per-fact contract is preserved per element; judgment prompt verbatim. classify stays a separate call from presence (guardrail).
- **Tie-break proxy:** presence emits no numeric confidence, so "severity then presence-confidence" is implemented as severity → fact-type priority (medication/observation first) → fact id. Documented in render.py; revisit if we add a confidence signal.
- **Reconciliation is conservative:** missing/invalid classifier verdicts keep the flag (expected=true, minor) rather than silently dropping — suppression must be earned, not defaulted.
- **Run gate encoded in run_checkpoint3.py:** asserts checkpoint-2 injections exist; instructions to read checkpoint_2.md (miss rate → fix presence first; benchmark → --model pick) before running.

### Checkpoint 2 decisions
- **Clinician review skipped** (user call, time): AGREE? column removed from checkpoint_1.md; the 9-agent audit is the quality gate.
- **Audit results (all vetted):** 0 invented facts across 123. Systematic issues: over-bundling (BMP analytes, vitals, PRAPARE), inconsistent judge strictness (~8 present→partial under-calls, mostly med timing/instructions), missed history facts in the geriatric case (prior MI, metabolic syndrome, variable home BP). Written into checkpoint_1.md.
- **Audit → checkpoint-2 implications:** (a) injected med facts may be judged leniently (timing detail dropped ≠ absent) — the confirm-absent QC gate protects the answer key; (b) bundled facts are risky injection targets (partial deletion possible) — accepted for now, harness discards on failed confirm.
- **Injection edits use Opus 4.8** (spec text said Sonnet; user's earlier "Opus for everything" override stands).
- **Checkpoint-2 caches fresh for all 25** (not reusing checkpoint1_artifacts for the 3 heroes): condense_fhir changed post-audit (dose/freq fix), so all facts come from the same extractor version — cleaner fixed answer key.
- Severity heuristic: medication/observation/red_flag_screen/order/referral→major; followup/symptom/sdoh/counseling→minor; nothing maps to safety_critical yet (no usable AllergyIntolerance in dataset — allergy scenarios need labeled synthetic injection later).
- Benchmark (Haiku/Sonnet/Opus presence-judge comparison) deferred to a post-run pass: caches make it a cheap incremental `--benchmark` rerun.

### Checkpoint 3 results (2026-07-18)
- **57/69 = 82.6% detected AND surfaced.** ALL 12 "misses" are severity-tier calls, not detection failures: presence caught every injected fact (CP2 recall stays 100%); the classifier then rated 11 of them `minor` (→ logged, not surfaced) and 1 `expected=false`. Several downgrades look CORRECT on inspection (e.g. PHQ-2 score 2, low/no-action → minor) — i.e. the crude type-based heuristic in the answer key over-tiers some facts. This is a calibration finding, not a bug; the spec's suppression spot-check should adjudicate.
- Severity calibration (heuristic major → classifier): 36 major · 21 safety_critical · 12 minor.
- **Relevance filter earns its place:** clean-note surfaced-flag rate 0.96/note vs 1.56 raw absent-rate; flags/note median 2, max 4 — no cap needed, volume stays clinician-usable.
- Usage: 89 calls, 0% cache — expected (classify prompts share no ≥1024-token stable prefix; caching pays in presence/edit calls, not classify).
- Rendered hero surfaces look demo-ready (severity-ranked, why-it-matters, transcript+FHIR evidence).

### Scaffold workflow results (CP4/5/6 — 6 agents, ~1.9M tokens)
- All three checkpoints **ready_with_fixes_applied**. Notable reviewer catches: CP5 run_R4/R5 crashed on a skipped-R3 dict (guard added) + report read wrong key (`examples` vs `full_arm_examples`); CP6 negation screen missed 5 real negative-fact phrasings ("none reported", "not taking"…) and write-receipt cache bug; CP4 needed an eval-cache completeness gate.
- CP4 design highlights (from builder): verify_patch recomputes `pass` in code (never trusts model's own); apply_patch fully deterministic (verified section headers uniform across all 94 notes); evidence_for inlines actual FHIR resource content (deliberate strengthening over ref-string); redundancy = repeated 5-gram rate (no embedding dep); 10 deterministic stress patches (4 ungrounded / 4 redundant / 2 misplaced). Same-note items sorted adjacent for cache TTL locality.
- Known minors accepted: --workers-as-last-arg IndexError (consistent with other runners); partial-failure count not in report (resumable rerun heals); some cached prefixes below 1024-token min (silently uncached, harmless).
- **CP4 run launched** (57 eligible = 69 − 12 not-surfaced; note: eligibility recomputes from checkpoint3 cache). CP5 run deferred per user. CP6 ready to demo against live HAPI server.

### Demo assets (2026-07-18)
- demo/index.html (self-contained, cached-data replay, 25 encounters / 94 versions) served at localhost:8765; demo/DEMO_SCRIPT.md cut to ~60s around the HCTZ safety-critical case (quote + MedicationRequest dual evidence; potassium 3.97 rationale). Backup: lisinopril inj_1. Q&A one-liners retained.

### Events
- Scaffolded repo; venv created; SDK installed.
- Blocked briefly on API key; user added `.env`; key verified with live Opus 4.8 call.
- Inventory smoke test: 811 obs-with-values / 9 labeled MedReqs in 4 encounters / COVID 0/22 labeled — matches scoping doc. Heroes: HTN-initiation, geriatric cardiometabolic, new-HTN+metabolic (the 3 encounters with labeled MedicationRequests).
- Single-note smoke test: ~30s/note, clean SOAP output, transcript-grounded.
- Checkpoint 0 full run launched in background (4 workers, skip-if-exists = resumable).
- Ultracode code-review workflow launched (3 lenses + adversarial verify); findings to be applied before checkpoint 1.
- **Checkpoint 0 DONE:** 25/25 baseline notes generated (Opus 4.8, transcript-only), `checkpoint_0.md` written.
- **Code review returned:** 72 agents, 23 raw findings, 0 confirmed by the 2/3-refuter bar. Independently verified + fixed 4 of the rejected-but-useful ones anyway:
  1. `condense_fhir` — dose lives in the drug *label* (not lost), but frequency (`timing.repeat`) and structured `doseAndRate` quantity WERE dropped for 6/9 labeled meds → now rendered (`dose=`, `freq=`). Matters: med/dose/freq is the top injection bucket.
  2. `extract_facts` — now drops non-dict/text-less entries and dedupes model-supplied fact ids (prevented silent presence mis-mapping).
  3. `call_text` — truncation now retries once at 2× budget (adaptive thinking counts toward max_tokens); `refusal` stop_reason raises informatively instead of returning "".
  4. `run_checkpoint1` — resumable: cached artifacts are reused, so a failure on case 3 doesn't re-spend cases 1–2.
  Deliberately NOT fixed (judged non-issues here): `::` in filenames (macOS-only project), client() singleton race (benign), RECALL_MODEL env override (intentional escape hatch), extra `#` id column in checkpoint_1 table (aids audit cross-referencing).
