# MagicBricks localities — Delhi NCR mapping

Verified 2026-06-30 against MagicBricks's rendered locality pages and their
`domcache_locality_detail` state. The user-provided Hyderabad URL was used only
to identify the page family; no Hyderabad mapping or data was reused.

| Source component | Source city ID | Verified URL | Observed locality count |
|---|---:|---|---:|
| New delhi | 2624 | `https://www.magicbricks.com/localities-in-new-delhi` | 4,377 |
| Noida | 6403 | `https://www.magicbricks.com/localities-in-noida` | 716 |
| Gurgaon | 2951 | `https://www.magicbricks.com/localities-in-gurgaon` | 2,144 |
| Ghaziabad | 6146 | `https://www.magicbricks.com/localities-in-ghaziabad` | 932 |
| Faridabad | 2944 | `https://www.magicbricks.com/localities-in-faridabad` | 1,594 |

The combined `localities-in-delhi-ncr` URL rendered a loader and no locality
cards during verification. Production therefore uses the five explicit source
components above, retaining each source ID/name while assigning
`canonical_city_id=delhi_ncr`.

The site's public page JavaScript identifies the stage-1 pagination request as
`/mbutility/localitySearchPage?autoLoad=Y&page={page}&sortBy=&cityName={city_name}`
with 20 cards per page. This endpoint is stored explicitly in configuration;
the collector does not mutate or guess slugs. Stage 2 follows only the unique
`loc-card__title` URLs returned by stage 1.

Production remains gated by a >=90% first-page city-name match for every
component. A challenge page, mapping mismatch, empty first page, repeated page,
or incomplete detail manifest stops/quarantines the run. The observed counts
are evidence for review, not hard-coded completion assumptions; current page
metadata controls enumeration and repeated-page/end detection protects it.

Bounded preflight evidence on 2026-06-30: all five components returned 20/20
matching first-page cards (100% each), and five followed New Delhi detail links
parsed with stable IDs and coordinates (5/5). This is a parser/mapping PASS,
not a full-production count; diagnostic runs are marked `diagnostic_complete`
and `production_complete=false` in the manifest.
