# Methodology

This document summarizes the main formulas and assumptions used in the bundle.
The implementation in `scripts/` remains the authoritative source.

## Locality enrichment

### Support weight

The stage 1 / stage 1.5 locality weight is:

```text
support_weight = registry_count
               if registry_count > 0
               else (rent_total_count + sale_total_count + 0.1 * reviews_count)
               else 1
```

This means registry count is treated as the strongest signal, inventory count as
the next best fallback, and reviews as a weak support signal.

### H3 smoothing

For a locality observation assigned to an H3 cell, the neighboring cells receive
smoothed contributions with decay:

```text
decay(distance) = 1 / (1 + distance)
```

This is used for the H3 heatmap metrics and stage 1 rollups.

### Budget shares

Budget shares are normalized from the weighted budget counts:

```text
share(segment) = budget_weight(segment) / sum(all budget weights)
```

Dominant budget segment is the argmax of the shares. Budget entropy is:

```text
entropy = - Σ share_i * log2(share_i)
```

### Stage 1 feature formulas

The heatmap-style raw metrics include:

- `price_sqft`
- `high_income`
- `rental_yield`
- `activity_score = inventory_total + reviews_count`
- `premium_lens_score`

Premium lens score is:

```text
price_score = 0                       if price_sqft < 6000
price_score = 1                       if price_sqft >= 12000
price_score = (price_sqft - 6000)/6000 otherwise

count_factor = min(1, bhk_34_count / 20)
density = bhk_34_count / inventory_total
premium_lens_score = count_factor * density * price_score
```

### Coordinate and polygon assumptions

- Missing or invalid coordinates are excluded from H3 placement.
- The metro bounding box is config-driven and is used to drop obvious outliers.
- Neighborhood assignment uses polygon containment first, then geocoding and a
  distance-based refinement pass.

## Society, school, and hospital categorization

### Societies

Premium society quartiles are determined from maximum sale price.

- Ultra Luxury: `>= 4.5 Cr`
- Super Luxury: `3.0 Cr - 4.5 Cr`
- Luxury: `2.6 Cr - 3.0 Cr`
- Premium: `2.1 Cr - 2.6 Cr`

The script first takes the top quartile by max price and then splits it into the
four labels above.

### Hospitals

Hospitals are ranked by maximum consultation fee.

- Ultra Premium: `>= 1500`
- Super Premium: `1200 - 1499`
- Premium: `1050 - 1199`
- Mid-Premium: `1000`

Only the top quartile by max fee is retained for the Q4 set.

### Schools

Schools are ranked by average annual fee.

- Ultra Premium: `>= 165000`
- Super Premium: `114996 - 164999`
- Premium: `84996.01 - 114995.99`
- Mid-Premium: `84996`

## Stage 1.5 rollup

Stage 1.5 rolls H3-8 into H3-7:

```text
parent_hex = h3.cell_to_parent(child_hex, 7)
```

Within each parent cell, weighted averages are computed for the retained metric
set, and budget segments are averaged across child cells to get the parent
dominant budget segment and entropy.

## Habitability

Building footprints from Overture are aggregated into H3-7 cells.

```text
habitability_score = 0.45 * coverage_norm
                   + 0.35 * density_norm
                   + 0.20 * count_norm
```

Where:

- `coverage_norm` normalizes building coverage ratio
- `density_norm` normalizes building density per square kilometer
- `count_norm` normalizes building count

Habitability gate:

```text
habitable_for_residential_tam = habitability_score >= 0.25
```

## SEZ contribution

For each hex and SEZ polygon:

```text
proximity_decay = 1.0 if overlap_ratio > 0 else exp(-distance / 3.0)
contribution = (0.60 * overlap_ratio + 0.40 * proximity_decay) * log1p(office_spaces)
```

This is used as an access signal, not a count of families.

## Commercial catchment analysis

The commercial batch step reuses the web-platform catchment rules for each
commercial listing.

### Catchment geometry

Primary mode:

```text
ORS driving isochrone at 7 km
```

No fallback mode is allowed in the batch job. A routing failure should stop the
run so the output contract stays strictly ORS-based.

### Matching rules

- H3-7 hexes are counted when the hex centroid falls inside the catchment
  polygon.
- Societies, schools, and hospitals are assigned to H3-7 cells and counted when
  the cell falls in the matched hex set.
- SEZ office spaces are counted when the SEZ centroid falls within the 7 km
  radius using haversine distance.

### Stored aggregate values

Each listing stores:

- `countable_family_tam`
- `direct_family_tam`
- `direct_total_units`
- `school_age_children`
- `wealthy_school_children`
- `society_count`
- `school_count`
- `hospital_count`
- `sez_office_spaces`
- `income_bands`

The batch job also writes one GeoJSON file per listing for the 7 km catchment
geometry, plus summary and audit JSON sidecars.

## Stage 2 scoring

All of the main component scores are min-max normalized after collecting the
raw signals per H3-7 cell.

### Society score

```text
direct_nearby_society_score =
    0.55 * luxury_family_tam_density
  + 0.20 * society_category_density
  + 0.15 * society_units_density
  + 0.10 * project_confidence

society_cluster_score =
    0.55 * society_cluster_mass
  + 0.25 * surrounding_society_cluster_mass
  + 0.15 * society_cluster_ultra_super_density
  + 0.05 * society_cluster_count_weighted

society_score =
    0.62 * direct_nearby_society_score
  + 0.28 * society_cluster_score
  + 0.10 * resale_rental_liquidity
```

### School score

```text
school_score =
    0.40 * premium_school_travel_access
  + 0.25 * annual_fee_travel_weighted
  + 0.20 * student_tam_travel_weighted
  + 0.15 * top_school_count_access
```

### Hospital score

```text
hospital_score =
    0.35 * premium_hospital_travel_access
  + 0.25 * doctor_capacity_travel_weighted
  + 0.20 * review_rating_confidence
  + 0.20 * hospital_count_access
```

### Market score

```text
market_score =
    0.35 * market_price_per_sqft
  + 0.20 * premium_lens_score
  + 0.20 * budget_segment_score
  + 0.15 * sale_inventory_depth
  + 0.10 * locality_support_weight
```

### Residential school fit

```text
residential_anchor_strength = max(society_score, 0.75 * society_cluster_score, 0.60 * market_score)
residential_school_fit_score = school_score * residential_anchor_strength
```

### Base affluence score

```text
sez_score = min(1.0, 0.60 * sez_overlap_area + 0.40 * sez_proximity_access)

base_affluence_score = 100 * (
    0.45 * society_score
  + 0.14 * residential_school_fit_score
  + 0.15 * hospital_score
  + 0.21 * market_score
  + 0.05 * sez_score
)
```

If a cell is not habitability-qualified and has no direct family TAM, the base
score is downweighted:

```text
base_affluence_score *= 0.45
```

### Evidence confidence

```text
evidence_confidence =
    0.40 * max(
        min(1.0, societies_nearby_count / 5.0),
        0.75 * min(1.0, society_cluster_project_count / 6.0)
    )
  + 0.20 * min(1.0, locality_count / 3.0)
  + 0.20 * min(1.0, schools_nearby_count / 3.0)
  + 0.15 * min(1.0, hospitals_nearby_count / 2.0)
  + 0.05 * (0.6 if quality_flags else 1.0)
```

### Spatial adjustment and final score

```text
spatial_score = 0.85 * base_affluence_score + 0.15 * neighbor_mean

final_score = clamp(spatial_score - island_penalty + cluster_boost, 0, 100)
```

Where:

- high isolated scores may receive an island penalty unless they have an
  independent anchor
- compact clusters of strong cells may receive a small boost

## Final TAM layer

The final layer keeps countable family TAM as the primary TAM signal.

```text
countable_school_age_families = countable_family_tam * 0.38
countable_school_age_children = countable_school_age_families * 1.25
```

Conservative 50L+ TAM counts only direct TAM in the upper bands:

- `50L-1Cr`
- `1Cr-2Cr`
- `2Cr-5Cr`
- `5Cr+`

The linear 40L+ estimate adds a 10/25 share of the `25L-50L` band:

```text
estimated_40l_plus = conservative_50l_plus + (10 / 25) * direct_25L_50L
```

## Assumptions

- If no direct neighborhood containment is found, the refinement script may use
  geocoding and a 1 km proximity threshold.
- The OSRM-based travel scores assume a local, reachable OSRM instance.
- `school_score`, `hospital_score`, `society_score`, and `market_score` are all
  relative scores, not counts.
- The final deliverable is intended as company-facing decision support, not a
  formal demographic census or an enrollment model.
