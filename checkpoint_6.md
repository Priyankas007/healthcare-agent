# Checkpoint 6 — FHIR write-back demo (STRETCH)

**Top line:** 3/3 selected chart coverage gaps written to the sandbox as unconfirmed FHIR R4 resources for encounter `1be66dc9-cf0b-cb78-e88e-ada9a9a5405b::1be66dc9-cf0b-cb78-ee14-c92f2fe041a4` (18 gap candidates excluded by safety screens). **This is a demo, not an eval metric** — coverage-gap counts are never folded into headline recall numbers.

## Safety framing

- **Human-in-the-loop:** every resource required explicit approval before writing.
- **Nothing is verified truth:** AllergyIntolerance/Condition carry `verificationStatus=unconfirmed`; other types use their most conservative legal status; every resource carries an `unconfirmed` meta tag and a provenance note with the verbatim transcript quote.
- **Provisional codes:** RxNorm/SNOMED/LOINC codings are model-suggested and explicitly marked needs-verification — a clinician must confirm before any downstream use.
- **Sensitive exclusions:** IPV, substance-use, and mental-health disclosures (plus all SDOH-typed facts and negative findings) are screened out before structuring; see the skipped list.
- **Sandbox only:** writes are refused for any host other than localhost / 127.0.0.1 / hapi.fhir.org.

## Configuration

- Base URL: `http://localhost:8080/fhir`
- Patient: `Patient/1005` (synthetic, from the encounter's patient_context)
- Encounter scaffold: `Encounter/1006`
- Gap cap: --max-gaps 3

## Coverage gaps selected

| Fact | Target FHIR type | In note? | Authored | Valid | Approved | Written | Server id |
|---|---|---|---|---|---|---|---|
| Allergy: aspirin, causes swelling (`f22`) | AllergyIntolerance | partial | ✅ | ✅ | ✅ | ✅ | `1007` |
| Allergy: peanuts, severe — throat itching even with peanut dust (`f23`) | AllergyIntolerance | partial | ✅ | ✅ | ✅ | ✅ | `1008` |
| Allergy: animal dander — cannot tolerate cats or dogs (`f24`) | AllergyIntolerance | partial | ✅ | ✅ | ✅ | ✅ | `1009` |

## Skipped by safety screens (with reasons)

- `f10` (symptom): “Patient reports polyphagia — increased hunger and eating despite feeling weak/em” — fact type 'symptom' is not in the safe-to-code mapping (allergy/medication/condition/family history/observation only)
- `f11` (symptom): “Patient reports bilateral tingling/paresthesias in feet and hands, worse at nigh” — fact type 'symptom' is not in the safe-to-code mapping (allergy/medication/condition/family history/observation only)
- `f12` (symptom): “Patient reports increased daytime napping/sleeping half the day (reported by dau” — fact type 'symptom' is not in the safe-to-code mapping (allergy/medication/condition/family history/observation only)
- `f13` (symptom): “Patient reports mild cognitive fogginess and word-finding difficulty (intermitte” — fact type 'symptom' is not in the safe-to-code mapping (allergy/medication/condition/family history/observation only)
- `f2` (symptom): “Patient reports generalized fatigue, everything wears her out” — fact type 'symptom' is not in the safe-to-code mapping (allergy/medication/condition/family history/observation only)
- `f20` (red_flag_screen): “Patient denies recent chest tightness / has not needed nitroglycerin in a long w” — negative finding ('denies') — not writable as a positive FHIR resource
- `f21` (counseling): “Counseled patient to press call button and report immediately if chest pressure ” — fact type 'counseling' is not in the safe-to-code mapping (allergy/medication/condition/family history/observation only)
- `f25` (order): “Ordered peanut-free flag on all meal trays and diabetic-friendly diet accommodat” — fact type 'order' is not in the safe-to-code mapping (allergy/medication/condition/family history/observation only)
- `f26` (order): “Therapy dog to be kept off patient's hallway due to animal dander allergy” — fact type 'order' is not in the safe-to-code mapping (allergy/medication/condition/family history/observation only)
- `f27` (order): “Aspirin allergy to be documented prominently on front of chart” — fact type 'order' is not in the safe-to-code mapping (allergy/medication/condition/family history/observation only)
- `f28` (symptom): “Patient reports poor oral intake, barely eating at hospital” — fact type 'symptom' is not in the safe-to-code mapping (allergy/medication/condition/family history/observation only)
- `f29` (referral): “Dietitian referral for diabetic-friendly, peanut-free meal planning based on pat” — fact type 'referral' is not in the safe-to-code mapping (allergy/medication/condition/family history/observation only)
- `f37` (followup): “Weekly interdisciplinary team review of care plan (nursing, therapy, dietitian, ” — fact type 'followup' is not in the safe-to-code mapping (allergy/medication/condition/family history/observation only)
- `f39` (sdoh): “SDOH: patient lives alone; daughter lives 40 minutes away with her own family — ” — sensitive fact type 'sdoh' — social/safety context is never auto-structured into the chart
- `f40` (sdoh): “SDOH: patient reports difficulty cooking proper diabetic meals for one person an” — sensitive fact type 'sdoh' — social/safety context is never auto-structured into the chart
- `f41` (order): “Ordered to add scheduled vitamin B12 injection to facility schedule so dose does” — fact type 'order' is not in the safe-to-code mapping (allergy/medication/condition/family history/observation only)
- `f8` (symptom): “Patient reports polydipsia — constant thirst, never satisfied” — fact type 'symptom' is not in the safe-to-code mapping (allergy/medication/condition/family history/observation only)
- `f9` (symptom): “Patient reports nocturia, urinating 4-5 times per night” — fact type 'symptom' is not in the safe-to-code mapping (allergy/medication/condition/family history/observation only)

## Before / after (sandbox resource counts for this patient)

| Resource type | Before | After |
|---|---|---|
| AllergyIntolerance | 0 | 0 |
| Condition | 0 | 0 |
| FamilyMemberHistory | 0 | 0 |
| MedicationStatement | 0 | 0 |
| Observation | 0 | 0 |

## Example authored resources

### AllergyIntolerance — “Allergy: aspirin, causes swelling”

```json
{
 "resourceType": "AllergyIntolerance",
 "clinicalStatus": {
  "coding": [
   {
    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
    "code": "active",
    "display": "Active"
   }
  ]
 },
 "verificationStatus": {
  "coding": [
   {
    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
    "code": "unconfirmed",
    "display": "Unconfirmed"
   }
  ]
 },
 "code": {
  "coding": [
   {
    "system": "http://snomed.info/sct",
    "code": "387458008",
    "display": "Aspirin (provisional \u2014 needs verification)"
   }
  ],
  "text": "aspirin"
 },
 "patient": {
  "reference": "Patient/1000"
 },
 "encounter": {
  "reference": "Encounter/1001"
 },
 "reaction": [
  {
   "manifestation": [
    {
     "coding": [
      {
       "system": "http://snomed.info/sct",
       "code": "65124004",
       "display": "Swelling (provisional \u2014 needs verification)"
      }
     ],
     "text": "swelling"
    }
   ]
  }
 ],
 "note": [
  {
   "text": "Aspirin swells me up."
  },
  {
   "text": "RECALL write-back demo: patient-reported fact captured from the ambient transcript; absent from the structured chart; all codings provisional and pending clinician verification. Transcript: \"Aspirin swells me up.\""
  }
 ],
 "meta": {
  "tag": [
   {
    "system": "urn:recall:verification",
    "code": "unconfirmed",
    "display": "Unconfirmed \u2014 patient-reported ambient capture, pending clinician verification"
   }
  ]
 }
}
```

### AllergyIntolerance — “Allergy: peanuts, severe — throat itching even with peanut dust”

```json
{
 "resourceType": "AllergyIntolerance",
 "clinicalStatus": {
  "coding": [
   {
    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
    "code": "active",
    "display": "Active"
   }
  ]
 },
 "verificationStatus": {
  "coding": [
   {
    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
    "code": "unconfirmed",
    "display": "Unconfirmed"
   }
  ]
 },
 "code": {
  "coding": [
   {
    "system": "http://snomed.info/sct",
    "code": "91935009",
    "display": "Allergy to peanuts (provisional \u2014 needs verification)"
   }
  ],
  "text": "peanuts"
 },
 "patient": {
  "reference": "Patient/1000"
 },
 "encounter": {
  "reference": "Encounter/1001"
 },
 "reaction": [
  {
   "manifestation": [
    {
     "text": "throat itching"
    }
   ],
   "severity": "severe"
  }
 ],
 "note": [
  {
   "text": "Peanuts are the dangerous one \u2014 even peanut dust starts my throat itching."
  },
  {
   "text": "RECALL write-back demo: patient-reported fact captured from the ambient transcript; absent from the structured chart; all codings provisional and pending clinician verification. Transcript: \"Peanuts are the dangerous one \u2014 even peanut dust starts my throat itching.\""
  }
 ],
 "meta": {
  "tag": [
   {
    "system": "urn:recall:verification",
    "code": "unconfirmed",
    "display": "Unconfirmed \u2014 patient-reported ambient capture, pending clinician verification"
   }
  ]
 }
}
```

### AllergyIntolerance — “Allergy: animal dander — cannot tolerate cats or dogs”

```json
{
 "resourceType": "AllergyIntolerance",
 "clinicalStatus": {
  "coding": [
   {
    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
    "code": "active",
    "display": "Active"
   }
  ]
 },
 "verificationStatus": {
  "coding": [
   {
    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
    "code": "unconfirmed",
    "display": "Unconfirmed"
   }
  ]
 },
 "code": {
  "text": "Animal dander allergy (provisional \u2014 needs verification)"
 },
 "patient": {
  "reference": "Patient/1000"
 },
 "encounter": {
  "reference": "Encounter/1001"
 },
 "note": [
  {
   "text": "I can't be around cats or dogs for long"
  },
  {
   "text": "RECALL write-back demo: patient-reported fact captured from the ambient transcript; absent from the structured chart; all codings provisional and pending clinician verification. Transcript: \"I can't be around cats or dogs for long\""
  }
 ],
 "meta": {
  "tag": [
   {
    "system": "urn:recall:verification",
    "code": "unconfirmed",
    "display": "Unconfirmed \u2014 patient-reported ambient capture, pending clinician verification"
   }
  ]
 }
}
```

## Caveats

- Codings are provisional model suggestions, not terminology-service lookups — every code needs human verification.
- The approval gate here is a terminal prompt; a real deployment needs an EHR-integrated review queue with audit trail.
- Sensitive-disclosure screening is a keyword heuristic that deliberately over-excludes; it is a floor, not a guarantee.
- Sandbox-only by construction; nothing here touches a production system.
- Stretch demo: results are illustrative and excluded from headline metrics.
