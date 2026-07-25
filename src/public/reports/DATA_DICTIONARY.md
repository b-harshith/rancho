# Data Dictionary

| Metric | Meaning | Client Use |
| --- | --- | --- |
| `countable_family_tam` | Primary affluent-family estimate from direct society aggregation. | Main TAM number. |
| `direct_family_tam` | Non-duplicated family TAM inside the hex or grouped region. | Cross-check against countable TAM. |
| `nearby_family_tam_weighted_context` | Nearby weighted family TAM context. | Context only; do not add to countable TAM. |
| `society_cluster_tam_weighted_context_not_counted` | Cluster influence around the hex. | Cluster signal only; not unique families. |
| `q3_and_below_property_count` | Count of Q1/Q2/Q3 projects in the selected area from the full project universe. | Market-depth signal separate from Q4 TAM scoring. |
| `confidence_score` | Evidence strength from model inputs and quality flags. | Use to decide field-validation priority. |
| `habitability_score` | Overture building evidence and residential plausibility. | Helps avoid non-residential false positives. |
| `commute_score` | Free OSM/OSRM-derived commute-friction proxy. | Access quality screen, not live traffic. |
| `quality_flags` | Known caveats such as missing evidence or low building evidence. | Must be reviewed before final decisions. |
