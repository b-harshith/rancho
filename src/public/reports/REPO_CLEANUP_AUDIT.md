# Repo Cleanup Audit

I treated your request as a multi-pass cleanup audit and split it into four review areas:

1. Data files
2. Scripts
3. Reports and deliverables
4. Runtime / local-only artifacts

This is a report only. I did not delete anything.

## Biggest space drivers

These are the highest-value places to reclaim disk first:

- `venv/` - 69M
- `DATA/processed/` - 63M
- `maps/` - 25M
- `new data/` - 21M
- `src/public/data/` - 20M
- `src/static/data/` - 19M
- `DATA/final/` - 8.6M
- `DATA/Stage2 processing/` - 8.6M
- root `99acres_bangalore_societies.json` - 6.8M

## High-confidence removals

These are the safest items to delete or archive first:

- `src/.rerun_society_layer.py.swp`
- `src/osrm_server.log`
- `src/public/index.html.bak`
- `src/public/index.js.bak`
- `src/public/index.css.bak`
- `outputs/` if the previews and spreadsheets are just generated QA artifacts
- `venv/` if you are happy to recreate the environment from `src/requirements.txt`
- `node_modules/` and `out/` if they remain empty placeholders
- `src/listings.db` if you do not need local SQLite persistence for commercial listings
- `DATA/processed/stage2_routing_cache.json` if you can regenerate routing results on demand
- `99acres_bangalore_societies.json` if it is only a raw scrape archive and not a current pipeline input

## Staging data that can usually be trimmed

These folders look like pipeline intermediates rather than long-term source-of-truth assets:

- `new data/`
- `DATA/Stage2 processing/`
- `DATA/processed/`

Recommended approach:

- Keep them while the pipeline is still changing.
- Once the final outputs are published, move them to an archive area or delete them.
- Avoid keeping both the staging copy and the final/public copy forever.

## Canonical data tree

The cleanest long-term setup looks like this:

- `src/public/data/` becomes the live app data tree
- `DATA/final/` remains the final analytical output tree
- `src/public/reports/` becomes the public-facing report tree

What that means in practice:

- Do not maintain a permanent mirror in `src/static/data/`
- Do not keep the same dataset in `src/public/data/`, `src/static/data/`, `new data/`, and `DATA/*` unless each copy has a clearly different purpose

## `src/static/data/` recommendation

This folder looks like a stale mirror of the live public data tree.

Evidence:

- `src/server.py` loads runtime data from `src/public/data/`
- `src/suggest_micromarkets.py` prefers `src/public/data/hexes.geojson`
- `src/check_schools.py` still points at `src/static/data/schools.json`
- `src/public/index.html` still contains old `web_platform/static/data/...` text references

Recommendation:

- Update `src/check_schools.py` to use `src/public/data/` or a shared source path
- Update or remove the stale `static/data` text references in the HTML
- After that, remove `src/static/data/` and keep only `src/public/data/`

## Scripts to merge

### 1. `src/geocode_projects.py` + `src/geocode_schools.py`

Why merge:

- Both scripts do the same kind of work: Google geocoding, retry logic, text normalization, H3/zone classification, and audit reporting
- They differ mainly by input file, stopword set, and output file names

Suggested result:

- One parameterized `geocode_entities.py`
- A config block or CLI flags for entity type, source path, output path, and audit path

### 2. `src/analyse_neighbourhoods.py` + `src/suggest_micromarkets.py`

Why merge:

- Both scripts analyze hex-based market clusters
- Both compute centroid / distance / score style metrics
- Both read the same hex feature data

Suggested result:

- One `micro_market_analysis.py`
- Subcommands such as `suggest`, `analyse`, and `rank`

### 3. `src/check_schools.py`

Why merge or remove:

- It is a one-off validation utility
- The logic overlaps with the school geocoding / audit flow

Suggested result:

- Fold it into `geocode_schools.py` as `--audit-only`
- Or retire it once the school audit output is stable and archived

### 4. Shared geospatial helpers

These files contain overlapping helper logic and should share a module:

- `src/prepare_data.py`
- `src/rerun_society_layer.py`
- `src/server.py`
- `src/api/catchment.py`

Useful shared helpers to extract:

- H3 boundary / centroid utilities
- Haversine and bearing helpers
- Zone classification
- GeoJSON parsing / polygon cleanup
- Catchment isochrone parsing and aggregation

Important:

- I would not merge `src/server.py` and `src/api/listings.py` wholesale
- `src/server.py` is the router / entry point
- `src/api/listings.py` is a reusable request handler

## Reports and deliverables to consolidate

You currently have overlapping report trees:

- `DATA/audits/`
- `DATA/client_handoff/`
- `src/public/reports/`

This is not automatically wrong, but it is redundant.

Recommended cleanup policy:

- Keep one canonical report tree for final user-facing deliverables
- Use the other trees only as build inputs or temporary exports
- Avoid storing the same narrative report in three separate places

## Recommended cleanup order

If you want the biggest space win with the least risk, do it in this order:

1. Delete backups, logs, `.swp` files, empty folders, and `outputs/`
2. Remove `venv/` only if you are sure the environment is reproducible
3. Archive or delete `DATA/processed/stage2_routing_cache.json`
4. Decide whether `99acres_bangalore_societies.json` is still needed
5. Repoint `src/check_schools.py` away from `src/static/data/`
6. Remove `src/static/data/`
7. Merge the two geocoding scripts
8. Merge the two micro-market analysis scripts
9. Extract shared geospatial utilities

## Practical keep list

These should stay unless you intentionally redesign the pipeline:

- `src/server.py`
- `src/api/listings.py`
- `src/api/catchment.py`
- `src/public/index.js`
- `src/public/index.html`
- `src/public/index.css`
- `src/public/data/`
- `DATA/final/`

## Bottom line

The biggest bloat is not source code. It is duplicated generated data, staging outputs, local runtime state, and old backups.

If you want, I can turn this audit into an actual cleanup patch next and remove the low-risk files first.
