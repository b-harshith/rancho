# File Ownership

## Wave 1 exclusive ownership

| Owner | May modify | Must not modify |
|---|---|---|
| Orchestrator | `orchestration/**`, `config/**`, `runs/**` | specialist-owned docs while tasks are active; existing Bengaluru data |
| Baseline Auditor | `docs/multicity/00_baseline_audit.md`, `tests/fixtures/multicity/bengaluru/**` | config, orchestration, app/scraper code, production data |
| Source Mapping Agent | `docs/multicity/SCRAPER_INVENTORY.md`, `docs/multicity/source_mappings/**` | config, orchestration, production data, app/scraper code |
| Documentation Agent | `docs/multicity/RUNBOOK.md`, `DATA_DICTIONARY.md`, `METRIC_DEFINITIONS.md`, `FINAL_HANDOFF.md` | config, orchestration, code, data |

Existing repository files not listed above are read-only during Wave 1. Shared/cross-cutting changes will be performed by one later integration owner after audit acceptance. Two agents may not edit the same file concurrently.

## Wave 2 exclusive ownership

| Owner | May modify | Must not modify |
|---|---|---|
| Contracts Agent | `schemas/**`, `src/multicity/**`, `tests/multicity/**`, `config/schema/**` | registries, collectors, dashboard, existing data |
| Collector Safety Agent | `collectors/**`, `tests/collectors/**`, `.env.example`, `.gitignore` | external Desktop scripts, registries, production data, dashboard |
| Bengaluru Rebuild Producer | `pipelines/bengaluru_rebuild/**`, `data/staging/bengaluru/**`, `tests/reconciliation/**` | `src/public/data/**`, `DATA/**`, config, docs, collectors |
| Independent QA | `audits/wave2/**`, `tests/qa/**` | all producer files and public/reference data |
| Orchestrator | `orchestration/**`, shared integration after handoff | agent-owned files while tasks are active |

All existing Bengaluru public/reference outputs remain read-only. Any later publish is a separate orchestrator-owned task after independent QA.

## Scope-revision ownership

| Owner | May modify | Must not modify |
|---|---|---|
| Geospatial/PIN Agent | `pipelines/geospatial/**`, `data/reference/boundaries/**`, `data/reference/pincodes/**`, `data/cities/delhi_ncr/audits/geospatial/**`, `tests/geospatial/**`, `docs/multicity/geospatial/**` | collectors, dashboard, public data, shared registries |
| Ezyschooling Agent | `collectors/ezyschooling/**`, `pipelines/schools/**`, `tests/schools/**`, Ezyschooling fixtures/evidence | other collectors, shared config/schemas, dashboard |
| MagicBricks Localities Agent | `collectors/magicbricks_localities/**`, `tests/localities/**`, MagicBricks-locality fixtures/evidence | project collector, shared config/schemas, dashboard |
| Orchestrator | shared registries, orchestration, later integration | agent-owned active files |
