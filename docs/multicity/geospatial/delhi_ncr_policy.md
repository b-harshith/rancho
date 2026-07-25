# Delhi NCR geospatial and PIN policy

## Approved working scope

`delhi_ncr` is a metro roll-up, not an alias for New Delhi. Its five retained components are Delhi NCT, Gurugram, Faridabad, Ghaziabad, and Noida/Greater Noida. The reproducible polygon is the union of 15 district features: all 11 Delhi NCT districts and the Gurgaon, Faridabad, Ghaziabad, and Gautam Buddha Nagar districts. Source records must keep both `canonical_city_id: delhi_ncr` and their component ID. The project must deduplicate stable source IDs before aggregation; component totals are not safe to add blindly.

This district-union definition is deliberately broader than municipal-core definitions. It is suitable for a reproducible first collection boundary and avoids silently dropping schools in peri-urban NCR. Any later move to municipal-corporation limits is a policy change requiring a new boundary version and a regenerated PIN ledger.

## Boundary evidence and validation

The materialized boundary is extracted from geoBoundaries gbOpen India ADM2 revision `9469f09`, representing 2021 districts. Its metadata attributes the upstream data to Pathways Data Pvt. Ltd. and `lgdirectory.gov.in`; the published license is ODbL 1.0. The current extraction contains 15/15 expected district features, 11/11 Delhi NCT districts, five/five components, valid source geometries, and a valid union. The boundary is not claimed to be current enough for legal or cadastral use.

Google Geocoding is a reference layer only. It can return a center, viewport, and sometimes a rectangular `bounds` value, but not a reusable administrative polygon. `pipelines/geospatial/google_geocode.py` accepts the key only through `GOOGLE_MAPS_API_KEY`, removes it from saved request URLs, and expires cached coordinates within 29 days. The supplied key was not copied to a command, file, log, fixture, or handoff. Execution remains pending because the variable was not present in the agent runtime.

Overture divisions is documented as an additional open conflict-review source. Its divisions theme is derived from OpenStreetMap and geoBoundaries and is ODbL-licensed. A conflict must be retained as evidence; it must not silently overwrite the approved polygon.

## PIN inclusion and exclusion

The authoritative candidate base is the Department of Posts “All India Pincode Directory till last month” resource on data.gov.in, portal update 2025-10-03, licensed under the Government Open Data License - India. A PIN is included when any post-office row is in Delhi state or in the Gurgaon/Gurugram, Faridabad, Ghaziabad, or Gautam Buddha Nagar district. This produces 194 unique PINs. PIN `201009` is explicitly retained in both Ghaziabad and Noida/Greater Noida component membership while appearing only once in the UDISE search list.

The adjacent-prefix exclusion ledger contains 101 unique PINs that share a three-digit prefix with an included PIN but have no post office in an approved component district. Inclusion and exclusion are decided only after all office rows are grouped by PIN: a PIN with any approved-component office is included once and excluded nowhere. The ledger exists to make edge decisions reviewable; it is not an assertion that every excluded postal service area lies outside the polygon. PINs are postal service identifiers rather than polygons, so office/district membership and boundary containment are separate claims.

## Distance policy

High-volume distance screening uses the WGS84 Haversine implementation in `pipelines/geospatial/distance.py`. It is straight-line distance only. OSRM or another routing engine must not be called or described as the source of these distances, and Haversine output must not be labeled travel distance or travel time.

## Reproduction

With the official India Post CSV and geoBoundaries India ADM2 GeoJSON downloaded to temporary paths:

```bash
venv/bin/python pipelines/geospatial/prepare_delhi_ncr.py \
  --postal-source /tmp/data-gov-pincode.csv \
  --boundary-source /tmp/geoBoundaries-IND-ADM2.geojson
```

Then, after injecting the Google key in the runtime environment (never in shell history or a repository file), run the five queries in `google_query_manifest.json` through `pipelines/geospatial/google_geocode.py` and review center/bounds conflicts before admission.
