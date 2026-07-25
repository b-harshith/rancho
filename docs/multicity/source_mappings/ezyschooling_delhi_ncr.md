# Ezyschooling — Delhi NCR mapping

Status: **BLOCKED / mapping not yet verified** (2026-06-30).

## Local evidence

Two legacy local scripts were inspected:

- `/Users/malleswararao/Desktop/School Data/diagnostics/scrape_ezyschooling_api.py`
- `/Users/malleswararao/Desktop/BangaloreRancho/city_rerun_bundle/scripts/source/schools/scrape_ezyschooling_api.py`

They call `https://api.main.ezyschooling.com/api/v1/schools/document/` with a
`school_city` query, but infer that value from a CLI string and only fetch list
payloads. The local Bengaluru capture contains 1,811 records and demonstrates
that each list row has a source `id`, `slug`, `school_city`, optional
`geocoords`, fees, and board fields. This is structural evidence only; it does
not prove a Delhi NCR slug or component set.

## Required verification before live collection

Delhi NCR must be observed through Ezyschooling's current city selector or
first-party request state. Record each represented component (Delhi/New Delhi,
Noida, Gurugram/Gurgaon, Ghaziabad, Faridabad), the exact source city name/id/
slug, the rendered URL, timestamp, returned count, and a redacted sample. A
component is admitted only when sampled addresses belong to the approved NCR
boundary. Never infer a slug by lowercasing a city name.

The collector expects an explicit `source_mappings.ezyschooling` entry with
`verified: true`, `verified_url`, `verified_at`, and either one mapping or a
`components` array. The shared city registry currently has no such mapping, so
the safe expected result is `BLOCKED` before any request.

## Collection contract

The first stage paginates the verified API mapping and appends complete response
envelopes to `raw/ezyschooling/pages.jsonl`. The second stage deterministically
deduplicates source IDs, visits every school detail URL, and appends parsed
detail envelopes to `raw/ezyschooling/details.jsonl`. Independent page/detail
checkpoints make both stages resumable. Challenge pages and cross-city source
labels are hard failures. Normalized records retain hashes for both stages.

No live API request was made during the original task because the mapping gate
was not met.

## Bounded route discovery — 2026-06-30 UTC

Status: **canonical routes verified; API parameters still blocked**.

Ezyschooling's currently rendered, first-party pages and its own “Day Schools in
Popular Cities” navigation expose these seven distinct Delhi NCR surfaces. These
are route observations, not permission to copy the route segment into the API
`school_city` parameter.

| Component | Rendered first-party URL | Rendered source label | Displayed coverage | Bounded rendered sample | Route sample match |
|---|---|---|---:|---|---:|
| Delhi | `https://ezyschooling.com/delhi` | Delhi | 1,803+ verified schools | New Era Public School — Dwarka, South West Delhi; Mother's Pride School — Dwarka, South West Delhi; OPG World School — Dwarka, South West Delhi | 3/3 (100%) |
| Gurgaon/Gurugram | `https://ezyschooling.com/gurugram` | page heading: Gurgaon; addresses: Gurugram | 519+ verified schools | KIIT World School — Sohna Road, Gurugram; Manav Rachna International School — Sector 46, Gurugram; K.R. Mangalam World School — Gurugram | 3/3 (100%) |
| Ghaziabad | `https://ezyschooling.com/ghaziabad` | Ghaziabad | 458+ verified schools | St. Teresa School — Indirapuram, Ghaziabad; JKG International School — Indirapuram, Ghaziabad; Sapphire International School — Crossings Republik, Ghaziabad | 3/3 (100%) |
| Faridabad | `https://ezyschooling.com/faridabad` | Faridabad | 334+ verified schools | Ryan International School — Sector 21B, Faridabad; Grand Columbus International School — Sector 16A, Faridabad; Manav Rachna International School — Sector 14, Faridabad | 3/3 (100%) |
| Noida | `https://ezyschooling.com/noida` | Noida | 266+ verified schools | Delhi Public School — Sector 132, Noida; ASPAM Scottish School — Sector 62, Noida; Yadu Public School — Sector 73, Noida | 3/3 (100%) |
| Greater Noida | `https://ezyschooling.com/greater-noida` | Greater Noida | 124+ verified schools | GD Goenka Public School — Sector Tau, Greater Noida; Sparsh International School — Omega I, Greater Noida; Greater Noida World School — Sigma I, Greater Noida | 3/3 (100%) |
| Greater Noida West | `https://ezyschooling.com/greater-noida-west` | Greater Noida West | 56+ verified schools | St. Xavier's High School — Tech Zone IV, Greater Noida West; Delhi World Public School — Knowledge Park V, Greater Noida West; The Millennium School — Knowledge Park V, Greater Noida West | 3/3 (100%) |

Evidence was read from public rendered pages only. No login, form submission,
CAPTCHA interaction, token, cookie, or personal data was involved. No challenge
page was observed through that read-only surface.

### API mapping decision

The current rendered text verifies component routes and labels but does not
expose the underlying `/api/v1/schools/document/` request or its exact
`school_city` value/source city ID. The in-app browser/network-inspection surface
was unavailable, and the approved direct homepage-source inspection could not
run because the execution environment denied the request. Search did not reveal
an authoritative first-party API request.

Therefore all seven API mappings remain deliberately null:

```yaml
source_mappings:
  ezyschooling:
    verified: false
    verified_at: null
    verified_url: null
    api_url: https://api.main.ezyschooling.com/api/v1/schools/document/
    components:
      - {route_url: https://ezyschooling.com/delhi, city_slug: null, city_name: Delhi, city_id: null}
      - {route_url: https://ezyschooling.com/gurugram, city_slug: null, city_name: Gurgaon, city_id: null}
      - {route_url: https://ezyschooling.com/ghaziabad, city_slug: null, city_name: Ghaziabad, city_id: null}
      - {route_url: https://ezyschooling.com/faridabad, city_slug: null, city_name: Faridabad, city_id: null}
      - {route_url: https://ezyschooling.com/noida, city_slug: null, city_name: Noida, city_id: null}
      - {route_url: https://ezyschooling.com/greater-noida, city_slug: null, city_name: Greater Noida, city_id: null}
      - {route_url: https://ezyschooling.com/greater-noida-west, city_slug: null, city_name: Greater Noida West, city_id: null}
```

This is a blocked mapping proposal, not configuration to merge. A future browser
session must observe the first-party request emitted by selecting each component,
then run exactly one API page and require at least 90% returned `school_city` or
address agreement before setting `verified: true`. Because that evidence was not
available, the collector preflight was not run and no API sample/full scrape was
started.
