# Multi-City Metric Definitions

> Status: methodology skeleton. A metric is publishable only after its formula, scope, unit, freshness, coverage denominator, source lineage, and qualification rules are completed and verified. No threshold or count is implied by a placeholder.

## 1. Metric classification

### Absolute and potentially cross-city comparable

These metrics may be ranked across admitted cities only when definitions, periods, and coverage are comparable:

- Countable affluent family TAM.
- Direct eligible residential units.
- Unique residential project count.
- Total raw known residential units and unit-data coverage.
- Unique school campus/entity count.
- Total UDISE enrollment and matched-fee enrollment coverage.
- Premium/high-fee school count under one national absolute fee threshold and year.
- Unique hospital facility count.
- Known hospital bed total with visible bed-data coverage qualification.
- Unique locality count.
- SEZ/office capacity only if collected consistently for every ranked city.

### Relative, within-city only

Do not use these for absolute cross-city rankings:

- Price quartiles and fee quartiles.
- Affluence tiers derived from city distributions.
- Percentiles and normalized 0–100 scores.
- PageRank, rank shift, and city-specific top-X labels.

### Modeled or contextual

Keep these visibly distinct from direct counts:

- Confidence and habitability scores.
- Commute/accessibility proxies.
- Nearby weighted family TAM context.
- Cluster influence/context.
- Any imputed quantity under a separately approved model.

## 2. Required metric specification template

Complete this block for every published metric:

| Attribute | Required content |
| --- | --- |
| Metric ID / label | Stable ID and user-facing label |
| Type | Absolute, relative, modeled, or contextual |
| Unit | Families, units, facilities, students, INR/year, percent, etc. |
| Grain | City, H3, zone, micro-market, catchment, entity |
| Numerator | Exact included records/value |
| Denominator | Exact coverage/rate denominator, or `not applicable` |
| Formula | Deterministic calculation |
| Inclusion/exclusion | Status, boundary, identity, dedup, and eligibility rules |
| Sources | Raw fields and approved sources |
| Time basis | As-of date/year and refresh policy |
| Methodology version | Version identifier |
| Coverage | Formula and minimum qualification threshold |
| Null handling | Unknown remains null; exclusion behavior |
| Direction / ties | Ranking direction and deterministic tie rule |
| QA/reconciliation | Independent recomputation and expected equality |
| Known limitations | Bias, missingness, comparability constraints |

## 3. Absolute metric definitions

### `countable_family_tam`

- Type: absolute.
- Unit: families / eligible non-duplicated direct units.
- Definition: sum of direct units/families from eligible, non-duplicated residential inventory under the approved methodology.
- Explicit exclusion: `nearby_family_tam_weighted_context`, cluster influence, duplicate phases/projects, ineligible inventory, and unknown units.
- Formula: **TODO after baseline method audit**.
- Eligibility/status rules: **TODO**.
- Affluence criterion and national/city basis: **TODO; must be explicit before cross-city comparison**.
- Coverage: contributing eligible projects with known units divided by all eligible projects, plus any value-weighted denominator approved by methodology (**TODO**).
- Reconciliation: city value must equal admitted child-record contributions under the documented dedup ledger.

### `direct_eligible_residential_units`

- Type: absolute; unit: units.
- Numerator: known `total_units` for non-duplicated projects/phases meeting the approved eligibility policy.
- Unknown units: excluded from numerator and exposed through coverage; never treated as zero.
- Eligibility, phase rollup, and date rules: **TODO**.

### `unique_residential_project_count`

- Type: absolute; unit: projects.
- Numerator: admitted unique projects after source-ID-first and conservative secondary deduplication.
- Parent project versus phase counting policy: **TODO** and must remain consistent across cities.

### `total_raw_known_residential_units`

- Type: absolute; unit: units.
- Numerator: known units before eligibility/TAM filtering, after approved duplicate handling.
- Coverage percentage formula: **TODO**; denominator must be all in-scope unique residential records, not only known-unit records.

### `unique_school_campus_count`

- Type: absolute; unit: physical campuses.
- Numerator: admitted unique physical campuses; branches at different locations remain separate.
- Campus/entity resolver and ambiguous handling: **TODO**.

### `unique_school_entity_count`

- Type: absolute; unit: institutions/entities.
- Numerator: admitted canonical school entities under the versioned identity policy.
- Relationship to campuses and multi-campus institutions: **TODO**.

### `total_udise_enrollment`

- Type: absolute; unit: students.
- Numerator: authoritative UDISE enrollment for unique admitted schools/campuses under an approved academic-year and grade scope.
- Academic year, grade scope, entity/campus rollup: **TODO**.
- Never substitute YellowSlate or modeled enrollment without separate labeling.

### `matched_fee_enrollment_coverage_pct`

- Type: absolute coverage rate; unit: percent.
- Intended numerator: UDISE enrollment attached to valid YellowSlate fee matches.
- Intended denominator: total in-scope UDISE enrollment.
- Match-status inclusion and fee validity/year: **TODO**.
- Report school-count match coverage separately from enrollment-weighted coverage.

### `premium_high_fee_school_count`

- Type: absolute; unit: schools/campuses (**TODO choose one grain**).
- Numerator: unique admitted records whose comparable annual fee meets one national INR threshold.
- Threshold amount, fee components, academic year, grade basis, and inflation treatment: **TODO/owner approval required**.
- City-specific quartiles must not be used for this cross-city count.

### `unique_hospital_facility_count`

- Type: absolute; unit: facilities.
- Numerator: admitted unique branches/facilities; same-name different-address branches remain separate.
- Dedup and category eligibility: **TODO**.

### `known_hospital_bed_total`

- Type: absolute but coverage-qualified; unit: beds.
- Numerator: explicitly sourced bed counts for unique admitted facilities.
- Unknown beds remain null and contribute no invented value.
- Coverage: facilities with known beds divided by in-scope facilities; optional second denominator by another defensible basis is **TODO**.
- Ranking qualification threshold: **TODO before ranking**.

### `unique_locality_count`

- Type: absolute; unit: localities.
- Numerator: admitted unique 99acres localities after source-ID-first deduplication and city validation.
- Boundary edge cases and aliases: **TODO**.

### `sez_office_capacity`

- Type: absolute only if consistent source and definition exist for every ranked city.
- Unit/formula/source/coverage: **TODO**.
- Until completed and comparable, exclude from cross-city rankings.

## 4. Relative and contextual metric definitions

### `price_quartile`, `fee_quartile`, and `affluence_tier`

Within-city classifications derived from that city's eligible distribution. Preserve the underlying INR values. Population, interpolation, ties, missing values, and refresh behavior are **TODO**. These labels do not mean equal purchasing power or price level across cities.

### `nearby_family_tam_weighted_context`

Contextual weighted signal from nearby inventory. Formula, radius/decay, dedup safeguards, and version are **TODO**. It must never be added to `countable_family_tam`.

### `society_cluster_tam_weighted_context_not_counted`

Contextual cluster-influence signal. Formula and topology are **TODO**. It is not a unique-family count.

### `q3_and_below_property_count`

Baseline documentation describes this as a market-depth signal for Q1/Q2/Q3 projects, separate from Q4 TAM scoring. Quartile ordering, project universe, city-specific thresholds, and rollup grain require baseline audit before reuse.

### `confidence_score`

Modeled evidence-strength score. Inputs, weights, range, thresholds, and calibration are **TODO**. It must not be presented as an absolute market size.

### `habitability_score`

Modeled residential-plausibility signal using building evidence. Inputs, provider version/date, range, and missingness policy are **TODO**.

### `commute_score`

Contextual OSM/OSRM-derived commute-friction proxy; not live traffic. Destinations, travel mode, routing snapshot, formula, range, and unreachable-route behavior are **TODO**.

## 5. Ranking and qualification policy

- Rank only admitted cities with comparable methodology versions and time bases.
- Default tie policy: competition ranking (`1, 2, 2, 4`), with deterministic secondary display order by `canonical_city_id`.
- Direction is metric-specific and must be declared.
- Null values receive no numeric rank and display as unavailable.
- Low-coverage values must show coverage adjacent to the value and be warned or excluded under a predeclared threshold.
- Never infer rank from percentile, quartile, normalized score, or PageRank.
- Ranking build must be deterministic and generated from validated city summaries, not frontend constants.

Qualification thresholds for every metric are **TODO and must be fixed before seeing final city rankings to reduce outcome-driven threshold selection**.

