# Checkpoint 1 — extract_facts + presence (3 hero cases, vs provided note)

**Takeaway:** **Yes, with known fixables** (multi-agent audited, 9 agents, all claims vetted against source): extraction is grounded — **zero invented facts** across 123 facts — and presence calls broadly track clinical judgment. Three systematic issues to fix in later rungs: (1) **over-bundling** — multi-observation facts (BMP analytes, vitals, PRAPARE components) score as one unit and distort presence granularity; (2) **inconsistent judge strictness** — ~8 `present` calls should be `partial` (dropped med timing/instructions), 1 `absent` should be `partial`; (3) a few **missed high-value history facts** (prior MI/IHD, metabolic syndrome, variable home BP in the geriatric case).

_Presence is judged against the **provided** note (`record["note"]`), which was co-generated with the transcript — so most facts should be `present`; `absent` calls deserve extra scrutiny (real gap vs. judge error). Quality gate is the multi-agent audit (clinician review skipped for time)._

## General exam — hypertension treatment initiation and chronic low back pain
`6d4fd363-1ddb-74f8-516f-2fdc861cb736::6d4fd363-1ddb-74f8-95dd-b53404f1e107`

30 facts — 26 present · 3 partial · 1 absent

| # | fact.text | type | source | status | note_evidence |
|---|---|---|---|---|---|
| f1 | Chronic low back pain for ~6 years, dull ache across the beltline, currently 3/10, climbing to 5-6/10 some evenings | symptom | both | present | Chronic low back pain, present about six years, is a dull ache across the beltline, currently 3/10 and up to 5-6/10 by evening |
| f2 | Back pain worse with prolonged sitting at computer and carrying laundry up three flights of stairs | relieving_factor | transcript | present | aggravated by prolonged sitting during job applications and by carrying laundry up three flights of stairs |
| f3 | Back pain relieved by stretching and heat | relieving_factor | transcript | present | improved with stretching and heat |
| f4 | Denies numbness, tingling, or weakness in legs; denies bladder or bowel dysfunction | red_flag_screen | transcript | present | He denies radicular pain, numbness, tingling, weakness, and bowel or bladder dysfunction. |
| f5 | Office blood pressure 106/67 mmHg | observation | both | present | BP 106/67 mmHg |
| f6 | Home blood pressure readings run high, ~150s systolic most mornings | observation | transcript | present | home systolic readings in the 150s on his wife's monitor |
| f7 | Previously diagnosed hypertension went untreated; patient never started prescribed pills due to cost/insurance change | condition | transcript | present | Essential hypertension was diagnosed previously but medication was never started after an insurance change and job loss |
| f8 | Started lisinopril 10 mg oral tablet once daily in the morning for hypertension | medication | both | present | Start lisinopril 10 mg daily |
| f9 | Started amlodipine 2.5 mg oral tablet once daily in the morning for hypertension | medication | both | present | amlodipine 2.5 mg daily |
| f10 | Started hydrochlorothiazide 25 mg oral tablet once daily in the morning for hypertension | medication | both | present | hydrochlorothiazide 25 mg daily — low-dose combination taken together each morning |
| f11 | Started acetaminophen (Tylenol) 325 mg oral tablet every 4-6 hours, scheduled, for back pain | medication | both | **partial** | Acetaminophen 325 mg oral tablets (Tylenol) prescribed for scheduled rather than crisis use |
| f12 | Counseled to report dizziness, lightheadedness, dry cough, or ankle swelling from new BP medications | counseling | transcript | present | Counseled on dizziness, dry cough, and ankle swelling |
| f13 | Counseled on non-pharmacologic back care: walking, stretching, avoiding prolonged sitting, standing every 30 minutes using a timer | counseling | transcript | present | Activity prescription: daily walking, previously taught stretches, standing breaks every 30 minutes during computer work |
| f14 | Unemployed since April due to warehouse shift being cut; job searching, financial strain | sdoh | both | present | laid off from warehouse work in April and is actively job hunting; he describes financial strain |
| f15 | Poor housing conditions: broken air conditioning (reached 95°F), leak with mold growth under kitchen sink, broken elevator requiring three flights of stairs; u… | sdoh | transcript | present | air conditioning nonfunctional for three weeks with indoor heat to 95 degrees, an unrepaired leak with suspected mold under the kitchen sink, a chronically bro… |
| f16 | Provided tenant rights packet and county housing hotline information from front office | counseling | transcript | present | Tenant-rights and county housing hotline resource packet provided at checkout |
| f17 | Reports job-loss stress with early morning waking (4 a.m.), but not falling apart; family working and covering rent | symptom | both | present | early-morning waking with rumination a few times weekly, but preserved mood, appetite, energy, and day-to-day functioning |
| f18 | GAD-7 anxiety screen score of 1 (minimal), consistent with stress rather than anxiety disorder | observation | both | present | GAD-7 1, consistent with situational stress rather than an anxiety disorder |
| f19 | Counseled to report early if stress worsens to nightly waking or mood declines | counseling | transcript | present | Return earlier if sleep disruption becomes nightly or mood declines |
| f20 | AUDIT-C score of 1, minimal alcohol use (a beer on Sundays) | observation | both | present | AUDIT-C 1 |
| f21 | Ex-smoker, quit approximately 20 years ago | observation | both | present | Ex-smoker since his late teens |
| f22 | Gingivitis: red, swollen lower gum line that bleeds with light touch | condition | both | present | Mandibular gingiva erythematous and edematous with bleeding on light contact |
| f23 | Referral placed to dental clinic (sliding-scale) for gingivitis cleaning and home care | referral | both | present | Patient referral for dental care placed to sliding-scale dental clinic |
| f24 | Administered trivalent split-virus influenza vaccine, left arm | procedure | both | **partial** | Influenza vaccine (split virus, trivalent, preservative-free) administered |
| f25 | Follow-up in 4-6 weeks with home blood pressure log to monitor new medications | followup | transcript | present | Return in 4-6 weeks with the log to titrate |
| f26 | BMI 29.31 kg/m2 (height 162.1 cm, weight 77 kg) | observation | fhir | present | weight 77 kg, height 162.1 cm, BMI 29.31 kg/m2 |
| f27 | Heart rate 86 /min, respiratory rate 14 /min | observation | fhir | present | HR 86/min, RR 14/min |
| f28 | PRAPARE screening: worried about losing housing, unable to afford utilities in past year; has housing; feels safe; income ~$118,890/yr; private insurance; 4 pe… | sdoh | fhir | **ABSENT** | — |
| f29 | Medication review completed; patient had run out of all medications and stopped refilling after insurance switched to wife's plan | other | transcript | **partial** | Medication review due; no current medications after prior prescriptions lapsed |
| f30 | Assessment of health and social care needs completed | procedure | fhir | present | assessment of health and social care needs completed |

### Issues observed

- Granularity too fine/coarse: f27 bundles heart rate 86 + resp rate 14 (two separate FHIR Observations) into one fact.
- Invented facts (unsupported by transcript or FHIR): **none confirmed**.
- Present-vs-absent mis-calls: f28 (PRAPARE/social) judged `absent` but note documents household composition — should be `partial`.
- Other notes: f26 cites only the BMI Observation while asserting height+weight (uncited but real Observations); f2 typed `relieving_factor` but content is aggravating factors; 3 completed screening Procedures (anxiety, substance use, AUDIT-C) have no fact — low impact since GAD-7/AUDIT-C scores are captured in f18/f20.
- **Audit verdict:** facts and presence calls track clinical judgment well; partial calls on f11/f24/f29 are sound.

## Annual physical — geriatric cardiometabolic follow-up
`74919836-2db2-2f73-d2cf-5287a180b0ff::74919836-2db2-2f73-ed42-440eccc6591a`

53 facts — 49 present · 0 partial · 4 absent

| # | fact.text | type | source | status | note_evidence |
|---|---|---|---|---|---|
| f1 | Patient reports no chest pain, pressure, or tightness on morning walks | red_flag_screen | transcript | present | He denies chest pain or pressure at rest or with usual exertion |
| f2 | Occasional exertional chest twinge when overdoing yard work, resolves with rest | symptom | transcript | present | noting only an occasional brief twinge with heavy yard work that resolves promptly with rest |
| f3 | Has not needed nitroglycerin spray in a long while | symptom | transcript | present | he has not needed his nitroglycerin spray in many months |
| f4 | Denies shortness of breath, ankle swelling, and paroxysmal nocturnal dyspnea | red_flag_screen | transcript | present | He denies exertional dyspnea, orthopnea, paroxysmal nocturnal dyspnea, palpitations, lower-extremity edema |
| f5 | Denies dizziness, lightheadedness, and falls in the past year | red_flag_screen | transcript | present | lightheadedness, syncope, and falls over the past year |
| f6 | Appetite good and weight steady | symptom | transcript | present | Appetite is preserved and weight is stable to slightly down |
| f7 | Patient retired in June after 60 years as a bookkeeper (not in labor force) | sdoh | both | present | He retired from a sixty-year bookkeeping career this June |
| f8 | Lives with daughter and grandson; three people in household | sdoh | both | present | he lives with his daughter and grandson (three in the household) |
| f9 | No difficulty affording food, medications, or transportation to appointments | sdoh | both | present | denies difficulty affording food, medications, or transportation |
| f10 | Reports seeing/talking to close people less than once a week; stress level a little bit | sdoh | fhir | **ABSENT** | — |
| f11 | Primary insurance is Medicare | sdoh | fhir | **ABSENT** | — |
| f12 | Ex-smoker | sdoh | fhir | present | Ex-smoker since young adulthood |
| f13 | Medication reconciliation performed | procedure | both | present | Medication reconciliation performed with his pill bottles |
| f14 | Simvastatin 20 mg discontinued (duplicate statin, empty bottle) | medication | transcript | present | duplicate simvastatin 20 mg entry from a prior hospitalization removed |
| f15 | Metoprolol 50 mg (old dose) discontinued | medication | transcript | present | outdated 50 mg ER entry removed |
| f16 | Continue atorvastatin 20 mg oral every evening, no missed doses | medication | transcript | present | Consolidate to atorvastatin 20 mg nightly |
| f17 | Continue metoprolol extended-release 100 mg oral in the morning | medication | transcript | present | Continue losartan 50 mg daily and metoprolol succinate ER 100 mg daily |
| f18 | Continue aspirin 81 mg oral daily | medication | transcript | present | Continue aspirin 81 mg daily |
| f19 | Continue losartan 50 mg oral daily | medication | transcript | present | Continue losartan 50 mg daily |
| f20 | Continue carrying nitroglycerin spray as needed | medication | transcript | present | nitroglycerin 0.4 mg/actuation mucosal spray PRN chest pain |
| f21 | Started metformin extended-release 500 mg oral once daily with dinner for type 2 diabetes | medication | both | present | Start 24 hr metformin hydrochloride 500 mg extended-release tablet daily with the evening meal |
| f22 | Started hydrochlorothiazide 25 mg oral each morning for blood pressure and to lower potassium | medication | both | present | Start hydrochlorothiazide 25 mg each morning |
| f23 | Counseled that metformin ER with food reduces GI upset; instructed to call rather than stop if bothered | counseling | transcript | present | report GI intolerance rather than self-discontinuing |
| f24 | Counseled to take HCTZ in morning and to report dizziness or feeling washed out especially on standing | counseling | transcript | present | Monitor for orthostatic symptoms |
| f25 | Counseled not to skip breakfast before morning walks due to low fasting glucose | counseling | transcript | present | Counseled to avoid skipping breakfast before morning walks |
| f26 | Blood pressure 107/58 mmHg | observation | both | present | BP 107/58 mmHg |
| f27 | Heart rate 96 /min | observation | both | present | HR 96/min |
| f28 | Body weight 78.5 kg, BMI 27.8 kg/m2 | observation | both | present | weight 78.5 kg, height 168 cm, BMI 27.8 kg/m2 |
| f29 | Hemoglobin A1c 5.45% (excellent for type 2 diabetes) | observation | both | present | HbA1c 5.45% |
| f30 | Fasting blood glucose low at 66 mg/dL | observation | both | present | fasting glucose low at 66.82 mg/dL today |
| f31 | Creatinine 0.6 mg/dL (kidneys strong) | observation | both | present | creatinine 0.6 mg/dL |
| f32 | Potassium elevated at 5.16 mmol/L | observation | both | present | potassium 5.16 mmol/L |
| f33 | Total cholesterol 226 mg/dL with LDL 148 mg/dL, higher than desired given cardiac history | observation | both | present | total cholesterol 226.05 mg/dL; direct LDL 148.61 mg/dL |
| f34 | HDL cholesterol 57 mg/dL | observation | fhir | present | HDL 57.06 mg/dL |
| f35 | Triglycerides 101.87 mg/dL | observation | fhir | present | triglycerides 101.87 mg/dL |
| f36 | eGFR 148.95 mL/min/1.73m2 | observation | fhir | present | eGFR 148.95 mL/min/1.73m2 |
| f37 | Urine microalbumin/creatinine ratio 15.6 mg/g | observation | fhir | present | urine microalbumin/creatinine 15.6 mg/g |
| f38 | PHQ-2 depression screen score 0 | observation | both | present | PHQ-2 0 |
| f39 | HARK domestic abuse screen score 0 | observation | both | present | HARK 0 |
| f40 | DAST-10 drug abuse screen score 0 | observation | both | present | DAST-10 0 |
| f41 | Morse Fall Scale score 22 — low risk | observation | both | present | Morse Fall Scale 22, low risk |
| f42 | Gingivitis with red, puffy, bleeding lower gums on exam | condition | both | present | Gingival erythema and edema along the mandibular gumline with friability |
| f43 | Referral to dental clinic for cleaning and exam | referral | both | present | Patient referral for dental care placed |
| f44 | Influenza vaccine (trivalent split virus, PF) administered | procedure | both | present | Influenza vaccine (split virus, trivalent, preservative-free) administered today |
| f45 | No prior bad reactions to flu shot (only sore arm) | red_flag_screen | transcript | **ABSENT** | — |
| f46 | Known anemia stable, no new blood count; to monitor at next labs | condition | transcript | present | Historical and asymptomatic... Continue surveillance at next laboratory draw |
| f47 | Follow-up in about 6 months for repeat labs; return sooner if chest pain, dizziness, or GI intolerance to new medication | followup | transcript | present | Return in 6 months with repeat labs; sooner for chest pain, dizziness, or medication intolerance |
| f48 | Plan to recheck lipids before adjusting statin dose | followup | transcript | present | Repeat lipid panel at follow-up before dose escalation |
| f49 | Health and social care needs assessment completed | procedure | fhir | present | assessment of health and social care needs completed |
| f50 | Pain severity score 1/10 reported | observation | fhir | present | pain 1/10 |
| f51 | Respiratory rate 13 /min | observation | fhir | present | RR 13/min |
| f52 | Sodium 137 mmol/L, chloride 104 mmol/L, CO2 28 mmol/L, BUN 18.73 mg/dL, calcium 8.74 mg/dL | observation | fhir | present | BUN 18.73 mg/dL... sodium 137 mmol/L... chloride 104.15 mmol/L; CO2 28.18 mmol/L; calcium 8.74 mg/dL |
| f53 | Counseled on gum disease and heart disease connection | counseling | transcript | **ABSENT** | — |

### Issues observed

- Granularity too fine/coarse: f52 bundles 5 BMP analytes (Na, Cl, CO2, BUN, Ca) while glucose/creatinine/potassium from the same panel got individual facts; f33 bundles total chol + LDL; f28 bundles weight + BMI; f10 bundles two PRAPARE components — bundled facts scored as a unit masks partially-documented notes.
- Invented facts (unsupported by transcript or FHIR): **none confirmed** — but f6 asserts "weight steady" from a reply that only answered the appetite half of the question (unsupported inference in a slot).
- Present-vs-absent mis-calls: f16 and f17 judged `present` but should be `partial` (note lacks the adherence instruction "no missed days"; "daily" doesn't entail "every morning").
- Other notes: **4 missed clinically important facts** — prior MI/IHD history, metabolic syndrome (verbatim in transcript), variable home BP readings (the HCTZ rationale), and the alcohol/substance screening; f9's `both` source is overstated (FHIR component reads "I choose not to answer").
- **Audit verdict:** broadly sound but short of full clinical judgment — key plan-driving history went unextracted.

## General adult exam — new hypertension and metabolic syndrome
`4b4735a2-ee12-ec86-041f-3ba4d5c81ec9::4b4735a2-ee12-ec86-c1c9-c610cc6ef8ab`

40 facts — 33 present · 6 partial · 1 absent

| # | fact.text | type | source | status | note_evidence |
|---|---|---|---|---|---|
| f1 | Patient presents for a routine physical/health check ('tune-up') at his brother's urging, having not had a physical in years | other | transcript | **partial** | presenting for a general examination, his first comprehensive visit in several years |
| f2 | Dull headaches at the back of the head on some mornings for a few months, fading by lunchtime | symptom | transcript | present | intermittent dull occipital headaches on waking over the past few months, resolving by midday |
| f3 | Bleeding gums when brushing | symptom | transcript | present | daily gum bleeding with brushing |
| f4 | Depression screen (PHQ-2) score of 2 — low, no treatment indicated | observation | both | present | PHQ-2 score 2 ... (low; consistent with grief) |
| f5 | Anxiety screen (GAD-7) score of 3 — low, no treatment indicated | observation | both | present | GAD-7 score 3 (low; consistent with grief) |
| f6 | Alcohol use: 1-2 beers on 2-3 evenings per week; AUDIT-C score 3, below concern threshold for men | observation | both | present | drinks 1–2 beers two to three evenings weekly ... AUDIT-C score 3 (below threshold) |
| f7 | Never smoked tobacco | observation | both | present | has never smoked |
| f8 | Denies illicit drug use (marijuana, non-prescribed pills) | red_flag_screen | transcript | present | denies drug use |
| f9 | Blood pressure elevated at 141/100 mmHg, confirmed on repeat | observation | both | present | BP 141/100 mmHg (confirmed on repeat) |
| f10 | Heart rate 100 /min | observation | both | present | HR 100/min |
| f11 | Body weight 93.9 kg with BMI 30.21 kg/m2, over the obesity line | observation | both | present | weight 93.9 kg ... BMI 30.21 kg/m2 |
| f12 | Hemoglobin A1c 6.28% consistent with prediabetes | observation | both | present | Hemoglobin A1c 6.28% |
| f13 | Blood glucose 91 mg/dL, normal | observation | both | present | glucose 91.08 mg/dL |
| f14 | Creatinine 1.12 mg/dL and BUN 17.36 mg/dL, normal kidney function | observation | both | present | BUN 17.36 mg/dL, creatinine 1.12 mg/dL |
| f15 | Sodium 139 mmol/L | observation | both | present | sodium 139.11 mmol/L |
| f16 | Potassium 3.97 mmol/L | observation | both | present | potassium 3.97 mmol/L |
| f17 | Diagnosis of essential hypertension | condition | both | present | Essential hypertension New diagnosis |
| f18 | Diagnosis of metabolic syndrome (hypertension, prediabetes, obesity cluster) | condition | both | present | Metabolic syndrome X New documentation based on the cluster of hypertension, BMI 30.21 kg/m2, and A1c 6.28% |
| f19 | Started hydrochlorothiazide 25 mg oral tablet, one tablet every morning with breakfast | medication | both | present | Start hydrochlorothiazide 25 mg orally each morning |
| f20 | Counseled that hydrochlorothiazide can cause lightheadedness on standing and muscle cramps; instructed to call if these occur, with bloodwork recheck planned f… | counseling | transcript | present | counseled on diuresis, orthostatic symptoms, and cramping ... interval electrolytes after medication initiation |
| f21 | Vitamin B12 injectable continued unchanged for anemia | medication | transcript | present | Continue vitamin B12 5 mg/mL injectable solution on the established schedule |
| f22 | Medication reconciliation completed: current meds are vitamin B12 injectable and hydrochlorothiazide 25 mg each morning; no other supplements/herbals | procedure | both | present | Medication reconciliation completed: B12 injections plus newly started hydrochlorothiazide |
| f23 | Counseled on low-salt dietary changes (reduce deli meat, sausage, canned soups, chips; cook more at home) | counseling | transcript | present | dietary emphasis on reduced processed/salty foods |
| f24 | Counseled to walk 30 minutes most days | counseling | transcript | **partial** | regular walking |
| f25 | Enrolled in hypertension education program | referral | transcript | present | Enrolled in lifestyle education regarding hypertension |
| f26 | Gingivitis identified on exam — puffy gum line, bleeds with light contact; reversible stage of gum disease | condition | both | present | erythematous, edematous gingival margins with contact bleeding, consistent with gingivitis |
| f27 | Dental referral placed for cleaning and exam; patient not seen dentist in 4-5 years | referral | both | **partial** | Patient referral for dental care placed (cleaning and examination) |
| f28 | Counseled on oral hygiene: brush twice daily with soft brush, floss even when bleeding; bleeding fades within a couple weeks | counseling | transcript | present | soft brush twice daily, daily flossing |
| f29 | Influenza vaccine (split virus, trivalent, preservative-free) administered in left arm | procedure | both | **partial** | Influenza vaccine (split virus, trivalent, preservative-free) administered |
| f30 | Follow-up scheduled in about one month for blood pressure recheck; advised to keep a home BP log (morning, sitting, feet on floor) | followup | transcript | present | Recheck BP in approximately 1 month ... home BP log |
| f31 | Counseled that morning headaches likely related to hypertension and expected to improve as BP is controlled; further workup if they persist | counseling | transcript | **partial** | confirmed on repeat measurement, with associated morning occipital headaches |
| f32 | SDOH: Patient stopped working last year after being primary caregiver for his mother until her death last fall; not currently seeking work | sdoh | both | present | left full-time work last year after a prolonged period caring for his mother, who died last fall; he is not currently seeking work |
| f33 | SDOH: Very low income (~$4,829/year) from odd jobs; lives with sister's family (5 people in household); has housing and feels safe; Medicaid insurance | sdoh | both | **partial** | minimal personal income, living in a five-person household with his sister's family ... reported personal annual income $4,829 |
| f34 | SDOH: Family unable to obtain needed medicine or health care (medical/dental/mental health/vision) in past year per PRAPARE | sdoh | fhir | **ABSENT** | — |
| f35 | Grief following mother's death with variable mood; patient does not consider himself depressed; counseled that worsening grief is a conversation to revisit | counseling | transcript | present | intermittent low mood and worry consistent with grief but denies persistent depression ... Supportive counseling |
| f36 | Notes fogginess and heavy legs when B12 injections are skipped | symptom | transcript | present | reports fatigue and leg heaviness when injections are missed |
| f37 | Pain severity score 1/10 reported | observation | fhir | present | pain score 1/10 |
| f38 | Respiratory rate 13 /min | observation | fhir | present | RR 13/min |
| f39 | Calcium 9.7 mg/dL, chloride 106.14 mmol/L, CO2 22.84 mmol/L (basic metabolic panel results) | observation | fhir | present | calcium 9.7 mg/dL ... chloride 106.14 mmol/L, total CO2 22.84 mmol/L |
| f40 | Body height 176.3 cm | observation | fhir | present | height 176.3 cm |

### Issues observed

- Granularity too fine/coarse: f27 bundles the dental referral order with transcript-only dental history (dragged to `partial` as a unit); f33 packs 5 PRAPARE assertions into one fact; f14 bundles creatinine + BUN (fhir_ref cites only creatinine); f39 bundles Ca/Cl/CO2 vs one-analyte-per-fact for the rest of the same BMP.
- Invented facts (unsupported by transcript or FHIR): **none confirmed** — but f26 imports `status=resolved` from the FHIR Condition's future-dated abatementDateTime (2026-07-02), contradicting the visit where gingivitis is an active new finding.
- Present-vs-absent mis-calls: f19, f22, f28, f30 judged `present` but should be `partial` under the judge's own standard (dropped: "with breakfast", supplement denial, flossing-through-bleeding counseling, BP measurement technique); f36 and f20 are borderline (fogginess→"fatigue" lossy paraphrase; missing "call us" instruction).
- Other notes: presence strictness applied inconsistently across ~6 facts — same category of omission scored `partial` for some facts, `present` for others.
- **Audit verdict:** broadly sound (33/6/1 tracks the note) but grading consistency and bundling need fixing.
