# School Market v1 methodology

## Purpose and scope

`src/build_multicity_platform.py` converts the supplied **Final Data** CSVs into
city-scoped artifacts for Delhi NCR, Bengaluru, Hyderabad, Mumbai, and Pune. It
does not modify the source files. The primary demand measure is private-school
Grade 2–9 enrollment. Residential projects, hospitals, offices, and
locality/society records are contextual coverage layers; they are not silently
converted into family TAM.

This is methodology version `school-market-v1.0` and output schema
`multicity-platform-v1`.

## Fee categories

The school source supplies labels, not annual fee values. The only supported
single-tier selections are:

- `super_premium`: Super-Premium
- `premium`: Premium
- `affordable`: Affordable
- `budget`: Budget

The deterministic rollups are:

- `premium_plus`: Super-Premium + Premium
- `affordable_plus`: Super-Premium + Premium + Affordable
- `all_private`: all four supplied tiers

There is deliberately no custom annual-fee selector. The labels describe the
provided source classification and must not be interpreted as audited common
INR thresholds until a separate fee methodology is supplied.

## City normalization and boundaries

Raw `Bangalore` and `Bengaluru` labels map to `bengaluru`; spelling, case, space,
hyphen, and underscore forms of Delhi NCR map to `delhi_ncr`. Hyderabad, Mumbai,
and Pune are case-normalized. Source labels outside these five target cities are
counted in `manifest.json` under `excluded_source_city_labels` and are not lost
silently.

Delhi NCR is reported both as a comparison-market rollup and as component
markets derived from school state/district: Delhi, Gurugram, Faridabad,
Noida/Greater Noida (Gautam Buddha Nagar), Ghaziabad, Hapur, Palwal,
Bulandshahr, and Meerut. Unresolvable source records remain `unassigned`.
Components represent the coverage present in the supplied file, not an asserted
legal metropolitan boundary.

## Student and family measures

`students_grade_2_9` is the sum of non-null `enrollment_grade_2_9` values for
schools admitted to the city and selected tier(s). It is not added to
`enrollment_total`; the latter is shown only as broader enrollment context.

The school source currently identifies enrollment as either
`UDISE_reported_total` or `estimated_from_premium_benchmark`. Each summary
separates reported and estimated Grade 2–9 contributions. Missing enrollment is
excluded from the sum and exposed through school-count coverage. A cohort with
no known enrollment values remains `null`; it is never silently converted to
zero, including its modeled family scenarios. A genuinely empty selected cohort
(zero schools) remains a real zero.

Estimated school-going families are a model, not a household census count:

`estimated families = Grade 2–9 students / relevant children per family`

Three explicit sensitivity cases are emitted:

| Scenario | Relevant children per family | Interpretation |
| --- | ---: | --- |
| conservative | 1.35 | lower family estimate |
| base | 1.20 | central planning assumption |
| high | 1.08 | higher family estimate |

The ratios are configurable constants in the pipeline. They should be replaced
or calibrated by city/tier only when Rancho customer or defensible household
evidence is available. Sibling overlap across schools cannot be resolved from
the source and is the reason students are not equated one-to-one with families.

## Quality and identity

The build validates controlled fee-tier values, coordinates, duplicate
`school_id` values, and duplicate non-null UDISE codes. Coordinate coverage and
the subset marked `verified_google_places` are reported separately. A coordinate
that is present but not Google-verified remains usable for exploratory maps with
a quality warning.

Each aggregate is rebuilt from source rows; no frontend constants participate.
The manifest records source row counts, file byte sizes, modification times, and
SHA-256 hashes. It also records the byte size, relative path, and SHA-256 hash of
every generated comparison/city artifact. The API enforces declared artifact
hashes before serving them. These hashes are the reproducibility contract.

`generated_at` is deterministically set to the newest admitted source-file
modification timestamp, rather than the build machine's wall clock. Consequently
two builds from the same source directory are byte-identical. This timestamp is
an evidence snapshot marker, not a claim about the schools' academic year.

Residential `known_residential_units` sums known `total_units` values from the
supplied, already-normalized project file. It is explicitly labelled context,
not deduplicated family TAM. Missing units are excluded and disclosed through
coverage rather than treated as zero.

## Artifact contract

- `src/public/data/multicity/manifest.json`: entry point, city catalog,
  categories, assumptions, constraints, source provenance, and exclusions.
- `src/public/data/multicity/city_comparison.json`: full comparable city
  summaries with category metrics, coverage, family scenarios, quality flags,
  and context-layer summaries.
- `src/public/data/multicity/cities/{canonical_city_id}.json`: the corresponding
  city summary plus Delhi components (where applicable), districts, pincodes,
  locality fallback groups, and H3 resolution-7 aggregates.

City-level category metrics contain complete family scenarios and quality
coverage. Geography-level category metrics are intentionally compact:
`school_count`, `students_grade_2_9`, and `estimated_families_base`. A UI can
apply the manifest's alternative family ratios without downloading repeated
coverage payloads for every cell.

Each city/category also contains comparable exploratory concentration measures:
the number of occupied H3 resolution-7 cells, the share of mapped students in
the 10 largest cells, and a student HHI across occupied cells (sum of squared
student shares). Higher top-10 share/HHI means the mapped school population is
more concentrated. These measure campus enrollment locations, not student home
addresses, and must be labelled accordingly.

## Running the build

From the repository root:

```sh
python3 src/build_multicity_platform.py
```

Paths can be overridden with `--data-root` and `--output-root`. The Python `h3`
package is required. The command fails when any required source file is absent.

## Known limitations

- Fee tiers are accepted as supplied; tier thresholds, academic-year price
  basis, and inflation comparability are unavailable.
- The 301 records identified by the source as benchmark-estimated enrollment
  are included but disclosed in coverage.
- Presence of a UDISE code is identity evidence, not proof of the source file's
  academic year; the source lacks an explicit academic-year field.
- School coordinates have high presence but much lower verified-place coverage.
- `area` is mostly missing, so locality aggregates fall back to district and
  then pincode. They should not be presented as curated micro-markets.
- Context datasets have uneven city coverage, especially the Mumbai locality
  layer. Context record counts are not suitable as direct demand rankings.
- Travel times, competition, rents, operating costs, and actual Rancho customer
  capture rates are not supplied by this pipeline and must remain separate
  decision inputs.
