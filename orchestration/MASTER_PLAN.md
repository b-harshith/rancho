# Multi-City Research Master Plan

Updated: 2026-06-30 (Asia/Kolkata)

## Objective

Preserve Bengaluru as the regression baseline and sequentially admit Delhi NCR, Mumbai, Hyderabad, Chennai, Kolkata, Pune, and Ahmedabad only after source mapping, collection, normalization, spatial derivation, independent QA, dashboard ingestion, and reconciliation gates pass.

## Execution order and gates

1. Wave 1: baseline audit, scraper/source mapping inventory, and documentation skeleton.
2. Wave 2: approve canonical schemas/configuration and assign exclusive implementation ownership.
3. Active-city Stage 0: verify boundary, PIN provenance, all source mappings (including Ezyschooling and MagicBricks Localities), and one-page preflights.
4. Active-city Stages 1–3: collect, normalize, deduplicate, geocode, and match independent source families.
5. Independent source QA; failed artifacts return to their producer.
6. Active-city Stages 4–5: TAM/classification and spatial intelligence.
7. City-wide QA, Bengaluru regression, UI/E2E, reconciliation, and final admission decision.
8. Finalize city report/handoff before advancing to the next city.

The active unfinished city is `delhi_ncr`. No later city may receive production datasets until Delhi NCR receives an admission decision. Discovery and fixture work may run ahead but cannot write production city data.

## Current wave

Wave 1 and bounded Wave 2 framework QA are complete. Scope revision work is active: Ezyschooling integration, a multi-stage MagicBricks Localities collector replacing 99acres Localities, and Google/open-source boundary/PIN preparation. Delhi NCR Stage 0 cannot pass until verified mappings, boundary/component policy, PIN provenance, and all required source preflights are complete.

## Admission policy

A producer never self-certifies. Normalized inputs require independent QA before spatial consumption; derived city outputs require city-wide independent QA before dashboard admission. Unknown values remain null, synthetic/fabricated substitutions are prohibited, and human action is required for lawful CAPTCHA/session workflows.

## Checkpoint policy

This workspace has no Git metadata. Checkpoints therefore use immutable raw layers, atomic derived writes, task manifests with hashes, and the handoff/decision logs. Existing Bengaluru source/reference files are read-only unless a later task explicitly assigns a narrow integration change.
