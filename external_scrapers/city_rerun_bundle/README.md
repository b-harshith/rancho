# City Rerun Bundle

This folder is the self-contained rerun package for the project.

It keeps the raw scrape steps, normalization scripts, stage 1 / stage 1.5 / stage 2
analysis, and the final company-facing deliverables in one place.

## What it produces

- Final JSON evidence pack
- Spreadsheet-friendly CSV
- GeoJSON for GIS tooling
- KML for Google Earth / client review
- Audit and methodology docs

Heatmap HTML outputs are disabled by default in the runner so the bundle goes
straight to the final deliverables.

## Quick Start

1. Edit or duplicate [`config/city_profile.template.json`](config/city_profile.template.json).
2. Fill in the city-specific URLs, map center, metro bounds, zone names, and external asset paths.
3. Run the bundle:

```bash
python3 run_bundle.py --config config/bangalore.json
```

## Expected prerequisites

- Python environment with the project dependencies used by the scripts
- Playwright and browser support for the 99acres scrapers
- Local OSRM server if you want stage 2 and final routing-based scoring
- Source assets such as the SEZ KML and Overture building extract at the paths in the config

## Typical outputs

- `data/raw/` contains the page-level captures and flattened raw arrays
- `data/processed/` contains the normalized locality, H3, stage 1.5, and stage 2 datasets
- `data/final/` contains the final nested and flat evidence files
- `maps/final/` contains the KML map
- `data/audits/` contains lineage and methodology sidecars

## Porting to another city

1. Copy the template config to a new JSON file.
2. Update `city_slug`, `city_name`, the 99acres URLs, city bounds, zone names, and source asset paths.
3. Re-run `run_bundle.py` with the new config.

## Manual OSRM prep

If your OSRM graph is not already available, the repository includes
[`scripts/analysis/prepare_stage2_osrm_graph.sh`](scripts/analysis/prepare_stage2_osrm_graph.sh)
to build it from the Southern Zone extract. That step is intentionally left
outside the default runner because it can take a long time and requires the
OSRM toolchain.
