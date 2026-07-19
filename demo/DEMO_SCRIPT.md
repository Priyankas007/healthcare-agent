# RECALL — Demo Script (~60 seconds)

*Open `http://localhost:8765`. Encounter: **"General adult exam — new
hypertension and metabolic syndrome"** → first **Degraded** copy (the HCTZ
deletion). Have it selected before recording. Cues in [brackets].*

---

**[On the note, point at the amber banner]**

"About three-quarters of ambient-scribe errors are omissions — things said in
the visit that silently never make the note. RECALL is a coverage agent that
audits every note before signature. To grade it honestly, we manufacture
ground truth: here our harness deleted one known fact from a gold note — a
new medication start."

**[Click "Run verifier engine"]**

"Four separate Opus 4.8 calls: decompose the transcript and FHIR into atomic
facts with provenance; a grounded entailment judge marks each present or
absent in the note; absent facts get severity classified; a relevance filter
surfaces only what matters."

**[Point at the red flag + evidence]**

"Caught — safety-critical: hydrochlorothiazide 25 milligrams, flagged with
the reasoning — borderline potassium on a potassium-wasting diuretic — and
grounded in both the transcript quote and the coded FHIR resource.

Across our fixed eval set: **100% recall** on 69 planted omissions, under
one surfaced flag per clean note. This is the note *before* it's signed —
the moment this data is worth the most, and today it's discarded."

---

## Q&A one-liners (keep from full version)

- **Why injection eval?** No answer key exists for omissions; deleting a
  known-present fact manufactures exact ground truth, and the fixed set makes
  every later ablation a clean delta.
- **Recall is a floor** — the honest signal is the clean-note flag rate
  (1.56 raw → 0.96 after the relevance filter, median 2 flags/note).
- **Severity disagreements:** 12/69 planted facts were down-tiered by the
  classifier; several downgrades are arguably *correct* (PHQ-2 of 2 → minor)
  — the classifier out-judging our heuristic answer key. We report it.
- **Zero invented facts** across 123 in a source-vetted multi-agent audit;
  judgment is never mixed with generation — every stage is a separate
  structured-JSON call.
