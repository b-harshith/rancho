# Wave 2 Independent QA Report

**Task:** `W2-INDEPENDENT-QA`  
**Verdict:** **FAIL**  
**Recommendation:** Return Wave 2 to the responsible producers. Do not accept it until the collector/contract mismatch, collector path escape, and exposed credential have been remediated and independently retested.

This is a producer-independent result. No producer code, configuration, orchestration, documentation, or public data was modified. This report does not make a city admission decision.

## Result summary

| Artifact | Result | Independent evidence |
|---|---:|---|
| City config/registry | PASS | 8 cities in required order; all 40 currently unverified city/source mappings block |
| Canonical IDs and partition paths | PASS | Cross-city IDs differ; `..`, absolute paths, backslashes, and invalid ID parts reject |
| Absolute ranking | PASS | Competition ranks `1,2,2,4`; null and low coverage remain visible/unranked; pending city excluded; output validates |
| Seven JSON Schemas | PASS | Draft 2020-12 metaschema checks and relative references pass |
| Collector-to-contract integration | **FAIL** | 0/4 automated source fixtures pass runtime entity validation or source JSON Schema |
| Collector framework | **FAIL** | Positive tests pass, but a malicious config city `../escape` writes outside `--output-root` and exits 0 |
| Bengaluru staged rebuild | PASS | Two fresh runs byte-identical; reconciliation passes; three mutations fail as required |
| Secret/OCR scan | **FAIL** | Hard-coded Google Maps API key at `src/server.py:33`; no OCR/CAPTCHA-solving implementation found in the in-repo collector framework |

## Blocking findings

### W2-QA-001 — Critical — collector records violate canonical contracts

`collectors.adapters.normalize()` emits IDs such as `hyderabad:magicbricks:mb-redacted-1`, while the canonical contract requires a namespaced entity type in a four-part namespace (`city:entity_type:source:source_id`). A direct validation against `common_entity.schema.json` produced 0/4 passes: every fixture failed the four-part ID pattern and the required nested `lineage` object. The outputs also lack `entity_kind` and every source schema's required source-specific fields. All YellowSlate, MagicBricks, 99acres, and Practo fixtures therefore fail the common schema, `validate_entity()`, and their source-specific JSON Schema.

The existing collector parser test only asserts an ID prefix and hash length; it does not validate normalized output against the contracts. Thus the green producer suite does not cover this integration boundary.

### W2-QA-002 — High — collector path containment can be escaped

The canonical `src/multicity/paths.py` guard works. The collector uses a separate unguarded `Layout`. With a local config declaring `canonical_city_id: ../escape`, the CLI accepted `--city ../escape`, exited 0, and wrote `<temp>/escape/normalized/magicbricks.json` outside `<temp>/safe`, the supplied output root.

### W2-QA-004 — Critical — exposed credential

The secret scan found a Google Maps API key literal in `src/server.py:33`. It should be treated as compromised and rotated/revoked by its owner. Deleting the literal without rotating it is not sufficient.

## Bengaluru rebuild and reconciliation

Two isolated rebuilds generated identical hashes for all six outputs:

| Output | SHA-256 |
|---|---|
| `client_summary.json` | `5854faa57019c7060bd03fd4401eb6379ecb6bef5c756cbb59391af5faa8e3f0` |
| `hexes.geojson` | `0438e0c38ee81fb0f715e241258873a615b7462f896d619c24e2f1a0954584d2` |
| `hexes_master.json` | `ebea3677ad8b0af0493d8b697796da16471d9b59b1adef8109e864eb69393e00` |
| `report.json` | `77b6af8eed812c05131979e054719875bccfcb49c997db8ab820375672b115b7` |
| `residential.json` | `45e54585664835663bb08e67acae8f05b673bcc28df6c4af9619eddb15134994` |
| `run_manifest.json` | `7f3da54245c997a8ab7ec2d3bb49dab4bd80105f72608df92e288fdf5175c43d` |

Independent counts: 309 master H3s, 309 GeoJSON H3s, 2,268 residential records, all 2,268 with H3 IDs, 220 unique residential H3s, 186 inside the master, and 34 outside it.

The 34 outside-footprint H3s contain 54 residential records. Inspection found zero missing names and zero missing coordinates; their TAM and unit sums are both 19,297. They are disclosed as coverage and are not added to master H3 aggregates.

Independent totals:

| Metric | Total |
|---|---:|
| Countable family TAM | 0.00 |
| Direct family TAM | 316,676.00 |
| Direct total units | 316,676.00 |
| Nearby weighted context | 353,613.62 |
| Society-cluster context, not counted | 528,821.07 |
| Surrounding affluent context, not counted | 143,292.89 |

The zero countable TAM is faithfully present in the hash-locked accepted input, so it is not a rebuild drift. It is nevertheless a medium-severity semantic concern because direct family TAM is nonzero; the metric owner should explicitly confirm this meaning before downstream use.

Failure detection was proven on copies in temporary directories. Changing one GeoJSON H3 ID, changing the report countable total, and changing the summary outside-footprint count each produced exit code 1 with the expected reconciliation error.

## Tests and commands

- Targeted multi-city: 10/10 pass.
- Targeted collectors: 6/6 pass.
- Targeted reconciliation: 2/2 pass.
- Core legacy suite, run separately: 26/26 pass.
- Seven schemas pass Draft 2020-12 schema checks.
- Independent ranking output passes `ranking.schema.json`.
- All 40 null/unverified mappings across 8 cities × 5 sources were confirmed blocked.

Commands executed:

```text
python3 -m unittest discover -s tests/multicity -p 'test_*.py' -v
python3 -m unittest discover -s tests/collectors -p 'test_*.py' -v
python3 -m unittest discover -s tests/reconciliation -p 'test_*.py' -v
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 pipelines/bengaluru_rebuild/rebuild.py --repo-root . --output <temp>/one
python3 pipelines/bengaluru_rebuild/rebuild.py --repo-root . --output <temp>/two
python3 tests/reconciliation/reconcile_bengaluru.py --staging <temp>/one
python3 tests/reconciliation/reconcile_bengaluru.py --staging <mutated-temp>
```

Machine-readable evidence and the complete per-artifact disposition are in `audits/wave2/qa_results.json`.
