# Independent QA — scope revision

**Task:** DNC-SCOPE-REVISION-QA  
**Date:** 2026-06-30  
**Overall:** **FAIL — NO GO**

This review was offline and independent. It did not use the supplied Google key, repeat live website requests, alter producer code, run a full scrape, or admit Delhi NCR. Machine-readable details are in `qa_results.json`; reproducible assertions are in `tests/qa_scope_revision/independent_checks.py`.

## Decision summary

| Track | Result | Highest severity | Launch decision |
|---|---|---:|---|
| DNC-GEO-PINS | FAIL | High | Hold until PIN exclusion semantics are reconciled and pending Google conflict checks are explicitly resolved or waived by the owner |
| DNC-EZYSCHOOLING | FAIL | High | Hold; mapping/preflight is still blocked and runtime/schema/challenge guarantees are incomplete |
| DNC-MB-LOCALITIES | FAIL | Critical | Hold; emitted rows do not implement the canonical locality contract |

## DNC-GEO-PINS

Independent recomputation confirms 194 rows and 194 unique six-digit PINs. Component membership counts are Delhi NCT 97, Faridabad 15, Ghaziabad 26, Gurugram 29, and Noida/Greater Noida 28, with one cross-component PIN. All candidate rows carry source and decision-rule fields.

However, seven PINs occur in both inclusion and exclusion files: `110025`, `121004`, `122103`, `122502`, `201015`, `212652`, and `245304`. The underlying reason is understandable—one PIN can contain offices in both approved and out-of-scope districts—but the exclusion metadata calls these “non-component PINs” and the CSV gives them an `exclude` decision. That makes the ledger contradictory at PIN granularity and unsafe as an automated exclusion source.

The 15 boundary features independently load as valid geometries; their union is a valid Polygon with bounds `[76.65104, 28.07571, 77.71876, 28.92616]`. Counts are the expected 11 Delhi districts plus one district for each other component. Boundary lineage records ODbL, a 2021 represented vintage and 2023 source update. India Post lineage records GODL-India and portal update 2025-10-03. The Overture cross-check is documented but not materialized; Google conflict checking remains blocked/pending.

Haversine independently returns 111.195080 km for one equatorial longitude degree. No OSRM reference exists under the new `pipelines/`, `collectors/`, `tests/`, `config/`, or `schemas/` paths. Legacy Bangalore artifacts still mention OSRM; they are baseline data, not evidence of use in this new pipeline.

## DNC-EZYSCHOOLING

The supplied page/detail fixtures parse and normalize successfully, and the normalized fixture passes `school.schema.json`. The entity ID `in:delhi_ncr:school:101` satisfies the common schema's four-segment pattern; no `in:city...` placeholder/mismatch was observed. Reconciliation correctly returns `collision_review` when two primary schools contend for one candidate and returns deterministic unmatched states.

Launch still fails. The source memo explicitly says the Delhi NCR mapping is unverified, and both shared registries retain nulls. This is the correct safe block, but it means collection is not ready. The collector also writes normalized JSON without runtime JSON Schema validation. A detail challenge raised inside the worker pool exits without durable quarantine/manifest evidence, and successful manifests hard-code `challenge_detected: false`.

The school geocoder applies an optional bounding box and does not serialize the API key into normal results. Its cache, however, has no expiry metadata/TTL, and uncaught HTTP errors can include the credential-bearing request URL. This differs from the safer shared Google client, which redacts errors and applies 29-day expiry.

## DNC-MB-LOCALITIES

The architecture correctly has page enumeration followed by detail visits, durable per-stage raw captures, checkpoints/resume, challenge stops, and repeated-page fingerprints. Fixture parsing confirms two listing links and detail identity `78191`. The exact configured components are New delhi/2624, Noida/6403, Gurgaon/2951, Ghaziabad/6146, and Faridabad/2944.

The blocker is fundamental: `finalize()` labels and writes detail-parser rows as normalized, but those rows do not satisfy `locality.schema.json`. Independent validation reports 13 missing required fields. Among them, parser output uses `latitude`/`longitude` while the canonical schema requires `lat`/`lon`; it also lacks `entity_id`, `source`, `entity_kind`, `price_per_sqft`, `review_count`, timestamps, schema version, quality flags, and lineage. There is no runtime validator to catch this.

The mapping memo claims bounded live evidence (five 20/20 page checks and five detail checks), yet no corresponding raw responses, manifest, preflight JSON, or sample-run artifact exists in the repository. QA therefore treats the claim as unverified and did not repeat live requests. The five mappings also remain absent from the shared city registries and exist only in an example config/memo.

Path containment needs hardening: detail URLs are followed without a MagicBricks host allowlist, and a configured source city ID can become part of a raw filename without rejecting separators. Diagnostic completeness is also misleading when `--limit` truncates the discovered set before the missing-detail calculation, although `production_complete` remains correctly false.

## Secret and test evidence

The repository scan found no committed `AIza...` key and no literal key assignment. The user-supplied key was not used or reproduced in QA artifacts. Pytest is unavailable in this interpreter; this was not treated as an excuse. The independent script directly imports parsers/processors and uses `jsonschema` and Shapely assertions/recomputation.

## Required gates before re-review

1. Make the PIN exclusion artifact unambiguous at PIN versus office-row granularity and eliminate contradictory include/exclude decisions.
2. Verify and register Ezyschooling component mappings, materialize bounded preflight evidence, add runtime school validation, and make challenge/cache/error evidence durable and secret-safe.
3. Add a canonical MagicBricks locality normalization layer plus runtime schema validation; materialize the claimed preflight/sample evidence, retain full enumeration totals under limits, and enforce URL/path containment.

No track should be admitted or used for a full Delhi NCR production run until these gates pass independent re-review.
