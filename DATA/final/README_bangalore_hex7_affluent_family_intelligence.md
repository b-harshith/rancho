# Bangalore Hex-7 Affluent Family Intelligence

This folder contains the final per-hex deliverable for the affluent-family TAM analysis.

## Recommended files

- `bangalore_hex7_affluent_family_intelligence_master.json` - full nested evidence file.
- `bangalore_hex7_affluent_family_intelligence_flat.csv` - spreadsheet-friendly summary.
- `bangalore_hex7_affluent_family_intelligence.geojson` - GIS polygon layer.
- `../../maps/final/bangalore_hex7_affluent_family_intelligence.kml` - click-ready Google Earth map.
- `../client_handoff/README_CLIENT.md` - client-facing handoff guide.

## Coverage convention

- Final H3 coverage: **309 hexes**
- Active analysis coverage: **309 hexes**

The final package keeps all modeled H3 cells. The active analysis layer is the filtered set used in the web platform for zone and micro-market summaries.

## What to use for decisions

- Use `tam.countable_family_tam` for countable affluent family TAM.
- Use nearby and cluster TAM fields only as context, not as extra families.
- Use `commute.score` as a free commute-friction proxy, not live traffic.
- Use `top_evidence` to inspect the societies, schools, hospitals, and SEZ/workplace context behind each score.

## Current totals

- Countable family TAM: 0
- Countable school-age children: 0
- Conservative 60L+ direct TAM share: 0.00%
- Estimated 40L+ direct AHI TAM share: 0.00%

## Important caveat

This is a decision-support layer, not ground truth. Derived child estimates and commute scores are useful for prioritization, but should be validated with field research before commercial decisions.
