# RanchoLabs Market Intelligence Portal

Private source repository for the Rancho multi-city school-market and catchment
intelligence platform.

## Repository contents

- `src/` — deployable Vercel application and required production data.
- `collectors/`, `pipelines/`, and `orchestration/` — collection and processing code.
- `external_scrapers/` and `archived_pipelines/` — retained, reusable scraper and
  transformation source.
- `final_data/`, `DATA/final/`, and `maps/final/` — final source datasets and
  deliverables.
- `config/`, `schemas/`, `docs/`, and `tests/` — configuration, contracts,
  documentation, and validation.

Runtime credentials are never stored in this repository. Create local values from
`.env.example` and configure production secrets through the hosting environment.

## Verification

```bash
shasum -a 256 -c FINAL_DATA_CHECKSUMS.sha256
python3 -m unittest discover -s tests -p 'test_*.py'
```

See `MINIMAL_RANCHO_README.md` for retained-data and reproducibility notes.
