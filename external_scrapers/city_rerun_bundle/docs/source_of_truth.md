# Source Of Truth

This bundle treats the following artifacts as canonical, in order:

1. `config/*.json` for city-specific parameters and external asset locations.
2. Raw page-level scrapes in `data/raw/*.jsonl`.
3. Flattened raw arrays in `data/raw/*.json` or `data/*.json`.
4. Normalized intermediate datasets in `data/processed/`.
5. Final deliverables in `data/final/` and `maps/final/`.
6. `data/audits/` for provenance, audits, and methodology sidecars.
7. Commercial catchment outputs in `data/final/bangalore_commercial/` when the
   batch commercial step is run.

The scripts are the authoritative implementation. The docs below summarize the
expected lineage so the bundle can be rerun or audited without reverse-engineering
the entire workspace.

## Folder Map

- `scripts/source/locality/` - 99acres locality scraping, flattening, geocoding, neighborhood assignment, and merge logic.
- `scripts/source/societies/` - 99acres society scraping and Q4 categorization.
- `scripts/source/schools/` - school scraping, enrichment, and Q4 categorization.
- `scripts/source/hospitals/` - Practo scraping and Q4 categorization.
- `scripts/analysis/` - H3 construction, stage 1.5 rollups, stage 2 scoring, and final KML/CSV/JSON exports.
- `scripts/active/generate_bangalore_commercial_catchment.py` - batch commercial
  catchment analysis with one 7 km ORS catchment per listing.
- `scripts/shared/` - utilities shared by multiple capture scripts.
- `config/` - city profile JSON files.
- `docs/` - provenance and methodology notes.

## Raw To Final Lineage

### 1) Localities

Direct inputs:

- 99acres locality response pages captured as JSONL
- ArcGIS geocoding results
- Nominatim / Overture boundary lookups

Derived outputs:

- Flattened locality array
- Restructured locality JSON with canonical field names
- Income bracket distribution
- BudgetRange prediction
- Coordinate augmentation
- Boundary / neighborhood assignment
- Final locality enrichment JSON
- Stage 1 H3 cell file
- Stage 1.5 H3-7 rollup

### 2) Societies

Direct inputs:

- 99acres society response pages captured as JSONL
- Society detail pages and any fallback rescrapes

Derived outputs:

- Flattened society array
- Q4 categorization JSON
- Optional markdown summary artifact

### 3) Schools

Direct inputs:

- School scraping / enrichment pipeline output

Derived outputs:

- `school_averages_summary_<city>.json`
- Q4 categorized schools JSON
- Optional markdown summary artifact

### 4) Hospitals

Direct inputs:

- Practo hospital scrape output

Derived outputs:

- Q4 categorized hospitals JSON
- Optional markdown summary artifact

### 5) Stage 1

Direct inputs:

- Enriched locality JSON

Derived outputs:

- H3 resolution 8 cell features
- Smoothed H3 metrics
- Budget share summaries
- H3 coordinate and spatial audits

### 6) Stage 1.5

Direct inputs:

- Stage 1 locality features
- Stage 1 H3 cells
- Enriched locality JSON

Derived outputs:

- H3 resolution 7 rollup
- Parent-child H3 aggregation
- Stage 1.5 audit and flattened outputs

### 7) Stage 2

Direct inputs:

- Stage 1.5 H3-7 features
- Society, school, and hospital Q4 datasets
- SEZ KML
- Overture building footprints
- Local OSRM routing service

Derived outputs:

- Society, school, hospital, market, SEZ, and habitability component scores
- Base affluence score
- Spatial adjustment
- Final affluence score
- GIS / CSV / JSON / KML deliverables

### 8) Final Deliverable

Direct inputs:

- Stage 2 master output
- Q4 societies / schools / hospitals

Derived outputs:

- Final evidence pack
- Countable family TAM
- School-age child TAM
- Wealthy-school child TAM
- Top evidence summaries
- Client-ready KML map

### 9) Commercial Catchment Analysis

Direct inputs:

- Commercial listings dataset with coordinates
- `web_platform/static/data/hexes_master.json`
- `web_platform/static/data/hexes.geojson`
- `web_platform/static/data/societies.json`
- `web_platform/static/data/schools.json`
- `web_platform/static/data/hospitals.json`
- `web_platform/static/data/sez_zones.geojson`

Derived outputs:

- Per-listing 7 km catchment GeoJSON
- Commercial catchment aggregate JSON master file
- Routing summary and audit sidecars

## Direct vs Derived

Direct artifacts are produced by scraping, geocoding, Overture lookup, routing,
or external static source files. Derived artifacts are computed from one or more
direct or derived inputs through deterministic transforms or scoring logic.

Examples:

- Direct: 99acres raw page JSONL, ArcGIS coordinates, Nominatim boundary polygons, Overture building footprints, SEZ polygons, OSRM route distances.
- Derived: budgetRange, income distributions, neighborhood assignments, Q4 labels, H3 scores, affluence scores, TAM estimates, final KML summaries, commercial catchment aggregates, and per-listing catchment GeoJSON.

## City Portability

The bundle is city-configured through `config/*.json`. For a new city, update:

- `city_slug`
- `city_name`
- 99acres URLs and city IDs
- city bounds and map center
- zone names
- Overture building footprint path
- SEZ KML path
- OSRM endpoint

The scripts will continue to write the same contract, but with city-specific filenames.
