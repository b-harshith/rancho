# Agent Registry

| Agent | Role | Active task | Writable scope | State |
|---|---|---|---|---|
| `/root` | Orchestrator / Integration | `W1-ORCHESTRATE` | orchestration, shared config, later integration | in progress |
| `/root/baseline_audit` | Baseline and Architecture Auditor | `W1-BASELINE-AUDIT` | baseline audit and approved Bengaluru fixtures | complete; handoff accepted |
| `/root/source_mapping` | Source Mapping and Compliance | `W1-SOURCE-MAP` | scraper inventory and source-mapping evidence | complete; handoff accepted with blockers |
| `/root/docs_skeleton` | Documentation and Handoff | `W1-DOCS-SKELETON` | four documentation skeletons | complete; handoff accepted |

Future roles are reserved but unassigned: Schools Pipeline; Residential Projects Pipeline; Localities and Hospitals Pipeline; Spatial Intelligence and Metrics; Dashboard and API; Independent QA and Reconciliation. They receive work only after Wave 1 review and exclusive file ownership assignment.

## Wave 2 assignments

| Agent | Role | Active task | Writable scope | State |
|---|---|---|---|---|
| `/root/contracts_config` | Canonical Contracts and Config | `W2-CONTRACTS-CONFIG` | `schemas/**`, `src/multicity/**`, `tests/multicity/**`, `config/schema/**` | complete; QA PASS |
| `/root/safe_collectors` | Collector Safety and CLI Adapters | `W2-SAFE-COLLECTORS` | `collectors/**`, `tests/collectors/**`, `.env.example`, `.gitignore` | complete after R1; QA PASS |
| `/root/bengaluru_rebuild` | Bengaluru Rebuild Producer | `W2-BLR-REBUILD` | `pipelines/bengaluru_rebuild/**`, `data/staging/bengaluru/**`, `tests/reconciliation/**` | complete staging build; QA PASS; not admitted |
| `/root/independent_qa` | Independent QA and Reconciliation | `W2-INDEPENDENT-QA` | `audits/wave2/**`, `tests/qa/**` | R0 FAIL, R1 PASS |

An Independent QA and Reconciliation Agent will be assigned only after these bounded producer artifacts are ready. It must not share their writable scopes.

## Scope-revision assignments

| Agent | Role | Active task | Writable scope | State |
|---|---|---|---|---|
| `/root/geo_boundary_pins` | Geospatial Boundary and PIN Preparation | `DNC-GEO-PINS` | geospatial pipelines/reference/audits/tests/docs | complete; QA PASS |
| `/root/ezyschooling_pipeline` | Schools Pipeline — Ezyschooling | `DNC-EZYSCHOOLING` | Ezyschooling collector, school pipeline/tests/evidence | code QA PASS; mapping blocked |
| `/root/magicbricks_localities` | Localities Pipeline — MagicBricks | `DNC-MB-LOCALITIES` | MagicBricks Localities collector/tests/evidence | complete; QA PASS; production held by Stage 0 |

Every handoff must report task ID, status, summary, changed/created files, commands, tests, counts, coverage, assumptions, warnings, blockers, and recommended next task. The orchestrator verifies artifacts before acceptance.
