import json
import math
from pathlib import Path

import h3

from generate_h3_heatmaps import (
    ANALYSIS_METRICS,
    BUDGET_SHARE_METRICS,
    DATA_DIR,
    GETIS_ORD_K,
    H3_CELLS_PATH,
    KDE_BLUR,
    KDE_RADIUS,
    MAPS_DIR,
    SPATIAL_ANALYSIS_METRICS,
    calculate_getis_ord_gistar,
    metric_slug,
    percentile_bounds,
    normalized,
)


OUTPUT_PATH = MAPS_DIR / "h3_unified_viewer.html"


def load_h3_cells():
    with H3_CELLS_PATH.open("r") as f:
        feature_collection = json.load(f)

    cells = {}
    geometries = {}
    for feature in feature_collection.get("features", []):
        props = dict(feature.get("properties") or {})
        cell = props.get("h3_cell")
        if not cell:
            continue
        for key in ("budget_weights", "budget_shares"):
            value = props.get(key)
            if isinstance(value, str):
                try:
                    props[key] = json.loads(value)
                except json.JSONDecodeError:
                    props[key] = {}
        cells[cell] = props
        geometries[cell] = feature.get("geometry")
    return cells, geometries


def js_string(value):
    return json.dumps(value, ensure_ascii=False)


def build_metric_layers(cells, geometries):
    layers = []
    metric_configs = {
        **ANALYSIS_METRICS,
        **BUDGET_SHARE_METRICS,
    }

    for metric_key, config in metric_configs.items():
        values = [
            props.get(metric_key)
            for props in cells.values()
            if props.get(metric_key) is not None
        ]
        low, high = percentile_bounds(values)
        features = []
        for cell, props in cells.items():
            value = props.get(metric_key)
            if value is None or cell not in geometries:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": geometries[cell],
                    "properties": {
                        "h3_cell": cell,
                        "value": value,
                        "intensity": normalized(value, low, high),
                        "metric_label": config["label"],
                        "formatted": config["format"](value),
                        "source_locality_count": props.get("source_locality_count", 0),
                        "source_localities": props.get("source_localities", ""),
                    },
                }
            )
        layers.append(
            {
                "id": f"h3-{metric_slug(metric_key)}",
                "group": "H3 Choropleth",
                "name": config["label"],
                "type": "geojson",
                "palette": config["colors"],
                "low": low if low is not None else 0,
                "high": high if high is not None else 1,
                "data": {"type": "FeatureCollection", "features": features},
            }
        )
    return layers


def build_getis_layers(cells, geometries):
    layers = []
    for metric_key, config in SPATIAL_ANALYSIS_METRICS.items():
        results = calculate_getis_ord_gistar(cells, metric_key)
        if not results:
            continue
        z_values = [result["gi_z_score"] for result in results.values()]
        max_abs = max(1.96, min(4.0, max(abs(value) for value in z_values)))
        features = []
        for cell, gi_props in results.items():
            if cell not in geometries:
                continue
            props = cells[cell]
            z_score = gi_props["gi_z_score"]
            if z_score >= 1.96:
                cluster = "hot spot"
            elif z_score <= -1.96:
                cluster = "cold spot"
            else:
                cluster = "not significant"
            features.append(
                {
                    "type": "Feature",
                    "geometry": geometries[cell],
                    "properties": {
                        "h3_cell": cell,
                        "z": z_score,
                        "p": gi_props["gi_p_value"],
                        "cluster": cluster,
                        "metric_label": config["label"],
                        "metric_value": config["format"](gi_props["metric_value"]),
                        "source_locality_count": props.get("source_locality_count", 0),
                        "source_localities": props.get("source_localities", ""),
                    },
                }
            )
        layers.append(
            {
                "id": f"gi-{metric_slug(metric_key)}",
                "group": "Getis-Ord Gi*",
                "name": config["label"],
                "type": "gi",
                "low": -max_abs,
                "high": max_abs,
                "data": {"type": "FeatureCollection", "features": features},
            }
        )
    return layers


def build_kde_layers(cells):
    layers = []
    for metric_key, config in SPATIAL_ANALYSIS_METRICS.items():
        values = [
            props.get(metric_key)
            for props in cells.values()
            if props.get(metric_key) is not None
        ]
        low, high = percentile_bounds(values)
        points = []
        for cell, props in cells.items():
            value = props.get(metric_key)
            if value is None:
                continue
            intensity = normalized(value, low, high)
            if intensity <= 0:
                continue
            lat, lon = h3.cell_to_latlng(cell)
            points.append([lat, lon, intensity])
        layers.append(
            {
                "id": f"kde-{metric_slug(metric_key)}",
                "group": "KDE Point Heatmap",
                "name": config["label"],
                "type": "heat",
                "radius": KDE_RADIUS,
                "blur": KDE_BLUR,
                "data": points,
            }
        )
    return layers


def render_html(layers):
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Unified H3 Heatmap Viewer</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
  <style>
    html, body {{
      height: 100%;
      margin: 0;
      font-family: Arial, sans-serif;
      color: #222;
    }}
    #map {{
      height: 100%;
      width: 100%;
    }}
    .panel {{
      position: fixed;
      top: 14px;
      left: 14px;
      z-index: 1000;
      width: 340px;
      max-height: calc(100vh - 28px);
      overflow: auto;
      background: rgba(255, 255, 255, 0.95);
      border: 1px solid #d7d7d7;
      box-shadow: 0 2px 10px rgba(0,0,0,0.16);
      padding: 12px;
    }}
    .panel h1 {{
      font-size: 16px;
      margin: 0 0 8px 0;
      line-height: 1.25;
    }}
    .panel .meta {{
      font-size: 11px;
      line-height: 1.4;
      color: #555;
      margin-bottom: 10px;
    }}
    details {{
      border-top: 1px solid #e6e6e6;
      padding: 8px 0;
    }}
    summary {{
      cursor: pointer;
      font-size: 13px;
      font-weight: 700;
    }}
    .layer-row {{
      display: grid;
      grid-template-columns: 18px 1fr 82px;
      gap: 6px;
      align-items: center;
      margin-top: 7px;
      font-size: 12px;
    }}
    .layer-row input[type="range"] {{
      width: 82px;
    }}
    .actions {{
      display: flex;
      gap: 8px;
      margin: 10px 0 2px 0;
    }}
    .actions button {{
      border: 1px solid #bdbdbd;
      background: #fff;
      padding: 5px 8px;
      font-size: 12px;
      cursor: pointer;
    }}
    .legend {{
      position: fixed;
      right: 16px;
      bottom: 22px;
      z-index: 1000;
      background: rgba(255,255,255,0.94);
      border: 1px solid #d7d7d7;
      padding: 9px 10px;
      font-size: 12px;
      line-height: 1.5;
      min-width: 220px;
    }}
    .swatch {{
      display: inline-block;
      width: 11px;
      height: 11px;
      margin-right: 5px;
      vertical-align: -1px;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <aside class="panel">
    <h1>Unified H3 Heatmap Viewer</h1>
    <div class="meta">
      Toggle any combination of H3 choropleth, Getis-Ord Gi*, and KDE layers.
      Layer opacity sliders let you overlap maps without leaving this view.
      Gi* red cells are high-value clusters; blue cells are low-value clusters.
    </div>
    <div class="actions">
      <button id="clearLayers">Clear</button>
      <button id="fitBounds">Fit</button>
    </div>
    <div id="layerControls"></div>
  </aside>
  <div class="legend" id="legend">No layers selected.</div>
  <script>
    const layerSpecs = {js_string(layers)};
    const map = L.map('map', {{ preferCanvas: true }}).setView([12.9716, 77.5946], 11);
    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
      subdomains: 'abcd',
      maxZoom: 20
    }}).addTo(map);

    const activeLayers = new Map();
    const layerObjects = new Map();
    const layerOpacities = new Map();

    function hexToRgb(hex) {{
      const clean = hex.replace('#', '');
      return [
        parseInt(clean.substring(0, 2), 16),
        parseInt(clean.substring(2, 4), 16),
        parseInt(clean.substring(4, 6), 16)
      ];
    }}

    function rgbToHex(rgb) {{
      return '#' + rgb.map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('');
    }}

    function lerpColor(colors, t) {{
      if (!colors || colors.length === 0) return '#777777';
      if (colors.length === 1) return colors[0];
      const x = Math.max(0, Math.min(1, t)) * (colors.length - 1);
      const i = Math.floor(x);
      const j = Math.min(colors.length - 1, i + 1);
      const frac = x - i;
      const a = hexToRgb(colors[i]);
      const b = hexToRgb(colors[j]);
      return rgbToHex(a.map((v, idx) => v + (b[idx] - v) * frac));
    }}

    function giColor(z, low, high) {{
      const t = (z - low) / (high - low);
      return lerpColor(['#2166ac', '#f7f7f7', '#b2182b'], t);
    }}

    function featureTooltip(props, type) {{
      if (type === 'gi') {{
        return `<strong>Getis-Ord Gi*</strong><br>${{props.metric_label}}: ${{props.metric_value}}<br>Z-score: ${{props.z.toFixed(2)}}<br>p-value: ${{props.p.toFixed(4)}}<br>Cluster: ${{props.cluster}}<br>Direct localities: ${{props.source_locality_count}}<br>${{props.source_localities || 'Smoothed neighbor cell'}}`;
      }}
      return `<strong>H3 cell</strong><br>${{props.metric_label}}: ${{props.formatted}}<br>Direct localities: ${{props.source_locality_count}}<br>${{props.source_localities || 'Smoothed neighbor cell'}}`;
    }}

    function createLayer(spec) {{
      if (spec.type === 'heat') {{
        return L.heatLayer(spec.data, {{
          radius: spec.radius,
          blur: spec.blur,
          minOpacity: 0.18,
          maxZoom: 13
        }});
      }}
      return L.geoJSON(spec.data, {{
        style: feature => {{
          const opacity = layerOpacities.get(spec.id) ?? 0.65;
          if (spec.type === 'gi') {{
            const z = feature.properties.z;
            return {{
              fillColor: giColor(z, spec.low, spec.high),
              color: '#4a4a4a',
              weight: 0.25,
              fillOpacity: Math.abs(z) >= 1.65 ? opacity : opacity * 0.45
            }};
          }}
          return {{
            fillColor: lerpColor(spec.palette, feature.properties.intensity),
            color: '#4a4a4a',
            weight: 0.25,
            fillOpacity: opacity
          }};
        }},
        onEachFeature: (feature, layer) => {{
          layer.bindTooltip(featureTooltip(feature.properties, spec.type), {{ sticky: true }});
        }}
      }});
    }}

    function updateLegend() {{
      const selected = [...activeLayers.keys()].map(id => layerSpecs.find(spec => spec.id === id)).filter(Boolean);
      if (!selected.length) {{
        document.getElementById('legend').innerHTML = 'No layers selected.';
        return;
      }}
      document.getElementById('legend').innerHTML = selected.map(spec => {{
        if (spec.type === 'gi') {{
          return `<div><strong>${{spec.group}}: ${{spec.name}}</strong><br><span class="swatch" style="background:#2166ac"></span>Cold spot <span class="swatch" style="background:#f7f7f7;border:1px solid #ccc"></span>Neutral <span class="swatch" style="background:#b2182b"></span>Hot spot</div>`;
        }}
        if (spec.type === 'heat') {{
          return `<div><strong>${{spec.group}}: ${{spec.name}}</strong><br>KDE radius ${{spec.radius}}, blur ${{spec.blur}}</div>`;
        }}
        return `<div><strong>${{spec.group}}: ${{spec.name}}</strong><br><span class="swatch" style="background:${{spec.palette[0]}}"></span>Low <span class="swatch" style="background:${{spec.palette[Math.floor(spec.palette.length / 2)]}}"></span>Mid <span class="swatch" style="background:${{spec.palette[spec.palette.length - 1]}}"></span>High</div>`;
      }}).join('<hr style="border:0;border-top:1px solid #ddd;margin:7px 0;">');
    }}

    function setLayerVisible(spec, visible) {{
      if (visible) {{
        if (!layerObjects.has(spec.id)) {{
          layerObjects.set(spec.id, createLayer(spec));
        }}
        const layer = layerObjects.get(spec.id);
        layer.addTo(map);
        activeLayers.set(spec.id, layer);
      }} else {{
        const layer = activeLayers.get(spec.id);
        if (layer) {{
          map.removeLayer(layer);
          activeLayers.delete(spec.id);
        }}
      }}
      updateLegend();
    }}

    function setLayerOpacity(spec, opacity) {{
      layerOpacities.set(spec.id, opacity);
      const layer = layerObjects.get(spec.id);
      if (!layer) return;
      if (spec.type === 'heat') {{
        if (layer._canvas) {{
          layer._canvas.style.opacity = opacity;
        }}
        return;
      }}
      layer.setStyle(feature => {{
        if (spec.type === 'gi') {{
          const z = feature.properties.z;
          return {{
            fillColor: giColor(z, spec.low, spec.high),
            color: '#4a4a4a',
            weight: 0.25,
            fillOpacity: Math.abs(z) >= 1.65 ? opacity : opacity * 0.45
          }};
        }}
        return {{
          fillColor: lerpColor(spec.palette, feature.properties.intensity),
          color: '#4a4a4a',
          weight: 0.25,
          fillOpacity: opacity
        }};
      }});
    }}

    function buildControls() {{
      const byGroup = new Map();
      for (const spec of layerSpecs) {{
        if (!byGroup.has(spec.group)) byGroup.set(spec.group, []);
        byGroup.get(spec.group).push(spec);
      }}
      const container = document.getElementById('layerControls');
      for (const [group, specs] of byGroup.entries()) {{
        const details = document.createElement('details');
        details.open = group === 'H3 Choropleth';
        const summary = document.createElement('summary');
        summary.textContent = group;
        details.appendChild(summary);

        for (const spec of specs) {{
          layerOpacities.set(spec.id, spec.type === 'heat' ? 0.72 : 0.62);
          const row = document.createElement('label');
          row.className = 'layer-row';
          const checkbox = document.createElement('input');
          checkbox.type = 'checkbox';
          checkbox.addEventListener('change', () => setLayerVisible(spec, checkbox.checked));
          const name = document.createElement('span');
          name.textContent = spec.name;
          const range = document.createElement('input');
          range.type = 'range';
          range.min = '0.1';
          range.max = '1';
          range.step = '0.05';
          range.value = String(layerOpacities.get(spec.id));
          range.title = 'Opacity';
          range.addEventListener('input', () => setLayerOpacity(spec, Number(range.value)));
          row.appendChild(checkbox);
          row.appendChild(name);
          row.appendChild(range);
          details.appendChild(row);
        }}
        container.appendChild(details);
      }}
    }}

    document.getElementById('clearLayers').addEventListener('click', () => {{
      document.querySelectorAll('.layer-row input[type="checkbox"]').forEach(input => {{
        input.checked = false;
      }});
      for (const layer of activeLayers.values()) map.removeLayer(layer);
      activeLayers.clear();
      updateLegend();
    }});

    document.getElementById('fitBounds').addEventListener('click', () => {{
      let bounds = null;
      for (const layer of activeLayers.values()) {{
        if (typeof layer.getBounds === 'function') {{
          const layerBounds = layer.getBounds();
          if (layerBounds.isValid()) bounds = bounds ? bounds.extend(layerBounds) : layerBounds;
        }}
      }}
      if (bounds) map.fitBounds(bounds.pad(0.08));
    }});

    buildControls();
  </script>
</body>
</html>
"""
    return html


def main():
    MAPS_DIR.mkdir(exist_ok=True)
    cells, geometries = load_h3_cells()
    if not cells:
        raise RuntimeError(f"No H3 cells found in {H3_CELLS_PATH}. Run generate_h3_heatmaps.py first.")

    layers = []
    layers.extend(build_metric_layers(cells, geometries))
    layers.extend(build_getis_layers(cells, geometries))
    layers.extend(build_kde_layers(cells))

    OUTPUT_PATH.write_text(render_html(layers))
    audit_path = DATA_DIR / "audits" / "h3_unified_viewer_audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "viewer": str(OUTPUT_PATH),
                "layer_count": len(layers),
                "groups": sorted({layer["group"] for layer in layers}),
                "getis_ord_neighbor_k": GETIS_ORD_K,
                "kde_radius": KDE_RADIUS,
                "kde_blur": KDE_BLUR,
                "source_h3_cells": len(cells),
            },
            indent=2,
        )
    )
    print(f"Generated {OUTPUT_PATH}")
    print(f"Wrote {audit_path}")


if __name__ == "__main__":
    main()
