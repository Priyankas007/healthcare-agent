# RECALL — Judges' Brief (comprehensive)

## The problem (why omissions, why pre-signature)
Ambient scribes have largely solved *commission* — Abridge catches ~97% of
hallucinations. The unsolved half is **omission**: in published evaluations,
~76% of ambient-scribe errors are omissions (~69% of the severe ones), meds
are the largest severe bucket, and a UCSF study found 47% of GPT-4 ED
summaries omitted clinically relevant information. An omission is a *recall*
failure — there is no artifact in the note to point at, which is exactly why
it's harder than hallucination detection (published detector F1 ~0.59–0.64 vs
~0.72–0.85). The note is upstream of the AVS, coding, the next clinician, and
the legal record — so we audit **before signature**, the moment of maximum
leverage.

## The data
Abridge's `synthetic-ambient-fhir-25`: 25 Synthea-grounded synthetic
encounters, each with a speaker-labeled ambient transcript, a SOAP note, an
AVS, and the encounter's FHIR R4 resources (811 value-bearing Observations,
9 label-resolvable MedicationRequests, zero AllergyIntolerance — a fact we
exploit in the stretch demo). Crucially, transcript and note are
*co-generated* from the structured record, so structured→note recall is ~100%
by construction — which is why we generate our own baseline notes and
manufacture the evaluation signal by injection.

## Architecture (orchestrator–worker; every stage a separate structured-JSON Opus 4.8 call)
1. **`generate_note`** — a deliberately *naive* transcript-only scribe (B0
   baseline). No guideline scaffolding by design: its natural omissions are
   the failure mode under study; a checklist-in-prompt version is a planned
   ablation rung (R1), an experimental variable, not an assumption.
2. **`extract_facts`** — decomposes transcript + condensed FHIR (never raw
   JSON dumps) into atomic, typed clinical facts with slots (drug/dose/route/
   freq) and provenance: a verbatim transcript quote and/or a FHIR resource
   reference. One assertion = one fact.
3. **`presence`** — a grounded entailment judge, one batched call per note:
   is each fact present / partial / absent in the note *text alone*, with a
   verbatim evidence span? Key subtlety: omission detection **reverses the
   entailment direction** vs. hallucination checking — we decompose the
   *source* and test entailment against the *note*.
4. **`classify`** — for each absent fact, two judgments: `expected` (should a
   complete note for THIS visit document it — false for non-pertinent
   negatives/incidental normals) and `severity` (safety_critical / major /
   minor by impact if left uncorrected). Judgment is never mixed with
   generation; classify is a separate call from presence.
5. **`render`** — relevance filter: surface expected ∧ (safety_critical ∨
   major), ranked by severity; minors logged quietly; suppressed list kept.
   **No count cap** — flag volume is an output we measure, not a limit we
   impose.
6. **`patch` + `verify_patch`** — evaluator–optimizer loop (max 3
   iterations): propose the *minimal* grounded insertion (augment, never
   regenerate), then an independent verifier judges grounded /
   non-redundant / correctly-placed — and our code **recomputes `pass` as the
   conjunction**, never trusting the model's own verdict. Failures feed
   reasons back for revision; still-failing flags are marked unpatchable and
   surfaced without a diff.
7. **`writeback` (stretch)** — transcript-only facts absent from FHIR are
   *chart coverage gaps*. The agent structures them as FHIR R4 resources
   (`verificationStatus=unconfirmed`, transcript quote as provenance,
   provisional RxNorm/SNOMED codes marked needs-verification) and — with a
   mandatory human approval gate — POSTs to a sandbox HAPI server
   (localhost allowlist; IPV/substance/mental-health/SDOH never auto-coded).

## Evaluation methodology (the injection harness)
You cannot grade omission detection without an answer key, so we manufacture
one: take a provided gold note, delete exactly one fact that is (a) grounded
in transcript/FHIR and (b) verified present, using an LLM edit that smooths
the text; then run a **confirm-absent QC gate** (presence on the degraded
note must say absent, else discard — 6 of 75 were discarded, e.g. facts
stated in multiple places). Result: **69 confirmed single-fact deletions
across all 25 encounters** (weighted to meds/observations), plus the 25
untouched notes as a false-positive control. This is a *fixed answer key*:
later ablation rungs run against the same set, so every comparison is a clean
delta.

## Results (all numbers reproducible from committed caches)
- **Detection (CP2):** recall **100% (69/69)** — meds 41/41, observations
  20/20, red-flag screens 8/8. Clean-note flag rate **1.56/note**, explicitly
  an *upper bound* on false positives (some are genuine natural omissions).
  Injection specificity: **0.34%** collateral present→absent flips.
- **Severity + surface (CP3):** **82.6% (57/69)** detected AND surfaced. All
  12 "misses" are severity-tier calls, not detection failures: 11 downgraded
  to minor (logged, not surfaced), 1 suppressed as not-expected. On
  inspection several downgrades look *correct* (e.g. PHQ-2 score of 2 →
  minor) — the classifier out-judging our crude type-based heuristic answer
  key. Relevance filter halves the clean-note surfaced rate to **0.96/note**;
  flags/note median 2, max 4 — economical without any cap.
- **Correction (CP4):** 57/57 verifier-accepted (0 unpatchable, mean 1.32
  iterations). Fact restored: **64.9% strict** (every slot) / **94.7%
  substance** (17 partials all share one diagnosed failure mode — a dropped
  slot detail like "20 mg" or "with breakfast" — with a one-line prompt fix
  identified but not retroactively applied). **Faithfulness 96.5%** (post-hoc
  grounding, no new commission), redundancy delta ≈ 0 (thorough *without*
  bloat), and the verifier stress test rejected **10/10 deliberately bad
  patches, flagging the correct violated field every time**.
- **Write-back (CP6):** 3/3 patient-stated allergies (aspirin/peanut/dander)
  — none of which exist anywhere in the coded chart — authored, validated,
  human-approved, written to a live sandbox FHIR server, and confirmed by
  GET. 18 other candidates auto-excluded by safety screens with logged
  reasons.
- **Quality audit:** a 9-agent adversarial review vetted every extracted fact
  against source: **zero invented facts across 123**; systematic issues found
  (over-bundled multi-observation facts, inconsistent judge strictness) are
  documented in checkpoint_1.md rather than hidden.

## Engineering
Claude Opus 4.8 for every call (adaptive thinking); structured-JSON contracts
with defensive reconciliation at every stage; **prompt caching** by block
architecture (stable rules+facts prefix cached, varying note last — verified
live, 32% of CP4-run input served from cache); per-item JSON caches make every
run resumable; multi-agent workflows (108-agent research pass, 72-agent code
review, 9-agent extraction audit) used for research, review, and QA.

## Honest limitations (say these before judges do)
n=25 synthetic encounters (proof-of-concept, not a validated benchmark);
provided notes are not clinically reviewed; recall-vs-injection is partly a
floor/sanity measure — the more revealing signal is the clean-note flag rate;
the injected-severity answer key is a crude type heuristic (the classifier
demonstrably out-judges it in places); the FHIR help-vs-harm ablation (CP5)
is scaffolded but deliberately deferred; clinician validation was skipped for
time — the multi-agent audit stands in; single-model (a Haiku/Sonnet/Opus
presence-judge benchmark is scaffolded and one flag away).

## Likely judge questions
- **"Isn't 100% recall suspicious?"** It's a floor: it proves the entailment
  judge reliably detects a *clean* deletion. Its value is as a fixed answer
  key for ablation deltas. The number we watch is the clean-note flag rate.
- **"Why did surfacing drop to 82.6%?"** By design: the relevance filter
  surfaces only what a clinician should act on. Every "miss" was detected;
  they were tier-downgraded — and several downgrades are arguably right.
- **"How do you know patches don't hallucinate?"** Three ways: every added
  claim must trace to the fact's evidence; an independent verifier (that
  rejected 10/10 planted bad patches) gates acceptance; and a fresh post-hoc
  grounding check scores 96.5%. Redundancy delta ≈ 0 shows no bloat.
- **"Would this work on real data?"** The architecture makes no
  synthetic-data assumptions — inputs are a transcript and FHIR bundle. The
  eval harness ports directly: injection ground truth works on any gold note.
- **"Why not fine-tune / use embeddings?"** The task is judgment over long
  clinical context with evidence citation — frontier-model entailment with
  structured outputs beats similarity retrieval for auditability, and every
  verdict carries a quotable evidence span.
- **"What's novel?"** (1) Omission-first, pre-signature framing with a
  grounded-entailment detector; (2) the injection harness + confirm-absent QC
  as a reusable, fixed answer key; (3) an evaluator-optimizer patch loop
  whose verifier is independently stress-tested; (4) chart write-back of
  discarded conversational data under a hard human-approval gate.
