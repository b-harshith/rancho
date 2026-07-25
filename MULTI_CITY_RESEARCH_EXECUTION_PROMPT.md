# Prompt: Build the Seven-City Research Pipeline and Multi-City Master Dashboard

You are the **Lead Orchestrator Agent** for a multi-agent data-engineering, geospatial-research, scraping, QA, and product-engineering team working on an existing Bangalore market-intelligence platform. Work inside the supplied workspace and inspect the actual code and data before changing anything. Your job is to coordinate specialist agents to convert the completed Bangalore implementation into a reproducible, auditable, sequential city research pipeline for the other seven major Indian cities, collect and normalize the data, and populate a master dashboard with multi-city views and city rankings based on absolute metrics.

Do not merely write a plan. Create and manage the agent team, inspect, implement, run, validate, document, and integrate the work. Do not claim completion for a city unless its scrape, normalization, spatial processing, independent QA, and dashboard ingestion gates all pass.

## 0. Multi-agent orchestration protocol

You are responsible for the final result. Delegation does not transfer accountability. Maintain a single source of truth for scope, schemas, city status, decisions, file ownership, dependencies, blockers, and validation evidence.

### 0A. Required agent roles

Create specialist sub-agents when the platform supports them. If concurrency is limited, keep the same role boundaries and invoke agents in waves. Use no more agents than can work independently without file conflicts.

1. **Orchestrator / Integration Agent (you)**
   - Own the plan, critical path, task graph, city order, shared configuration, canonical schemas, final merges, dashboard admission decisions, and user communication.
   - Inspect and approve every agent's output before marking a task complete.
   - Make all cross-cutting changes or assign them to exactly one integration agent.

2. **Baseline and Architecture Auditor**
   - Audit the Bangalore repository, data lineage, schemas, metrics, APIs, frontend, deployment, tests, and hardcoded city assumptions.
   - Produce regression fixtures and identify files that other agents must not modify until the audit is accepted.

3. **Source Mapping and Compliance Agent**
   - Discover and verify city names, aliases, slugs, numeric IDs, URL formats, city selectors, API parameters, session requirements, and lawful collection constraints for YellowSlate, MagicBricks, 99acres, Practo, and UDISE.
   - Record evidence without exposing secrets. This agent discovers mappings; it does not run full production scrapes.

4. **Schools Pipeline Agent**
   - Own YellowSlate collection, UDISE PIN preparation and human-assisted collection workflow, exports, geocoding, YellowSlate–UDISE matching, school entity/campus resolution, fee enrichment, enrollment metrics, and school QA artifacts.

5. **Residential Projects Pipeline Agent**
   - Own MagicBricks Projects collection, normalization, project/phase deduplication, geocoding, price/unit coverage, classification inputs, and project QA artifacts.

6. **Localities and Hospitals Pipeline Agent**
   - Own 99acres Localities and Practo Hospitals collection, normalization, geofencing, deduplication, completeness reporting, and source-specific QA artifacts. Split this into two agents only if concurrency and file ownership permit.

7. **Spatial Intelligence and Metrics Agent**
   - Own boundary preparation, H3 generation, spatial joins, zones, micro-markets, TAM calculations, accessibility/commute layers, city summaries, metric lineage, and absolute ranking input tables.
   - Must not begin final derivations until upstream normalized contracts pass.

8. **Dashboard and API Agent**
   - Own multi-city backend contracts, city-scoped data loading, routes, caching, All Cities view, city selector, city detail views, rankings UI, exports, and removal of Bangalore-only assumptions.

9. **Independent QA and Reconciliation Agent**
   - Must be independent of the agent that produced the data/code being tested.
   - Recompute totals, inspect samples, run schema/contract/regression/E2E tests, check cross-city leakage, verify ranking semantics, review visual output, and issue PASS/FAIL evidence.
   - Cannot waive its own failures; only the orchestrator may request owner acceptance of a documented exception.

10. **Documentation and Handoff Agent**
    - Maintain the runbook, source lineage, data dictionary, decision log, city status reports, scraper inventory, and final handoff from verified evidence supplied by other agents.
    - Must not invent missing counts or mark unverified work complete.

### 0B. Orchestrator state files

Create and continuously maintain:

```text
orchestration/MASTER_PLAN.md
orchestration/TASK_GRAPH.json
orchestration/AGENT_REGISTRY.md
orchestration/FILE_OWNERSHIP.md
orchestration/DECISION_LOG.md
orchestration/BLOCKERS.md
orchestration/HANDOFF_LOG.md
orchestration/cities/{city_id}/STATUS.md
```

`TASK_GRAPH.json` must give every task a stable ID, city, owner agent, status, dependencies, allowed files/directories, expected outputs, acceptance criteria, and verifier. Allowed statuses are `pending`, `ready`, `in_progress`, `blocked`, `needs_review`, `failed`, and `complete`.

Each agent assignment must include:

- Objective and explicit non-goals.
- Inputs and authoritative file paths.
- Exact files/directories it may modify.
- Required output files and schemas.
- Commands/tests to run.
- Acceptance criteria and evidence required.
- Dependencies and downstream consumers.
- A prohibition on modifying unrelated user files or another agent's owned files.
- A requirement to report assumptions, blockers, changed files, counts, test results, and unresolved risks.

### 0C. Concurrency and sequencing rules

- Cities remain **sequential**: do not start full production collection for city N+1 until city N reaches an admission decision. Source-ID discovery and parser-fixture preparation for later cities may run ahead, but must not write production city datasets.
- Within the active city, parallelize only independent source families after the city mapping/preflight gate passes.
- The schools, projects, and localities/hospitals agents may collect in parallel because they own separate directories.
- Spatial derivation waits for all required normalized source contracts.
- Dashboard framework refactoring may run alongside collection only against fixtures and must not consume unverified production outputs.
- QA begins as soon as a bounded artifact is ready, but the final city admission review waits for all required artifacts.
- Never allow two agents to edit the same file concurrently. The orchestrator assigns ownership first and resolves overlaps through a single integration task.
- Agents must not reset, discard, overwrite, or reformat unrelated changes. They must inspect the current worktree before editing.
- Use atomic writes, city-partitioned output directories, immutable raw layers, and task-specific temporary directories.

### 0D. Agent communication and handoffs

Every agent must return a structured handoff:

```text
TASK_ID:
STATUS: complete | blocked | failed | needs_review
SUMMARY:
FILES_CHANGED:
FILES_CREATED:
COMMANDS_RUN:
TEST_RESULTS:
RECORD_COUNTS:
DATA_COVERAGE:
ASSUMPTIONS:
WARNINGS:
BLOCKERS:
RECOMMENDED_NEXT_TASK:
```

The orchestrator must verify the files and tests rather than trusting the handoff summary. Record accepted handoffs in `orchestration/HANDOFF_LOG.md`. If an agent is blocked, the orchestrator should first inspect the evidence, try a safe alternate path, reassign a narrowly scoped diagnostic task if useful, and ask the owner only when human action or a consequential decision is genuinely required.

### 0E. Review and admission authority

Use a producer–reviewer pattern:

- Source agents produce raw and normalized artifacts.
- The QA agent independently verifies them.
- The spatial agent consumes only contract-passing normalized artifacts.
- The dashboard agent consumes only admitted city summaries/derived data.
- The orchestrator performs the final integration review and changes city status to `admitted`.

No producer may self-certify its final output. A city is admitted only when:

1. All required task dependencies are complete.
2. Independent QA returns PASS.
3. Reconciliation and regression checks pass.
4. The orchestrator verifies evidence and records the admission decision.

### 0F. Recommended execution waves

Use this default wave plan, adapting only when dependencies require it:

- **Wave 1:** Baseline Auditor + Source Mapping Agent + Documentation Agent (inventory skeleton only).
- **Wave 2:** Orchestrator integrates canonical schemas/config and assigns exclusive scraper ownership.
- **Wave 3 for active city:** Schools Agent + Projects Agent + Localities/Hospitals Agent in parallel after preflight PASS.
- **Wave 4:** Independent QA validates each normalized source; failed artifacts return to their producer.
- **Wave 5:** Spatial/Metrics Agent builds city intelligence; Dashboard Agent works against approved contracts/fixtures.
- **Wave 6:** QA Agent performs city-wide reconciliation, UI/E2E, ranking, and Bangalore regression checks.
- **Wave 7:** Orchestrator admits or rejects the city; Documentation Agent finalizes its handoff; then advance to the next city.

At the beginning of work, publish the initial agent registry, task graph, file-ownership map, and Wave 1 assignments. At every wave boundary, report completed tasks, evidence, blockers, changes to the critical path, and the next assignments.

## 1. Scope and target cities

Bengaluru/Bangalore is already complete and is the baseline/reference implementation. Preserve its results and use it as a regression fixture.

Unless the repository or owner supplies a different approved definition of “top 8,” use this explicit working registry:

1. Bengaluru (complete baseline)
2. Delhi NCR
3. Mumbai
4. Hyderabad
5. Chennai
6. Kolkata
7. Pune
8. Ahmedabad

Before scraping, record this assumption in `config/cities.yaml`. Treat Delhi NCR as a metro region, not automatically as only New Delhi. Discover and document whether each source represents Delhi, New Delhi, Noida, Gurugram/Gurgaon, Ghaziabad, and Faridabad as one city or separate city identifiers. If the source splits NCR, collect all approved NCR components, retain `source_city_name`/`source_city_id`, and normalize them to `canonical_city_id: delhi_ncr` without double counting.

Process the unfinished cities sequentially in the exact order above. Complete all gates for one city before starting the next. If a source is blocked, checkpoint the city, document the blocker, and do not silently substitute fabricated or synthetic data.

## 2. Mandatory source policy

Use these sources and the latest corresponding scraper already available on the machine:

- Schools: YellowSlate scraper plus UDISE+ collector and their matching/enrichment pipeline.
- Societies/residential projects: MagicBricks Projects scraper (not the older 99acres societies feed).
- Localities: 99acres Localities scraper.
- Hospitals: Practo Hospitals scraper.

Known code locations to inspect first (resolve paths on the actual machine; do not assume copies are identical):

- Current dashboard/research workspace: `/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest`
- Latest school work: `/Users/malleswararao/Desktop/school extraction`
- YellowSlate scripts: `/Users/malleswararao/Desktop/school extraction/scripts`
- UDISE collector: `/Users/malleswararao/Desktop/school extraction/udise_scraper`
- MagicBricks Projects and 99acres Localities: `/Users/malleswararao/Desktop/Harshith files/final try`
- Practo scraper: `/Users/malleswararao/Desktop/School Data/scratch/practo_hospitals_scraper.py`

Search the Desktop for newer variants using filenames, modification time, Git history where present, and feature completeness. Produce a scraper inventory with path, modified time, inputs, outputs, dependencies, hardcoded Bangalore values, secrets/session requirements, and why the selected version is authoritative. Never copy embedded cookies, login tokens, CAPTCHA answers, or personal credentials into Git. Move runtime secrets to environment variables or ignored local files, and provide `.env.example` containing names only.

Follow applicable site terms, robots directives, rate limits, privacy requirements, and access-control boundaries. Do not bypass CAPTCHAs or anti-bot controls. Human-assisted CAPTCHA/session steps are permitted only where already designed and lawful. Use conservative concurrency, exponential backoff, jitter, caching, resume support, and clear user-agent/contact configuration.

## 3. First deliverable: repository and schema audit

Before modifying code, inspect the full Bangalore pipeline and produce `docs/multicity/00_baseline_audit.md` containing:

- Current frontend and backend architecture, data-loading paths, API endpoints, build/deploy method, and tests.
- Every Bangalore hardcode in UI copy, HTML metadata, JavaScript, Python, geocoder queries, API URLs, file paths, totals, map center/bounds, source city names, source city IDs, slugs, and assumptions.
- Current canonical schemas for schools, societies/projects, localities, hospitals, H3 hexes, zones, micro-markets, catchments, listings, reports, and client summary.
- Metric lineage: source field -> normalized field -> derived metric -> dashboard component.
- Bangalore output counts, null coverage, coordinate coverage, duplicate rates, and key aggregate totals to preserve as regression fixtures.
- Which existing derived metrics are absolute, normalized, percentile, weighted, modeled, or contextual.
- Data leakage/double-counting risks, especially `countable_family_tam` versus nearby/cluster context, project phases, duplicate school campuses, and NCR component cities.

The existing public layer currently includes schemas similar to:

- `schools.json`: name, coordinates, area, fee bracket/min/max, board, students/enrollment source, match status, UDISE code, rank, hex, zone, URL, address/pincode, source/geocoding lineage, and quartile tags.
- `societies.json`: name, coordinates, category, TAM, units, price, locality, hex, zone, URL, confidence, construction status, and price bounds.
- `localities.json`: name, coordinates, price per square foot, budget segment, hex, and zone.
- `hospitals.json`: name, coordinates, category, beds, rating, reviews, hex, and zone.
- `hexes_master.json`: metadata, schema notes, and per-hex intelligence.

Confirm the real schemas from the files; never rely only on this summary.

## 4. City-source discovery: never guess a slug or numeric ID

Create `config/cities.yaml` and a machine-readable `config/source_city_registry.json`. Each canonical city must contain:

```yaml
canonical_city_id: hyderabad
display_name: Hyderabad
aliases: [Hyderabad, Secunderabad]
state: Telangana
country: India
center: {lat: null, lon: null}
bounds: null
source_mappings:
  yellowslate: {city_id: null, city_name: null, city_slug: null, lat: null, lon: null, verified_url: null}
  magicbricks: {city_id: null, city_name: null, verified_url: null}
  99acres: {city_id: null, city_name: null, city_slug: null, review_url: null, verified_url: null}
  practo: {city_query: null, city_slug: null, verified_url: null}
udise:
  collection_mode: pincode
  pincode_file: null
status: pending
```

For every website and city, determine the exact spelling, alias, URL slug, numeric ID, cookie/session city value, and API parameter by observing that website's own city selector, rendered page, embedded state, or network request. Examples from Bangalore are clues only, not templates to blindly mutate:

- YellowSlate uses a city object in cookies and may use `Bengaluru`/`bengaluru`, with fields such as `cityId`, `cityName`, `lat`, `lan`, and `citySlug`. Its `/search` route may depend on `current_city` and `city` cookies; `/schools/{city_slug}` is an alternate route. Discover each city's actual object and result count/page count.
- MagicBricks Projects calls `https://www.magicbricks.com/mbproject/newProjectCards?pageNo={page}&city={numeric_city_id}&possessionCheck=N`. Bangalore's observed ID must not be reused for another city. Discover IDs from MagicBricks's own city selection/network traffic and verify returned `ctname` values.
- 99acres Localities calls a city review/rating page plus `api-aggregator/content/locations/rei/cityPageData` with a value like `{numeric_id}_LOCATION`. It also uses city-specific cookies and fresh request tokens. Discover the review URL, city ID, and cookie state for each city. Never commit a personal session cookie.
- Practo uses `city={site_city_slug}` in the hospital search URL. Validate spelling (for example, whether the site expects `bangalore` rather than `bengaluru`) from Practo's own city selector/canonical URL and verify returned addresses belong to the target city.
- UDISE collection is PIN-code based via the existing human-assisted collector. Build the complete in-scope PIN-code list from authoritative postal/city-boundary data, preserve PIN provenance, and collect through the existing CAPTCHA workflow. Do not automate CAPTCHA solving.

For each mapping, save evidence in `docs/multicity/source_mappings/{canonical_city_id}.md`: discovery timestamp, page URL, redacted request example, returned city label, sample record names/addresses, result count, and validation outcome. Add a preflight command that fetches only one page/sample and fails if at least 90% of sampled records do not match the expected city/region or if the response repeats another city's known sample.

## 5. Refactor all scrapers into configuration-driven, resumable CLIs

Do not maintain seven copy-pasted scripts. Preserve raw source payloads and refactor/adapt the latest scripts to accept a canonical city configuration.

Required CLI shape (adapt to the language while preserving intent):

```bash
python scraper.py --city hyderabad --config config/cities.yaml --output-root data/cities/hyderabad --resume --sample 1
python scraper.py --city hyderabad --config config/cities.yaml --output-root data/cities/hyderabad --resume
```

Every scraper must support:

- `--city`, `--config`, `--output-root`, `--resume`, `--sample/--limit`, request timeout, retry count, sleep/rate limit, and safe worker count.
- Deterministic filenames using `canonical_city_id`, never “bangalore” hardcoded.
- Append-safe JSONL raw capture, atomic normalized output writes, ID-based deduplication, checkpoints, and restart without re-scraping completed pages.
- Source URL, source record ID, source city ID/name, scrape timestamp (UTC), scraper version/commit, raw payload hash, and normalization version.
- Structured logs and a run manifest with pages attempted/succeeded/failed, HTTP status distribution, records raw/unique/normalized/rejected, and rejection reasons.
- A `--dry-run`/preflight mode that prints resolved URLs and city mapping without collecting the full dataset.
- No premature stop merely because a concurrently fetched page is empty while lower pages are still in flight. Determine pagination safely and tolerate transient gaps.
- Schema validation and quarantine files for malformed records.

### 5A. YellowSlate schools

Parameterize the current `DEFAULT_CITY`, city cookie, city slug, coordinates, pagination, output paths, and address heuristics (which currently contain Bengaluru/Bangalore/Karnataka terms). Discover fee-bracket page counts per city dynamically; do not reuse Bangalore's fixed counts. Collect fee records and school detail locations. Preserve YellowSlate IDs, names, school URL, fee range, board/academics, address, coordinates, area, contact fields where allowed, source bracket, and scrape lineage.

Run the HTTP/RSC route when valid and browser fallback only when required. Detect fee-filter leakage and report it. Deduplicate schools appearing in multiple fee brackets, retaining all source observations and a deterministic resolved fee range.

### 5B. UDISE+ schools and YellowSlate matching

Use the current UDISE human-assisted network collector. For each city:

1. Generate and validate a city/metro PIN-code file with provenance.
2. Use the collector dashboard and human-entered CAPTCHA workflow to query each PIN.
3. Store search and report-card API payloads in a city-isolated SQLite database or a database with mandatory `canonical_city_id` columns and unique keys that prevent cross-city collisions.
4. Export normalized UDISE schools and enrollment/metadata using the existing export tools, parameterized by city.
5. Geocode/clean coordinates with city bounds checks and source confidence.
6. Match YellowSlate to UDISE using name, pincode/address, board, and geospatial evidence; use one-to-one assignment where appropriate.
7. Separate automatic, ambiguous, manual, unmatched, and rejected matches. Never force a match to improve coverage.
8. Preserve campus/entity relationships so branches are not merged incorrectly.

Produce match-coverage metrics by school count and UDISE student enrollment. Keep UDISE enrollment as the authoritative student count where matched. YellowSlate fee data enriches UDISE; it must not overwrite stronger UDISE identity/enrollment evidence.

### 5C. MagicBricks residential projects/societies

Parameterize numeric city ID, city name, output paths, pagination, current year logic, and geocoding query. Preserve at minimum project ID/name, developer, project URL, min/max price, formatted prices, price/sqft bounds, total units, possession year, occupancy/ready status, pincode, locality, returned city name, visibility metadata, description where permitted, and lineage.

Do not equate missing units to zero. Do not invent TAM. Detect duplicate phases/projects using source ID first and a conservative name/developer/locality/coordinate rule second; preserve phase-level raw records and document any parent-project rollup. Validate returned `ctname` and sampled addresses against the target city before a full run.

Geocoding must use the configured city/region and bounds, retain candidate score and method, reject out-of-bounds candidates, cache responses, and never silently fall back to a locality centroid as if it were a precise project coordinate. Label centroid/fallback precision explicitly.

Recreate the Bangalore classification/affluence methodology consistently, but calculate city-specific price thresholds transparently. If quartiles are used, preserve raw absolute price, units, and fee values and label quartile metrics as within-city relative metrics.

### 5D. 99acres localities

Parameterize review page URL, `{cityId}_LOCATION`, city-specific cookie values, output paths, max pages, and referer. Capture fresh API tokens through the normal browser session. Read session material only from runtime environment/ignored storage. Do not include the existing embedded personal cookie in production code.

Normalize each locality's source ID/name, coordinates, ratings/reviews if present, price/sqft and budget values, source city, URL, and lineage. Preserve the raw response per page. Deduplicate by source ID and audit repeated pages. Stop only on a confirmed end-of-data condition. Validate locality coordinates and city association.

### 5E. Practo hospitals

Parameterize Practo's city query/slug and output paths. Extract from the page's current structured/Redux state or documented response path, with a parser test fixture. Preserve hospital source ID, name, URL, full locality/address, coordinates if supplied, categories/specialties, rating, review count, bed count only when explicitly sourced, and lineage.

Do not set unknown beds or ratings to zero; use null plus availability flags. Detect challenge/block pages, repeated result pages, and city leakage. Validate addresses/coordinates against the city boundary. Deduplicate branches conservatively; same-name hospitals at different addresses remain separate facilities.

## 6. Canonical multi-city data model

Create versioned schemas and validators. Every entity must include:

```json
{
  "canonical_city_id": "hyderabad",
  "entity_id": "stable-namespaced-id",
  "source": "magicbricks",
  "source_entity_id": "...",
  "source_city_id": "...",
  "source_city_name": "...",
  "name": "...",
  "lat": null,
  "lon": null,
  "coordinate_source": null,
  "coordinate_precision": null,
  "source_url": "...",
  "scraped_at": "UTC ISO-8601",
  "schema_version": "...",
  "quality_flags": []
}
```

Use namespaced IDs such as `{canonical_city_id}:{entity_type}:{source}:{source_id}`. Never rely on a name alone as a primary key. Add `canonical_city_id` to every city-dependent table, cache, API, GeoJSON property, report, and frontend state. Partition outputs as:

```text
data/cities/{city_id}/raw/{source}/...
data/cities/{city_id}/normalized/{schools|societies|localities|hospitals}.json
data/cities/{city_id}/derived/{hexes|zones|micromarkets|catchments|summary}...
data/cities/{city_id}/audits/...
data/master/city_summary.json
data/master/city_rankings.json
```

Maintain raw, normalized, and derived layers. Never edit raw data to make downstream output look correct. All transformations must be reproducible from raw inputs plus versioned configuration.

## 7. Stage-wise research and spatial analysis

Run these stages for each city and save a stage manifest with status, input hashes, output hashes, counts, warnings, and timestamps.

### Stage 0 — City definition and preflight

- Approve source mappings, city/metro boundary, center/bounds, PIN codes, aliases, and Delhi NCR component policy.
- Run one-page/sample preflights for all four source families.
- Produce expected-versus-observed evidence and obtain a PASS before bulk collection.

### Stage 1 — Raw collection

- Run YellowSlate, UDISE, MagicBricks Projects, 99acres Localities, and Practo.
- Preserve append-only raw payloads and manifests.
- Reconcile source-reported totals with collected unique totals.

### Stage 2 — Normalize, clean, and deduplicate

- Validate required fields/types, normalize prices/currencies/units, parse coordinates, standardize nulls, and retain original values.
- Deduplicate only with explainable rules and produce merge ledgers.
- Quarantine malformed/out-of-scope records.
- Produce per-field completeness and source freshness reports.

### Stage 3 — Identity matching and enrichment

- Match YellowSlate schools to UDISE and retain confidence/evidence.
- Geocode only records requiring it; cache and bound-check results.
- Assign authoritative locality/pincode/city labels.
- Preserve source conflicts instead of silently choosing values.

### Stage 4 — Residential classification and family TAM

- Apply the Bangalore methodology consistently after auditing its implementation.
- Keep raw project price, price/sqft, units, status, and source dates.
- Define eligible residential inventory and handling of ready/under-construction projects.
- Derive price/affluence categories with documented city-specific thresholds.
- `countable_family_tam` must be based on non-duplicated eligible direct units/families only. Nearby weighted or cluster context must remain contextual and must never be added to the countable total.
- Report missing-unit coverage and uncertainty; do not impute without an explicitly approved, separately labeled model.

### Stage 5 — H3 and spatial intelligence

- Use a consistent H3 resolution across cities unless a documented technical reason requires otherwise.
- Generate the city analysis footprint from its approved boundary; do not reuse Bangalore hexes.
- Spatially join all entities to city, H3, locality, zone, and micro-market.
- Recalculate direct TAM/units, society/project counts, school/student/fee metrics, hospital counts/beds/reviews, locality price metrics, evidence confidence, habitability, accessibility/commute, and quality flags.
- Generate zones and contiguous micro-markets reproducibly; label modeled/relative scores clearly.
- If OSM/OSRM/Overture/SEZ/metro layers are needed for feature parity, collect them per city with lineage and comparable definitions.

### Stage 6 — City QA and admission gate

Require all of the following before a city enters the master dashboard:

- Source-city mappings verified with evidence.
- No cross-city leakage above the documented tolerance.
- Raw totals reconcile with normalized totals after explained duplicates/rejections.
- Coordinates pass valid-range and city-boundary checks; fallback precision is labeled.
- Stable IDs are unique; no cross-city key collisions.
- Required field completeness thresholds pass (define thresholds before running).
- School UDISE match coverage and enrollment coverage are reported, not hidden.
- Project unit coverage, locality price coverage, hospital coordinate/rating/bed coverage are reported.
- Aggregate rollups equal the sum of admitted child records under the documented deduplication rules.
- Re-running normalization produces identical hashes.
- Bangalore regression metrics and UI behavior remain within approved tolerance.

### Stage 7 — City report

Produce a city research report and machine-readable summary containing source coverage, absolute metrics, within-city analysis, top localities/hexes/micro-markets, caveats, freshness, and recommended field validations. Do not rank cities using incomplete metrics without a coverage warning.

## 8. Master dashboard: multi-city views and absolute rankings

Refactor the current Bangalore-only app into a multi-city app while preserving the Bangalore view.

Required product behavior:

- Global city selector available on every relevant view; city selection persists in the URL and local state.
- “All Cities” overview with a comparable city table, map, data freshness, and coverage badges.
- A city detail route/view that loads only that city's datasets, center/bounds, labels, zones, micro-markets, entities, and reports.
- Cross-city ranking pages based on absolute metrics, not percentile scores, quartile labels, normalized 0–100 scores, or PageRank.
- A metric-definition tooltip with numerator, denominator (if any), unit, source, date, and coverage.
- Sort direction appropriate to the metric and explicit tie handling.
- Null/unknown values displayed as unavailable, never zero.
- Ability to filter ranking by minimum data-completeness threshold and show the denominator/coverage beside each value.
- Download/export includes `canonical_city_id`, metric version, freshness, and coverage.

At minimum, implement city rankings for defensible absolute metrics available consistently across admitted cities:

- Countable affluent family TAM (families/eligible non-duplicated units).
- Direct eligible residential units.
- Unique residential project count.
- Total raw known residential units and unit-data coverage.
- Unique school campus/entity count.
- Total UDISE enrollment and matched-fee enrollment coverage.
- Premium/high-fee school count using one nationally comparable absolute fee threshold, with the threshold and year shown.
- Unique hospital facility count.
- Known hospital bed total plus bed-data coverage (rank only with a visible coverage qualification).
- Unique locality count.
- Any SEZ/office capacity metric only if collected consistently for every city.

Keep these separate from relative within-city metrics:

- Price quartiles, fee quartiles, affluence tier, percentile, normalized score, PageRank, rank shift, and city-specific top-X labels.

The ranking data contract should resemble:

```json
{
  "metric_id": "countable_family_tam",
  "label": "Countable affluent family TAM",
  "unit": "families",
  "metric_type": "absolute",
  "direction": "desc",
  "methodology_version": "...",
  "as_of": "...",
  "rows": [
    {
      "canonical_city_id": "hyderabad",
      "value": 123456,
      "rank": 1,
      "coverage_pct": 91.2,
      "quality_status": "qualified",
      "source_count": 1234
    }
  ]
}
```

Compute rankings in a backend/build step from validated city summaries; do not hardcode them in frontend JavaScript. Use a deterministic competition-ranking policy (`1, 2, 2, 4`) or another documented policy. Rankings must update automatically when a city dataset is refreshed.

Remove/refactor hardcoded references such as Bangalore titles, `totalBangaloreTam`, Bengaluru-only geocoder suffixes, fixed coordinates, static file paths, and Bangalore-specific copy. Do not use global mutable data that can mix cities. All API requests and caches must be city-scoped and reject unknown city IDs.

## 9. Testing and verification

Add and run:

- Unit tests for city config validation, URL construction, city-cookie construction, parsing fixtures, normalization, ID creation, deduplication, geofence checks, absolute ranking, ties, nulls, and coverage qualification.
- Contract tests for every public JSON/API schema.
- Scraper parser tests using saved redacted fixtures; live-network tests must be optional.
- Integration test that builds two small city fixtures and proves no cross-city contamination.
- Bangalore regression tests for counts, totals, routes, map center, key copy, and representative UI flows.
- End-to-end browser checks for All Cities, switching cities, deep-linking, rankings, map layers, empty/error/loading states, and responsive layout.
- Reconciliation scripts that independently recompute city totals from normalized records and compare them to dashboard summaries/rankings.

After frontend changes, run the app locally and visually inspect screenshots at desktop and mobile sizes. Check browser console and network failures. Verify that map layers and detail drawers display the selected city's data only.

## 10. Sequential execution protocol

For each city, create `runs/{NN}_{city_id}/STATUS.md` and keep this checklist current:

1. City/source mapping discovered and evidenced.
2. All source preflights passed.
3. Raw collection complete and reconciled.
4. Normalization/deduplication complete.
5. School matching and enrichment complete.
6. Spatial/affluence/TAM analysis complete.
7. QA/admission gate passed.
8. Dashboard data generated.
9. City UI and ranking verified.
10. City report and handoff complete.

At the end of each city, stop and produce a concise checkpoint: files created, exact record counts, coverage, warnings, failed pages/records, tests run, and whether the admission gate passed. Then proceed to the next city only if it passed or the owner explicitly accepts the documented exception.

Commit/checkpoint work in small reversible units if version control is available. Never delete or overwrite the Bangalore raw/reference data. Preserve unrelated user changes.

## 11. Required final deliverables

Deliver all of the following:

- Configuration-driven scrapers/adapters and city registry.
- Raw, normalized, derived, and audit data for each successfully completed city.
- Versioned schemas, data dictionary, source lineage, metric definitions, and city mapping evidence.
- Master city summaries and absolute ranking files.
- Multi-city dashboard with All Cities overview and city detail views.
- Automated tests, reconciliation checks, and visual QA evidence.
- `docs/multicity/RUNBOOK.md` with exact setup and commands, human-assisted UDISE/session steps, resume/retry instructions, refresh workflow, and deployment steps.
- `docs/multicity/FINAL_HANDOFF.md` listing city-by-city status, counts, coverage, freshness, known limitations, and anything requiring owner action.

## 12. Non-negotiable accuracy rules

- Never guess website city slugs, IDs, names, pagination counts, or URL formats; discover and verify each one.
- Never fabricate missing schools, units, prices, enrollment, beds, ratings, coordinates, or TAM.
- Never treat null as zero.
- Never present a relative/normalized score as an absolute cross-city metric.
- Never rank incomparable definitions together.
- Never hide low coverage; show it adjacent to the metric and qualify/exclude as specified.
- Never commit cookies, tokens, CAPTCHA answers, passwords, or personal identifiers.
- Never say a scrape succeeded based only on HTTP 200; validate the returned city and records.
- Never admit a city to the master dashboard before its QA gate passes.
- Preserve source lineage and raw evidence so every dashboard number can be reproduced and audited.

Begin now with the baseline audit and scraper inventory. Show your evidence and decisions as you work, but keep progressing autonomously unless a human CAPTCHA, login/session action, source-policy issue, or genuinely consequential product decision requires owner input.
