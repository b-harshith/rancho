# Bangalore Market Research Readiness Report

## Verdict

**Mostly ready for high-level Bangalore market research, with a few data-quality caveats.**

The school and project datasets are both rich enough to support:
- zone-level and locality-level demand analysis
- fee-band and premium-segment comparisons
- school-to-project proximity analysis using `lat` / `lon`
- quartile-based positioning of schools and residential projects

The datasets are **not yet perfect for fully granular hex-based analysis** because the project file still has missing `hex_id` values for every row and some school rows still rely on reverse-geocoded fallback rather than a direct venue match.

## Dataset Coverage

### Schools
- Records: `2,007`
- Removed out-of-Bangalore rows: `8`
- Clean Bangalore scope: `2,007` rows
- Quartile split:
  - `Q1`: `502`
  - `Q2`: `502`
  - `Q3`: `502`
  - `Q4`: `501`
- Q4 sub-split:
  - `Q4-Sub-Q1`: `126`
  - `Q4-Sub-Q2`: `125`
  - `Q4-Sub-Q3`: `125`
  - `Q4-Sub-Q4`: `125`

### Projects
- Records: `8,920`
- Quartile split:
  - `Q1`: `2,161`
  - `Q2`: `2,280`
  - `Q3`: `2,206`
  - `Q4`: `2,273`
- Q4 sub-split:
  - `Q4-Sub-Q1`: `554`
  - `Q4-Sub-Q2`: `570`
  - `Q4-Sub-Q3`: `562`
  - `Q4-Sub-Q4`: `559`

## School Data Quality

### Strengths
- All rows are now inside the Bengaluru bounding box.
- Every row has a location payload and no rows are left without an address.
- Quartile fields are consistent and balanced.
- The dataset now has a clear premium hierarchy using:
  - `quartile analysis 1`
  - `quartile analysis 2`
  - `quartile_category`
  - `quartile_tag`

### Gaps
- Duplicate school names remain because many are valid chain branches.
- Duplicate coordinates remain because some schools share campuses or very close campus points.
- `941` rows still have no `udise_code`.
- `297` rows still have no `pincode`.
- Some rows were resolved via reverse geocoding rather than a direct Google place match.

### Key school metrics
- Duplicate names: `128`
- Duplicate coordinate points: `240`
- Missing UDISE code: `941`
- Missing pincode: `297`
- Median `fee_max`: `40,000`
- 90th percentile `fee_max`: `125,004`

## Project Data Quality

### Strengths
- Good scale for market mapping: `8,920` projects.
- No projects fall outside the Bengaluru bounds.
- Strong locality coverage.
- Price quartiles are already present and well distributed.
- Project fee segmentation looks internally consistent.

### Gaps
- `hex_id` is missing on all rows.
- `price_SQFT` is missing or zero for `7,171` rows.
- Duplicate names and duplicate coordinate points exist, though this is likely expected for repeated project naming / nearby listings.

### Key project metrics
- Duplicate names: `77`
- Duplicate coordinate points: `377`
- Missing `hex_id`: `8,920`
- Missing / zero `price_SQFT`: `7,171`
- Median `max_price`: `16,460,000`
- 90th percentile `max_price`: `33,000,000`

## Readiness Assessment

### Ready now for:
- Bangalore market sizing
- school-fee segmentation
- premium / luxury positioning
- comparing school tiers against residential project tiers
- zone and locality storytelling
- coarse demand-supply analysis

### Not ideal yet for:
- exact hex-grid spatial scoring
- very fine-grained geospatial matching by H3 cell
- fully automated citywide deduplication without manual exceptions

## Recommendation

**Use the datasets for market research now, but treat the output as high-confidence for strategic analysis rather than cadastral precision.**

If you want to make it fully production-grade for spatial market intelligence, the next best cleanup steps are:
1. Populate `hex_id` for projects.
2. Fill missing school `pincode` values where possible.
3. Review the reverse-geocoded school rows flagged as weaker matches.
4. Add a small duplicate-branch reconciliation pass for chain schools.

## Source Files

- [Canonical school entities](/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/src/public/data/school_entities.json)
- [Physical school campuses](/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/src/public/data/school_campuses.json)
- [Projects data](/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/new%20data/bangalore_projects_classified.json)
- [School market summary](/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/src/public/data/school_market_summary.json)
- [School market audit](/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/src/public/data/school_market_audit.json)
