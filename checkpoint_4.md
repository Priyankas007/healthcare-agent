# Checkpoint 4 — Patch + independent verifier loop

**Top line:** 37/57 accepted patches restored the missing fact (65%); post-hoc grounding 96%; mean redundancy Δ +0.0005 (repeated 5-gram rate); verifier stress test rejected 10/10 bad patches — patching needs attention before building further rungs.

## Metrics

| Metric | Value |
|---|---|
| Eligible degraded notes (omission caught AND surfaced) | 57 (skipped: 0 not detected, 12 not surfaced) |
| Patched (verifier accepted within 3 iterations) | 57/57 |
| Unpatchable rate | 0/57 = 0.0% |
| **Patch success (fact restored ÷ patched) — HEADLINE** | **37/57 = 64.9%** |
| Patch success — safety_critical | 14/21 = 66.7% |
| Patch success — major | 23/36 = 63.9% |
| Patch faithfulness (fresh post-hoc `grounded`) | 55/57 = 96.5% |
| Redundancy Δ (repeated 5-gram rate, after − before) | mean +0.0005 · max +0.0299 |
| Loop stats | mean iterations 1.32 · hist {1: 41, 2: 14, 3: 2} · unpatchable 0 |
| Verifier efficacy (stress test) | rejected 10/10; correct field caught it 10/10 |

## Verifier stress test detail

| Kind | Rejected | Target field caught |
|---|---|---|
| misplaced | 2/2 | 2/2 |
| redundant | 4/4 | 4/4 |
| ungrounded | 4/4 | 4/4 |

## Before/after diffs (picked from actual results)

#### Clean accept (first-try pass) — `01573895-dbf5-29c6-4ef9-cd09aecc51f6::01573895-dbf5-29c6-f885-ade2bd6537a5__inj_0` (major)

- Missing fact: “Uses OTC naproxen 220 mg with food, one to two times per week for hand pain”
- Patch → **Subjective** (append), iterations 1, fact_restored: ✅

Diff (degraded → patched):

```diff
@@ -1,0 +2 @@
+Uses OTC naproxen 220 mg with food, one to two times per week, for hand pain.
```

Section tail after patch: > …ns, dyspnea, fever, GI bleeding symptoms, or unintentional weight change. Never-smoker; alcohol about two beers on Saturdays; no other substances. No medications. No known allergies.
Uses OTC naproxen 220 mg with food, one to two times per week, for hand pain.

#### Revised by the loop (rejected → fixed) — `374e68b2-ee15-0852-cd48-3c7b6fd8e114::374e68b2-ee15-0852-8f80-26e1007e6c00__inj_0` (major)

- Missing fact: “Patient takes no daily prescription medications; hospital medications tapered off at follow-ups”
- Patch → **Assessment and Plan** (append), iterations 2, fact_restored: ✅
- First-round rejection reasons (fixed by the loop):
  - First claim (no daily prescription medications) is supported by 'Nothing regular.'
  - Second claim's phrase 'discontinued at follow-up visits' is not supported; evidence says medications were whittled down 'and then off entirely' after leaving the hospital, with no mention of follow-up visits.
  - Insertion adds specific medication detail not already in the note, so non-redundant.
  - Medication content correctly belongs in the Assessment and Plan medication review section.

Diff (degraded → patched):

```diff
@@ -39,0 +40 @@
+Patient takes no daily prescription medications; hospital medications were tapered down and then discontinued entirely after discharge.
```

Section tail after patch: > …rus, trivalent, preservative-free) administered today.
- Follow-up visit in approximately 6 months, sooner for any concerns.
Patient takes no daily prescription medications; hospital medications were tapered down and then discontinued entirely after discharge.

#### Rejected / unpatchable (surfaced without diff)

_No case of this kind occurred in this run._

## Diagnosis of non-restored patches (post-run analysis)

Restore-check statuses across all 57 accepted patches: **37 present · 17 partial · 3 absent**.

The 17 `partial` cases share a single failure mode: the patch restored the core clinical
assertion but dropped one slot-level component (e.g. drug restored without the "20 mg"
dose; vaccine documented without the administration site; GAD-7 score without its
interpretation), and the presence judge — intentionally strict — demands every component.
Counting clinical-substance restoration (present **or** partial), patches succeed in
**54/57 = 94.7%**; the 64.9% headline is the strictest full-slot bar. Only 3/57 patches
genuinely failed to land the fact.

**Actionable fix (future tuning rung):** require `insert_text` to carry every slot of the
missing fact explicitly in the patch prompt. Not applied retroactively — the numbers above
reflect the prompt as originally specced.
