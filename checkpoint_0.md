# Checkpoint 0 — Data inventory & baseline notes

**Takeaway:** The data supports the plan — Observations with values are the richest ground-truth substrate (811 across 25 encounters) while labeled MedicationRequests are sparse (9 labeled, in 4/25 encounters), and AllergyIntolerance exists only as counts (allergy scenarios must be labeled synthetic injections). Demo anchors: General exam — hypertension treatment initiation and chronic low back pain; Annual physical — geriatric cardiometabolic follow-up; General adult exam — new hypertension and metabolic syndrome.

## Inventory (one row per encounter)

| Visit title | Transcript words | Condition | Observation | Procedure | DiagnosticReport | MedicationRequest | Immunization | ImagingStudy | MedReq w/ label | Obs w/ value (flagged abn.) | AllergyIntolerance (count only) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Annual physical — preventive screening and migraine check-in | 1485 | 3 | 15 | 6 | 4 | 0 | 2 | 0 | 0/0 | 15 (0) | 0 |
| Inpatient admission — COVID-19 isolation with pneumonia and hypoxemia | 1441 | 3 | 498 | 23 | 54 | 22 | 0 | 0 | 0/22 | 498 (0) | 2 |
| Prenatal intake visit — initial obstetric evaluation | 1413 | 1 | 0 | 20 | 1 | 0 | 0 | 0 | 0/0 | 0 (0) | 0 |
| Annual wellness examination — preventive screening and health maintenance | 1336 | 2 | 27 | 6 | 6 | 0 | 1 | 0 | 0/0 | 27 (0) | 0 |
| Young adult preventive exam — prediabetes and allergy follow-up | 1531 | 4 | 33 | 9 | 7 | 0 | 4 | 0 | 0/0 | 33 (0) | 7 |
| Annual check-up — post-sepsis recovery and prediabetes | 1601 | 3 | 20 | 6 | 4 | 0 | 1 | 0 | 0/0 | 20 (0) | 0 |
| General adult exam — new hypertension and metabolic syndrome | 1461 | 5 | 21 | 8 | 5 | 2 | 1 | 0 | 2/2 | 21 (0) | 0 |
| General exam — chronic low back pain and positive depression screen | 1518 | 3 | 13 | 9 | 5 | 1 | 0 | 0 | 1/1 | 13 (0) | 0 |
| Annual general exam — prediabetes, hyperlipidemia, and knee osteoarthritis | 1411 | 2 | 37 | 9 | 8 | 0 | 1 | 0 | 0/0 | 37 (0) | 0 |
| Prenatal intake visit — first trimester, newly identified anemia | 1669 | 2 | 0 | 20 | 1 | 0 | 0 | 0 | 0/0 | 0 (0) | 0 |
| Annual physical — geriatric cardiometabolic follow-up | 1388 | 2 | 29 | 9 | 7 | 2 | 1 | 0 | 2/2 | 29 (0) | 0 |
| Annual physical — new adult patient wellness exam | 1302 | 2 | 17 | 8 | 6 | 0 | 2 | 0 | 0/0 | 17 (0) | 0 |
| General exam — hypertension treatment initiation and chronic low back pain | 1241 | 3 | 11 | 5 | 3 | 4 | 1 | 0 | 4/4 | 11 (0) | 0 |
| Annual exam — psychosocial screening with safety disclosure | 1364 | 4 | 13 | 8 | 5 | 0 | 1 | 0 | 0/0 | 13 (0) | 3 |
| General adult exam — preventive screening and sleep review | 1248 | 1 | 28 | 8 | 7 | 0 | 1 | 0 | 0/0 | 28 (0) | 1 |
| Skilled nursing facility admission after hospitalization | 1592 | 0 | 0 | 85 | 1 | 0 | 0 | 0 | 0/0 | 0 (0) | 4 |
| Initial prenatal visit — new pregnancy at 43 | 1520 | 1 | 0 | 20 | 1 | 0 | 0 | 0 | 0/0 | 0 (0) | 0 |
| Dental referral visit — gingival disease treatment | 1505 | 1 | 0 | 12 | 1 | 1 | 0 | 1 | 0/1 | 0 (0) | 0 |
| Prenatal intake visit — first pregnancy with chronic pain | 1571 | 1 | 0 | 20 | 1 | 0 | 0 | 0 | 0/0 | 0 (0) | 0 |
| SNF admission — rehabilitation and pain management | 1565 | 0 | 0 | 26 | 1 | 0 | 0 | 0 | 0/0 | 0 (0) | 0 |
| Annual physical — prediabetes and psychosocial screening | 1405 | 4 | 32 | 7 | 6 | 0 | 1 | 0 | 0/0 | 32 (0) | 0 |
| Hospice admission — end-stage colon cancer | 1374 | 0 | 0 | 45 | 1 | 0 | 0 | 0 | 0/0 | 0 (0) | 0 |
| Hospice admission — advanced colon cancer with cardiac comorbidity | 1346 | 0 | 0 | 49 | 1 | 0 | 0 | 0 | 0/0 | 0 (0) | 0 |
| Skilled nursing facility admission — diabetes stabilization and rehabilitation | 1380 | 0 | 0 | 88 | 1 | 0 | 0 | 0 | 0/0 | 0 (0) | 0 |
| Annual physical — hand osteoarthritis and anxiety screening | 1484 | 2 | 17 | 9 | 6 | 0 | 3 | 0 | 0/0 | 17 (0) | 0 |

*Notes: `MedReq w/ label` = MedicationRequests with a resolvable inline drug label / total (reference-based entries have no usable label). `Obs w/ value` counts Observations carrying an actual value (valueQuantity/CodeableConcept/String/components); the dataset rarely sets `interpretation`, so flagged-abnormal is shown in parentheses where present. **AllergyIntolerance is a longitudinal count only — the dataset contains no usable allergy resources (no substance/code); allergy scenarios require labeled synthetic injection.***

## Hero-case shortlist

1. **General exam — hypertension treatment initiation and chronic low back pain** (`6d4fd363-1ddb-74f8-516f-2fdc861cb736::6d4fd363-1ddb-74f8-95dd-b53404f1e107`) — 4 labeled MedicationRequests, 11 Observations with values. 
2. **Annual physical — geriatric cardiometabolic follow-up** (`74919836-2db2-2f73-d2cf-5287a180b0ff::74919836-2db2-2f73-ed42-440eccc6591a`) — 2 labeled MedicationRequests, 29 Observations with values. 
3. **General adult exam — new hypertension and metabolic syndrome** (`4b4735a2-ee12-ec86-041f-3ba4d5c81ec9::4b4735a2-ee12-ec86-c1c9-c610cc6ef8ab`) — 2 labeled MedicationRequests, 21 Observations with values. 

*Why: ranked by labeled MedicationRequests (the highest-value, scarcest injection substrate — med/dose omissions are the top severe-error category), then by Observations with values (the most abundant substrate for actionable-result omissions). These encounters give the injection harness the most real, structured ground truth to delete from and verify against.*

## Baseline note generation (B0)

**25/25 baseline notes generated** from transcripts only (model: Opus 4.8, adaptive thinking) and saved to `generated_notes/{id}.md`. The provided `note` field was not used or modified — it remains the gold reference for the later injection harness.
