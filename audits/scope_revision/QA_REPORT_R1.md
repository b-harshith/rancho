# Independent remediation QA R1

**Task:** DNC-SCOPE-REVISION-QA-R1  
**Overall:** **FAIL — NO GO**  
**Scope:** Only findings from the original scope-revision QA; no live scrape or API request.

| Track | Verdict | Launch recommendation |
|---|---|---|
| DNC-GEO-PINS | **PASS** | Geo/PIN remediation may advance |
| DNC-EZYSCHOOLING | **FAIL** | Keep blocked; mapping is unverified and cache retention is incomplete |
| DNC-MB-LOCALITIES | **FAIL** | Do not launch; containment and evidence-authenticity gates remain open |

## DNC-GEO-PINS — PASS

The regenerated artifacts now contain 194 unique candidates and 101 exclusions with no intersection. The corrected generator groups the full directory by PIN before exclusion, so a PIN with any approved-component office cannot also enter the exclusion ledger.

An independent synthetic source containing one PIN shared by Delhi and an out-of-scope district produced the PIN only in candidates. Two independent builds were byte-identical. The revised metadata now accurately defines PIN-level exclusion semantics. This closes the prior finding.

## DNC-EZYSCHOOLING — FAIL

Producer tests passed 5/5. The collector now performs both canonical runtime validation and `school.schema.json` validation before writing normalized data. An invalid record is rejected. Challenge failures create a durable `FAILED_QUARANTINED` manifest and hashed evidence file. The Google cache uses SHA-256 keys, strips query/URL/key fields, does not serialize the runtime key, refuses stale coordinates, rejects out-of-bounds results, and converts network failures to non-secret quality flags.

Two gates remain:

1. Delhi NCR mapping remains explicitly unverified. This is a legitimate hard block, and the collector correctly makes no request. It is sufficient by itself to prevent launch.
2. The advertised 29-day cache policy is enforced only for reuse. A 30-day-old entry was not used, but remained persisted when no refresh occurred. Thus retention/deletion is not actually capped at 29 days.

Code remediation is otherwise substantially successful; re-review can be narrow after mapping evidence and expired-entry pruning are supplied.

## DNC-MB-LOCALITIES — FAIL

Producer tests passed 9/9. Locality normalization now emits the common entity fields plus typed locality fields, and runtime validation passes valid fixtures. Independent mutations of the entity ID, negative review count, and invalid latitude were all rejected. Detail limits retain the full discovered denominator and report missing details; production completion stays false. Normal listing challenges and foreign links are quarantined, and HTTPS host/path validation works.

Two high-severity gates remain:

1. Output containment is incomplete. A mutated component ID of `../../../../escape` passed initialization and `_save_raw` wrote an HTML file outside the raw/stage tree. `_save_raw` keys and checkpoint names do not use the containment helper or a safe component-ID grammar. The file remained inside QA's temporary directory, but proves that configured output structure can be escaped.
2. The new preflight summary has the right fields: five components, five detail samples, timestamps, status/counts, and well-formed SHA-256 values. It explicitly says it was reconstructed from temporary files. No raw response or durable hash target is present, so none of those hashes can be independently recomputed. This is summary evidence, not authenticatable source evidence.

Additionally, foreign links parsed in stage 1 are quarantined, but foreign URLs introduced through resumed/discovered state raise in stage 2 before quarantine is appended.

## Security and routing scan

No committed `AIza...` credential or literal Google key assignment was found in the rechecked pipeline/test/data paths. No OSRM reference was found in the new collectors or pipeline remediation paths. QA made no live request and did not use the supplied key.

## Required next gates

- Ezyschooling: verify and durably evidence mappings; delete expired cache entries rather than merely ignoring them.
- MagicBricks: validate/sanitize every filesystem key and checkpoint name, quarantine stage-2 foreign state, and retain raw or otherwise independently verifiable preflight evidence.

No full production run or admission should proceed until the two failed tracks pass independent re-review.
