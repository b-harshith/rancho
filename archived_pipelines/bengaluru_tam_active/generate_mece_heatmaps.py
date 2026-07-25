import json
import math
from collections import defaultdict
from pathlib import Path

import branca.colormap as cm
import folium
import h3

from generate_h3_heatmaps import (
    DATA_DIR,
    GETIS_ORD_K,
    H3_RESOLUTION,
    KDE_BLUR,
    KDE_RADIUS,
    MAPS_DIR,
    MAP_CENTER,
    build_cell_geometries,
    calculate_getis_ord_gistar,
    h3_cell_feature,
    load_localities,
    metric_slug,
    parse_localities,
    percentile_bounds,
    smoothing_decay,
)


MAPS_DIR = Path("maps") / "mece"
AUDIT_PATH = DATA_DIR / "audits" / "mece_heatmap_audit.json"


MECE_METRICS = {
    "price_level": {
        "title": "MECE 1 - Price Level",
        "filename": "mece_price_level.html",
        "question": "Where is the market expensive?",
        "source": "market_price_per_sqft / price_per_sqft",
        "label": "Price Level",
        "value_key": "price_sqft",
        "mode": "weighted_average",
        "weight_key": "weight",
        "format": lambda v: f"Rs {v:,.0f} / sqft",
        "legend": "Weighted price per sqft",
        "colors": ["#f7fbff", "#6baed6", "#08519c"],
    },
    "investment_yield": {
        "title": "MECE 2 - Investment Yield",
        "filename": "mece_investment_yield.html",
        "question": "Where does property generate stronger rental return?",
        "source": "rental_yield",
        "label": "Rental Yield",
        "value_key": "rental_yield",
        "mode": "weighted_average",
        "weight_key": "weight",
        "format": lambda v: f"{v:.2f}%",
        "legend": "Weighted rental yield",
        "colors": ["#fff7bc", "#fec44f", "#d95f0e"],
    },
    "market_activity": {
        "title": "MECE 3 - Market Activity",
        "filename": "mece_market_activity.html",
        "question": "Where is market depth/liquidity strongest?",
        "source": "rent inventory + sale inventory + reviews",
        "label": "Activity",
        "value_key": "activity_score",
        "mode": "sum",
        "transform": "log1p",
        "format": lambda v: f"{v:,.0f}",
        "legend": "Activity score, log-scaled for color",
        "colors": ["#fff5eb", "#fd8d3c", "#a63603"],
    },
    "large_home_share": {
        "title": "MECE 4 - Large Home Inventory Share",
        "filename": "mece_large_home_share.html",
        "question": "Where is the housing stock more 3BHK/4BHK-heavy?",
        "source": "3BHK + 4BHK inventory share of total rent/sale inventory",
        "label": "3/4 BHK Share",
        "value_key": "large_home_share",
        "mode": "weighted_average",
        "weight_key": "inventory_total",
        "format": lambda v: f"{v:.1%}",
        "legend": "3/4 BHK share",
        "colors": ["#f2f0f7", "#9e9ac8", "#54278f"],
    },
    "income_share_proxy": {
        "title": "MECE 5 - Income Share Proxy",
        "filename": "mece_income_share_proxy.html",
        "question": "Where is the high-income-share proxy strongest?",
        "source": "income_analytics.distribution.high; derived label, not raw ground truth",
        "label": "High Income Share",
        "value_key": "high_income",
        "mode": "weighted_average",
        "weight_key": "weight",
        "format": lambda v: f"{v:.1f}%",
        "legend": "High income share proxy",
        "colors": ["#f7fcf5", "#74c476", "#006d2c"],
    },
}


def enrich_localities(localities):
    enriched = []
    for loc in localities:
        inventory_total = loc.get("inventory_total") or 0.0
        large_home_share = (
            loc.get("bhk_34_count", 0.0) / inventory_total
            if inventory_total > 0
            else None
        )
        row = dict(loc)
        row["large_home_share"] = large_home_share
        enriched.append(row)
    return enriched


def compute_mece_cells(localities):
    accumulators = {
        key: defaultdict(lambda: [0.0, 0.0])
        for key, config in MECE_METRICS.items()
        if config["mode"] == "weighted_average"
    }
    sums = {
        key: defaultdict(float)
        for key, config in MECE_METRICS.items()
        if config["mode"] == "sum"
    }
    source_localities = defaultdict(list)
    source_counts = defaultdict(int)

    for loc in localities:
        source_counts[loc["h3_cell"]] += 1
        if len(source_localities[loc["h3_cell"]]) < 8:
            source_localities[loc["h3_cell"]].append(loc["name"])

        for neighbor in h3.grid_disk(loc["h3_cell"], 1):
            try:
                distance = h3.grid_distance(loc["h3_cell"], neighbor)
            except Exception:
                distance = 1
            decay = smoothing_decay(distance)

            for metric_key, config in MECE_METRICS.items():
                value = loc.get(config["value_key"])
                if value is None:
                    continue
                if config["mode"] == "sum":
                    sums[metric_key][neighbor] += value * decay
                    continue

                raw_weight = loc.get(config.get("weight_key", "weight")) or loc.get("weight") or 1.0
                if raw_weight <= 0:
                    raw_weight = 1.0
                weight = raw_weight * decay
                accumulators[metric_key][neighbor][0] += value * weight
                accumulators[metric_key][neighbor][1] += weight

    all_cells = set()
    for metric_acc in accumulators.values():
        all_cells |= set(metric_acc)
    for metric_sum in sums.values():
        all_cells |= set(metric_sum)

    cells = {}
    for cell in all_cells:
        props = {
            "source_locality_count": source_counts.get(cell, 0),
            "source_localities": source_localities.get(cell, []),
        }
        for metric_key in accumulators:
            numerator, denominator = accumulators[metric_key].get(cell, [0.0, 0.0])
            props[metric_key] = numerator / denominator if denominator > 0 else None
        for metric_key in sums:
            props[metric_key] = sums[metric_key].get(cell, 0.0)
        cells[cell] = props

    return cells


def display_value(config, value):
    return math.log1p(value) if config.get("transform") == "log1p" else value


def make_tooltip(config, props, value):
    localities = props.get("source_localities") or []
    locality_text = ", ".join(localities) if localities else "Smoothed neighbor cell"
    return f"""
    <div style="font-family: Arial, sans-serif; font-size: 12px; line-height: 1.5;">
      <strong>{config["label"]}</strong><br/>
      Value: {config["format"](value)}<br/>
      Question: {config["question"]}<br/>
      Direct localities: {props.get("source_locality_count", 0)}<br/>
      Source examples: {locality_text}
    </div>
    """


def build_metric_features(cells, cell_geometries, metric_key, config):
    display_values = [
        display_value(config, props.get(metric_key))
        for cell, props in cells.items()
        if cell in cell_geometries and props.get(metric_key) is not None
    ]
    low, high = percentile_bounds(display_values)
    features = []
    for cell, props in cells.items():
        if cell not in cell_geometries:
            continue
        value = props.get(metric_key)
        if value is None:
            continue
        shown_value = display_value(config, value)
        intensity = 1.0 if high == low else max(0.0, min(1.0, (shown_value - low) / (high - low)))
        features.append(
            h3_cell_feature(
                cell,
                {
                    "value": value,
                    "display_value": shown_value,
                    "intensity": intensity,
                    "tooltip": make_tooltip(config, props, value),
                },
                cell_geometries[cell],
            )
        )
    return features, low, high


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


def create_single_map(cells, cell_geometries, metric_key, config):
    features, low, high = build_metric_features(cells, cell_geometries, metric_key, config)
    color_map = cm.LinearColormap(
        colors=config["colors"],
        vmin=low if low is not None else 0,
        vmax=high if high is not None else 1,
        caption=config["legend"],
    )
    map_obj = folium.Map(location=MAP_CENTER, zoom_start=11, tiles="CartoDB positron")
    add_title(map_obj, config["title"], config["question"])
    folium.GeoJson(
        {"type": "FeatureCollection", "features": features},
        name=config["label"],
        style_function=lambda feature: {
            "fillColor": color_map(feature["properties"]["display_value"]),
            "color": "#444",
            "weight": 0.25,
            "fillOpacity": 0.68,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["tooltip"],
            aliases=[""],
            labels=False,
            sticky=True,
            style=("font-family: Arial, sans-serif; font-size: 12px;"),
        ),
    ).add_to(map_obj)
    color_map.add_to(map_obj)
    folium.LayerControl(collapsed=True).add_to(map_obj)
    output = MAPS_DIR / config["filename"]
    map_obj.save(output)
    return output


def build_gi_layer_specs(cells, cell_geometries):
    layers = []
    for metric_key, config in MECE_METRICS.items():
        results = calculate_getis_ord_gistar(cells, metric_key)
        if not results:
            continue
        z_values = [result["gi_z_score"] for result in results.values()]
        max_abs = max(1.96, min(4.0, max(abs(value) for value in z_values)))
        features = []
        for cell, gi_props in results.items():
            if cell not in cell_geometries:
                continue
            props = cells[cell]
            z_score = gi_props["gi_z_score"]
            if z_score >= 1.96:
                cluster = "Hot spot"
            elif z_score <= -1.96:
                cluster = "Cold spot"
            else:
                cluster = "Not significant"
            features.append(
                h3_cell_feature(
                    cell,
                    {
                        "z": z_score,
                        "p": gi_props["gi_p_value"],
                        "cluster": cluster,
                        "metric_label": config["label"],
                        "metric_value": config["format"](gi_props["metric_value"]),
                        "source_locality_count": props.get("source_locality_count", 0),
                        "source_localities": ", ".join(props.get("source_localities") or []),
                        "tooltip": (
                            f"<strong>Getis-Ord Gi*</strong><br/>"
                            f"{config['label']}: {config['format'](gi_props['metric_value'])}<br/>"
                            f"Z-score: {z_score:.2f}<br/>"
                            f"p-value: {gi_props['gi_p_value']:.4f}<br/>"
                            f"Cluster: {cluster}<br/>"
                            f"Direct localities: {props.get('source_locality_count', 0)}"
                        ),
                    },
                    cell_geometries[cell],
                )
            )
        layers.append(
            {
                "id": f"gi_{metric_key}",
                "group": "Getis-Ord Gi*",
                "name": f"Gi* - {config['title']}",
                "shortName": f"Gi* {config['label']}",
                "question": f"Where are statistically significant hot/cold clusters for {config['label']}?",
                "source": config["source"],
                "type": "gi",
                "low": -max_abs,
                "high": max_abs,
                "data": {"type": "FeatureCollection", "features": features},
            }
        )
    return layers


def build_kde_layer_specs(cells):
    layers = []
    for metric_key, config in MECE_METRICS.items():
        values = [
            props.get(metric_key)
            for props in cells.values()
            if props.get(metric_key) is not None
        ]
        low, high = percentile_bounds([
            display_value(config, value)
            for value in values
        ])
        points = []
        for cell, props in cells.items():
            value = props.get(metric_key)
            if value is None:
                continue
            shown_value = display_value(config, value)
            intensity = 1.0 if high == low else max(0.0, min(1.0, (shown_value - low) / (high - low)))
            if intensity <= 0:
                continue
            lat, lon = h3.cell_to_latlng(cell)
            points.append([lat, lon, intensity])
        layers.append(
            {
                "id": f"kde_{metric_key}",
                "group": "KDE Point Heatmap",
                "name": f"KDE - {config['title']}",
                "shortName": f"KDE {config['label']}",
                "question": f"Where is the smoothed point-density surface strongest for {config['label']}?",
                "source": config["source"],
                "type": "heat",
                "radius": KDE_RADIUS,
                "blur": KDE_BLUR,
                "data": points,
            }
        )
    return layers


def create_unified_map(cells, cell_geometries):
    output = MAPS_DIR / "mece_unified_viewer.html"
    layer_specs = []
    for metric_key, config in MECE_METRICS.items():
        features, low, high = build_metric_features(cells, cell_geometries, metric_key, config)
        layer_specs.append({
            "id": metric_key,
            "group": "MECE Core",
            "name": config["title"],
            "shortName": config["label"],
            "question": config["question"],
            "source": config["source"],
            "type": "choropleth",
            "palette": config["colors"],
            "low": low if low is not None else 0,
            "high": high if high is not None else 1,
            "data": {"type": "FeatureCollection", "features": features},
        })

    layer_specs.extend(build_gi_layer_specs(cells, cell_geometries))
    layer_specs.extend(build_kde_layer_specs(cells))

    inference_presets = [
        {
            "id": "premium_residential_pockets",
            "title": "Premium Residential Pockets",
            "question": "Where do expensive pricing, large-home stock, and high-income proxy reinforce each other?",
            "answer": "Look for areas where price, large-home share, and income proxy overlap strongly. These are the strongest premium-residential candidates.",
            "layers": {"price_level": 0.48, "large_home_share": 0.46, "income_share_proxy": 0.44},
        },
        {
            "id": "rental_investment_zones",
            "title": "Rental Investment Zones",
            "question": "Where does rental yield coincide with enough market activity to make the signal more investable?",
            "answer": "Yield without activity can be thin-market noise. Look for investment-yield and activity overlap.",
            "layers": {"investment_yield": 0.58, "market_activity": 0.42},
        },
        {
            "id": "liquid_premium_markets",
            "title": "Liquid Premium Markets",
            "question": "Where are premium prices supported by deeper market liquidity?",
            "answer": "Price plus activity overlap points to established premium markets rather than isolated expensive pockets.",
            "layers": {"price_level": 0.52, "market_activity": 0.42, "income_share_proxy": 0.32},
        },
        {
            "id": "family_upgrade_corridors",
            "title": "Family Upgrade Corridors",
            "question": "Where do larger homes, activity, and income proxy point to family-upgrade demand?",
            "answer": "Large-home share overlapping with activity and income can indicate family-oriented housing demand.",
            "layers": {"large_home_share": 0.54, "market_activity": 0.36, "income_share_proxy": 0.42},
        },
        {
            "id": "early_premium_watchlist",
            "title": "Early Premium Watchlist",
            "question": "Where does income proxy appear before the strongest price/activity confirmation?",
            "answer": "Start with income and large-home share, then manually add price or activity to see whether the market has already priced in the signal.",
            "layers": {"income_share_proxy": 0.54, "large_home_share": 0.42},
        },
    ]

    output.write_text(render_inference_viewer(layer_specs, inference_presets))
    return output


def render_inference_viewer(layer_specs, inference_presets):
    layer_specs_json = json.dumps(layer_specs, ensure_ascii=False)
    inference_presets_json = json.dumps(inference_presets, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>MECE Inference Heatmap Viewer</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
  <style>
    html, body {{ height: 100%; margin: 0; font-family: Arial, sans-serif; color: #222; }}
    #map {{ height: 100%; width: 100%; }}
    .leaflet-overlay-pane svg path {{ mix-blend-mode: multiply; }}
    .panel {{
      position: fixed; top: 14px; left: 14px; z-index: 1000; width: 390px;
      max-height: calc(100vh - 28px); overflow: auto; background: rgba(255,255,255,0.95);
      border: 1px solid #d7d7d7; box-shadow: 0 2px 10px rgba(0,0,0,0.16); padding: 12px;
    }}
    h1 {{ font-size: 16px; margin: 0 0 8px 0; line-height: 1.25; }}
    .meta, .answer {{ font-size: 11px; line-height: 1.45; color: #555; }}
    .preset-grid {{ display: grid; gap: 6px; margin: 10px 0; }}
    button {{
      border: 1px solid #bdbdbd; background: #fff; padding: 6px 8px;
      font-size: 12px; cursor: pointer; text-align: left;
    }}
    button:hover {{ background: #f4f4f4; }}
    .preset-active {{ border-color: #333; background: #efefef; font-weight: 700; }}
    details {{ border-top: 1px solid #e4e4e4; padding-top: 8px; margin-top: 8px; }}
    summary {{ cursor: pointer; font-size: 13px; font-weight: 700; }}
    .layer-row {{
      display: grid; grid-template-columns: 18px 1fr 86px; align-items: center;
      gap: 6px; margin-top: 7px; font-size: 12px;
    }}
    .layer-row input[type="range"] {{ width: 86px; }}
    .section-title {{
      border-top: 1px solid #e4e4e4; padding-top: 9px; margin-top: 9px;
      font-size: 13px; font-weight: 700;
    }}
    .actions {{ display: flex; gap: 8px; margin-top: 8px; }}
    .actions button {{ text-align: center; }}
    .legend {{
      position: fixed; right: 16px; bottom: 22px; z-index: 1000;
      background: rgba(255,255,255,0.94); border: 1px solid #d7d7d7;
      padding: 9px 10px; font-size: 12px; line-height: 1.5; min-width: 230px; max-width: 330px;
    }}
    .swatch {{ display: inline-block; width: 11px; height: 11px; margin-right: 5px; vertical-align: -1px; }}
  </style>
</head>
<body>
  <div id="map"></div>
  <aside class="panel">
    <h1>MECE Inference Heatmap Viewer</h1>
    <div class="meta">Pick an inference question to automatically overlap relevant MECE layers. You can fine-tune layers and opacity manually.</div>
    <div class="section-title">Inference presets</div>
    <div class="preset-grid" id="presetGrid"></div>
    <div class="section-title">Active inference</div>
    <div class="answer" id="activeInference">No preset selected.</div>
    <div class="actions">
      <button id="clearLayers">Clear</button>
      <button id="fitBounds">Fit active layers</button>
    </div>
    <div class="section-title">Manual layers</div>
    <div id="layerControls"></div>
  </aside>
  <div class="legend" id="legend">No layers selected.</div>
  <script>
    const layerSpecs = {layer_specs_json};
    const inferencePresets = {inference_presets_json};
    const map = L.map('map', {{ preferCanvas: true }}).setView([12.9716, 77.5946], 11);
    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
      subdomains: 'abcd',
      maxZoom: 20
    }}).addTo(map);

    const layerObjects = new Map();
    const activeLayers = new Map();
    const opacities = new Map();

    function hexToRgb(hex) {{
      const clean = hex.replace('#', '');
      return [parseInt(clean.substring(0, 2), 16), parseInt(clean.substring(2, 4), 16), parseInt(clean.substring(4, 6), 16)];
    }}
    function rgbToHex(rgb) {{
      return '#' + rgb.map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('');
    }}
    function lerpColor(colors, t) {{
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
          const opacity = opacities.get(spec.id) ?? 0.55;
          if (spec.type === 'gi') {{
            const z = feature.properties.z;
            return {{
              fillColor: giColor(z, spec.low, spec.high),
              color: '#4a4a4a',
              weight: 0.24,
              fillOpacity: Math.abs(z) >= 1.65 ? opacity : opacity * 0.45
            }};
          }}
          return {{
            fillColor: lerpColor(spec.palette, feature.properties.intensity),
            color: '#4a4a4a',
            weight: 0.24,
            fillOpacity: opacity
          }};
        }},
        onEachFeature: (feature, layer) => layer.bindTooltip(feature.properties.tooltip, {{ sticky: true }})
      }});
    }}
    function setLayerOpacity(spec, opacity) {{
      opacities.set(spec.id, opacity);
      const layer = layerObjects.get(spec.id);
      if (!layer) return;
      if (spec.type === 'heat') {{
        if (layer._canvas) layer._canvas.style.opacity = opacity;
        return;
      }}
      layer.setStyle(feature => ({{
        fillColor: spec.type === 'gi' ? giColor(feature.properties.z, spec.low, spec.high) : lerpColor(spec.palette, feature.properties.intensity),
        color: '#4a4a4a',
        weight: 0.24,
        fillOpacity: spec.type === 'gi' && Math.abs(feature.properties.z) < 1.65 ? opacity * 0.45 : opacity
      }}));
    }}
    function setLayerVisible(spec, visible) {{
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
      updateLegend();
    }}
    function updateLegend() {{
      const specs = [...activeLayers.keys()].map(id => layerSpecs.find(spec => spec.id === id)).filter(Boolean);
      if (!specs.length) {{
        document.getElementById('legend').innerHTML = 'No layers selected.';
        return;
      }}
      document.getElementById('legend').innerHTML = specs.map(spec => `
        <div>
          <strong>${{spec.shortName}}</strong><br>
          ${{spec.type === 'gi'
            ? '<span class="swatch" style="background:#2166ac"></span>Cold <span class="swatch" style="background:#f7f7f7;border:1px solid #ccc"></span>Neutral <span class="swatch" style="background:#b2182b"></span>Hot'
            : spec.type === 'heat'
              ? `KDE radius ${{spec.radius}}, blur ${{spec.blur}}`
              : `<span class="swatch" style="background:${{spec.palette[0]}}"></span>Low <span class="swatch" style="background:${{spec.palette[Math.floor(spec.palette.length / 2)]}}"></span>Mid <span class="swatch" style="background:${{spec.palette[spec.palette.length - 1]}}"></span>High`
          }}
        </div>
      `).join('<hr style="border:0;border-top:1px solid #ddd;margin:7px 0;">');
    }}
    function syncControls() {{
      for (const spec of layerSpecs) {{
        const checkbox = document.querySelector(`[data-layer-check="${{spec.id}}"]`);
        const range = document.querySelector(`[data-layer-range="${{spec.id}}"]`);
        if (checkbox) checkbox.checked = activeLayers.has(spec.id);
        if (range) range.value = String(opacities.get(spec.id) ?? 0.55);
      }}
    }}
    function clearAll() {{
      for (const layer of activeLayers.values()) map.removeLayer(layer);
      activeLayers.clear();
      document.querySelectorAll('.preset-grid button').forEach(button => button.classList.remove('preset-active'));
      document.getElementById('activeInference').innerHTML = 'No preset selected.';
      syncControls();
      updateLegend();
    }}
    function applyPreset(preset) {{
      clearAll();
      for (const [layerId, opacity] of Object.entries(preset.layers)) {{
        const spec = layerSpecs.find(item => item.id === layerId);
        if (!spec) continue;
        opacities.set(layerId, opacity);
        setLayerVisible(spec, true);
        setLayerOpacity(spec, opacity);
      }}
      document.querySelector(`[data-preset="${{preset.id}}"]`)?.classList.add('preset-active');
      document.getElementById('activeInference').innerHTML = `<strong>${{preset.title}}</strong><br><em>${{preset.question}}</em><br>${{preset.answer}}`;
      syncControls();
      updateLegend();
    }}
    function buildPresetControls() {{
      const grid = document.getElementById('presetGrid');
      for (const preset of inferencePresets) {{
        const button = document.createElement('button');
        button.dataset.preset = preset.id;
        button.innerHTML = `<strong>${{preset.title}}</strong><br><span style="font-size:11px;color:#555;">${{preset.question}}</span>`;
        button.addEventListener('click', () => applyPreset(preset));
        grid.appendChild(button);
      }}
    }}
    function buildLayerControls() {{
      const container = document.getElementById('layerControls');
      const groups = [...new Set(layerSpecs.map(spec => spec.group || 'Layers'))];
      for (const group of groups) {{
        const details = document.createElement('details');
        details.open = group === 'MECE Core';
        const summary = document.createElement('summary');
        summary.textContent = group;
        details.appendChild(summary);
        for (const spec of layerSpecs.filter(item => (item.group || 'Layers') === group)) {{
          opacities.set(spec.id, spec.type === 'heat' ? 0.72 : 0.55);
          const row = document.createElement('label');
          row.className = 'layer-row';
          const checkbox = document.createElement('input');
          checkbox.type = 'checkbox';
          checkbox.dataset.layerCheck = spec.id;
          checkbox.addEventListener('change', () => {{
            setLayerVisible(spec, checkbox.checked);
            document.querySelectorAll('.preset-grid button').forEach(button => button.classList.remove('preset-active'));
          }});
          const name = document.createElement('span');
          name.textContent = spec.shortName;
          const range = document.createElement('input');
          range.type = 'range';
          range.min = '0.1';
          range.max = '0.9';
          range.step = '0.05';
          range.value = String(opacities.get(spec.id));
          range.dataset.layerRange = spec.id;
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
    document.getElementById('clearLayers').addEventListener('click', clearAll);
    document.getElementById('fitBounds').addEventListener('click', () => {{
      let bounds = null;
      for (const layer of activeLayers.values()) {{
        if (typeof layer.getBounds !== 'function') continue;
        const layerBounds = layer.getBounds();
        if (layerBounds.isValid()) bounds = bounds ? bounds.extend(layerBounds) : layerBounds;
      }}
      if (bounds) map.fitBounds(bounds.pad(0.08));
    }});
    buildPresetControls();
    buildLayerControls();
  </script>
</body>
</html>
"""


def main():
    MAPS_DIR.mkdir(exist_ok=True)
    raw_localities = load_localities()
    localities, coordinate_audit = parse_localities(raw_localities)
    localities = enrich_localities(localities)
    cells = compute_mece_cells(localities)
    cell_geometries = build_cell_geometries(cells)

    outputs = []
    for metric_key, config in MECE_METRICS.items():
        output = create_single_map(cells, cell_geometries, metric_key, config)
        outputs.append(str(output))
        print(f"Generated {output}")

    unified_output = create_unified_map(cells, cell_geometries)
    outputs.append(str(unified_output))
    print(f"Generated {unified_output}")

    audit = {
        "definition": "MECE heatmap set: one map per non-overlapping analytical question.",
        "excluded_from_core_mece": {
            "budget_segment": "Excluded because it overlaps with price/income and is mostly predicted in the source data.",
            "getis_ord_gi_star": "Excluded from core MECE because it is a statistical view of the same measures, not a separate signal.",
            "kde": "Excluded from core MECE because it is a rendering method for the same measures, not a separate signal.",
            "premium_lens_score": "Excluded because it combines price and large-home share, violating mutual exclusivity.",
        },
        "h3_resolution": H3_RESOLUTION,
        "source_records": coordinate_audit["total_records"],
        "included_records": coordinate_audit["included_records"],
        "outlier_records_excluded": coordinate_audit["outlier_records_excluded"],
        "h3_cells": len(cells),
        "maps": outputs,
        "metrics": {
            key: {
                "title": config["title"],
                "question": config["question"],
                "source": config["source"],
            }
            for key, config in MECE_METRICS.items()
        },
    }
    AUDIT_PATH.write_text(json.dumps(audit, indent=2))
    print(f"Wrote {AUDIT_PATH}")


if __name__ == "__main__":
    main()
