# Society Data Richness Audit

## Before vs After

- Previous premium-only public feed: **2,268** records across **246** hexes.
- New full project universe: **8,920** records across **436** derived H3-7 hexes.
- Net increase in observable residential projects: **6,652**.
- Relative expansion: **3.93x** the previous premium-only feed.

## Quartile Coverage

- Full universe quartile split: `{'Q4': 2268, 'Q3': 2200, 'Q2': 2271, 'Q1': 2152}`
- Q4 scorer input retained for premium affluence/TAM scoring: **2,268** projects
- Q4 derived scorer categories: `{'Ultra Luxury': 561, 'Premium Luxury': 551, 'Elite Luxury': 559, 'Super Luxury': 569, 'Luxury': 6, 'Premium': 7, 'Aspirational Premium': 15}`

## Q3 and Below

- Q1/Q2/Q3 property count: **6,623**
- Q1/Q2/Q3 units total: **919,856**
- Derived Q3-below hex coverage: **423** hexes
- Inside active scorer footprint: **5,805**
- Outside active scorer footprint: **818** across **197** hexes

## Completeness

- Valid geocoded project rows: **8,891**
- Rows missing source `price_SQFT`: **7,142**
- Rows missing source `hex_id` before derivation: **0**

## Interpretation

- Affluence scoring and family TAM still use the Q4 premium society layer only.
- The new **Q3 and Below Properties** metric is a separate market-depth signal built from the full project universe.
- School-market evidence is generated independently and never alters society TAM.
