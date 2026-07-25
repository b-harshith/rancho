# K12 Unified Spatial Pipeline

Automated end-to-end spatial processing for K12 school campuses. Given a city name and a school list CSV, this pipeline geocodes schools, downloads Overture Maps building/land-use data for the city, matches each school to its nearest building footprint, refines campus boundaries by merging adjacent structures, and exports master CSV/JSON/GeoJSON outputs.

## Pipeline Flow

```
City Input → Bounding Box Extent → Overture Download (Buildings & Land Use)
  → School Geocoding → Footprint Matching → Campus Polygon Refinement → Export
```

## Quick Start

```bash
cd K12-Unified-Spatial-Pipeline
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Full pipeline
python pipeline.py \
  --city bangalore \
  --schools ../BLR-SCHOOL-LIST/unique_schools_details.csv

# Optional: Google Maps geocoding (faster, more accurate)
export GOOGLE_MAPS_API_KEY=your_key_here
python pipeline.py --city mumbai --schools schools.csv --provider google
```

## CLI Options

| Flag | Description |
|------|-------------|
| `--city` | City name (required). Used for geocoding extent and query suffixes. |
| `--schools` | Path to school list CSV (required). |
| `--output` | Output directory (default: `./output`). |
| `--provider` | Geocoding provider: `google`, `arcgis`, or `osm`. Auto-selects if omitted. |
| `--stage` | Run a single stage: `extent`, `download`, `geocode`, `match`, `refine`, `export`, or `all`. |
| `--skip-download` | Skip Overture data download (use existing files). |
| `--skip-geocode` | Skip school geocoding stage. |
| `--skip-match` | Skip footprint matching stage. |
| `--skip-refine` | Skip campus refinement stage. |

## Input CSV Format

The school CSV should contain at minimum:

| Column | Required | Description |
|--------|----------|-------------|
| `School_Code` | Yes | Unique school identifier |
| `Name` | Yes | School name |
| `Pincode` | Recommended | Used in geocode queries |
| `Geocode_Query` | Optional | Pre-built geocode query string |
| `Latitude` / `Longitude` | Optional | Pre-geocoded coordinates (skipped if present) |
| `Boundary_Polygon` | Optional | Pre-matched footprint (skipped if present) |

## Outputs

All outputs are written to `./output/` (or `--output` path):

| File | Description |
|------|-------------|
| `{city}_master.csv` | Full school data with coordinates and boundary polygons |
| `{city}_master.json` | Same data as JSON array |
| `{city}_master.geojson` | GeoJSON FeatureCollection with campus polygons |

Intermediate Overture data is stored in `./data/overture/`:

| File | Description |
|------|-------------|
| `{city}_buildings.geojson` | Overture building footprints |
| `{city}_no_buildings.geojson` | Overture land_use features |

Geocode queries are cached in `./data/cache/geocode_cache.db` (SQLite).

## Pipeline Stages

### 1. City Extent Resolution

Geocodes the city name via ArcGIS `findAddressCandidates` and extracts the geographic bounding box (`min_lon, min_lat, max_lon, max_lat`). Falls back to a ±0.25° buffer around the centroid if no extent is returned.

### 2. Overture Download

Downloads Overture Maps feature layers restricted to the city bounding box:

```bash
overturemaps download --bbox=... -f geojson --type=building -o data/overture/{city}_buildings.geojson
overturemaps download --bbox=... -f geojson --type=land_use -o data/overture/{city}_no_buildings.geojson
```

Existing files are skipped automatically.

### 3. School Geocoding

Geocodes each school using the configured provider:

- **Google Maps** (if `GOOGLE_MAPS_API_KEY` is set) — fastest, highest accuracy
- **ArcGIS** (default free tier) — primary fallback
- **OpenStreetMap Nominatim** — secondary fallback

All queries are cached in SQLite to avoid redundant API calls.

### 4. Footprint Matching

Builds a spatial grid index on Overture building polygons and assigns each geocoded school to the nearest building centroid within **200 meters**.

### 5. Campus Boundary Refinement

Evaluates adjacent Overture features (buildings, land_use, water) near each school polygon and scores candidates using the rubric below. Polygons scoring **≥ 35 points** are merged into the campus footprint via `unary_union`.

#### Scoring Rubric

| Category | Condition | Points |
|----------|-----------|--------|
| **Proximity** | Overlaps/contains school polygon | +60 |
| | Touches (shared edge) | +50 |
| | Gap ≤ 15 m | +35 |
| | Gap ≤ 30 m | +20 |
| | Gap ≤ 50 m | +10 |
| **Feature type** | Building | +20 |
| | Land_use: education/school | +40 |
| | Recreation/park/playground | +25 |
| | Residential/commercial/industrial | −15 |
| | Water < 2000 m² | +10 |
| | Water ≥ 2000 m² | −20 |
| **Size ratio** (candidate/school area) | < 0.5× | +15 |
| | 0.5–2× | +10 |
| | 2–5× | 0 |
| | 5–10× | −25 |
| | > 10× | −50 |
| **Name match** | Fuzzy overlap ≥ 70% | +40 |
| | ≥ 40% | +20 |
| | ≥ 20% (incl. edu keywords) | +10 |

**Merge threshold: ≥ 35 points**

### 6. Export

Writes master CSV, JSON, and GeoJSON with all school metadata and refined campus boundary coordinates.

## Project Structure

```
K12-Unified-Spatial-Pipeline/
├── pipeline.py              # Main CLI orchestrator
├── requirements.txt
├── README.md
├── src/
│   ├── config.py            # Paths and pipeline configuration
│   ├── city_extent.py       # City bounding box resolution
│   ├── overture_download.py # Overture Maps CLI wrapper
│   ├── geocode.py           # School geocoding + SQLite cache
│   ├── footprint.py         # Nearest-building matching
│   ├── campus_refiner.py    # Campus boundary refinement
│   ├── export.py            # CSV/JSON/GeoJSON export
│   └── progress.py          # Terminal progress logging
├── data/
│   ├── cache/               # SQLite geocode cache
│   └── overture/            # Downloaded Overture GeoJSON
└── output/                  # Master export files
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GOOGLE_MAPS_API_KEY` | Optional. Enables Google Maps geocoding. |

## Running Individual Stages

```bash
# Resolve city bounding box only
python pipeline.py --city bangalore --schools schools.csv --stage extent

# Download Overture data only
python pipeline.py --city bangalore --schools schools.csv --stage download

# Geocode schools (uses cached Overture data if available)
python pipeline.py --city bangalore --schools schools.csv --stage geocode --skip-download

# Match footprints (requires geocoded schools + building data)
python pipeline.py --city bangalore --schools schools.csv --stage match --skip-download --skip-geocode

# Refine campus boundaries
python pipeline.py --city bangalore --schools schools.csv --stage refine --skip-download --skip-geocode --skip-match
```
