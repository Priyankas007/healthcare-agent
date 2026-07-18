# Checkpoint 3 — Severity classification + relevance-filtered surface

**Top line:** 57/69 injected omissions detected AND surfaced (83%); clean-note surfaced-flag rate 0.96/note (vs 1.56 raw absent-rate in Checkpoint 2 — the relevance filter's effect); flags-per-note median 2 (injected set), no cap applied.

## Metrics

| Metric | Value |
|---|---|
| **Recall (detected AND surfaced), overall** | **57/69 = 82.6%** |
| Recall — injected major | 57/69 = 82.6% |
| Flags/note (injected set) | min 0 · median 2 · max 3 · hist {'0': 5, '1': 27, '2': 28, '3': 9} |
| Flags/note (clean set) | min 0 · median 1 · max 4 · hist {'0': 9, '1': 10, '2': 5, '4': 1} |
| Clean-note surfaced-flag rate | 0.96/note (raw absent-rate was 1.56) |

## Severity calibration (injected heuristic → classifier)

| Injected (heuristic) | Classifier | n |
|---|---|---|
| major | major | 36 |
| major | minor | 12 |
| major | safety_critical | 21 |

## Missed injected omissions (shown in full)

- `6b716621-5454-68ec-2017-362939ab6f36::6b716621-5454-68ec-7553-080856a4cfa2__inj_2` (injected major): **classified minor → logged, not surfaced** — classifier said `minor`
- `6b716621-5454-68ec-2017-362939ab6f36::6b716621-5454-68ec-7553-080856a4cfa2__inj_1` (injected major): **classified minor → logged, not surfaced** — classifier said `minor`
- `6b716621-5454-68ec-2017-362939ab6f36::6b716621-5454-68ec-7553-080856a4cfa2__inj_0` (injected major): **classified minor → logged, not surfaced** — classifier said `minor`
- `3a3a1f26-ed23-f65c-a7df-c96fac56f464::3a3a1f26-ed23-f65c-e264-be689558faea__inj_2` (injected major): **classified minor → logged, not surfaced** — classifier said `minor`
- `1ba8eeb9-bc93-7129-4390-0d2ddd560616::1ba8eeb9-bc93-7129-2e7d-8c427e72b964__inj_0` (injected major): **classified minor → logged, not surfaced** — classifier said `minor`
- `4b4735a2-ee12-ec86-041f-3ba4d5c81ec9::4b4735a2-ee12-ec86-c1c9-c610cc6ef8ab__inj_2` (injected major): **classified minor → logged, not surfaced** — classifier said `minor`
- `1ba8eeb9-bc93-7129-4390-0d2ddd560616::1ba8eeb9-bc93-7129-2e7d-8c427e72b964__inj_1` (injected major): **classified minor → logged, not surfaced** — classifier said `minor`
- `73043f9e-3254-a1d3-aa45-b82f0fc6d502::73043f9e-3254-a1d3-ecbd-a0c16f2d8db0__inj_1` (injected major): **classified minor → logged, not surfaced** — classifier said `minor`
- `be1b73f7-b0f0-0ca3-b24b-28369ce68943::be1b73f7-b0f0-0ca3-5c23-d051118e002b__inj_1` (injected major): **classified minor → logged, not surfaced** — classifier said `minor`
- `be1b73f7-b0f0-0ca3-b24b-28369ce68943::be1b73f7-b0f0-0ca3-5c23-d051118e002b__inj_2` (injected major): **classified minor → logged, not surfaced** — classifier said `minor`
- `4c893b3e-df6f-a2f0-5d03-98714cbad61a::4c893b3e-df6f-a2f0-3e2d-587d1263ccd4__inj_1` (injected major): **classified minor → logged, not surfaced** — classifier said `minor`
- `b504cdf2-e13b-979e-9c4a-95456823e3dd::b504cdf2-e13b-979e-4f0c-523d0948189e__inj_2` (injected major): **suppressed by expected=false** — classifier said `minor`

## Rendered surfaces — hero cases (demo preview)

#### Pre-signature flags — 4b4735a2-ee12-ec86-041f-3ba4d5c81ec9::4b4735a2-ee12-ec86-c1c9-c610cc6ef8ab__inj_2

1. 🟠 **[MAJOR] PRAPARE: family unable to get needed medicine or health care (medical/dental/mental/vision) in past year**
   - _Why it matters:_ Inability to access needed care in the past year directly affects the feasibility of the new hypertension, prediabetes, and dental follow-up plans and warrants documentation and intervention.
   - _FHIR:_ `Observation/4b4735a2-ee12-ec86-1ef6-1e2cd1adea0a`

<sub>2 minor flag(s) logged, not surfaced: PHQ-2 depression screen score 2 (low, no treatment indicated; Counseled that if depression/grief worsens, treatment discus</sub>

#### Pre-signature flags — 4b4735a2-ee12-ec86-041f-3ba4d5c81ec9::4b4735a2-ee12-ec86-c1c9-c610cc6ef8ab__inj_0

1. 🔴 **[SAFETY_CRITICAL] Started hydrochlorothiazide 25 mg oral tablet, one tablet every morning with breakfast**
   - _Why it matters:_ An actively started antihypertensive must be documented for accurate medication reconciliation, dosing safety, and monitoring—especially with borderline potassium 3.97 on a potassium-wasting thiazide.
   - _Transcript:_ “hydrochlorothiazide, 25 milligrams, one tablet every morning. It's a water pill”
   - _FHIR:_ `MedicationRequest/4b4735a2-ee12-ec86-2f73-08977934c44b`
2. 🟠 **[MAJOR] Counseled on hydrochlorothiazide side effects: increased urination initially, call for lightheadedness on standing or muscle cramps; bloodwork to be rechecked**
   - _Why it matters:_ Documenting counseling on orthostasis and cramp warning signs plus lab monitoring shows the patient was safeguarded against thiazide adverse effects and closes the documentation loop.
   - _Transcript:_ “If you feel lightheaded when you stand, or you get muscle cramps, call us — it can nudge your potassium and sodium, so we'll recheck bloodwork after you've been on it a while.”
3. 🟠 **[MAJOR] PRAPARE: family unable to get needed medicine or health care (medical/dental/mental/vision) in past year**
   - _Why it matters:_ Inability to obtain needed care directly affects adherence to the new hypertension, dental, and B12 plans and should drive resource intervention.
   - _FHIR:_ `Observation/4b4735a2-ee12-ec86-1ef6-1e2cd1adea0a`

<sub>1 minor flag(s) logged, not surfaced: Counseled that if depression/grief worsens, treatment discus</sub>

#### Pre-signature flags — 4b4735a2-ee12-ec86-041f-3ba4d5c81ec9::4b4735a2-ee12-ec86-c1c9-c610cc6ef8ab__inj_1

1. 🟠 **[MAJOR] Vitamin B12 injectable continued unchanged for anemia**
   - _Why it matters:_ An active injectable medication must be captured in the reconciliation to keep the medication list accurate and support ongoing anemia management.
   - _Transcript:_ “the B12 injections continue unchanged, that's for your anemia and it's doing its job.”
2. 🟠 **[MAJOR] PRAPARE: family unable to get needed medicine or health care (medical/dental/mental/vision) in past year**
   - _Why it matters:_ Documented barriers to obtaining care directly affect the feasibility of the new medication, lab follow-up, and dental referral plans.
   - _FHIR:_ `Observation/4b4735a2-ee12-ec86-1ef6-1e2cd1adea0a`
3. 🟠 **[MAJOR] Patient reports fogginess and heavy legs when B12 injections are skipped**
   - _Why it matters:_ These symptoms reflect the clinical consequence of missed B12 doses and justify continuing the injection, supporting adherence counseling.
   - _Transcript:_ “I do notice when I skip — I get foggy and my legs feel like sandbags.”

<sub>2 minor flag(s) logged, not surfaced: History of migrant/seasonal farm work as main income source ; Counseled that if depression/grief worsens, treatment discus</sub>

## Suppression spot-check (expected=false drops — verify by hand)

- `b342f27e-56bc-08ac-347c-323279c0d595::b342f27e-56bc-08ac-24f0-de401f6e3c47__inj_1`: “Counseled that there is no medical rule on when to announce the pregnancy” (counseling) — _Announcement timing is a psychosocial reassurance point with no medical bearing on care._  → OK to omit? ☐
- `b342f27e-56bc-08ac-347c-323279c0d595::b342f27e-56bc-08ac-24f0-de401f6e3c47__inj_0`: “Counseled that there is no medical rule on when to announce the pregnancy” (counseling) — _Announcement timing is a non-medical social discussion that has no bearing on clinical management._  → OK to omit? ☐
- `b342f27e-56bc-08ac-347c-323279c0d595::b342f27e-56bc-08ac-24f0-de401f6e3c47__inj_2`: “Counseled that there is no medical rule on when to announce the pregnancy” (counseling) — _Announcement timing is a non-medical social point that does not affect clinical care or note completeness._  → OK to omit? ☐
- `3a3a1f26-ed23-f65c-a7df-c96fac56f464::3a3a1f26-ed23-f65c-e264-be689558faea__inj_2`: “Counseled that tetanus/vaccine injection may cause a sore arm for a day or two” (counseling) — _Routine post-vaccination side-effect counseling is standard and its omission has negligible clinical consequence._  → OK to omit? ☐
- `4b4735a2-ee12-ec86-041f-3ba4d5c81ec9::4b4735a2-ee12-ec86-c1c9-c610cc6ef8ab__inj_2`: “History of migrant/seasonal farm work as main income source at some point in past 2 years” (sdoh) — _Prior seasonal farm work is background occupational history with limited bearing on today's management, though it could contextualize exposures._  → OK to omit? ☐
- `4b4735a2-ee12-ec86-041f-3ba4d5c81ec9::4b4735a2-ee12-ec86-c1c9-c610cc6ef8ab__inj_0`: “History of migrant/seasonal farm work as main income source at some point in past 2 years” (sdoh) — _Prior seasonal farm work is background occupational history with limited bearing on today's management, though it may inform exposure risk._  → OK to omit? ☐
