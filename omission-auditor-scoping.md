# Pre-Signature Coverage Agent for AI-Generated Clinical Notes

**Codename:** RECALL · **Event:** Anthropic × Abridge × Lightspeed hackathon · **Priority:** eng-first, clinician-validated, Monday-ready · **Status:** build-ready

---

## 1. What it is

Every ambient-generated note passes through an independent **coverage agent before signature**. The agent reconstructs the clinically important facts from the transcript and *dynamically-retrieved, relevant* FHIR, detects what the note omitted, and returns a clinician-usable surface: **all flags, ranked** (severity → evidence-confidence), each with its transcript span, FHIR evidence, why it could matter, a proposed note diff, and one-click **accept / edit / dismiss** — with a verifier ensuring each patch adds **no unsupported claims**. Evaluated with a controlled omission-injection harness for real recall / precision / false-positive numbers.

## 2. Why (concise)

Ambient scribes have largely solved commission (Abridge catches ~97% of hallucinations); the unsolved half is **omission** — clinically important content discussed or decided but silently dropped. It's more frequent (**~76% of ambient-scribe errors**, **~69% of the severe ones**), harder (a *recall* failure with no artifact to point at; detectors score F1 ~0.59–0.64 vs ~0.72–0.85 for hallucination), and higher-impact (the note is upstream of the AVS, coding, the next clinician, and the legal record). No one publicly ships note-omission detection grounded in FHIR — and it *extends* Abridge's thesis rather than competing.

## 3. Definition (borrowed authority, three failure classes)

> An **omission** is a clinically important fact evidenced in the transcript and/or clinically relevant in FHIR, expected in the note by a documentation standard, yet absent — tiered by severity.

- **FHIR never suppresses.** A coded `MedicationRequest` does not make the note complete: "start lisinopril," if said and undocumented, is still an omission. FHIR modulates **confidence/severity** and feeds a *separate* class (contradiction). See matrix, Appendix C.
- **Three classes, evaluated separately:** **omission** (primary), **chart-critical coverage** (FHIR-only relevant), **contradiction** (note conflicts FHIR — never folded into omission).
- **Standard = PDQI-9 "Thorough" + SOAP completeness + E/M pertinence.** Severity = npj major/minor; flag major/safety-critical only.
- **Not an omission:** redundancy/bloat (separate axis; we target thoroughness, never conciseness), facts already entailed anywhere in the note, non-pertinent negatives, incidental normals, irrelevant chart background.

## 4. Scope

**In:** the SOAP **note** audited before signature, across all 25 encounters (2–3 hero cases live); `transcript → note` generation (Claude); the ranked-flag review surface (no cap); omission + coverage + contradiction (separated); injection eval + physician-validated tiers.
**Out:** AVS/discharge paths, redundancy detection, EHR write-back, the Abridge API, fine-tuning, default full-chart FHIR ingestion.

## 5. Data — exactly what's provided (no overclaiming)

`patient_context`: demographics, resource_counts, condition_labels, medication_labels. Encounter `related_resources`: Condition, **Observation (811)**, Procedure (515), DiagnosticReport (143), **MedicationRequest (32)**, Immunization (20), one ImagingStudy.

- **No usable `AllergyIntolerance` resources** — it appears *only as a count* in resource_counts (no substance/code). Allergy scenarios require a **labeled synthetic** `AllergyIntolerance` injection; never imply the data contained one.
- **`MedicationRequest` is sparse/uneven:** 6/25 encounters, ~9 with resolvable drug labels (COVID admission's 22 are reference-based).
- **Abnormal `Observation`s (811) are the richest ground-truth substrate** → default hero material, then labeled med changes.
- **Pipeline reality:** provided transcript + note are co-generated from Synthea FHIR (not `transcript → note`), so structured→note recall is ~100% by construction — hence we generate our own note and manufacture the eval signal by injection.
- **Complementary (open):** ACI-Bench (207, dialogue↔note alignment — primary external anchor), PriMock57 (57, published omission baselines), MEDIQA-OE (gold orders). MIMIC = credentialed scale-up.

## 6. System design

**Pattern:** orchestrator-workers workflow with two agentic pockets — dynamic FHIR retrieval, and the evaluator-optimizer patch loop. Most of it is a deliberate workflow (per *Building Effective Agents*); we say so.

1. **Generate** `transcript (± FHIR) → SOAP note` (Claude).
2. **Reconstruct candidate facts** — parallel transcript-claim + encounter-FHIR extractors; terminology normalizer merges variants.
3. **Presence check (guard #1)** — one batched, structured entailment call per note: is each fact entailed *anywhere* in the note? Already-covered ⇒ not an omission (keeps it clinically useful, prevents manufactured redundancy).
4. **Dynamic FHIR retrieval (agentic #1)** — for surviving candidates, the agent decides *which resource types* to pull (meds / conditions / observations / procedures) and retrieves only those. No full-chart dump.
5. **Classify & score (routing)** — expected-by-standard? severity? evidence-pattern → confidence/severity; route note-vs-FHIR conflicts to the contradiction class.
6. **Patch + verifier (guard #2, agentic #2)** — propose a minimal diff (section + insert + merge/append); patch verifier checks grounded (no unsupported claims), non-redundant, correctly placed; revise on fail.
7. **Render** — all flags, ranked by severity then evidence-confidence (no cap, no collapse — updated 2026-07-18), each with span + FHIR evidence + why-it-matters + diff + accept/edit/dismiss.

**Tools:** dynamic FHIR query (targeted), PDQI-9/SOAP checklist lookup, ICD/terminology normalizer.

## 7. Locked build decisions

| Decision | Locked choice |
|---|---|
| Correction | **Augment (minimal diff)**, not regenerate |
| Fact granularity | **One clinical assertion = one fact**, typed slots (med → drug/dose/route/freq) |
| Presence check | **One batched structured entailment call/note**; per-fact only for hero cases |
| Model routing | **Sonnet** extract/entail · **Opus** severity/patch/verify |
| Headline metrics | Primary = injection recall/precision/FP; **PDQI-9 "thorough" as secondary** |
| Kappa | Physician adjudicates **15–20 gray-zone flags**, 3-way, Cohen's kappa vs system |
| Flag count | **No cap** (updated 2026-07-18): all flags surfaced, ranked severity → evidence-confidence |
| MEDIQA-OE slice | Stretch, not day-1 |

## 8. Ablation (the research spine) + the honest FHIR question

Toggleable stack; run the eval at each rung. **We do not pre-commit to "FHIR improves precision."** The question is *when does longitudinal FHIR context help or harm omission detection?* — targeted retrieval may raise confidence/severity while **full-chart context may lower precision** by dragging in irrelevant history. "Targeted helps, full-chart hurts" would be a genuinely Anthropic-style finding; run **targeted vs. full-chart** as an explicit arm and report whichever way it falls.

| Rung | Adds | Tests |
|---|---|---|
| B0 | generation only | baseline "before" |
| R1 | checklist in gen prompt | prompt-time reduction |
| R2 | presence guard #1 | detection, no FHIR |
| R3 | dynamic (targeted) FHIR | evidence-pattern confidence/severity |
| R4 | patch + verifier (guard #2) | the "after," no new commission |
| R5 | contradiction class + full-chart arm | separation + the honest FHIR finding |
| R6 | normalizer / tuning | precision/FP |

## 9. Evaluation

**Job 1 — manufactured ground truth (injection harness).** Per note: LLM removes one tagged fact + smooths text → **confirm absent via presence check** (discard if it survives) → record `InjectionRecord`. ~3/note weighted to meds/abnormal-obs; 25 clean notes for FP; a separate **~15–20 planted contradictions**. Allergy injections add a labeled synthetic `AllergyIntolerance`.

**Metrics:** recall by severity tier · precision · **FP-rate on clean notes (an upper bound — physician gray-zone adjudication converts it to a true estimate, since some clean-note flags are genuine omissions)** · patch faithfulness (added content grounded) · redundancy delta (self-overlap before/after patch) · contradiction detection (separate) · flag ranking quality (true major ranked at/near the top) · PDQI-9 thorough (secondary).

**Job 2 — real detection (demo).** Full agent on a transcript-only Claude note, rendered in the review surface. The before/after live moment.

**Physician (named):** define tiers up front; adjudicate the gray-zone slice for kappa near the end.

## 10. Data contracts

```
CandidateFact { id, text, type, slots{}, source: transcript|fhir|both,
                transcript_span{quote,idx}|null, fhir_ref|null }
Flag { fact_id, failure_class: omission|coverage|contradiction,
       severity: safety_critical|major|minor,
       evidence_pattern: transcript_only|transcript_fhir|fhir_only|conflict,
       why_it_matters, transcript_span, fhir_evidence,
       proposed_diff{section, insert_text, mode: append|merge}, patch_verified }
InjectionRecord { note_id, fact, type, severity, deletion_method, confirmed_absent }
```

**Modules (each togglable):** `generate_note` · `extract_facts` · `presence` · `retrieve_fhir` · `classify` · `patch` · `verify_patch` · `render` · `harness_inject` · `run_ablation` · `metrics`.
**Ablation config:** `{checklist_in_gen, presence_guard, fhir: off|targeted|full, patch, contradiction, normalizer}`.

## 11. Build order (thinnest vertical slice first)

1. `generate_note` + `extract_facts` (transcript-only) + `presence` → absent-fact list *(riskiest integration — do first)*.
2. `harness_inject` + `metrics` → first recall/FP numbers on one config *(prove the loop end-to-end)*.
3. `classify` + `render` → the ≤3-flag surface.
4. `patch` + `verify_patch` → the "after."
5. `retrieve_fhir` targeted + evidence-pattern → R3.
6. full-chart arm + contradiction → R5 *(protect from the cut list — the honest finding lives here)*.

## 12. Positioning

Monday-ready ranked-flag pre-signature surface · dynamic agent-decided retrieval + evaluator-optimizer patch loop (agentic depth) · honest "when does FHIR help/harm" finding + an ablation that can show a component that *harms* · clean omission/contradiction split · PDQI-9-grounded, physician-validated. To eng judges: retrieval-as-decision, eval rigor, the reusable injection harness. To Abridge: extends confabulation work into the recall half. To GTM/Lightspeed: the pre-signature safety surface and "data currently discarded."

## Appendix A — Injection taxonomy (grounded)

Omissions = 76.3% of ambient-scribe errors, 69% of severe, 38% medication-related (ScienceDirect 2025); VA 2024 (PDQI-9, transcript-vs-note): most patient-raised issues absent from notes; Weiner: 455 undocumented vs 181 falsely documented.

| # | Type | Severity | Dataset support |
|---|---|---|---|
| 1 | Medication / dose change | Major | Labeled `MedicationRequest` (~9) |
| 2 | Actionable abnormal result | Major | **Abundant** (`Observation` 811) — preferred |
| 3 | Red-flag exam/assessment finding | Major | Observations / narrative |
| 4 | Follow-up / return interval | Minor–Major | Transcript / note |
| 5 | Patient-reported symptom (buried) | Minor–Major | Transcript |
| 6 | Allergy (pre-prescription) | Safety-critical | **Labeled synthetic injection only** (literature, not this dataset) |

## Appendix C — Evidence-pattern → interpretation

```
Transcript only                 → candidate omission (baseline confidence)
Transcript + corroborating FHIR → high-confidence omission (raise severity)
FHIR only, clinically relevant  → chart-critical coverage candidate
Transcript conflicts with FHIR  → reconciliation needed — do NOT auto-patch
Note conflicts with FHIR        → contradiction — SEPARATE failure class
```
FHIR modulates confidence/severity; it never suppresses a documentation omission.
