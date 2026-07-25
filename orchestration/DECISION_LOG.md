# Decision Log

## D-001 — Working city registry

- Date: 2026-06-30
- Decision: Use Bengaluru, Delhi NCR, Mumbai, Hyderabad, Chennai, Kolkata, Pune, and Ahmedabad in that order.
- Basis: explicit fallback registry in the execution prompt.
- Revisit when: the owner supplies a different approved definition.

## D-002 — Delhi NCR scope

- Date: 2026-06-30
- Decision: Treat Delhi NCR as a metro region. Preserve each source component city identity and normalize approved components to `delhi_ncr`; do not assume New Delhi alone and do not merge/deduplicate until source and boundary evidence exists.

## D-003 — Unverified mappings

- Date: 2026-06-30
- Decision: Source IDs, slugs, URLs, boundaries, centers, and PIN files remain null until evidenced from authoritative sources. No mapping will be inferred by string substitution.

## D-004 — Version-control fallback

- Date: 2026-06-30
- Decision: The supplied workspace has no `.git` repository. Use atomic writes, immutable raw data, hashes/manifests, and orchestration logs as reversible checkpoints.

## D-005 — Schools source expansion

- Date: 2026-06-30
- Decision: Add Ezyschooling alongside YellowSlate and UDISE. Ezyschooling collection is explicitly multi-stage: enumerate search/page results, then fetch every unique school detail URL before canonical normalization, matching, entity/campus resolution, and geocoding.

## D-006 — Localities source replacement

- Date: 2026-06-30
- Decision: Replace 99acres Localities with a rebuilt MagicBricks Localities pipeline. Preserve the separate MagicBricks Projects pipeline. The localities pipeline must enumerate locality pages/links and then fetch every unique detail page.

## D-007 — Distance method

- Date: 2026-06-30
- Decision: Do not use OSRM for the multi-city pipeline. Use Haversine distance for proximity, screening, matching evidence, and lightweight routing-distance proxies; label it straight-line distance and never present it as routed travel time/distance.

## D-008 — Google and open geospatial sources

- Date: 2026-06-30
- Decision: Google Maps may be used for geocoding/bounds support using a runtime-only key supplied by the owner. The key must never enter tracked files/logs/manifests. Use authoritative/open sources such as India Post, ArcGIS, Overture, or OSM when needed and preserve source/license/conflict provenance. Provider-side rotation/restriction remains required because the key was exposed.

## D-009 — UDISE PIN/CAPTCHA workflow

- Date: 2026-06-30
- Decision: Retain sequential PIN-code searches. OCR-assisted CAPTCHA support was requested by the owner, but execution must remain challenge-gated and comply with the active browser/source access rules; do not silently bypass an access-control challenge or log CAPTCHA content/answers.
