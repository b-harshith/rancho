# Multi-City Final Handoff

> Status: handoff skeleton only. No city is marked complete or admitted by this document. All counts, coverage, freshness, hashes, test results, and approvals are `TODO/unverified` until supported by run artifacts.

## 1. Release summary

| Field | Value |
| --- | --- |
| Handoff date (UTC) | TODO |
| Release/build identifier | TODO |
| Methodology version(s) | TODO |
| Schema version(s) | TODO |
| Dashboard URL / artifact | TODO |
| Admitted cities | TODO — do not populate without Stage 6 PASS evidence |
| Excluded/blocked cities | TODO |
| Overall release decision | TODO: PASS / FAIL / OWNER EXCEPTION REQUIRED |
| Prepared/reviewed by | TODO |

## 2. City-by-city status

Status values: `NOT_ASSESSED`, `IN_PROGRESS`, `BLOCKED`, `QA_FAILED`, `PASS`, or `EXCEPTION_PENDING_OWNER_APPROVAL`. The initial entries below are deliberately `NOT_ASSESSED`; the execution prompt's description of Bengaluru as a baseline is not a substitute for current audit/admission evidence.

| Order | Canonical city | Status | Last completed stage | Admission | Freshness/as-of | Run status/evidence | Owner action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Bengaluru (`bengaluru`) | NOT_ASSESSED | TODO | NOT ASSESSED | TODO | TODO | Baseline audit and regression fixtures TODO |
| 2 | Delhi NCR (`delhi_ncr`) | NOT_ASSESSED | TODO | NOT ASSESSED | TODO | TODO | NCR component/boundary policy TODO |
| 3 | Mumbai (`mumbai`) | NOT_ASSESSED | TODO | NOT ASSESSED | TODO | TODO | TODO |
| 4 | Hyderabad (`hyderabad`) | NOT_ASSESSED | TODO | NOT ASSESSED | TODO | TODO | TODO |
| 5 | Chennai (`chennai`) | NOT_ASSESSED | TODO | NOT ASSESSED | TODO | TODO | TODO |
| 6 | Kolkata (`kolkata`) | NOT_ASSESSED | TODO | NOT ASSESSED | TODO | TODO | TODO |
| 7 | Pune (`pune`) | NOT_ASSESSED | TODO | NOT ASSESSED | TODO | TODO | TODO |
| 8 | Ahmedabad (`ahmedabad`) | NOT_ASSESSED | TODO | NOT ASSESSED | TODO | TODO | TODO |

## 3. Per-city completion record

Copy this section once per city and link every claim to a run manifest or audit artifact.

### CITY_DISPLAY_NAME (`CITY_ID`)

| Item | Result | Evidence / notes |
| --- | --- | --- |
| Approved boundary/aliases | TODO | TODO |
| Source mappings verified | TODO | YellowSlate TODO; MagicBricks TODO; 99acres TODO; Practo TODO; UDISE PIN provenance TODO |
| Preflights | TODO | Correct-city sample ratio and repeated-city guard TODO |
| Stage 1 raw collection | TODO | Manifest/hash TODO |
| Stage 2 normalization/dedup | TODO | Schema/merge/quarantine audits TODO |
| Stage 3 school matching/enrichment | TODO | Match audit TODO |
| Stage 4 residential/TAM | TODO | Eligibility/dedup/missing-unit audit TODO |
| Stage 5 spatial analysis | TODO | Boundary/H3/join audit TODO |
| Stage 6 QA/admission | TODO | Gate report TODO |
| Stage 7 report/dashboard | TODO | Report, summary, UI evidence TODO |
| Freshness by source | TODO | Exact UTC timestamps/as-of dates TODO |
| Known limitations | TODO | TODO |
| Owner action | TODO | TODO |

### Counts and coverage

Never fill a missing count with zero. State `unavailable` and explain why.

| Dataset/metric | Raw | Unique/normalized | Rejected/quarantined | Coverage numerator | Coverage denominator | Coverage % | As-of | Evidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| YellowSlate schools | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| UDISE schools | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| School match count | n/a | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| UDISE enrollment | n/a | TODO | n/a | TODO | TODO | TODO | TODO | TODO |
| Matched-fee enrollment | n/a | TODO | n/a | TODO | TODO | TODO | TODO | TODO |
| MagicBricks projects | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| Known residential units | n/a | TODO | n/a | TODO | TODO | TODO | TODO | TODO |
| Countable family TAM | n/a | TODO | n/a | TODO | TODO | TODO | TODO | TODO |
| 99acres localities | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| Practo hospitals | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| Known hospital beds | n/a | TODO | n/a | TODO | TODO | TODO | TODO | TODO |
| Valid/in-bound coordinates | n/a | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| H3 cells / zones / micro-markets | n/a | TODO | TODO | TODO | TODO | TODO | TODO | TODO |

### Stage 6 admission checklist

| Gate | Result | Evidence |
| --- | --- | --- |
| Source-city mappings verified | TODO | TODO |
| Cross-city leakage within predeclared tolerance | TODO | Tolerance and audit TODO |
| Raw-to-normalized totals reconciled | TODO | Duplicate/rejection ledger TODO |
| Coordinate range/boundary checks pass; fallback precision labeled | TODO | TODO |
| Stable IDs unique; no cross-city collisions | TODO | TODO |
| Predeclared required-field completeness thresholds pass | TODO | Thresholds/results TODO |
| UDISE school-count and enrollment match coverage reported | TODO | TODO |
| Project unit coverage reported | TODO | TODO |
| Locality price coverage reported | TODO | TODO |
| Hospital coordinate/rating/bed coverage reported | TODO | TODO |
| Aggregate rollups equal admitted child records | TODO | Independent reconciliation TODO |
| Normalization rerun hashes identical | TODO | Input/output hashes TODO |
| Bengaluru regression within approved tolerance | TODO | Fixture and result TODO |
| Admission decision | TODO | PASS / FAIL / EXCEPTION_PENDING_OWNER_APPROVAL |

## 4. Master dashboard and ranking verification

| Check | Result | Evidence |
| --- | --- | --- |
| All Cities overview and comparable table | TODO | TODO |
| City selector persists in URL/state | TODO | TODO |
| City detail loads city-scoped data only | TODO | TODO |
| Unknown city IDs rejected | TODO | TODO |
| Absolute rankings generated from validated summaries | TODO | Build artifact/hash TODO |
| Relative metrics excluded from cross-city ranking | TODO | Contract/test TODO |
| Null displayed as unavailable | TODO | Screenshot/test TODO |
| Coverage and denominator visible beside ranked values | TODO | Screenshot/test TODO |
| Tie policy deterministic (`1, 2, 2, 4`) | TODO | Unit test TODO |
| Exports include city, version, freshness, coverage | TODO | Contract test TODO |
| Desktop/mobile visual QA | TODO | Screenshot paths TODO |
| Browser console/network clean | TODO | Evidence TODO |

## 5. Verification record

| Verification | Exact command | Result | Evidence/date |
| --- | --- | --- | --- |
| Current Python unit tests | `python -m unittest discover -s tests -p 'test_*.py'` | TODO/unrun for this skeleton | TODO |
| Multi-city config/schema/parser tests | TODO: exact verified command | TODO | TODO |
| Two-city contamination integration test | TODO: exact verified command | TODO | TODO |
| Independent reconciliation | TODO: exact verified command | TODO | TODO |
| Frontend/browser checks | TODO: exact verified command | TODO | TODO |
| Deployment/preview smoke test | TODO: exact verified command | TODO | TODO |

## 6. Source lineage and reproducibility

| Source/layer | Selected implementation/version | Raw location | Normalized/derived location | Manifest/hash | Freshness | Caveats |
| --- | --- | --- | --- | --- | --- | --- |
| YellowSlate | TODO | TODO | TODO | TODO | TODO | TODO |
| UDISE+ | TODO | TODO | TODO | TODO | TODO | Human-assisted CAPTCHA/session constraints TODO |
| MagicBricks Projects | TODO | TODO | TODO | TODO | TODO | TODO |
| 99acres Localities | TODO | TODO | TODO | TODO | TODO | Fresh runtime session/token handling TODO |
| Practo Hospitals | TODO | TODO | TODO | TODO | TODO | TODO |
| Boundaries/PIN codes | TODO | TODO | TODO | TODO | TODO | Provenance TODO |
| OSM/OSRM/Overture/SEZ/metro | TODO | TODO | TODO | TODO | TODO | Include only used layers |
| Master summaries/rankings | TODO | n/a | TODO | TODO | TODO | Derived only from admitted cities |

## 7. Known limitations, blockers, and owner actions

| Priority | City/scope | Limitation or blocker | Impact | Safe next action | Owner/approver | Status |
| --- | --- | --- | --- | --- | --- | --- |
| TODO | TODO | TODO | TODO | TODO | TODO | TODO |

Mandatory owner-action examples include human CAPTCHA/login/session work, source-policy ambiguity, an NCR scope decision, metric/coverage threshold approval, admission exception, or production deployment approval.

## 8. Deliverable inventory

| Deliverable | Path/link | Status | Notes |
| --- | --- | --- | --- |
| City registry/config | TODO | TODO | TODO |
| Scraper inventory/baseline audit | TODO | TODO | TODO |
| Raw/normalized/derived/audit data | TODO | TODO | Per-city inventory required |
| Versioned schemas | TODO | TODO | TODO |
| Data dictionary | `docs/multicity/DATA_DICTIONARY.md` | Skeleton | Verify against implemented schemas |
| Metric definitions | `docs/multicity/METRIC_DEFINITIONS.md` | Skeleton | Complete thresholds/formulas before ranking |
| Runbook | `docs/multicity/RUNBOOK.md` | Skeleton | Replace TODO commands only with verified interfaces |
| City reports | TODO | TODO | TODO |
| Master summaries/rankings | TODO | TODO | TODO |
| Dashboard | TODO | TODO | TODO |
| Test/reconciliation evidence | TODO | TODO | TODO |
| Visual QA evidence | TODO | TODO | TODO |

## 9. Final sign-off

- Data/QA reviewer: TODO — decision/date/evidence.
- Product/dashboard reviewer: TODO — decision/date/evidence.
- Source-policy/security review: TODO — decision/date/evidence.
- Owner exception approvals: TODO or `none` with evidence.
- Production release authorization: TODO.

No completion claim is valid until each admitted city has a linked Stage 6 PASS, the master ranking build uses only admitted/comparable values, and all required reviewer fields are resolved.
