import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import branca.colormap as cm
import folium

from generate_h3_heatmaps import (
    BUDGET_SEGMENT_COLORS,
    DATA_DIR,
    H3_RESOLUTION,
    MAPS_DIR,
    MAP_CENTER,
    build_cell_geometries,
    h3,
    h3_cell_feature,
    load_localities,
    parse_localities,
    smoothing_decay,
)


MAPS_DIR = Path("maps") / "budget_source"
AUDIT_PATH = DATA_DIR / "audits" / "budget_source_heatmap_audit.json"

SOURCE_CONFIGS = {
    "original": {
        "title": "Budget Segment Heatmap - Original Source",
        "filename": "budget_segment_original_heatmap.html",
        "label": "Original Budget Segment",
        "description": "Only localities where budget_segment_source is original.",
    },
    "ml_predicted": {
        "title": "Budget Segment Heatmap - ML Predicted",
        "filename": "budget_segment_ml_predicted_heatmap.html",
        "label": "ML Predicted Budget Segment",
        "description": "Only localities where budget_segment_source is ml_predicted.",
    },
}


def build_source_budget_cells(localities, source):
    budget_acc = defaultdict(lambda: defaultdict(float))
    source_locality_names = defaultdict(list)
    source_counts = defaultdict(int)

    filtered = [
        loc for loc in localities
        if loc.get("budget_segment_source") == source
    ]

    for loc in filtered:
        source_counts[loc["h3_cell"]] += 1
        if len(source_locality_names[loc["h3_cell"]]) < 8:
            source_locality_names[loc["h3_cell"]].append(loc["name"])

        for neighbor in h3.grid_disk(loc["h3_cell"], 1):
            try:
                distance = h3.grid_distance(loc["h3_cell"], neighbor)
            except Exception:
                distance = 1
            budget_acc[neighbor][loc["budget_segment"]] += loc["weight"] * smoothing_decay(distance)

    cells = {}
    for cell, segment_weights in budget_acc.items():
        total = sum(segment_weights.values())
        if total <= 0:
            continue
        shares = {segment: weight / total for segment, weight in segment_weights.items()}
        dominant_segment = max(shares.items(), key=lambda item: item[1])[0]
        dominant_share = shares[dominant_segment]
        entropy = 0.0
        for share in shares.values():
            if share > 0:
                entropy -= share * math.log2(share)
        cells[cell] = {
            "budget_weights": dict(segment_weights),
            "budget_shares": shares,
            "dominant_budget_segment": dominant_segment,
            "dominant_budget_share": dominant_share,
            "budget_entropy": entropy,
            "source_locality_count": source_counts.get(cell, 0),
            "source_localities": source_locality_names.get(cell, []),
        }
    return filtered, cells


def tooltip_html(config, props):
    shares = props.get("budget_shares") or {}
    localities = props.get("source_localities") or []
    locality_text = ", ".join(localities) if localities else "Smoothed neighbor cell"
    return f"""
    <div style="font-family: Arial, sans-serif; font-size: 12px; line-height: 1.5;">
      <strong>{config["label"]}</strong><br/>
      Dominant: {props.get("dominant_budget_segment")} ({props.get("dominant_budget_share", 0):.0%})<br/>
      Affordable: {shares.get("Affordable", 0):.0%}<br/>
      Mid-Segment: {shares.get("Mid-Segment", 0):.0%}<br/>
      Premium: {shares.get("Premium", 0):.0%}<br/>
      Entropy: {props.get("budget_entropy", 0):.2f}<br/>
      Direct localities: {props.get("source_locality_count", 0)}<br/>
      Source examples: {locality_text}
    </div>
    """


def build_features(cells, geometries, config):
    features = []
    for cell, props in cells.items():
        if cell not in geometries:
            continue
        features.append(
            h3_cell_feature(
                cell,
                {
                    "dominant_budget_segment": props["dominant_budget_segment"],
                    "dominant_budget_share": props["dominant_budget_share"],
                    "budget_entropy": props["budget_entropy"],
                    "tooltip": tooltip_html(config, props),
                },
                geometries[cell],
            )
        )
    return features


def add_title(map_obj, title, subtitle):
    html = f"""
    <div style="
      position: fixed;
      top: 16px;
      left: 50px;
      z-index: 9999;
      background: rgba(255,255,255,0.94);
      padding: 10px 14px;
      border: 1px solid #d9d9d9;
      border-radius: 4px;
      font-family: Arial, sans-serif;
      max-width: 460px;
      box-shadow: 0 1px 5px rgba(0,0,0,0.15);
    ">
      <div style="font-size:15px;font-weight:700;">{title}</div>
      <div style="font-size:11px;line-height:1.4;margin-top:3px;color:#555;">{subtitle}</div>
    </div>
    """
    map_obj.get_root().html.add_child(folium.Element(html))


def create_budget_map(source, cells):
    config = SOURCE_CONFIGS[source]
    geometries = build_cell_geometries(cells)
    features = build_features(cells, geometries, config)
    map_obj = folium.Map(location=MAP_CENTER, zoom_start=11, tiles="CartoDB positron")
    add_title(map_obj, config["title"], config["description"])
    folium.GeoJson(
        {"type": "FeatureCollection", "features": features},
        name=config["label"],
        style_function=lambda feature: {
            "fillColor": BUDGET_SEGMENT_COLORS.get(
                feature["properties"].get("dominant_budget_segment"), "#969696"
            ),
            "color": "#404040",
            "weight": 0.25,
            "fillOpacity": 0.28 + 0.50 * feature["properties"].get("dominant_budget_share", 0),
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["tooltip"],
            aliases=[""],
            labels=False,
            sticky=True,
            style=("font-family: Arial, sans-serif; font-size: 12px;"),
        ),
    ).add_to(map_obj)

    legend = """
    <div style="
      position: fixed;
      bottom: 22px;
      right: 28px;
      z-index: 9999;
      background: rgba(255,255,255,0.92);
      padding: 10px 12px;
      border: 1px solid #d9d9d9;
      border-radius: 4px;
      font-family: Arial, sans-serif;
      font-size: 12px;
      line-height: 1.7;
    ">
      <strong>Budget segment</strong><br/>
      <span style="color:#2ca25f;">■</span> Affordable<br/>
      <span style="color:#fdae6b;">■</span> Mid-Segment<br/>
      <span style="color:#de2d26;">■</span> Premium
    </div>
    """
    map_obj.get_root().html.add_child(folium.Element(legend))
    output = MAPS_DIR / config["filename"]
    map_obj.save(output)
    return output


def render_overlap_viewer(layer_specs):
    specs_json = json.dumps(layer_specs, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Budget Segment Source Overlap Viewer</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    html, body {{ height: 100%; margin: 0; font-family: Arial, sans-serif; }}
    #map {{ height: 100%; width: 100%; }}
    .leaflet-overlay-pane svg path {{ mix-blend-mode: multiply; }}
    .panel {{
      position: fixed; top: 14px; left: 14px; z-index: 1000; width: 330px;
      background: rgba(255,255,255,0.95); border: 1px solid #d7d7d7;
      box-shadow: 0 2px 10px rgba(0,0,0,0.16); padding: 12px;
    }}
    h1 {{ font-size: 16px; margin: 0 0 8px 0; }}
    .meta {{ font-size: 11px; line-height: 1.45; color: #555; margin-bottom: 10px; }}
    .layer-row {{ display: grid; grid-template-columns: 18px 1fr 88px; gap: 6px; align-items: center; margin-top: 8px; font-size: 12px; }}
    .layer-row input[type="range"] {{ width: 88px; }}
    .legend {{
      position: fixed; right: 16px; bottom: 22px; z-index: 1000;
      background: rgba(255,255,255,0.94); border: 1px solid #d7d7d7;
      padding: 9px 10px; font-size: 12px; line-height: 1.6;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <aside class="panel">
    <h1>Budget Segment Source Overlap</h1>
    <div class="meta">
      Toggle original and ML-predicted budget segment H3 layers independently.
      Opacity sliders let you inspect agreement and disagreement between sources.
    </div>
    <div id="controls"></div>
  </aside>
  <div class="legend">
    <strong>Budget segment</strong><br>
    <span style="color:#2ca25f;">■</span> Affordable<br>
    <span style="color:#fdae6b;">■</span> Mid-Segment<br>
    <span style="color:#de2d26;">■</span> Premium
  </div>
  <script>
    const specs = {specs_json};
    const colors = {json.dumps(BUDGET_SEGMENT_COLORS)};
    const map = L.map('map', {{ preferCanvas: true }}).setView([12.9716, 77.5946], 11);
    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
      subdomains: 'abcd',
      maxZoom: 20
    }}).addTo(map);
    const layerObjects = new Map();
    const activeLayers = new Map();
    const opacities = new Map();

    function createLayer(spec) {{
      return L.geoJSON(spec.data, {{
        style: feature => {{
          const opacity = opacities.get(spec.id) ?? 0.55;
          return {{
            fillColor: colors[feature.properties.dominant_budget_segment] || '#969696',
            color: spec.stroke,
            weight: spec.id === 'original' ? 0.65 : 0.25,
            fillOpacity: opacity * (0.4 + 0.6 * feature.properties.dominant_budget_share)
          }};
        }},
        onEachFeature: (feature, layer) => layer.bindTooltip(feature.properties.tooltip, {{ sticky: true }})
      }});
    }}
    function setVisible(spec, visible) {{
      if (visible) {{
        if (!layerObjects.has(spec.id)) layerObjects.set(spec.id, createLayer(spec));
        const layer = layerObjects.get(spec.id);
        layer.addTo(map);
        activeLayers.set(spec.id, layer);
      }} else {{
        const layer = activeLayers.get(spec.id);
        if (layer) map.removeLayer(layer);
        activeLayers.delete(spec.id);
      }}
    }}
    function setOpacity(spec, opacity) {{
      opacities.set(spec.id, opacity);
      const layer = layerObjects.get(spec.id);
      if (!layer) return;
      layer.setStyle(feature => ({{
        fillColor: colors[feature.properties.dominant_budget_segment] || '#969696',
        color: spec.stroke,
        weight: spec.id === 'original' ? 0.65 : 0.25,
        fillOpacity: opacity * (0.4 + 0.6 * feature.properties.dominant_budget_share)
      }}));
    }}
    const controls = document.getElementById('controls');
    for (const spec of specs) {{
      opacities.set(spec.id, spec.id === 'original' ? 0.62 : 0.48);
      const row = document.createElement('label');
      row.className = 'layer-row';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = true;
      checkbox.addEventListener('change', () => setVisible(spec, checkbox.checked));
      const name = document.createElement('span');
      name.textContent = spec.name;
      const range = document.createElement('input');
      range.type = 'range';
      range.min = '0.1';
      range.max = '0.9';
      range.step = '0.05';
      range.value = String(opacities.get(spec.id));
      range.addEventListener('input', () => setOpacity(spec, Number(range.value)));
      row.appendChild(checkbox);
      row.appendChild(name);
      row.appendChild(range);
      controls.appendChild(row);
      setVisible(spec, true);
      setOpacity(spec, opacities.get(spec.id));
    }}
  </script>
</body>
</html>
"""


def create_overlap_viewer(source_cells):
    layer_specs = []
    for source, cells in source_cells.items():
        config = SOURCE_CONFIGS[source]
        geometries = build_cell_geometries(cells)
        layer_specs.append(
            {
                "id": source,
                "name": config["label"],
                "stroke": "#111111" if source == "original" else "#666666",
                "data": {"type": "FeatureCollection", "features": build_features(cells, geometries, config)},
            }
        )
    output = MAPS_DIR / "budget_segment_source_overlap_viewer.html"
    output.write_text(render_overlap_viewer(layer_specs))
    return output


def main():
    MAPS_DIR.mkdir(exist_ok=True)
    raw = load_localities()
    localities, coordinate_audit = parse_localities(raw)

    outputs = {}
    source_cells = {}
    source_counts = {}
    segment_counts = {}
    for source in SOURCE_CONFIGS:
        filtered, cells = build_source_budget_cells(localities, source)
        source_cells[source] = cells
        source_counts[source] = len(filtered)
        segment_counts[source] = dict(Counter(loc.get("budget_segment") for loc in filtered))
        output = create_budget_map(source, cells)
        outputs[source] = str(output)
        print(f"Generated {output}")

    viewer = create_overlap_viewer(source_cells)
    print(f"Generated {viewer}")

    audit = {
        "h3_resolution": H3_RESOLUTION,
        "source_records": coordinate_audit["total_records"],
        "included_records_after_coordinate_filter": coordinate_audit["included_records"],
        "outlier_records_excluded": coordinate_audit["outlier_records_excluded"],
        "source_counts": source_counts,
        "segment_counts": segment_counts,
        "h3_cell_counts": {source: len(cells) for source, cells in source_cells.items()},
        "outputs": {**outputs, "overlap_viewer": str(viewer)},
    }
    AUDIT_PATH.write_text(json.dumps(audit, indent=2))
    print(f"Wrote {AUDIT_PATH}")


if __name__ == "__main__":
    main()
