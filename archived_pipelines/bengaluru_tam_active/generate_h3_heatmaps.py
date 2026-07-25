import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import branca.colormap as cm
import folium
import h3
from folium.plugins import HeatMap
from shapely.geometry import Polygon, mapping


DATA_DIR = Path("DATA")
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
AUDIT_DIR = DATA_DIR / "audits"
MAPS_DIR = Path("maps") / "h3"
LOCALITIES_PATH = RAW_DATA_DIR / "bangalore_localities_enriched.json"
H3_CELLS_PATH = PROCESSED_DATA_DIR / "h3_heatmap_cells.geojson"
COORDINATE_AUDIT_PATH = AUDIT_DIR / "h3_coordinate_audit.json"
SPATIAL_ANALYSIS_AUDIT_PATH = AUDIT_DIR / "h3_spatial_analysis_audit.json"

H3_RESOLUTION = 8
SMOOTHING_K = 1
GETIS_ORD_K = 1
KDE_RADIUS = 24
KDE_BLUR = 18
MAP_CENTER = [12.9716, 77.5946]

# A broad Bengaluru metro envelope. It keeps peripheral places such as
# Devanahalli, Hoskote, Doddaballapur, Whitefield, and Attibele while excluding
# obvious geocoding failures that would blow up the map extent.
BENGALURU_METRO_BOUNDS = {
    "min_lat": 12.65,
    "max_lat": 13.40,
    "min_lon": 77.20,
    "max_lon": 78.05,
}

CONTINUOUS_METRICS = {
    "price_sqft": {
        "title": "H3 Price Per SqFt Heatmap",
        "filename": "h3_price_heatmap.html",
        "label": "Price/SqFt",
        "legend": "Price per sqft",
        "format": lambda v: f"Rs {v:,.0f} / sqft",
        "colors": ["#f7fbff", "#6baed6", "#08519c"],
    },
    "high_income": {
        "title": "H3 High Income Share Heatmap",
        "filename": "h3_income_heatmap.html",
        "label": "High Income %",
        "legend": "High income share",
        "format": lambda v: f"{v:.1f}%",
        "colors": ["#f7fcf5", "#74c476", "#006d2c"],
    },
    "rental_yield": {
        "title": "H3 Rental Yield Heatmap",
        "filename": "h3_yield_heatmap.html",
        "label": "Rental Yield",
        "legend": "Rental yield",
        "format": lambda v: f"{v:.2f}%",
        "colors": ["#fff7bc", "#fec44f", "#d95f0e"],
    },
}

ACTIVITY_CONFIG = {
    "title": "H3 Real Estate Activity Heatmap",
    "filename": "h3_activity_heatmap.html",
    "label": "Activity Score",
    "legend": "Activity score",
    "format": lambda v: f"{v:,.0f}",
    "colors": ["#fff5eb", "#fd8d3c", "#a63603"],
}

PREMIUM_LENS_CONFIG = {
    "title": "H3 Premium 3/4 BHK Lens Heatmap",
    "filename": "h3_premium_lens_heatmap.html",
    "label": "Premium Lens Score",
    "legend": "Premium 3/4 BHK lens score",
    "format": lambda v: f"{v:.2f}",
    "colors": ["#f2f0f7", "#9e9ac8", "#54278f"],
}

BUDGET_SEGMENT_COLORS = {
    "Affordable": "#2ca25f",
    "Mid-Segment": "#fdae6b",
    "Premium": "#de2d26",
    "unknown": "#969696",
}

ANALYSIS_METRICS = {
    **CONTINUOUS_METRICS,
    "activity_score": ACTIVITY_CONFIG,
    "premium_lens_score": PREMIUM_LENS_CONFIG,
}

BUDGET_SHARE_METRICS = {
    "budget_share_affordable": {
        "title": "Affordable Budget Share",
        "label": "Affordable Share",
        "legend": "Affordable budget share",
        "format": lambda v: f"{v:.0%}",
        "colors": ["#f7fcf5", "#74c476", "#006d2c"],
    },
    "budget_share_mid_segment": {
        "title": "Mid-Segment Budget Share",
        "label": "Mid-Segment Share",
        "legend": "Mid-segment budget share",
        "format": lambda v: f"{v:.0%}",
        "colors": ["#fff7ec", "#fdae6b", "#d94801"],
    },
    "budget_share_premium": {
        "title": "Premium Budget Share",
        "label": "Premium Share",
        "legend": "Premium budget share",
        "format": lambda v: f"{v:.0%}",
        "colors": ["#fff5f0", "#fb6a4a", "#a50f15"],
    },
}

SPATIAL_ANALYSIS_METRICS = {
    **ANALYSIS_METRICS,
    **BUDGET_SHARE_METRICS,
}

def clean_numeric(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = (
            value.replace(",", "")
            .replace("Rs", "")
            .replace("₹", "")
            .replace("/ sqft", "")
            .replace("%", "")
        )
        match = re.search(r"[-+]?\d*\.\d+|\d+", text)
        if match:
            return float(match.group())
    return None


def safe_dict(value):
    return value if isinstance(value, dict) else {}


def in_bounds(lat, lon, bounds):
    return (
        bounds["min_lat"] <= lat <= bounds["max_lat"]
        and bounds["min_lon"] <= lon <= bounds["max_lon"]
    )


def smoothing_decay(distance):
    return 1.0 / (1.0 + distance)


def h3_cell_polygon(cell):
    boundary = h3.cell_to_boundary(cell)
    coords = [(lon, lat) for lat, lon in boundary]
    return Polygon(coords)


def h3_cell_feature(cell, properties, geometry=None):
    geom = geometry if geometry is not None else h3_cell_polygon(cell)
    return {
        "type": "Feature",
        "geometry": mapping(geom),
        "properties": {"h3_cell": cell, **properties},
    }


def percentile_bounds(values, lower=2, upper=98):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None, None

    def pct(p):
        if len(values) == 1:
            return values[0]
        pos = (len(values) - 1) * p / 100.0
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            return values[lo]
        frac = pos - lo
        return values[lo] * (1.0 - frac) + values[hi] * frac

    return pct(lower), pct(upper)


def normalized(value, low, high):
    if value is None:
        return 0.0
    if low is None or high is None or high <= low:
        return 1.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def load_localities():
    with LOCALITIES_PATH.open("r") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise ValueError(f"{LOCALITIES_PATH} must contain a top-level array.")
    return raw


def parse_localities(raw_localities):
    parsed = []
    skipped = []
    outliers = []
    budget_counts_all = Counter()
    budget_counts_included = Counter()

    for idx, loc in enumerate(raw_localities):
        locality_info = safe_dict(loc.get("locality_info"))
        market = safe_dict(loc.get("market_insights"))
        inventory = safe_dict(loc.get("inventory"))
        income = safe_dict(loc.get("income_analytics"))

        locality_id = locality_info.get("id") or f"loc_{idx}"
        name = locality_info.get("name") or "Unknown"
        zone_name = safe_dict(locality_info.get("zone")).get("name")
        coords = safe_dict(locality_info.get("coordinates"))
        lat = clean_numeric(coords.get("latitude"))
        lon = clean_numeric(coords.get("longitude"))
        segment = market.get("budget_segment") or "unknown"
        budget_counts_all[segment] += 1

        if lat is None or lon is None:
            skipped.append(
                {
                    "locality_id": locality_id,
                    "name": name,
                    "reason": "missing_or_invalid_coordinates",
                    "lat": lat,
                    "lon": lon,
                    "zone": zone_name,
                }
            )
            continue

        if not in_bounds(lat, lon, BENGALURU_METRO_BOUNDS):
            outliers.append(
                {
                    "locality_id": locality_id,
                    "name": name,
                    "reason": "outside_bengaluru_metro_bounds",
                    "lat": lat,
                    "lon": lon,
                    "zone": zone_name,
                }
            )
            continue

        rent = safe_dict(inventory.get("rent"))
        sale = safe_dict(inventory.get("sale"))
        rent_total = clean_numeric(rent.get("total_count")) or 0.0
        sale_total = clean_numeric(sale.get("total_count")) or 0.0
        inventory_total = rent_total + sale_total

        registry_count = clean_numeric(market.get("registry_count"))
        reviews_count = clean_numeric(market.get("reviews_count")) or 0.0
        if registry_count and registry_count > 0:
            base_weight = registry_count
        elif inventory_total > 0:
            base_weight = inventory_total
        else:
            base_weight = 0.0
        weight = base_weight + 0.1 * reviews_count
        if weight <= 0:
            weight = 1.0

        price_sqft = clean_numeric(
            market.get("market_price_per_sqft") or market.get("price_per_sqft")
        )
        high_income = clean_numeric(safe_dict(income.get("distribution")).get("high"))
        rental_yield = clean_numeric(
            market.get("rental_yield_pct") or market.get("rental_yield")
        )
        activity_score = inventory_total + reviews_count

        rent_bhk = safe_dict(rent.get("bhk_details"))
        sale_bhk = safe_dict(sale.get("bhk_details"))
        bhk_34_count = 0.0
        for bhk in ("bhk_3", "bhk_4"):
            bhk_34_count += clean_numeric(safe_dict(rent_bhk.get(bhk)).get("total_count")) or 0.0
            bhk_34_count += clean_numeric(safe_dict(sale_bhk.get(bhk)).get("total_count")) or 0.0
        bhk_34_density = bhk_34_count / inventory_total if inventory_total > 0 else 0.0

        if price_sqft is None:
            price_score = 0.0
        elif price_sqft < 6000:
            price_score = 0.0
        elif price_sqft >= 12000:
            price_score = 1.0
        else:
            price_score = (price_sqft - 6000.0) / 6000.0
        count_factor = min(1.0, bhk_34_count / 20.0)
        premium_lens_score = count_factor * bhk_34_density * price_score

        cell = h3.latlng_to_cell(lat, lon, H3_RESOLUTION)
        budget_counts_included[segment] += 1
        parsed.append(
            {
                "locality_id": locality_id,
                "name": name,
                "zone": zone_name,
                "lat": lat,
                "lon": lon,
                "h3_cell": cell,
                "weight": weight,
                "budget_segment": segment,
                "budget_segment_source": market.get("budget_segment_source") or "unknown",
                "price_sqft": price_sqft,
                "high_income": high_income,
                "rental_yield": rental_yield,
                "activity_score": activity_score,
                "premium_lens_score": premium_lens_score,
                "bhk_34_count": bhk_34_count,
                "inventory_total": inventory_total,
                "reviews_count": reviews_count,
            }
        )

    audit = {
        "total_records": len(raw_localities),
        "parsed_valid_coordinate_records": len(raw_localities) - len(skipped),
        "included_records": len(parsed),
        "skipped_records": len(skipped),
        "outlier_records_excluded": len(outliers),
        "h3_resolution": H3_RESOLUTION,
        "bengaluru_metro_bounds": BENGALURU_METRO_BOUNDS,
        "budget_counts_all_records": dict(budget_counts_all),
        "budget_counts_included_records": dict(budget_counts_included),
        "skipped": skipped,
        "outliers": outliers,
    }
    return parsed, audit


def smooth_localities(localities):
    metric_acc = {
        "price_sqft": defaultdict(lambda: [0.0, 0.0]),
        "high_income": defaultdict(lambda: [0.0, 0.0]),
        "rental_yield": defaultdict(lambda: [0.0, 0.0]),
    }
    activity_acc = defaultdict(float)
    premium_acc = defaultdict(lambda: [0.0, 0.0])
    budget_acc = defaultdict(lambda: defaultdict(float))
    source_locality_names = defaultdict(list)
    source_locality_count = defaultdict(int)
    source_weight = defaultdict(float)

    for loc in localities:
        source_locality_count[loc["h3_cell"]] += 1
        source_weight[loc["h3_cell"]] += loc["weight"]
        if len(source_locality_names[loc["h3_cell"]]) < 8:
            source_locality_names[loc["h3_cell"]].append(loc["name"])

        for neighbor in h3.grid_disk(loc["h3_cell"], SMOOTHING_K):
            try:
                distance = h3.grid_distance(loc["h3_cell"], neighbor)
            except Exception:
                distance = 1
            decay = smoothing_decay(distance)

            for metric in metric_acc:
                value = loc.get(metric)
                if value is not None:
                    weighted = loc["weight"] * decay
                    metric_acc[metric][neighbor][0] += value * weighted
                    metric_acc[metric][neighbor][1] += weighted

            activity_acc[neighbor] += loc["activity_score"] * decay

            premium_weight = loc["weight"] * decay
            premium_acc[neighbor][0] += loc["premium_lens_score"] * premium_weight
            premium_acc[neighbor][1] += premium_weight

            budget_acc[neighbor][loc["budget_segment"]] += loc["weight"] * decay

    cells = {}
    all_cells = set(activity_acc) | set(premium_acc) | set(budget_acc)
    for metric in metric_acc:
        all_cells |= set(metric_acc[metric])

    for cell in all_cells:
        props = {
            "source_locality_count": source_locality_count.get(cell, 0),
            "source_weight": source_weight.get(cell, 0.0),
            "source_localities": source_locality_names.get(cell, []),
        }

        for metric, acc in metric_acc.items():
            numerator, denominator = acc.get(cell, [0.0, 0.0])
            props[metric] = numerator / denominator if denominator > 0 else None

        props["activity_score"] = activity_acc.get(cell, 0.0)

        premium_num, premium_den = premium_acc.get(cell, [0.0, 0.0])
        props["premium_lens_score"] = premium_num / premium_den if premium_den > 0 else 0.0

        segment_weights = dict(budget_acc.get(cell, {}))
        total_budget_weight = sum(segment_weights.values())
        if total_budget_weight > 0:
            segment_shares = {
                segment: value / total_budget_weight
                for segment, value in segment_weights.items()
            }
            dominant_segment = max(segment_shares.items(), key=lambda item: item[1])[0]
            dominant_share = segment_shares[dominant_segment]
            entropy = 0.0
            for share in segment_shares.values():
                if share > 0:
                    entropy -= share * math.log2(share)
        else:
            segment_shares = {}
            dominant_segment = "unknown"
            dominant_share = 0.0
            entropy = 0.0

        props["budget_weights"] = segment_weights
        props["budget_shares"] = segment_shares
        props["budget_share_affordable"] = segment_shares.get("Affordable", 0.0)
        props["budget_share_mid_segment"] = segment_shares.get("Mid-Segment", 0.0)
        props["budget_share_premium"] = segment_shares.get("Premium", 0.0)
        props["dominant_budget_segment"] = dominant_segment
        props["dominant_budget_share"] = dominant_share
        props["budget_entropy"] = entropy

        cells[cell] = props

    return cells


def build_cell_geometries(cells):
    return {cell: h3_cell_polygon(cell) for cell in cells}


def write_geojson(cells):
    features = []
    for cell, props in cells.items():
        serializable_props = dict(props)
        serializable_props["budget_weights"] = json.dumps(props.get("budget_weights", {}))
        serializable_props["budget_shares"] = json.dumps(props.get("budget_shares", {}))
        serializable_props["source_localities"] = ", ".join(props.get("source_localities", []))
        features.append(h3_cell_feature(cell, serializable_props))

    H3_CELLS_PATH.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2)
    )


def add_title(m, title):
    title_html = f"""
    <div style="
        position: fixed;
        top: 16px;
        left: 50px;
        z-index: 9999;
        background: rgba(255,255,255,0.92);
        padding: 10px 14px;
        border: 1px solid #d9d9d9;
        border-radius: 4px;
        font-family: Arial, sans-serif;
        font-size: 15px;
        font-weight: 700;
        box-shadow: 0 1px 5px rgba(0,0,0,0.15);
    ">{title}</div>
    """
    m.get_root().html.add_child(folium.Element(title_html))


def add_note(m):
    note_html = """
    <div style="
        position: fixed;
        bottom: 22px;
        left: 50px;
        z-index: 9999;
        background: rgba(255,255,255,0.90);
        padding: 8px 10px;
        border: 1px solid #d9d9d9;
        border-radius: 4px;
        font-family: Arial, sans-serif;
        font-size: 11px;
        line-height: 1.4;
        max-width: 360px;
    ">
      H3 values are computed from locality observations and smoothed across
      neighboring cells. No non-building mask is applied.
    </div>
    """
    m.get_root().html.add_child(folium.Element(note_html))


def metric_tooltip_html(props, config, value):
    localities = props.get("source_localities") or []
    locality_text = ", ".join(localities) if localities else "Smoothed neighbor cell"
    return f"""
    <div style="font-family: Arial, sans-serif; font-size: 12px; line-height: 1.5;">
      <strong>H3 cell</strong><br/>
      {config["label"]}: {config["format"](value)}<br/>
      Direct localities: {props.get("source_locality_count", 0)}<br/>
      Source examples: {locality_text}
    </div>
    """


def create_metric_map(cells, cell_geometries, metric_key, config):
    values = [
        props.get(metric_key)
        for cell, props in cells.items()
        if cell in cell_geometries and props.get(metric_key) is not None
    ]
    low, high = percentile_bounds(values)
    color_map = cm.LinearColormap(
        colors=config["colors"],
        vmin=low if low is not None else 0,
        vmax=high if high is not None else 1,
        caption=config["legend"],
    )

    features = []
    for cell, props in cells.items():
        if cell not in cell_geometries:
            continue
        value = props.get(metric_key)
        if value is None:
            continue
        intensity = normalized(value, low, high)
        properties = {
            "value": value,
            "intensity": intensity,
            "tooltip": metric_tooltip_html(props, config, value),
        }
        features.append(h3_cell_feature(cell, properties, cell_geometries[cell]))

    m = folium.Map(location=MAP_CENTER, zoom_start=11, tiles="CartoDB positron")
    add_title(m, config["title"])
    add_note(m)

    folium.GeoJson(
        {"type": "FeatureCollection", "features": features},
        name=config["label"],
        style_function=lambda feature: {
            "fillColor": color_map(feature["properties"]["value"]),
            "color": "#404040",
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
    ).add_to(m)
    color_map.add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    m.save(MAPS_DIR / config["filename"])


def create_budget_map(cells, cell_geometries):
    features = []
    for cell, props in cells.items():
        if cell not in cell_geometries:
            continue
        shares = props.get("budget_shares") or {}
        if not shares:
            continue
        segment = props.get("dominant_budget_segment") or "unknown"
        tooltip = f"""
        <div style="font-family: Arial, sans-serif; font-size: 12px; line-height: 1.5;">
          <strong>Dominant budget segment:</strong> {segment}<br/>
          Dominant share: {props.get("dominant_budget_share", 0):.0%}<br/>
          Affordable: {shares.get("Affordable", 0):.0%}<br/>
          Mid-Segment: {shares.get("Mid-Segment", 0):.0%}<br/>
          Premium: {shares.get("Premium", 0):.0%}<br/>
          Entropy: {props.get("budget_entropy", 0):.2f}<br/>
          Direct localities: {props.get("source_locality_count", 0)}
        </div>
        """
        features.append(
            h3_cell_feature(
                cell,
                {
                    "dominant_budget_segment": segment,
                    "dominant_budget_share": props.get("dominant_budget_share", 0),
                    "tooltip": tooltip,
                },
                cell_geometries[cell],
            )
        )

    m = folium.Map(location=MAP_CENTER, zoom_start=11, tiles="CartoDB positron")
    add_title(m, "H3 Budget Segment Heatmap")
    add_note(m)

    folium.GeoJson(
        {"type": "FeatureCollection", "features": features},
        name="Dominant budget segment",
        style_function=lambda feature: {
            "fillColor": BUDGET_SEGMENT_COLORS.get(
                feature["properties"].get("dominant_budget_segment"), "#969696"
            ),
            "color": "#404040",
            "weight": 0.25,
            "fillOpacity": 0.30 + 0.45 * feature["properties"].get("dominant_budget_share", 0),
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["tooltip"],
            aliases=[""],
            labels=False,
            sticky=True,
            style=("font-family: Arial, sans-serif; font-size: 12px;"),
        ),
    ).add_to(m)

    for segment, color in BUDGET_SEGMENT_COLORS.items():
        if segment == "unknown":
            continue
        segment_features = []
        for cell, props in cells.items():
            if cell not in cell_geometries:
                continue
            share = (props.get("budget_shares") or {}).get(segment, 0.0)
            if share <= 0:
                continue
            segment_features.append(
                h3_cell_feature(
                    cell,
                    {"segment": segment, "share": share},
                    cell_geometries[cell],
                )
            )
        folium.GeoJson(
            {"type": "FeatureCollection", "features": segment_features},
            name=f"{segment} concentration",
            show=False,
            style_function=lambda feature, layer_color=color: {
                "fillColor": layer_color,
                "color": layer_color,
                "weight": 0.15,
                "fillOpacity": 0.08 + 0.62 * feature["properties"].get("share", 0),
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["segment", "share"],
                aliases=["Segment", "Share"],
                localize=True,
                sticky=True,
            ),
        ).add_to(m)
    legend_html = """
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
    m.get_root().html.add_child(folium.Element(legend_html))
    folium.LayerControl(collapsed=True).add_to(m)
    m.save(MAPS_DIR / "h3_budget_segment_heatmap.html")


def metric_slug(metric_key):
    return metric_key.replace("_sqft", "").replace("_score", "").replace("_", "-")


def calculate_getis_ord_gistar(cells, metric_key, neighbor_k=GETIS_ORD_K):
    valid_values = {
        cell: props.get(metric_key)
        for cell, props in cells.items()
        if props.get(metric_key) is not None
    }
    n = len(valid_values)
    if n < 3:
        return {}

    values = list(valid_values.values())
    mean = sum(values) / n
    second_moment = sum(value * value for value in values) / n
    std = math.sqrt(max(0.0, second_moment - mean * mean))
    if std <= 0:
        return {}

    results = {}
    valid_cells = set(valid_values)
    for cell in valid_cells:
        weighted_sum = 0.0
        weight_sum = 0.0
        weight_sq_sum = 0.0
        for neighbor in h3.grid_disk(cell, neighbor_k):
            if neighbor not in valid_cells:
                continue
            try:
                distance = h3.grid_distance(cell, neighbor)
            except Exception:
                distance = 1
            weight = smoothing_decay(distance)
            weighted_sum += weight * valid_values[neighbor]
            weight_sum += weight
            weight_sq_sum += weight * weight

        denominator_inner = (n * weight_sq_sum - weight_sum * weight_sum) / (n - 1)
        if denominator_inner <= 0:
            continue

        z_score = (weighted_sum - mean * weight_sum) / (std * math.sqrt(denominator_inner))
        p_value = math.erfc(abs(z_score) / math.sqrt(2.0))
        results[cell] = {
            "gi_z_score": z_score,
            "gi_p_value": p_value,
            "gi_confidence": 1.0 - p_value,
            "metric_value": valid_values[cell],
        }

    return results


def getis_tooltip_html(props, config, gi_props):
    value = gi_props["metric_value"]
    z_score = gi_props["gi_z_score"]
    p_value = gi_props["gi_p_value"]
    if z_score >= 2.58:
        cluster = "Very strong high-value cluster"
    elif z_score >= 1.96:
        cluster = "Strong high-value cluster"
    elif z_score >= 1.65:
        cluster = "Moderate high-value cluster"
    elif z_score <= -2.58:
        cluster = "Very strong low-value cluster"
    elif z_score <= -1.96:
        cluster = "Strong low-value cluster"
    elif z_score <= -1.65:
        cluster = "Moderate low-value cluster"
    else:
        cluster = "Not statistically strong"

    localities = props.get("source_localities") or []
    locality_text = ", ".join(localities) if localities else "Smoothed neighbor cell"
    return f"""
    <div style="font-family: Arial, sans-serif; font-size: 12px; line-height: 1.5;">
      <strong>Getis-Ord Gi*</strong><br/>
      {config["label"]}: {config["format"](value)}<br/>
      Z-score: {z_score:.2f}<br/>
      p-value: {p_value:.4f}<br/>
      Cluster: {cluster}<br/>
      Direct localities: {props.get("source_locality_count", 0)}<br/>
      Source examples: {locality_text}
    </div>
    """


def create_getis_ord_map(cells, cell_geometries, metric_key, config):
    gi_results = calculate_getis_ord_gistar(cells, metric_key)
    if not gi_results:
        return None

    z_values = [result["gi_z_score"] for result in gi_results.values()]
    max_abs = max(1.96, min(4.0, max(abs(value) for value in z_values)))
    color_map = cm.LinearColormap(
        colors=["#2166ac", "#f7f7f7", "#b2182b"],
        vmin=-max_abs,
        vmax=max_abs,
        caption=f"{config['label']} Getis-Ord Gi* z-score",
    )

    features = []
    for cell, gi_props in gi_results.items():
        if cell not in cell_geometries:
            continue
        tooltip = getis_tooltip_html(cells[cell], config, gi_props)
        features.append(
            h3_cell_feature(
                cell,
                {
                    **gi_props,
                    "tooltip": tooltip,
                },
                cell_geometries[cell],
            )
        )

    m = folium.Map(location=MAP_CENTER, zoom_start=11, tiles="CartoDB positron")
    add_title(m, f"Getis-Ord Gi* - {config['title']}")
    add_note(m)
    folium.GeoJson(
        {"type": "FeatureCollection", "features": features},
        name="Gi* z-score",
        style_function=lambda feature: {
            "fillColor": color_map(feature["properties"]["gi_z_score"]),
            "color": "#404040",
            "weight": 0.25,
            "fillOpacity": 0.72
            if abs(feature["properties"]["gi_z_score"]) >= 1.65
            else 0.38,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["tooltip"],
            aliases=[""],
            labels=False,
            sticky=True,
            style=("font-family: Arial, sans-serif; font-size: 12px;"),
        ),
    ).add_to(m)
    color_map.add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)

    output = MAPS_DIR / f"h3_getis_ord_{metric_slug(metric_key)}.html"
    m.save(output)
    return output


def create_kde_point_map(cells, metric_key, config):
    values = [
        props.get(metric_key)
        for props in cells.values()
        if props.get(metric_key) is not None
    ]
    low, high = percentile_bounds(values)
    heatmap_data = []

    for cell, props in cells.items():
        value = props.get(metric_key)
        if value is None:
            continue
        lat, lon = h3.cell_to_latlng(cell)
        intensity = normalized(value, low, high)
        if intensity <= 0:
            continue
        heatmap_data.append([lat, lon, intensity])

    if not heatmap_data:
        return None

    m = folium.Map(location=MAP_CENTER, zoom_start=11, tiles="CartoDB positron")
    add_title(m, f"KDE Point Heatmap - {config['title']}")
    add_note(m)
    HeatMap(
        heatmap_data,
        name="KDE point heatmap",
        radius=KDE_RADIUS,
        blur=KDE_BLUR,
        min_opacity=0.18,
        max_zoom=13,
    ).add_to(m)

    top_cells = sorted(
        (
            (cell, props.get(metric_key), props)
            for cell, props in cells.items()
            if props.get(metric_key) is not None
        ),
        key=lambda item: item[1],
        reverse=True,
    )[:12]

    for rank, (cell, value, props) in enumerate(top_cells, 1):
        lat, lon = h3.cell_to_latlng(cell)
        localities = props.get("source_localities") or []
        locality_text = ", ".join(localities) if localities else "Smoothed neighbor cell"
        popup_html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 12px; line-height: 1.5; width: 230px;">
          <strong>#{rank} H3 cell</strong><br/>
          {config["label"]}: {config["format"](value)}<br/>
          Direct localities: {props.get("source_locality_count", 0)}<br/>
          Source examples: {locality_text}
        </div>
        """
        folium.CircleMarker(
            location=[lat, lon],
            radius=5,
            color="#252525",
            fill=True,
            fill_color="#525252",
            fill_opacity=0.85,
            popup=folium.Popup(popup_html, max_width=260),
            tooltip=f"#{rank} {config['label']}: {config['format'](value)}",
        ).add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)
    output = MAPS_DIR / f"h3_kde_{metric_slug(metric_key)}.html"
    m.save(output)
    return output


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2))


def main():
    MAPS_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)

    raw_localities = load_localities()
    localities, coordinate_audit = parse_localities(raw_localities)
    if not localities:
        raise RuntimeError("No locality records were usable after coordinate parsing.")

    cells = smooth_localities(localities)
    write_geojson(cells)

    cell_geometries = build_cell_geometries(cells)

    coordinate_audit["h3_source_cells"] = len(set(loc["h3_cell"] for loc in localities))
    coordinate_audit["h3_smoothed_cells"] = len(cells)
    coordinate_audit["h3_rendered_cells"] = len(cell_geometries)
    coordinate_audit["non_building_mask_applied"] = False

    write_json(COORDINATE_AUDIT_PATH, coordinate_audit)

    for metric_key, config in CONTINUOUS_METRICS.items():
        create_metric_map(cells, cell_geometries, metric_key, config)
        print(f"Generated {MAPS_DIR / config['filename']}")

    create_metric_map(cells, cell_geometries, "activity_score", ACTIVITY_CONFIG)
    print(f"Generated {MAPS_DIR / ACTIVITY_CONFIG['filename']}")

    create_metric_map(cells, cell_geometries, "premium_lens_score", PREMIUM_LENS_CONFIG)
    print(f"Generated {MAPS_DIR / PREMIUM_LENS_CONFIG['filename']}")

    create_budget_map(cells, cell_geometries)
    print(f"Generated {MAPS_DIR / 'h3_budget_segment_heatmap.html'}")

    getis_outputs = []
    kde_outputs = []
    for metric_key, config in SPATIAL_ANALYSIS_METRICS.items():
        getis_output = create_getis_ord_map(cells, cell_geometries, metric_key, config)
        if getis_output:
            getis_outputs.append(str(getis_output))
            print(f"Generated {getis_output}")

        kde_output = create_kde_point_map(cells, metric_key, config)
        if kde_output:
            kde_outputs.append(str(kde_output))
            print(f"Generated {kde_output}")

    write_json(
        SPATIAL_ANALYSIS_AUDIT_PATH,
        {
            "h3_resolution": H3_RESOLUTION,
            "h3_cells": len(cells),
            "getis_ord_neighbor_k": GETIS_ORD_K,
            "getis_ord_outputs": getis_outputs,
            "kde_radius": KDE_RADIUS,
            "kde_blur": KDE_BLUR,
            "kde_outputs": kde_outputs,
            "metrics": list(SPATIAL_ANALYSIS_METRICS.keys()),
        },
    )
    print(f"Wrote {H3_CELLS_PATH}")
    print(f"Wrote {COORDINATE_AUDIT_PATH}")
    print(f"Wrote {SPATIAL_ANALYSIS_AUDIT_PATH}")


if __name__ == "__main__":
    main()
