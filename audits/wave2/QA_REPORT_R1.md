# Wave 2 Independent QA Report — R1

**Task:** `W2-INDEPENDENT-QA-R1`  
**Verdict:** **PASS**  
**Recommendation:** Accept the bounded Wave 2 remediation evidence. External rotation/revocation of the previously exposed Google Maps key remains an owner action and cannot be verified locally.

This is a fresh producer-independent cycle. The prior producer claims were not used as evidence, and no producer files were modified.

## Results

| Artifact | Result | Independent evidence |
|---|---:|---|
| Five normalized collector fixtures | PASS | 5/5 pass runtime validation, `common_entity.schema.json`, and their typed schemas |
| Namespaced IDs and lineage | PASS | All IDs are `city:entity_type:source:source_id`; all records contain non-empty nested lineage |
| Collector path containment | PASS | 12/12 traversal, absolute, forward-slash, and backslash probes blocked |
| Null mappings | PASS | 40/40 mappings across 8 cities × 5 sources fail closed |
| Literal-key code remediation | PASS | No Google key literal remains in `src/server.py`; runtime lookup is environment-based |
| Secret/OCR scan | PASS | No high-confidence secret literal or in-repository OCR/CAPTCHA solver code found |
| Bengaluru staging regression | PASS | Reconciles with the same counts, totals, and hashes as the initial QA cycle |

## Collector contract verification

The five fixture-derived records independently passed `validate_entity()`, the shared common entity schema, and the matching school/project/locality/hospital schema:

```text
hyderabad:school:yellowslate:ys-redacted-1
hyderabad:school:udise:ud-redacted-1
hyderabad:project:magicbricks:mb-redacted-1
hyderabad:locality:99acres:ac-redacted-1
hyderabad:hospital:practo:pr-redacted-1
```

This closes the original critical mismatch: the `entity_type` namespace is present, lineage is nested and non-empty, and all typed required fields validate. Seven schemas also pass Draft 2020-12 metaschema checks.

## Path and fail-close verification

For each of the city, source, and source-record-ID boundaries, the following inputs were tested directly:

```text
../x
/tmp/x
foo/bar
foo\bar
```

All 12 probes raised `SafetyError`; none produced a write. Separately, all 40 currently null source mappings in the canonical registry were tested and blocked. The CLI's unknown-mapping path returned exit code 2.

## Credential and OCR review

The literal Google Maps key previously present in `src/server.py` is gone. `src/api/catchment_market.py` reads `GOOGLE_MAPS_API_KEY` from the environment, and `.env.example` contains names with empty values only. The high-confidence credential scan and Python/JavaScript OCR/CAPTCHA-solver scan returned no matches.

This establishes **code remediation PASS only**. Whether the previously exposed key was rotated/revoked at the provider cannot be inferred from repository state. The owner should complete that external action and review provider usage and restrictions.

## Bengaluru staging regression

The current staging reconciler returns PASS with 309 master H3s, 309 GeoJSON H3s, 2,268 residential records, and 34 residential H3 IDs outside the master. Independent totals remain unchanged:

| Metric | Total |
|---|---:|
| Countable family TAM | 0.00 |
| Direct family TAM | 316,676.00 |
| Direct total units | 316,676.00 |
| Nearby weighted context | 353,613.62 |
| Society-cluster context, not counted | 528,821.07 |
| Surrounding affluent context, not counted | 143,292.89 |

All six staging hashes exactly match the initial QA evidence. The earlier semantic observation about zero countable TAM versus nonzero direct TAM remains informational and unchanged; it is not remediation drift.

## Test evidence

- Multi-city targeted suite: 10/10 pass.
- Collector targeted suite: 8/8 pass.
- Reconciliation targeted suite: 2/2 pass.
- Core legacy suite, executed separately: 26/26 pass.
- Independent fixture validations: 5/5 pass across runtime, common schema, and typed schema.
- Independent hostile path probes: 12/12 blocked.
- Independent null-mapping probes: 40/40 blocked.

Machine-readable commands, hashes, and per-artifact results are recorded in `audits/wave2/qa_results_r1.json`.
