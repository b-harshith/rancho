# Multi-City Data Dictionary

> Status: schema-oriented skeleton. Existing files must be audited before field types or availability are treated as final. `TODO` indicates an unresolved contract; no counts are asserted here.

## 1. Conventions

- Layers: `raw` preserves source payloads; `normalized` holds canonical entities; `derived` holds reproducible analysis; `audit` holds validation evidence.
- Null means unknown/unavailable and must not be coerced to zero.
- IDs are namespaced: `{canonical_city_id}:{entity_type}:{source}:{source_id}`.
- All city-dependent records, tables, caches, APIs, GeoJSON properties, reports, and UI state require `canonical_city_id`.
- Timestamps use UTC ISO-8601.
- Original source values are retained alongside normalized values where transformation occurs.
- Coordinate fallback/centroid values require explicit precision labels.

## 2. Common entity fields

| Field | Type | Layer | Definition / constraint | Lineage requirement | Status |
| --- | --- | --- | --- | --- | --- |
| `canonical_city_id` | string | normalized+ | Approved canonical registry key | city registry | Required by specification; validator TODO |
| `entity_id` | string | normalized+ | Stable namespaced identifier | city, entity type, source, source ID | Required by specification; validator TODO |
| `source` | string | normalized+ | Source system name | raw capture | Required |
| `source_entity_id` | string/null | normalized+ | Identifier assigned by source | raw source field | Null only if source truly supplies none; fallback policy TODO |
| `source_city_id` | string/null | raw+ | Source-specific city identifier | verified city mapping | Never guessed |
| `source_city_name` | string/null | raw+ | City label returned by source | response/rendered evidence | Used for leakage checks |
| `name` | string | normalized+ | Entity display name | source field + documented cleaning | Required-field policy TODO by entity |
| `lat`, `lon` | number/null | normalized+ | WGS84 coordinates | source/geocoder candidate | Must be range and boundary checked |
| `coordinate_source` | string/null | normalized+ | Provider or derivation method | source/geocode log | Required when coordinates exist |
| `coordinate_precision` | string/null | normalized+ | E.g. rooftop, address, locality centroid | provider response/method | Centroid never presented as precise |
| `source_url` | string/null | raw+ | Record/page URL | source | Redact sensitive query material |
| `scraped_at` | string | raw+ | UTC collection timestamp | collector | Required |
| `schema_version` | string | normalized+ | Versioned contract identifier | schema registry | Required |
| `normalization_version` | string | normalized+ | Transformation version | pipeline | TODO contract |
| `raw_payload_hash` | string | raw+ | Deterministic hash of captured payload | collector | TODO algorithm/version |
| `quality_flags` | array[string] | normalized+ | Machine-readable caveats | validators/transforms | Empty array means no detected flags, not guaranteed perfection |

## 3. Entity-specific fields

### Schools and school identity

| Field | Type | Meaning | Source/derivation | Status |
| --- | --- | --- | --- | --- |
| `school_entity_id` | string | Canonical institution identity | entity resolver | TODO final name/schema |
| `campus_id` | string | Physical campus identity | campus resolver | TODO final name/schema |
| `udise_code` / `udise_codes` | string/null or array | UDISE identity evidence | UDISE+ | Confirm actual canonical shape |
| `address`, `pincode`, `area` | string/null | Location descriptors | source + normalization | Preserve original value |
| `board` / `boards` | string/null or array | Academic affiliation | YellowSlate/UDISE | Conflict policy TODO |
| `fee_min_inr`, `fee_max_inr` | number/null | Annual fee bounds in INR under documented basis | YellowSlate enrichment | Fee period/year contract TODO |
| `students_total` | integer/null | Authoritative total enrollment when available | UDISE+ when matched | Never estimate silently |
| `grade_2_9_enrollment` | integer/null | Enrollment for specified grades | UDISE/derived | Grade/year definition required |
| `enrollment_source` | string/null | Provenance of enrollment value | lineage | Required when enrollment exists |
| `match_status` | string | automatic/ambiguous/manual/unmatched/rejected | matcher | Controlled vocabulary TODO |
| `match_confidence` | number/null | Match confidence under versioned method | matcher | Scale/thresholds TODO |
| `match_evidence` | object/array | Identity/address/board/spatial evidence | matcher | Schema TODO |
| `fee_quartile` | string/null | Within-city relative fee band | derived city distribution | Relative; not cross-city absolute |

### Residential projects / societies

| Field | Type | Meaning | Source/derivation | Status |
| --- | --- | --- | --- | --- |
| `project_id` | string | Canonical project/phase identity | entity resolver | TODO relation to `entity_id` |
| `source_project_id` | string/null | MagicBricks project ID | source | Preserve phase record |
| `developer` | string/null | Developer name | MagicBricks | Normalization rules TODO |
| `project_url` | string/null | Source project URL | MagicBricks | Redact sensitive parameters |
| `min_price_inr`, `max_price_inr` | number/null | Absolute advertised price bounds | source normalization | Preserve formatted/original values |
| `min_price_per_sqft_inr`, `max_price_per_sqft_inr` | number/null | Price/sqft bounds | source normalization | Definition/date required |
| `total_units` | integer/null | Source-known residential units | MagicBricks | Missing is null, never zero |
| `possession_year` | integer/null | Source possession year | MagicBricks | Current-year logic versioned |
| `construction_status` | string/null | Ready/under-construction/etc. | source normalization | Vocabulary TODO |
| `locality`, `pincode` | string/null | Project location | source | City/boundary validation required |
| `parent_project_id` | string/null | Conservative phase rollup parent | derived | Rollup ledger required |
| `eligible_for_direct_tam` | boolean/null | Inclusion under approved residential policy | derived | Method/version required |
| `countable_family_tam` | number/null | Non-duplicated eligible direct units/families | derived | Absolute; no nearby context added |
| `nearby_family_tam_weighted_context` | number/null | Weighted nearby context | derived | Context only, non-additive |
| `society_cluster_tam_weighted_context_not_counted` | number/null | Cluster influence | derived | Context only, non-additive |
| `price_quartile`, `affluence_tier` | string/null | Within-city relative classification | city distribution | Not cross-city ranking metrics |

### Localities

| Field | Type | Meaning | Source/derivation | Status |
| --- | --- | --- | --- | --- |
| `source_locality_id` | string/null | 99acres locality identifier | source | Dedup key where present |
| `locality_name` | string | Normalized locality name | source + cleaning | TODO relation to `name` |
| `rating` | number/null | Source-provided locality rating | 99acres | Scale/date TODO |
| `review_count` | integer/null | Source review count | 99acres | Null if unavailable |
| `price_per_sqft_inr` | number/null | Absolute locality price/sqft | 99acres | Aggregation basis/date TODO |
| `budget_value_inr` | number/null | Source budget value | 99acres | Exact definition TODO |
| `budget_segment` | string/null | Derived/source classification | versioned method | Absolute-vs-relative tag required |

### Hospitals

| Field | Type | Meaning | Source/derivation | Status |
| --- | --- | --- | --- | --- |
| `source_hospital_id` | string/null | Practo facility identifier | source | Branch-safe identity |
| `hospital_url` | string/null | Source facility URL | Practo | Preserve canonical URL where supplied |
| `address`, `locality` | string/null | Facility location | Practo | Used in branch dedup/city validation |
| `categories`, `specialties` | array[string] | Facility categories/specialties | Practo | Normalization vocabulary TODO |
| `rating` | number/null | Explicit source rating | Practo | Unknown remains null |
| `review_count` | integer/null | Explicit source review count | Practo | Unknown remains null |
| `bed_count` | integer/null | Explicitly sourced bed total | Practo/approved source | Never inferred from facility type |
| `bed_count_available` | boolean | Whether bed data is explicitly known | derived availability flag | TODO canonical name |

### Spatial, zones, micro-markets, and catchments

| Field | Type | Meaning | Source/derivation | Status |
| --- | --- | --- | --- | --- |
| `hex_id` | string | H3 cell ID at approved resolution | H3 | Resolution metadata required |
| `h3_resolution` | integer | H3 resolution | config | Common across cities unless documented exception |
| `zone_id`, `micromarket_id` | string/null | Reproducible spatial grouping IDs | derived | Algorithm/version TODO |
| `direct_family_tam` | number/null | Non-duplicated direct TAM in area | eligible direct entities | Absolute; reconcile to children |
| `q3_and_below_property_count` | integer/null | Count under baseline-defined project quartile rule | derived | Relative classification input; definition audit TODO |
| `confidence_score` | number/null | Evidence-strength score | derived | Modeled; scale/components TODO |
| `habitability_score` | number/null | Residential plausibility signal | building evidence/model | Modeled; not an absolute count |
| `commute_score` | number/null | OSM/OSRM commute-friction proxy | routing model | Contextual/model; not live traffic |
| `quality_flags` | array[string] | Spatial/data caveats | QA | Definitions/version TODO |

## 4. City summary and ranking contracts

### City summary fields

The exact summary schema is **TODO**. At minimum it must include `canonical_city_id`, methodology/schema versions, `as_of`, source freshness, admission status, absolute values, denominators, coverage, source counts, and quality status. Every aggregate must reconcile to admitted normalized child records.

### Ranking metric object

| Field | Type | Definition |
| --- | --- | --- |
| `metric_id` | string | Stable metric identifier |
| `label` | string | Human-readable name |
| `unit` | string | Display/comparison unit |
| `metric_type` | string | `absolute`, `relative`, `modeled`, `contextual`, or **TODO approved vocabulary** |
| `direction` | string | `asc` or `desc` |
| `methodology_version` | string | Version defining calculation |
| `as_of` | string | Metric freshness/date basis |
| `rows[].canonical_city_id` | string | Admitted city key |
| `rows[].value` | number/null | Metric value; null remains unavailable |
| `rows[].rank` | integer/null | Deterministic rank only for qualified comparable values |
| `rows[].coverage_pct` | number/null | Numerator/denominator coverage percentage |
| `rows[].quality_status` | string | Qualified/excluded/warning status; vocabulary TODO |
| `rows[].source_count` | integer/null | Number of contributing source records |

Tie policy required by specification: deterministic competition ranking (`1, 2, 2, 4`) unless an alternative is approved and documented.

## 5. Lineage template

Every published field/metric must be traceable through:

| Published field/metric | Raw source field(s) | Raw artifact | Normalization | Derived method/version | Output artifact/component | Freshness | Coverage/quality |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO |

Current high-level baseline lineage mentions curated societies, schools, hospitals, localities, SEZ zones, Overture building evidence, metro stations, and OSRM routing graph, but exact field-level lineage is **unverified/TODO**.

