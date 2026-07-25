# Bangalore Rancho Affluent Family TAM Workspace

This workspace contains the H3-based Bengaluru affluent-family TAM pipeline. The current
company-facing deliverable is the final per-hex intelligence package generated from the
validated Stage 2 output.

## Recommended Final Outputs

- `DATA/final/bangalore_hex7_affluent_family_intelligence_master.json` - full nested per-hex evidence file.
- `DATA/final/bangalore_hex7_affluent_family_intelligence_flat.csv` - spreadsheet-friendly per-hex summary.
- `DATA/final/bangalore_hex7_affluent_family_intelligence.geojson` - GIS polygon layer.
- `maps/final/bangalore_hex7_affluent_family_intelligence.kml` - Google Earth / Google My Maps handoff with hex popups and POI pins.

## Current Production Flow

Run these from the project root.

```bash
python3 scripts/active/generate_stage2_hex7_affluence.py
python3 scripts/active/evaluate_stage2_hex7_spatial_diagnostics.py
python3 scripts/active/generate_final_hex_intelligence.py
```

Stage 2 requires local OSRM on `http://localhost:5001` because the routed school and
hospital access signals are OSRM-only.

The final intelligence generator does not call OSRM. It repackages the already-routed
Stage 2 output into company-facing files.

## Folder Layout

- `DATA/raw/` - original source data kept for traceability.
- `DATA/Stage2 processing/` - curated Stage 2 source inputs: Stage 1.5 hexes, societies, schools, hospitals, and SEZ KML.
- `DATA/overture/` - large Overture building polygon files used to build habitability.
- `DATA/routing/` - local OSRM graph and source PBF. Keep this if routing must be reproducible.
- `DATA/processed/` - generated Stage 1, Stage 1.5, and Stage 2 artifacts.
- `DATA/final/` - final company-facing per-hex handoff files.
- `DATA/audits/` - production audit, methodology, diagnostics, and cleanup reports.
- `DATA/experimental/` - experiments that are not part of the final handoff.
- `maps/final/` - final company-facing KML/map files.
- `maps/h3/` - exploratory H3 maps and Stage 1/Stage 2 KMLs.
- `maps/mece/` - MECE market viewer outputs.
- `maps/budget_source/` - original vs ML-predicted budget segment maps.
- `maps/legacy/` - older locality maps retained for reference.
- `maps/experimental/` - experimental map outputs that should not be used as final deliverables.
- `scripts/active/` - production scripts.
- `scripts/experimental/` - scripts for experiments that are not current production logic.
- `scripts/legacy/` - older scripts retained for reference.

## Final Logic Summary

Use the final per-hex package for decisions. The final model keeps the unit of analysis at
H3 resolution 7 and intentionally does not allocate individual children to schools.

- `tam.countable_family_tam` is the primary countable family TAM.
- `tam.countable_school_age_children` is derived from family TAM using the 0.38 school-age family rate and 1.25 children per school-age family.
- `tam.countable_wealthy_school_children` is a legacy field name for access-adjusted school-age children from the family model.
- School-side Grade 2-9 enrollment is a separate supply/enrollment metric and is not expected to match family-model school-age children one-to-one.
- Nearby and cluster TAM fields are context only, not extra countable families.
- KML popups include raw society, school, hospital, market, habitability, and SEZ evidence for manual inspection.

## Experimental Huff Model

The old Stage 3 production-constrained Huff / gravity model is archived under:

- `DATA/experimental/stage3_huff_model/`
- `maps/experimental/stage3_huff_model/`
- `scripts/experimental/generate_stage3_affluent_family_tam.py`

It is retained for reference only. It is not recommended as the final deliverable because
it answers a different question from the company need and can merge too many connected
hexes into oversized areas.
