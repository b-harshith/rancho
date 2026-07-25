# Bengaluru baseline architecture, schema, and regression audit

Audit task: `W1-BASELINE-AUDIT`  
Snapshot inspected: 2026-06-30, Asia/Kolkata  
Scope: the supplied `web_platform_vercel_exact_latest` directory only. The source-scraper locations outside this workspace belong to the source-mapping audit.

## Executive finding

The workspace is a Python/vanilla-JavaScript, file-backed Bengaluru decision-support application, not yet a city-partitioned platform. It contains a useful canonical school entity/campus ledger and live-drive catchment contract, but residential/hex artifacts are internally inconsistent and cannot yet be frozen as one golden numeric fixture. In the inspected working snapshot, `src/public/data/hexes.geojson`, `hexes_master.json`, `client_summary.json`, and `report.json` disagree on both hex count and family TAM (details below). The checked-in validation summary itself records a failed GeoJSON-versus-zone-TAM reconciliation. This is the principal baseline admission blocker.

The workspace also has no `.git` directory, so dirty-worktree/history checks are unavailable. File timestamps and content were used as evidence. No regression fixture was created: copying a currently irreconcilable artifact would bless an unknown state.

## 1. Architecture, loading, APIs, build, deployment, tests

### Runtime architecture

- Frontend: a single large static application in `src/public/index.html`, `index.js`, `events.js`, and CSS. Leaflet renders the maps; D3 renders the graph; all city data is held in browser globals after startup.
- Static data: `src/public/data/*`. `index.js:1093-1108` concurrently fetches hexes, report, localities, societies, hospitals, zones, summary, commute, Bengaluru metro, offices, micro-markets, project assets, and canonical school artifacts.
- Local backend: `src/server.py` uses `http.server.SimpleHTTPRequestHandler`, serves `src/public`, loads data into process-global dictionaries/spatial indexes, and dispatches API requests.
- Serverless backend: `src/api/catchment.py` and `src/api/listings.py`; shared domain logic lives in `src/api/catchment_market.py` (`SCHEMA_VERSION = "2.0"`).
- Persistence: only commercial listings are mutable, in SQLite `src/listings.db`; research datasets are JSON/GeoJSON files.
- Spatial stack: H3 resolution 7, Shapely geometries/STRtree, live Google drive isochrones for catchments, and precomputed OSRM/Google-derived routing context in data artifacts.

### Endpoints

| Method/path | Implementation | Contract/use |
| --- | --- | --- |
| `GET /api/catchment` | `server.py` locally; `api/catchment.py` on Vercel | Required `lat`, `lon`; live DRIVE/TRAFFIC_AWARE time isochrone; optional duration, bands, fee thresholds/capture parameters. Returns schema/version, geometry/cache metadata, residential aggregates, canonical school market, and capacity scenarios. |
| `POST /api/catchment` | same | Portfolio of at most 10 centers or supplied center results; unions unique entities/campuses, reports overlap and incremental reach. |
| `OPTIONS /api/catchment` | same | CORS preflight. |
| `GET /api/listings` | `api/listings.py` | List/fetch saved commercial listings. |
| `POST /api/listings` | `api/listings.py` | Create/update a listing and stored raw JSON. |
| `DELETE /api/listings?id=...` | `api/listings.py` | Delete a listing. |
| static `/*` | Vercel/static or local handler | Frontend and public data. |

The SQLite table is `commercial_listings(id, title, property_type, price, sqft, floor, amenities, latitude, longitude, listing_url, score, metro_name, metro_distance, road_type, visibility_score, catchment_tam, catchment_kids, raw_data, created_at)`.

### Build/deploy

There is no Node package/build step. `src/vercel.json` deploys `api/**/*.py` with `@vercel/python` (including `public/data/**`) and `public/**/*` with `@vercel/static`, routing `/api/(.*)` to `api/$1.py`. Python dependencies are only `requests`, `h3`, and `shapely`. Local execution is `python3 src/server.py` on `PORT` (default 8050). Important mismatch: the local monolithic server includes dispatch behavior and fallback data preparation that Vercel does not necessarily exercise.

### Tests and observed result

`python3 -m unittest discover -s tests -v` ran 26 tests and all passed. Coverage is concentrated in:

- canonical school identity/campus rules, quartiles, fee sensitivity, enrollment/capacity reconciliation (`tests/test_build_school_market.py`);
- catchment market inclusion, fee cohorts, portfolio deduplication/overlap, request validation, Google geometry cache/error behavior (`tests/test_catchment_market.py`).

Missing automated coverage: frontend/E2E and visual behavior; static-file schema contracts; Vercel routing/deployment smoke test; listings CRUD; cross-file TAM/hex reconciliation; localities/hospitals/projects data QA; city isolation; secrets scanning.

## 2. Data lineage and loading paths

| Layer | Inputs | Transform | Published/consumed outputs |
| --- | --- | --- | --- |
| Schools raw/enriched | `new data/schools.json`, `schools_geocoded.json` | `geocode_schools.py`; `build_school_market.py` resolves entity/campus identity, quarantines conflicts, assigns fee quartiles | `src/public/data/schools.json` (legacy/detail), `school_entities.json`, `school_campuses.json`, `school_market_summary.json`, `school_market_audit.json`; catchment consumes **entities only** |
| Projects/societies | `new data/bangalore_projects_classified.json`, `bangalore_projects_geocoded.json`; Stage 2 Q4 file; optional external raw feed | `geocode_projects.py`; `rerun_society_layer.py`; legacy `prepare_data.py` | `src/public/data/societies.json`, per-hex society evidence and reports |
| Localities | expected `DATA/raw/bangalore_localities_enriched.json` or an external sibling path | `prepare_data.py` / `rerun_society_layer.py` | `src/public/data/localities.json`, market fields in hexes |
| Hospitals | `DATA/Stage2 processing/Categorized Hospitals.json` | `prepare_data.py` / society-layer rerun | `src/public/data/hospitals.json`, per-hex hospital evidence |
| H3/derived | Stage 2 master, societies, localities, hospitals, SEZ, Overture, routing | historical active scripts named in `DATA/client_handoff/SOURCE_LINEAGE.md` are **not present in this workspace**; `rerun_society_layer.py` dynamically imports an external sibling generator | `hexes_master.json`, `hexes.geojson`, `report.json`, commute, graph, zones, micro-markets, client summary |
| UI | all `src/public/data/*` above | browser aggregation/filtering and API calls | maps, rankings, exports, catchment planner, school market, commercial listings |

Lineage weakness: several authoritative scripts referenced by the handoff (`scripts/active/generate_stage2_hex7_affluence.py`, spatial diagnostics, final intelligence, client outputs) are absent. `rerun_society_layer.py` also falls back to absolute Desktop sibling paths. Thus not every public number is reproducible from this directory alone.

## 3. Confirmed schemas from real files

The following are observed unions of keys, not inferred interfaces.

### Schools

- Legacy/public school row (`schools.json`, 2,007): `name, lat, lon, source_lat, source_lon, area, address, pincode, url, source, board, structural_category, category, fee, fee_text, fee_min, fee_max, fee_bracket_key, fee_bracket_label, fee_bracket_min, fee_bracket_max, students, students_total, students_grades_2_9, enrollment_source, match_status, udise_code, google_place_id, google_formatted_address, google_locality, google_postal_code, google_types, google_geocode_query, google_geocode_source, google_geocode_confidence, google_geocode_distance_m, hex_id, zone, rank_in_bracket, quartile analysis 1, quartile analysis 2, quartile_category, quartile_tag`.
- Canonical entity (`school_entities.json`, 1,996): stable `entity_id`/`school_entity_id`, `campus_id`, identity/source indexes and aliases, coordinates/area/address/pincode/URL, raw and normalized boards, affiliation, fee range/basis/quartile/subquartile/segment, total and grades 2-9 enrollment/source/status, UDISE codes, Google place, structural categories, merge status, H3/zone.
- Canonical campus (`school_campuses.json`, 1,961): `campus_id`, entity ID arrays/count, representative enrollment entity, non-summing `campus_enrollment_rule`, source enrollment, coordinates/address/area/URL, fee range, boards, Q4 entity context, H3/zone. Campus-level `quartile`, `q4_subquartile`, and `q4_segment` are present but null in all rows; use `has_q4_entity` and entity data.

### Residential projects/societies

`societies.json` row (2,268): `name, lat, lon, locality, category, tam, units, price, min_price, max_price, confidence, construction_status, url, hex_id, zone`. There is no source ID, RERA ID, phase/project relationship, source city, or lineage field in this public contract; API fallback generates a hash-like society ID.

### Localities

`localities.json` row (587): `name, lat, lon, price_sqft, budget_segment, hex_id, zone`. Missing source locality ID, ratings/reviews, budget bounds, URL, city, and lineage.

### Hospitals

`hospitals.json` row (235): `name, lat, lon, category, beds, rating, reviews, hex_id, zone`. Missing stable source ID, URL/locality in the public row, city, and lineage.

### H3 hexes

- Nested master top level: `{metadata, schema_notes, hexes}`; 310 rows at inspection. Each row includes identity/rank/name/centroid/zone, affluence tier and scores/components/confidence, `tam`, `market`, `habitability`, `commute`, routing, direct/nearby society evidence, hospitals, POIs, spatial relation, quality flags, and decision notes.
- Frontend GeoJSON: `FeatureCollection`; 308 features at the measured snapshot. Properties include rank/identity/centroid/zone; final affluence/confidence; direct/countable/context TAM and units; income estimates; market, society, hospital, SEZ, habitability and commute scores; direct/nearby counts; quality flags; PageRank/community fields. Geometry is a H3 polygon.

### Zones, micro-markets, catchments, reports, summary

- Zones are not standalone canonical records. `report.json.zones` is keyed by zone name; values aggregate `hex_count`, scores/tiers, direct/countable/cluster TAM, direct units, income bands, projects, hospitals, habitability, market/commute and evidence summaries. Zone assignment is a nine-class compass model around hardcoded Bengaluru center.
- Micro-markets (`micromarket_suggestions_8hex.json.disjoint_micro_markets`, 12): `hex_ids, total_units, total_tam, avg_score, combined_score, norm_units, norm_score, q3_and_below_property_count`. No stable ID/city ID/version in each row.
- Catchment response v2.0: geography + live isochrone metadata; metrics/comparison bands in handler; `school_market` with cohort/direct/adjacent/reachable/excluded/entities/campuses/absolute-fee sensitivity; `residential_market` with included tiers, inside-isochrone unique society totals/by-tier/rows; capacity scenarios. Portfolio adds unique entity/campus/enrollment totals, shared touchpoints, pairwise Jaccard/overlap, incremental-by-request-order, and capacity.
- Report (`report.json`): `overall`, `coverage`, `zones`, `top_10_micro_markets`, `all_micro_market_count`, `commute_summary`.
- Client summary: `generated_from, coverage, executive_metrics, recommendations, sensitivity, validation, commute, handoff_links, quartile_breakdown, project_type_breakdown`.

No canonical catchment file exists; catchments are request-time results. There is no canonical multi-city schema or `canonical_city_id` in any inspected public record.

## 4. Metric lineage and semantic type

| Source field/evidence | Normalized field | Derived/dashboard metric | Type and dashboard use |
| --- | --- | --- | --- |
| project `Total Units` / classified estimated families | society `units`, `tam`, category | per-hex `direct_total_units`, `direct_family_tam`; zone/micro-market totals; residential catchment `family_proxy` | Absolute proxy. Unique only if project/phase dedupe is correct. Used in hex/zone/micro-market/catchment KPIs. |
| society point + H3 polygon | `hex_id`, direct membership | `countable_family_tam` | Intended absolute primary TAM, sometimes habitability-filtered; current artifacts conflict. Never add nearby/cluster context. |
| societies within 2/3 km, category/confidence, exponential distance decay | nearby/cluster mass | `nearby_family_tam_weighted_context`, `society_cluster_tam_weighted_context_not_counted` | Weighted modeled context, non-additive. Used as evidence/score only. |
| society direct/nearby/cluster, resale/rental liquidity | component scores | `society_score`; `base_affluence_score = 100*(.50 society + .10 hospital + .22 market + .18 SEZ)` | Normalized weighted model score. |
| base score + neighboring mean + island/cluster adjustments | spatial evidence | `final_affluence_score`, tier, rank | Weighted/spatially modeled and ranked; not an absolute market size. Map colors/rankings. |
| locality price/yield/appreciation/activity/budget distribution | market normalization | market score, price/sqft, premium candidate | Mixed: price/yield/appreciation are contextual observed/derived values; score/candidate are normalized/modelled. |
| Overture building counts/area | coverage/density | habitability score/class and countability gate | Context + normalized modeled gate. |
| hospitals rating/reviews/beds and routed proximity | normalized hospital evidence | hospital score/top hospitals | Weighted/modelled; raw counts/ratings contextual. |
| SEZ/workplace proximity | workplace evidence | SEZ score | Weighted/modelled. |
| OSRM/Google routes, metro, network | component proxies | commute score/band | Weighted contextual proxy. Existing handoff says not live traffic; catchment API itself requires live Google traffic-aware isochrones. |
| school source rows + UDISE matching | canonical entity/campus and grades 2-9 enrollment | all/Q4/threshold school counts and enrollment | Counts absolute after identity rules; enrollment is mixed observed (UDISE-backed) and estimated. |
| canonical entity `fee_max` sorted descending | quartile | Q4 = top `floor(N/4)` entities | Percentile/rank cohort, city-relative—not comparable as an absolute fee tier across cities. |
| enrollment × capture rate / 200-seat capacity at 80% target | capacity scenarios | captured students, minimum/maximum centers, utilization | Modeled scenario, explicitly not a forecast. |
| catchment polygon covers unique society/entity point | covered records | family proxy, school entity/campus/enrollment | Absolute within request geometry, subject to source completeness and zone adjacency rules. |

## 5. Baseline counts and coverage to preserve (with reconciliation status)

### Stable source/public ledgers

| Dataset | Rows | Coordinate coverage | Key coverage/aggregate | Duplicate indicator |
| --- | ---: | ---: | --- | ---: |
| schools legacy | 2,007 | 2,007 (100%) | UDISE present 1,066 (53.11%); missing UDISE 941; missing Google locality/postcode/distance 640 each; missing H3/zone 100 each | 485 extra rows under aggressive normalized-name grouping; not a valid identity dedupe |
| canonical school entities | 1,996 | 100% | grades 2-9 enrollment 881,255; 499 Q4 entities; 493,773 UDISE-backed + 387,482 estimated | audit: 4 collapsed rows, 7 quarantined; entity IDs unique |
| canonical school campuses | 1,961 | 100% | 31 multi-entity campuses; grades 2-9 representative enrollment 868,930; 487 with a Q4 entity | campus IDs unique; campus rule prevents co-located enrollment summing |
| societies/projects | 2,268 | 100% | 384,295 units and 384,295 `tam`; every field in the small public contract populated | 6 extra rows by aggressive normalized name; checked audit says 5 duplicate names—requires source-ID/phase adjudication |
| localities | 587 | 100% | mean price/sqft 7,398.72; min 800, max 35,700 | 4 extra rows by normalized name; no source ID |
| hospitals | 235 | 100% | beds 3,495; reviews 145,758; mean rating 3.7745 | 54 extra rows by normalized name, likely branches/name collisions; no source ID |

School audit preservation values: 1,996 entities, 1,961 campuses, 499 Q4 entities, 487 Q4-context campuses, 458 positive-enrollment Q4 entities, Q4 grades 2-9 enrollment 258,833 (110,585 UDISE-backed; 148,248 estimated), Q4 fee cutoff INR 70,000. Note: the current audit’s raw-preclean Q4 enrollment is 264,742, while the test asserts 253,086 from the input it reads. Tests passed during inspection, indicating files were being changed concurrently or the published audit was generated from a different revision. Freeze hashes before accepting fixtures.

### Hex/residential reconciliation (not fixture-safe)

Measured artifacts disagree:

| Artifact | Hexes | Countable family TAM | Direct family TAM | Units/related total |
| --- | ---: | ---: | ---: | ---: |
| `src/public/data/hexes.geojson` measured snapshot | 308 | 364,998 | 316,676 | 364,998 direct units |
| `src/public/data/hexes_master.json` | 310 | 115,738 | 157,073 | 184,702 direct units |
| `src/public/data/report.json.overall` | 264 scored hexes | 0 | 316,676 | 316,676 direct units; cluster context 528,697 |
| `src/public/data/client_summary.json` | says 309 | 0 | validation expects zone 316,676 | executive Q4 units 384,295; Q4 families 384,544; total projects 8,920 |
| `DATA/audits/final_hex_intelligence_methodology.md` | says 309 | 0 | not reconciled | source pins: 2,268 societies, 480 schools, 235 hospitals |

`client_summary.validation.checks` explicitly marks “Active GeoJSON vs zone report TAM” as **fail** (recorded value 0 versus expected 316,676). The inspected GeoJSON subsequently contained nonzero values, which further demonstrates a mixed-revision publish directory. Do not choose one total silently.

## 6. Bengaluru hardcodes and portability blockers

This inventory groups every confirmed class of hardcode and identifies the concrete paths. Line-level matches can be reproduced with the commands at the end.

### City identity, copy, metadata, totals

- `src/public/index.html`: title/description, navigation, breadcrumbs, methodology text, landing/deck copy, data-path labels, school scope, “Bangalore’s” micro-market copy, custom coordinate placeholders.
- `src/public/explainer.html`: title and narrative, “Bangalore Centroid,” Bengaluru label, fixed 46% claim, fixed center/fly-to locations.
- `src/public/index.js`: `totalBangaloreTam` fallback 157,073; variable names/logging/share denominators; Bengaluru breadcrumbs/scope; query suffixing and regex aliases.
- `bangalore_units_analysis.mjs`: Bangalore-specific input/output/narrative plus population constants 8,443,675 (2011 city) and 10,456,000 (2016 UA estimate).
- Reports and final filenames throughout `DATA/**`, `maps/**`, and `src/public/reports/**` embed Bangalore names and historic fixed totals.

### Center, bounds, zones, maps

- `(12.9716, 77.5946)` is repeated in `src/public/index.js`, `explainer.html`, `build_school_market.py`, `geocode_schools.py`, `geocode_projects.py`, `prepare_data.py`, `rerun_society_layer.py`, `analyse_neighbourhoods.py`, and `api/catchment_market.py`.
- Initial map zooms (10/11), search zoom behavior, 15 km Places radius, 35 km/h fallback routing speed, and nine compass-zone logic are city-wide assumptions, not config.
- Geocoders use fixed Bengaluru distance/bounds checks and append `Bangalore, Karnataka, India`; school builder quarantines Google addresses outside Bengaluru scope.
- Tests encode Bengaluru addresses, Indiranagar/Jayanagar/Whitefield, and center coordinates.

### Files, source names, IDs/slugs, URLs

- Fixed paths/names include `bangalore_projects_*`, `q4_categorized_societies_bangalore.json`, `bangalore_localities_enriched.json`, `bangalore_buildings.geojson`, `bangalore_hex7_*`, and `bangalore_metro_stations.json` across preparation, rerun, server/API, analysis, and frontend.
- `rerun_society_layer.py` includes the absolute external path `/Users/malleswararao/Desktop/Harshith files/final try/data/raw/bangalore_projects.jsonl` and imports generators from a sibling workspace.
- Source URLs embedded in evidence are Bengaluru-specific (99acres `/...bangalore...`, Practo `/bangalore/...`). No public row retains canonical/source city IDs, making leakage detection impossible downstream.
- No numeric source-city IDs were found in this workspace’s application code; scraper discovery must confirm them externally rather than infer them.

### API/secrets and deployment portability

- `src/server.py` contains a literal Google Maps API key fallback and the frontend directly calls Google APIs in several places. This is a credential exposure and quota/billing risk; rotate the key and require environment/server-side proxying.
- Frontend geocoding appends Bengaluru to searches and calls Nominatim/Google directly. Catchment server coordinates are validated against Bengaluru-centric bounds in shared logic.
- `server.py` can copy a Bengaluru final master when public data is missing; this would leak Bengaluru into another city rather than fail closed.

## 7. Leakage and double-counting risks

1. **Countable versus context:** `countable_family_tam`/direct society totals are intended additive; nearby and cluster weighted context are not. UI/report paths expose both and mixed revisions already show divergent totals. Enforce field-level additivity metadata and reconciliation tests.
2. **Units equal TAM:** public societies currently total exactly 384,295 for both units and TAM. This is a strong sign that family TAM is a units proxy in this revision, not observed occupied households. Label it and preserve occupancy/model parameters separately.
3. **Project phases:** no stable source project ID, RERA ID, parent project ID, or phase ID exists in `societies.json`; names such as phases can be summed as independent projects or collapsed incorrectly. The 8,920 “total projects” in client summary does not reconcile to 2,268 public rows.
4. **School entity versus campus:** 1,996 entities map to 1,961 campuses. Summing campus and entity ledgers together, or summing enrollment of co-located entities, double counts. Catchment code correctly uses unique entity demand and one campus marker, but legacy `schools.json` remains available.
5. **School enrollment provenance:** 44% of all grades 2-9 entity enrollment and 57% of Q4 enrollment are estimated. Cross-city rankings must not present these as equally observed without coverage/provenance columns.
6. **Name-based duplicates:** raw normalized-name indicators are high for schools/hospitals and cannot distinguish branches. Stable source IDs plus city and address/coordinate identity are required.
7. **H3 footprint:** 264/308/309/310 counts appear across current artifacts. Aggregates can change merely because the active footprint changes. Store boundary/version and denominator.
8. **Relative cohorts/scores:** Q4 is a within-city percentile, so “Q4 Bengaluru” and “Q4 another city” are not an absolute affordability match. Rankings requested as absolute metrics must use INR thresholds and raw counts alongside percentiles.
9. **NCR components:** the future `delhi_ncr` rollup can double count records returned under Delhi, New Delhi, Noida, Gurugram, Ghaziabad, and Faridabad. Retain `source_city_id/name`, canonical component, stable source ID, and dedupe before NCR aggregation.
10. **Fallback leakage:** missing public files can trigger Bengaluru file copies or generated placeholder localities (`Bangalore, Local Sector ...`). Multi-city loaders must fail closed on city mismatch.
11. **Static/public split:** `src/static/data` is an older parallel copy while deployment serves `src/public/data`; accidental writes to the wrong tree yield stale local/deployed data.
12. **Mutable mixed revision:** output files changed during this audit (timestamps/content did not form one immutable release). A manifest with hashes and atomic publish is necessary before regression locking.

## 8. Regression fixture proposal

Do not copy full production data into tests yet. After the residential reconciliation blocker is resolved, create `tests/fixtures/multicity/bengaluru/manifest.json` containing release ID, city/boundary/H3 resolution, source and output SHA-256 hashes, row counts, coordinate/null coverage, unique-ID counts, and reconciled totals. Pair it with small, license-safe semantic fixtures:

- canonical school cases: same-UDISE merge, conflicting-UDISE quarantine, two entities/one campus, observed versus estimated enrollment, quartile boundary;
- residential cases: one parent project with two phases, exact duplicate source ID, same name/different coordinates, direct versus nearby/cluster context, non-habitable hex;
- locality/hospital cases: branch/name collision and out-of-bound coordinate;
- H3 golden ledger: 3–5 adjacent hexes with explicit direct/countable/context totals and expected zone/micro-market/catchment aggregates;
- NCR leakage case: one entity returned under two component-city searches but one canonical source ID.

Golden acceptance should require: schema validation; IDs unique in `(canonical_city_id, source, source_id)` scope; 100% coordinate validity for published POIs; artifact hex counts identical; sum of countable/direct/unit fields reconciled at hex/zone/city layers; context fields excluded from additive totals; canonical school entity/campus/enrollment reconciliation; no Bengaluru tokens or coordinates in non-Bengaluru partitions; and frontend/API totals sourced from the same manifest release.

Suggested locked Bengaluru expectations, pending a single atomic rebuild: source row counts above; school entity/campus/audit values above; nine zones; H3 resolution 7; and 12 current micro-market rows. **Do not lock a family-TAM or hex-count expectation until the conflicting artifacts are regenerated together and independently reconciled.**

## 9. Evidence commands

```sh
# Repository state (result: not a Git repository)
git status --short

# Inventory and hardcodes
find . -maxdepth 3 -type f -not -path './node_modules/*' -print | sort
rg -n 'Bangalore|Bengaluru|bangalore|bengaluru|12\.9716|77\.5946' src tests bangalore_units_analysis.mjs
rg -n 'fetch\(|/api/|data/' src/public/index.js src/public/events.js src/public/index.html

# Schemas/counts/coverage (representative)
jq -r '[.[]|keys[]]|unique|join(", ")' src/public/data/societies.json
jq '{feature_count:(.features|length),sum_countable:([.features[].properties.countable_family_tam//0]|add),sum_direct:([.features[].properties.direct_family_tam//0]|add)}' src/public/data/hexes.geojson
jq '{hex_count:(.hexes|length),sum_countable:([.hexes[].tam.countable_family_tam//0]|add),sum_direct:([.hexes[].tam.direct_family_tam//0]|add)}' src/public/data/hexes_master.json
sqlite3 src/listings.db '.schema'

# Tests
python3 -m unittest discover -s tests -v
```

## 10. Admission decision and required next action

Baseline architecture/schema audit: **complete**. Bengaluru numeric regression fixture: **not admitted**. First regenerate all residential/H3/report/client-summary artifacts into a versioned staging directory from one input manifest, then independently reconcile counts/TAM and atomically publish. Rotate/remove the exposed Google key before further deployment. Only after those two issues are resolved should the orchestrator accept a Bengaluru golden fixture and allow downstream cities to inherit this contract.
