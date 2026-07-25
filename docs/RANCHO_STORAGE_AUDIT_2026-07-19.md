# Rancho storage and consolidation audit

Audit date: 2026-07-19 (Asia/Kolkata)

> Historical pre-cleanup audit. The approved cleanup was completed later the same day.
> The canonical Rancho folder is now about 529 MiB and the disk has about 32 GiB free.
> See `RANCHO_DELETION_MANIFEST_2026-07-19.md` for the completed action record.

The inventory phase was read-only. The sizes and paths below describe the machine before
the subsequent approved consolidation and permanent deletion.

## Executive summary

- The data volume is effectively full: 228 GiB total, 203 GiB used, about 1.3 GiB
  available at inspection time.
- `Desktop/BangaloreRancho` is the correct canonical parent folder, but it currently
  contains production assets, generated caches, old deployments, duplicate data and
  raw scrape evidence together (about 18 GiB total).
- Additional Rancho work is scattered across `school extraction`, `final new data`,
  `foursquare categories`, `School Data`, `CatchmentIQ`, `Rancho Labs`, and several
  paths under `Harshith files`.
- The live Vercel project binding is under
  `BangaloreRancho/web_platform_vercel_exact_latest/src/.vercel/project.json`; the
  deployable application root is `BangaloreRancho/web_platform_vercel_exact_latest/src`.
- The deployed multi-city manifest was generated on 2026-07-12 and publishes four
  cities: Delhi NCR, Bengaluru, Hyderabad and Mumbai.
- About 6.5 GiB is exact duplicate or clearly regenerable material before considering
  OSRM graph files. Keeping the 528 MiB source PBF but removing the generated OSRM
  graph adds about 5.7 GiB. After extracting 11 differing Pune raw pages from the old
  workspace copy, the conservative recovery opportunity is roughly 16 GiB.
- If raw network evidence and intermediate outputs are no longer required, the total
  recovery opportunity is roughly 25-30 GiB.

## Canonical assets to keep

### 1. Deployed application

Keep:

- `BangaloreRancho/web_platform_vercel_exact_latest/src/`
- `src/public/` (277 MiB of deployed static code/data)
- `src/runtime_data/` (97 MiB included by Vercel functions)
- `src/api/`, `src/multicity/`, Python/JS source, `vercel.json`, `package.json`,
  lockfiles and requirements files
- `src/.vercel/project.json` and, until its purpose is reviewed,
  `src/.vercel/.env.preview.local`

Generated material inside the deployed source that is not canonical:

- `src/.vercel/cache/`
- `src/.vercel/output/`
- `src/.vercel/python/`
- `src/node_modules/`
- `src/__pycache__/`

The `.vercel` generated tree consumes about 789 MiB by allocated-block measurement;
the project link itself is only a few KiB.

### 2. Final multi-city source data

The exact source files recorded by the deployed manifest are under
`Desktop/final new data/Final Data/`:

| Dataset | File | Data rows | Size |
|---|---|---:|---:|
| Projects | `Projects/magicbricks_projects_final_master.csv` | 34,959 | 28,637,503 bytes |
| Hospitals | `hospitals/hospitals_all_cities.csv` | 6,203 | 2,557,732 bytes |
| Localities | `localities/real_estate_localities_and_societies.csv` | 15,216 | 5,332,990 bytes |
| Offices | `offices/offices_unified_all_cities.csv` | 18,398 file lines; manifest reports 18,352 data rows | 7,186,882 bytes |
| Schools | `schools/final_schools.csv` | 29,199 | 9,899,822 bytes |

Also keep `schools/raw/udise_private_unaided_with_enrollment.csv` (28,973 data rows,
48,950,754 bytes) until the final lineage decision is made.

The deployed manifest contains SHA-256 hashes for the five main source datasets. The
project file and the manifest therefore provide a strong verification anchor after the
data is moved into the canonical Rancho folder.

### 3. Final Bengaluru TAM outputs and production pipeline

Keep:

- `BangaloreRancho/DATA/final/`
- `BangaloreRancho/maps/final/`
- `BangaloreRancho/scripts/active/`
- `BangaloreRancho/README.md`
- `BangaloreRancho/DATA/Stage2 processing/`
- Selected `BangaloreRancho/DATA/processed/stage2_*` files if final-output
  reproducibility is desired

The workspace README explicitly identifies the JSON, CSV, GeoJSON and KML files in
these folders as the company-facing deliverables.

### 4. Authoritative scraper starting points

Keep these code snapshots, but centralize and sanitize them before removing their
current parent folders:

| Source | Authoritative starting point |
|---|---|
| YellowSlate | `school extraction/scripts/scrape_yellowslate_fees.py`, `scrape_yellowslate_browser.py`, `scrape_yellowslate_locations.py` |
| UDISE+ | `school extraction/app.py` and `school extraction/udise_scraper/` plus export scripts |
| MagicBricks Projects | `Harshith files/final try/scrape_magicbricks_projects.py` and the 11 MiB `data/raw/bangalore_projects.jsonl` fixture/evidence |
| MagicBricks Localities | `BangaloreRancho/web_platform_vercel_exact_latest/collectors/magicbricks_localities/` |
| 99acres Localities/Societies | `BangaloreRancho/city_rerun_bundle/scripts/source/locality/` and `scripts/source/societies/` |
| Practo Hospitals | `BangaloreRancho/city_rerun_bundle/scripts/source/hospitals/practo_hospitals_scraper.py` |
| Foursquare Offices | `foursquare categories/download_and_classify_cities_offices.py` plus the seven small `*_office_listings.json` files |

Important safety notes already documented in the workspace:

- The adopted 99acres code contains an embedded historical session cookie. It should
  remain quarantined until the cookie is removed and rotated/revoked.
- The current UDISE worker contains an automatic CAPTCHA branch even though its README
  says human-assisted. Keep the architecture, but do not treat that worker as final
  production code until the automated branch and answer logging are removed.

## Hard-coded dependencies that block immediate folder deletion

Before moving the scattered source folders, update these code paths:

- `src/build_multicity_platform.py`, `src/build_city_legacy_artifacts.py` and
  `src/free_society_geocode.py` default to `Desktop/final new data/Final Data`.
- `pipelines/process_entities.py` reads `Desktop/foursquare categories` and
  `Desktop/School Data`.
- `src/rerun_society_layer.py` falls back to
  `Desktop/Harshith files/final try/data/raw/bangalore_projects.jsonl`.
- Tests and research docs repeat some of these absolute paths.

The final consolidation should move the required files first, update these paths to
repository-relative locations, then run manifest/hash checks before staging the old
folders for deletion.

## High-confidence cleanup candidates

These are exact duplicates, deployment build products, caches or reproducible
environments. Exact targets should still be recorded in the deletion manifest.

| Candidate | Allocated size | Evidence |
|---|---:|---|
| `web_platform_vercel_exact_latest/src/.vercel/{cache,output,python}` | about 789 MiB | Vercel build/cache products; keep project link and review env file |
| `web_platform_vercel_exact_latest/venv` | 69 MiB | Re-creatable Python environment |
| `school extraction/.venv` | 1.0 GiB | Re-creatable from requirements |
| Two `Rancho Labs/*/.venv` folders | about 789 MiB | Re-creatable environments |
| `CatchmentIQ/overture/` | 1.2 GiB | Both files byte-identical to canonical `BangaloreRancho/DATA/overture/` copies; separate inodes |
| `city_rerun_bundle/DATA/overture/bangalore_buildings.geojson` | 875 MiB | Byte-identical to canonical Overture building file; separate inode |
| Duplicate `final_data_consolidated.xlsx` under `Harshith files` | 23 MiB | SHA-256 identical to the copy under `final new data/scripts and cache/` |
| Non-Bangalore content in `Harshith files/data of 15 cities magic bricks` | about 1.6 GiB | Metadata comparison shows it is already present in `Harshith files/final try/data`; only the older Bangalore JSONL differs |
| Old `BangaloreRancho/web_platform` | 185 MiB | Superseded deployment workspace; review-only before deletion |
| `web_platform_vercel_previous_deployment` | 3 MiB | Superseded deployment snapshot |

Generated OSRM graph candidate:

- `BangaloreRancho/DATA/routing/` is 6.2 GiB.
- `southern-zone-latest.osm.pbf` is 528 MiB.
- Keeping the PBF and removing the generated `.osrm*` graph files can recover about
  5.7 GiB while retaining the source needed to rebuild the graph.

## Review-before-deletion candidates

These are large but contain unique raw evidence or intermediate work. They should go
into an organized review bucket, not be deleted automatically.

| Candidate | Size | Reason for review |
|---|---:|---|
| `BangaloreRancho/web_platform_vercel_exact_latest_copy` | 3.8 GiB | Superseded and missing the deployed `src`, but 11 Pune detail HTML files differ from the current folder |
| `web_platform_vercel_exact_latest/DATA/multicity` | 4.2 GiB | Mostly MagicBricks locality raw HTML; final deployed artifacts exist, but deleting loses raw evidence |
| `school extraction/data/runtime/udise_data.sqlite3` | 4.8 GiB | Unique raw collection DB: 73,066 schools, 884,081 requests and 819,464 response records |
| `school extraction/data/output` | 1.0 GiB | Intermediate reports, MagicBricks processing and geocode caches; final exports exist elsewhere |
| `Harshith files/final try/data/raw` | 3.0 GiB | Mostly old MagicBricks rental/listing raw files; retain authoritative project JSONL and required 99acres evidence |
| `foursquare categories/{foursquare_bangalore_places.csv,foursquare_bangalore_places.json,bangalore_pois_by_category.json}` | about 302 MiB | Large raw/intermediate POI files; final office JSONs and unified CSV exist |
| Desktop `magicbricks_raw.jsonl` | 255 MiB | Older April raw scrape; not byte-identical to the other Bangalore raw files |
| `final new data/scripts and cache/processed` | 284 MiB | Coordinate-review intermediates; keep final decisions/master if future audit is required |
| `CatchmentIQ` excluding duplicate Overture data | about 170 MiB | Earlier prototype with unique code/output; not referenced by the deployed build |
| `Rancho Labs` excluding virtual environments | about 106 MiB | Earlier K12 prototypes and outputs; not referenced by the deployed build |

Related older work under `Harshith files` also needs human scope confirmation rather
than automatic deletion: `BBA_Python_final` (1.9 GiB, including a 1.5 GiB venv),
`python_realestate` (444 MiB), `Schools data + UIDSE`, and `Rancho Labs`. These appear
to be predecessors or separate academic projects and are not referenced by the current
deployment code.

## Proposed final folder shape

Use the existing `Desktop/BangaloreRancho` as the one canonical parent:

```text
BangaloreRancho/
  deployment/                 # current deployable src, project link, lockfiles
  data/
    final_multicity/          # the five manifest-hashed source CSV datasets
    final_bengaluru_tam/      # final JSON/CSV/GeoJSON/KML handoff
    source_evidence/          # only selected compact raw/normalized evidence
  scrapers/
    magicbricks_projects/
    magicbricks_localities/
    schools_udise_yellowslate/
    99acres/
    practo/
    foursquare/
  pipelines/                  # active generation/build scripts
  docs/                       # audit, runbooks, lineage and this cleanup manifest
```

To avoid breaking the current deployment path unnecessarily, this can be implemented
with conservative names inside the existing folder first, followed by repository-
relative path updates. The deployable `src` directory does not need to be renamed if
keeping the current Vercel workflow is preferable.

## Proposed review folder

Use a separate same-volume staging folder such as:

```text
Desktop/Rancho_Delete_Review_2026-07-19/
  01_superseded_workspaces/
  02_generated_caches_and_envs/
  03_exact_duplicate_data/
  04_raw_scrape_evidence_review/
  05_old_prototypes_review/
  MANIFEST.tsv
```

Moving files to this folder on the same disk does not free space. It only makes review
and final deletion safer. Because free space is critically low, perform high-confidence
cache/duplicate deletion first or move the review folder to an external disk. Do not
create full copied backups on the current disk.

## Verification required after consolidation

1. Recompute hashes of the five final source CSVs and compare them with
   `src/public/data/multicity/manifest.json`.
2. Verify `src/.vercel/project.json` still identifies project `ranchoblr`.
3. Search again for absolute Desktop paths; there should be no active-code dependency
   on folders staged for deletion.
4. Run the existing unit tests and a local/static smoke check from the canonical
   deployment directory.
5. Record every moved/deleted path, byte count, original modification time and hash (for
   unique evidence) in `MANIFEST.tsv`.
6. Only then permanently delete or empty Trash for the review folder.
