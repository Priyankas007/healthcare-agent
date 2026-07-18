# Checkpoint 2 — Injection harness + first detection numbers

**Top line:** recall 100% on 69 confirmed single-fact deletions with a clean-note flag rate of 1.56 facts/note (upper bound) — detection works well enough to build on.

## Metrics

| Metric | Value |
|---|---|
| **Recall (primary)** | **69/69 = 100.0%** |
| Recall — major | 69/69 = 100.0% |
| Recall — type: medication | 41/41 = 100.0% |
| Recall — type: observation | 20/20 = 100.0% |
| Recall — type: red_flag_screen | 8/8 = 100.0% |
| Clean-note flag rate (**FP upper bound**) | 1.56 facts/note across 25 untouched notes |
| Injection specificity (collateral present→absent flips) | 8 flips / 8 of 69 degraded notes affected (rate 0.34%) |

_The clean-note flag rate is explicitly an **upper bound** on false positives: some flags are genuine natural omissions in the provided notes, not judge errors. A physician pass converts this to a true estimate later._

## Injection counts

- Attempted: 75  ·  Confirmed absent: 69  ·  Discarded: 6
  - discarded (3×): fact survived deletion (status=present) after retry
  - discarded (3×): fact survived deletion (status=partial) after retry
- Coverage: 25/25 encounters have ≥1 injection (mean 2.8/covered note; target was ≤3).

## Example cases

- ✅ **Caught** (`6b716621-5454-68ec-2017-362939ab6f36::6b716621-5454-68ec-7553-080856a4cfa2__inj_0`, major/observation): deleted “Depression screening (PHQ-2) negative, total score 0; denies feeling down/hopeless and denies anhedonia” → judge: `absent` — “No PHQ-2 or depression screening documented.”
- ✅ **Caught** (`6b716621-5454-68ec-2017-362939ab6f36::6b716621-5454-68ec-7553-080856a4cfa2__inj_1`, major/observation): deleted “Anxiety screening (GAD-7) total score 1; occasional mild worry about financial wisdom of leaving job, a couple times a month, self-resolving” → judge: `absent` — “No GAD-7 or anxiety screening documented.”
- ❌ Missed: _none — every confirmed deletion was flagged absent._
- ⚠️ **Clean-note flag** (`6b716621-5454-68ec-2017-362939ab6f36::6b716621-5454-68ec-7553-080856a4cfa2__clean`): “PRAPARE screening: has housing, feels safe, close social contacts 5+ times/week, stress level 'not at all'; reported food insecurity in past year (unable to get food when needed)” flagged absent on an untouched note — “Note denies material hardship and does not document food insecurity or these PRAPARE details.” (natural omission or judge error — exactly the ambiguity the physician pass resolves)

## Interpretation guardrail

At this stage the detector is just `extract_facts` + `presence`, so recall here is partly a floor/sanity measure — it mostly confirms the presence judge reliably detects a clean deletion. Its real power is as a **fixed answer key** for the later ablation comparisons (same injected set, different rungs → meaningful deltas). The more revealing first signal is the clean-note flag rate. Don't over-claim from recall alone.
