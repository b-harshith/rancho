# Final independent QA R2

**Task:** DNC-SCOPE-REVISION-QA-R2  
**Code/data verdict:** **PASS**  
**MagicBricks technical launch verdict:** **ADMITTED** for a bounded, conservative full-production collection run.  
**Whole Delhi NCR readiness:** External blockers remain for Ezyschooling mapping and the pending Google runtime comparison.

No live call, API key use, producer edit, or full scrape occurred during QA.

| Track | Code/data | External readiness |
|---|---|---|
| DNC-GEO-PINS | **PASS** | Google runtime comparison pending |
| DNC-EZYSCHOOLING | **PASS** | **BLOCKED** by unverified source mapping |
| DNC-MB-LOCALITIES | **PASS** | Technically admitted for production launch |

## Geo/PIN — PASS

The final files retain 194 candidate rows, all unique, and 101 exclusions. Candidate and exclusion PIN sets remain disjoint. The deterministic grouping behavior proven in R1 remains unchanged. This track's code/data remediation is accepted.

The separate Google reference comparison is still pending runtime execution. That is an external completeness gate, not a defect in the accepted open-source polygon or PIN artifacts.

## Ezyschooling — code/data PASS, externally blocked

All five producer tests pass. Runtime canonical validation, `school.schema.json` validation, challenge quarantine and failed-manifest evidence remain sound.

The independent cache probe seeded four entries: expired, fresh, malformed-timestamp, and malformed-key/secret-bearing. Before any lookup, the cache was physically rewritten with only the fresh SHA-256-keyed entry. The expired and malformed entries were deleted, and no sentinel secret or disallowed field remained. This closes the 29-day retention finding. Existing bounds and network-error probes remain passing.

The source mapping is still intentionally unverified. Therefore the implementation passes QA, but Ezyschooling collection must remain blocked until exact Delhi NCR component mappings are independently evidenced and registered.

## MagicBricks localities — PASS and technically admitted

All twelve producer tests pass. Independent QA additionally found:

- Nine traversal/token variants were rejected: parent traversal, dot tokens, absolute path, backslash, percent-encoded traversal, embedded slash/backslash, and NUL input.
- A foreign URL injected into resumed detail state was redacted in quarantine and produced a durable `status: failed`, `failed_stage: detail`, `production_complete: false` manifest.
- All ten preflight observations resolve to retained evidence artifacts. Every SHA-256 was independently recomputed successfully. Component IDs/counts and detail IDs/city IDs/coordinate presence agree with the manifest.
- A valid normalized locality passes common and typed locality validation. Four mutations—invalid entity ID, latitude, review-count type, and negative price—were rejected.
- Limit accounting remains honest: the bounded two-link probe reports two discovered/required, one completed, one missing, and `production_complete: false`.

The evidence artifacts are redacted structured captures reconstructed from the earlier bounded run, not raw HTML. Their hashes and contents are now durable and internally verifiable, which satisfies this remediation gate; they should not be misrepresented as immutable raw source responses.

MagicBricks is technically admitted for the requested bounded, serialized full-production launch. This authorizes the collector to run under its documented rate, challenge, checkpoint, and completeness controls; it does **not** claim that a full dataset has already been collected or admitted downstream.

## Security and routing

No committed Google API key pattern or literal key assignment was found in the rechecked paths. No OSRM reference exists in the new scope-revision collector/pipeline paths. QA made no network request.

## External blockers

1. Ezyschooling Delhi NCR component mapping must be verified before that collector can run.
2. Google runtime comparison for geographic reference/conflict checking remains pending. Open-source boundary and PIN preparation pass independently.

Subject to those explicit separations, the scope-revision implementation itself passes final QA.
