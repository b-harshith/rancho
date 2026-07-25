# Multi-City Research Runbook

> Status: documentation skeleton. Commands marked **verified-present** map to files and interfaces inspected in this repository. Commands marked **TODO** must not be run until the corresponding CLI is implemented and verified. This document does not assert that any city has passed an admission gate.

## 1. Scope and safety rules

Target processing order: Bengaluru baseline, Delhi NCR, Mumbai, Hyderabad, Chennai, Kolkata, Pune, Ahmedabad. Unfinished cities must be processed sequentially and admitted only after Stage 6 passes.

- Never guess source city IDs, slugs, cookies, pagination, or URL formats.
- Never treat a successful HTTP status as proof of correct-city data.
- Never bypass CAPTCHA or anti-bot controls.
- Keep cookies, tokens, passwords, CAPTCHA answers, and personal identifiers out of version control and logs.
- Preserve append-only raw payloads. Fix transformations, not raw evidence.
- Preserve nulls as nulls; never replace unknown values with zero.
- Keep direct/countable totals separate from weighted nearby or cluster context.
- Keep absolute cross-city metrics separate from within-city relative metrics.

## 2. Repository baseline

Workspace root:

```text
/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest
```

Observed application layout:

- `src/server.py`: local Python HTTP server and data loading.
- `src/public/`: static frontend and current public datasets.
- `src/api/`: Vercel Python API handlers.
- `src/vercel.json`: Vercel build and route configuration.
- `tests/`: current Python `unittest` suites.
- `src/requirements.txt`: current Python dependency list.

Repository-wide multi-city setup, supported Python version, environment variables, and deployment project/account are **TODO/unverified**.

## 3. Current verified commands

Run from the workspace root unless noted.

### Tests — verified-present

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

This command is derived from the two present `unittest` modules. Passing status and environment compatibility are **TODO: record after execution by the verification owner**.

### Build school-market artifacts — verified-present interface

```bash
python src/build_school_market.py --input PATH_TO_INPUT_JSON --output-dir PATH_TO_OUTPUT_DIRECTORY
```

The flags are verified from `src/build_school_market.py`. Input schema, safe city-scoped destination, and multi-city compatibility remain **TODO/unverified**. Do not point this at canonical outputs until those are approved.

### Local server — verified-present interface

```bash
python src/server.py
```

The server reads `PORT` and defaults to `8050`. It currently contains Bangalore-specific data paths and copy; therefore this is a baseline-only command until refactoring and regression verification are complete. Additional runtime requirements and secret handling are **TODO**.

### Deployment configuration — observed, not a deployment authorization

`src/vercel.json` routes `/api/*` to Python handlers and serves `src/public/**/*` statically. The exact deploy command, project binding, environment variables, preview checks, and production approval procedure are **TODO/unverified**. Do not deploy from this skeleton.

## 4. Required environment and secrets

Before any live collection:

1. Create/verify `.env.example` containing variable names only. **TODO: inventory required names from selected scraper versions.**
2. Store live values in ignored runtime storage. **TODO: verify ignore rules; Git metadata is not present at this workspace root.**
3. Record user-agent/contact, rate limit, timeout, retry count, jitter, and safe worker count per source.
4. Confirm applicable source terms, robots directives, privacy constraints, and access boundaries.
5. Stop for owner action when a lawful human login, fresh session, or CAPTCHA entry is required.

Never paste session material into city mapping evidence, run manifests, terminal transcripts, or handoff documents.

## 5. City execution workflow

For each city, maintain `runs/{NN}_{city_id}/STATUS.md`. Do not begin the next unfinished city until the current city passes or the owner explicitly accepts a documented exception.

### Stage 0 — definition and preflight

- Approve boundary, center/bounds, aliases, PIN-code scope, and—where relevant—Delhi NCR component policy.
- Discover each source mapping through its own selector, rendered state, or network request.
- Save redacted evidence under `docs/multicity/source_mappings/{city_id}.md`.
- Run a one-page/sample preflight for YellowSlate, MagicBricks Projects, 99acres Localities, and Practo.
- Require at least 90% of sampled records to match the intended city/region and reject known repeated records from another city.

Future CLI shape from the execution specification (**TODO: implement and verify; not currently confirmed in this repository**):

```bash
python PATH_TO_SCRAPER.py --city CITY_ID --config config/cities.yaml --output-root data/cities/CITY_ID --resume --sample 1
```

Record exact commands and resolved, redacted URLs in the city run status once the authoritative scripts are selected.

### Stage 1 — raw collection

- Run only after all source preflights pass.
- Preserve append-safe JSONL/raw responses, checkpoints, structured logs, and run manifests.
- Reconcile source-reported totals with collected unique totals.
- On block/challenge/repeated pages, checkpoint and stop; do not synthesize replacements.

Full-run command template (**TODO/unverified**):

```bash
python PATH_TO_SCRAPER.py --city CITY_ID --config config/cities.yaml --output-root data/cities/CITY_ID --resume
```

### Human-assisted UDISE collection

1. Generate the approved city/metro PIN list with source and boundary provenance.
2. Launch the existing UDISE collector using its verified local instructions. **TODO: authoritative path/interface must be established by scraper inventory.**
3. A human enters each CAPTCHA through the collector's intended workflow; never automate solving.
4. Store search and report-card payloads in city-isolated storage or with mandatory `canonical_city_id` keys.
5. Checkpoint every completed PIN and resume only through the collector's supported mechanism.
6. Export normalized UDISE records, then report search/report-card failures and missing PINs.

Owner action is required for CAPTCHA, login/session renewal, or an access-policy question.

### Stage 2 — normalize and deduplicate

- Validate versioned schemas; quarantine malformed/out-of-scope rows.
- Normalize values while retaining original fields.
- Deduplicate with explainable rules and a merge ledger.
- Produce completeness, coordinate, freshness, and duplicate reports.
- Verify a rerun produces identical hashes.

Normalization/reconciliation commands are **TODO: document only after their interfaces exist and are tested**.

### Stage 3 — identity matching and enrichment

- Match YellowSlate to UDISE using identity, address/PIN, board, and spatial evidence.
- Report automatic, ambiguous, manual, unmatched, and rejected groups separately.
- Preserve campus/entity relationships and source conflicts.
- Geocode only missing records; cache, retain method/precision, and reject out-of-bounds candidates.

### Stage 4 — residential classification and family TAM

- Apply the audited baseline method consistently.
- Preserve absolute price, units, status, and source dates.
- Publish missing-unit coverage and uncertainty.
- Never add nearby weighted or cluster context to `countable_family_tam`.
- Do not impute units without separately approved and labeled methodology.

### Stage 5 — H3 and spatial intelligence

- Generate footprints from the approved city boundary.
- Use the approved common H3 resolution or document the exception.
- Recompute all spatial joins and city-specific layers.
- Record lineage for OSM/OSRM/Overture/SEZ/metro inputs used.

### Stage 6 — QA and admission

Complete every gate in `FINAL_HANDOFF.md`: mapping evidence, leakage tolerance, reconciliation, coordinate/geofence quality, ID uniqueness, completeness thresholds, source-specific coverage, rollup equality, deterministic hashes, and Bengaluru regression.

Admission result must be one of `PASS`, `FAIL`, or `EXCEPTION_PENDING_OWNER_APPROVAL`. Only `PASS` is automatic admission.

### Stage 7 — report and publication

- Generate city report and machine-readable summary.
- Recompute master summaries/rankings from admitted city summaries.
- Run contract, unit, integration, reconciliation, and browser checks.
- Record desktop/mobile screenshots and console/network results.
- Update all four multi-city documents with exact counts, freshness, limitations, and commands actually used.

## 6. Resume, retry, and incident handling

- Use only the scraper's implemented `--resume` behavior; do not manually splice raw payloads.
- Retry transient failures with configured backoff/jitter and a finite retry count.
- Preserve failed page/record identifiers and rejection reasons.
- If the city mapping changes, invalidate affected preflight evidence and derived runs explicitly.
- If a source returns another city, halt before bulk collection and mark the source preflight failed.
- If normalization code changes, increment its version and rebuild downstream artifacts from raw inputs.
- If an admitted city's input changes, rerun its admission gate before refreshing master rankings.

## 7. Refresh workflow

1. Record requested scope, source dates, and prior admitted artifact hashes.
2. Revalidate mappings and sessions with samples.
3. Resume/collect raw source data.
4. Normalize, deduplicate, match, classify, and spatially rebuild.
5. Reconcile and run Stage 6.
6. Generate city summary only after PASS.
7. Recompute master ranking files; never patch frontend totals.
8. Run tests and visual QA.
9. Update freshness, coverage, limitations, and handoff.
10. Deploy only after owner/release approval using the **TODO: verified deployment procedure**.

## 8. Evidence to retain per run

- Configuration and schema versions.
- Redacted source mapping evidence and preflight samples.
- Raw/normalized/derived input and output hashes.
- Pages attempted/succeeded/failed and status distribution.
- Raw, unique, normalized, quarantined, rejected, and merged counts.
- Field, coordinate, unit, enrollment, fee, rating, and bed coverage as applicable.
- Exact commands, timestamps (UTC), scraper version/commit when available, warnings, and test results.
- Admission decision and approver for any exception.

