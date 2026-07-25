# Minimal Rancho workspace

This folder is the canonical Rancho project after the July 2026 storage cleanup.
It retains the deployed application, final source data, production outputs, scraper
source code, configuration, dependency manifests, and lineage documentation. Large
raw responses, scrape databases, virtual environments, browser/build caches, routing
graphs, old deployments, and intermediate datasets are intentionally not retained.

## Keep-set

- `src/` — deployable Vercel application and its required static/runtime data.
- `src/.vercel/project.json` — Vercel project binding. Generated `.vercel` cache,
  output and Python runtime folders are disposable.
- `final_data/multicity_source/` — manifest-hashed final projects, hospitals,
  localities, offices and schools source files.
- `DATA/final/` and `maps/final/` — final Bengaluru TAM deliverables.
- `collectors/`, `pipelines/`, `config/`, `schemas/`, `tests/` — current collection,
  processing, validation and configuration code.
- `external_scrapers/` — compact source-only snapshots of authoritative or useful
  legacy scrapers.
- `archived_pipelines/` — compact source-only snapshots of final-data and Bengaluru
  TAM processing code.
- `FINAL_DATA_CHECKSUMS.sha256` — verification hashes for retained final source data.

## Recreating removed data

Recreate Python environments from the retained `requirements.txt`, `pyproject.toml`,
and lock files. Recreate JavaScript dependencies from retained package manifests.
Scrapers should write new raw data beneath this repository (normally `DATA/raw/` or
their own repository-relative working directory).

Live `.env` files, API credentials, browser cookies and sessions were deliberately not
copied from legacy workspaces. Configure fresh authorized values when rerunning. The
preserved 99acres implementations require `ACRES99_SESSION` or `COOKIE_HEADER` at
runtime and contain no embedded historical session.

The UDISE code archive contains the collection architecture, but its automated CAPTCHA
branch is not approved for use. Restore/verify a human-assisted flow before rerunning.

## Verification

From this directory:

```bash
shasum -a 256 -c FINAL_DATA_CHECKSUMS.sha256
python -m unittest discover -s tests -p 'test_*.py'
```

The deployed multi-city manifest is `src/public/data/multicity/manifest.json`.
