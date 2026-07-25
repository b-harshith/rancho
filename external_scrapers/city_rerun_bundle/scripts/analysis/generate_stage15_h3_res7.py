import csv
import json
import math
import os
import re
from collections import defaultdict
from pathlib import Path

import h3


CITY_SLUG = os.environ.get("CITY_SLUG", "bangalore").strip().lower().replace(" ", "-")
DATA_DIR = Path("DATA")
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
AUDIT_DIR = DATA_DIR / "audits"

STAGE1_LOCALITIES_PATH = PROCESSED_DATA_DIR / f"{CITY_SLUG}_stage1_locality_features.json"
STAGE1_H3_CELLS_PATH = PROCESSED_DATA_DIR / f"{CITY_SLUG}_h3_heatmap_cells.geojson"
RAW_LOCALITIES_PATH = RAW_DATA_DIR / f"{CITY_SLUG}_localities_enriched.json"

OUTPUT_JSON = PROCESSED_DATA_DIR / f"{CITY_SLUG}_stage1_5_hex7_features.json"
OUTPUT_CSV = PROCESSED_DATA_DIR / f"{CITY_SLUG}_stage1_5_hex7_features_flat.csv"
OUTPUT_GEOJSON = PROCESSED_DATA_DIR / f"{CITY_SLUG}_stage1_5_hex7_cells.geojson"
AUDIT_PATH = AUDIT_DIR / f"{CITY_SLUG}_stage1_5_hex7_audit.json"

H3_RESOLUTION = 7
SOURCE_H3_RESOLUTION = 8
SMOOTHING_K = 1
NEIGHBOURHOOD_COMPOSITE_MIN_SHARE = 0.15
BUDGET_SEGMENTS = ("Affordable", "Mid-Segment", "Premium")
CITY_METRO_BOUNDS = json.loads(
    os.environ.get(
        "CITY_METRO_BOUNDS_JSON",
        json.dumps(
            {
                "min_lat": 12.65,
                "max_lat": 13.40,
                "min_lon": 77.20,
                "max_lon": 78.05,
            }
        ),
    )
)

DIRECT_METRICS = (
    "market_price_per_sqft",
    "rental_yield_pct",
    "yearly_appreciation_pct",
    "activity_score",
    "premium_lens_score",
)

H3_8_ROLLUP_METRICS = (
    "price_sqft",
    "high_income",
    "rental_yield",
    "activity_score",
    "premium_lens_score",
)


def safe_dict(value):
    return value if isinstance(value, dict) else {}


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


def parse_json_object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def load_json(path):
    with path.open("r") as f:
        return json.load(f)


def weighted_metric_empty():
    return {
        "weighted_sum": 0.0,
        "weight_sum": 0.0,
        "source_count": 0,
        "min": None,
        "max": None,
    }


def add_weighted_metric(acc, value, weight):
    value = clean_numeric(value)
    if value is None:
        return
    weight = clean_numeric(weight) or 0.0
    if weight <= 0:
        weight = 1.0
    acc["weighted_sum"] += value * weight
    acc["weight_sum"] += weight
    acc["source_count"] += 1
    acc["min"] = value if acc["min"] is None else min(acc["min"], value)
    acc["max"] = value if acc["max"] is None else max(acc["max"], value)


def finalize_weighted_metric(acc):
    if acc["weight_sum"] <= 0:
        return {
            "weighted_avg": None,
            "min": acc["min"],
            "max": acc["max"],
            "source_count": acc["source_count"],
            "source_weight": 0.0,
        }
    return {
        "weighted_avg": acc["weighted_sum"] / acc["weight_sum"],
        "min": acc["min"],
        "max": acc["max"],
        "source_count": acc["source_count"],
        "source_weight": acc["weight_sum"],
    }


def entropy(shares):
    value = 0.0
    for share in shares.values():
        if share and share > 0:
            value -= share * math.log2(share)
    return value


def h3_polygon_geometry(cell):
    boundary = h3.cell_to_boundary(cell)
    ring = [[lon, lat] for lat, lon in boundary]
    if ring:
        ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def h3_feature(cell, properties):
    return {
        "type": "Feature",
        "geometry": h3_polygon_geometry(cell),
        "properties": {"hex_id": cell, **properties},
    }


def in_city_bounds(lat, lon):
    lat = clean_numeric(lat)
    lon = clean_numeric(lon)
    if lat is None or lon is None:
        return False
    return (
        CITY_METRO_BOUNDS["min_lat"] <= lat <= CITY_METRO_BOUNDS["max_lat"]
        and CITY_METRO_BOUNDS["min_lon"] <= lon <= CITY_METRO_BOUNDS["max_lon"]
    )


def support_weight(record):
    support = safe_dict(record.get("support"))
    inventory = safe_dict(record.get("inventory"))
    registry_count = clean_numeric(support.get("registry_count"))
    reviews_count = clean_numeric(support.get("reviews_count")) or 0.0
    rent_total = clean_numeric(inventory.get("rent_total_count")) or 0.0
    sale_total = clean_numeric(inventory.get("sale_total_count")) or 0.0
    inventory_total = rent_total + sale_total

    if registry_count and registry_count > 0:
        base_weight = registry_count
    elif inventory_total > 0:
        base_weight = inventory_total
    else:
        base_weight = 0.0

    weight = base_weight + 0.1 * reviews_count
    return weight if weight > 0 else 1.0


def count_range_empty():
    return {"count": 0.0, "min_price": None, "max_price": None}


def add_count_range(acc, name, item):
    item = safe_dict(item)
    count = clean_numeric(item.get("count")) or clean_numeric(item.get("total_count")) or 0.0
    price_range = safe_dict(item.get("price_range"))
    min_price = clean_numeric(price_range.get("min"))
    max_price = clean_numeric(price_range.get("max"))

    bucket = acc[name]
    bucket["count"] += count
    if min_price is not None:
        bucket["min_price"] = (
            min_price if bucket["min_price"] is None else min(bucket["min_price"], min_price)
        )
    if max_price is not None:
        bucket["max_price"] = (
            max_price if bucket["max_price"] is None else max(bucket["max_price"], max_price)
        )


def finalize_count_ranges(acc):
    return {
        name: {
            "count": values["count"],
            "min_price": values["min_price"],
            "max_price": values["max_price"],
        }
        for name, values in sorted(acc.items())
    }


def bhk_34_count(inventory):
    total = 0.0
    for mix_name in ("rent_bhk_mix", "sale_bhk_mix"):
        mix = safe_dict(inventory.get(mix_name))
        for bhk in ("bhk_3", "bhk_4"):
            total += clean_numeric(safe_dict(mix.get(bhk)).get("total_count")) or 0.0
    return total


def premium_lens_score(record):
    inventory = safe_dict(record.get("inventory"))
    market = safe_dict(record.get("raw_market"))
    rent_total = clean_numeric(inventory.get("rent_total_count")) or 0.0
    sale_total = clean_numeric(inventory.get("sale_total_count")) or 0.0
    inventory_total = rent_total + sale_total
    premium_count = bhk_34_count(inventory)
    price_sqft = clean_numeric(market.get("market_price_per_sqft"))

    if price_sqft is None:
        price_score = 0.0
    elif price_sqft < 6000:
        price_score = 0.0
    elif price_sqft >= 12000:
        price_score = 1.0
    else:
        price_score = (price_sqft - 6000.0) / 6000.0

    count_factor = min(1.0, premium_count / 20.0)
    density = premium_count / inventory_total if inventory_total > 0 else 0.0
    return count_factor * density * price_score


def activity_score(record):
    support = safe_dict(record.get("support"))
    inventory = safe_dict(record.get("inventory"))
    rent_total = clean_numeric(inventory.get("rent_total_count")) or 0.0
    sale_total = clean_numeric(inventory.get("sale_total_count")) or 0.0
    reviews_count = clean_numeric(support.get("reviews_count")) or 0.0
    return rent_total + sale_total + reviews_count


def build_raw_lookup(raw_records):
    lookup = {}
    duplicate_ids = []
    for idx, raw in enumerate(raw_records):
        locality_info = safe_dict(raw.get("locality_info"))
        locality_id = locality_info.get("id") or locality_info.get("locality_id") or f"loc_{idx}"
        if locality_id in lookup:
            duplicate_ids.append(locality_id)
            continue
        lookup[locality_id] = raw
    return lookup, duplicate_ids


def raw_neighbourhood(raw_record, stage_record):
    stage_locality = safe_dict(stage_record.get("locality"))
    overture = safe_dict(safe_dict(raw_record).get("overture_neighborhood"))
    zone_name = stage_locality.get("zone")
    zone_id = stage_locality.get("zone_id")

    name = overture.get("name") or zone_name or stage_locality.get("name") or "Unknown"
    neighbourhood_id = overture.get("id") or zone_id or name
    source = "overture_neighborhood" if overture.get("name") else "stage1_zone_or_locality"

    return {
        "id": neighbourhood_id,
        "name": name,
        "subtype": overture.get("subtype"),
        "source": source,
    }


def normalized_tag_name(tag):
    if isinstance(tag, dict):
        return tag.get("tag") or tag.get("name")
    if isinstance(tag, str):
        return tag
    return None


def child_h3_8_rollups():
    feature_collection = load_json(STAGE1_H3_CELLS_PATH)
    parent_acc = defaultdict(
        lambda: {
            "cells": [],
            "metrics": defaultdict(weighted_metric_empty),
            "budget_share_sums": defaultdict(float),
            "budget_share_count": 0,
            "source_locality_count": 0,
            "source_weight": 0.0,
        }
    )

    for feature in feature_collection.get("features", []):
        props = dict(feature.get("properties") or {})
        cell = props.get("h3_cell")
        if not cell:
            continue
        try:
            parent = h3.cell_to_parent(cell, H3_RESOLUTION)
        except Exception:
            continue

        budget_shares = parse_json_object(props.get("budget_shares"))
        if not budget_shares:
            budget_shares = {
                "Affordable": clean_numeric(props.get("budget_share_affordable")) or 0.0,
                "Mid-Segment": clean_numeric(props.get("budget_share_mid_segment")) or 0.0,
                "Premium": clean_numeric(props.get("budget_share_premium")) or 0.0,
            }

        source_locality_count = clean_numeric(props.get("source_locality_count")) or 0.0
        source_weight = clean_numeric(props.get("source_weight")) or 0.0
        parent_bucket = parent_acc[parent]
        parent_bucket["source_locality_count"] += source_locality_count
        parent_bucket["source_weight"] += source_weight
        parent_bucket["budget_share_count"] += 1
        for segment in BUDGET_SEGMENTS:
            parent_bucket["budget_share_sums"][segment] += clean_numeric(budget_shares.get(segment)) or 0.0

        child = {
            "hex_id": cell,
            "source_locality_count": source_locality_count,
            "source_weight": source_weight,
            "source_localities": props.get("source_localities"),
            "dominant_budget_segment": props.get("dominant_budget_segment"),
            "dominant_budget_share": clean_numeric(props.get("dominant_budget_share")) or 0.0,
            "budget_shares": {
                segment: clean_numeric(budget_shares.get(segment)) or 0.0
                for segment in BUDGET_SEGMENTS
            },
            "metrics": {
                metric: clean_numeric(props.get(metric))
                for metric in H3_8_ROLLUP_METRICS
            },
        }
        parent_bucket["cells"].append(child)

        for metric in H3_8_ROLLUP_METRICS:
            add_weighted_metric(parent_bucket["metrics"][metric], props.get(metric), 1.0)

    finalized = {}
    for parent, bucket in parent_acc.items():
        child_count = len(bucket["cells"])
        average_shares = {
            segment: (
                bucket["budget_share_sums"][segment] / bucket["budget_share_count"]
                if bucket["budget_share_count"] > 0
                else 0.0
            )
            for segment in BUDGET_SEGMENTS
        }
        dominant_segment = max(average_shares.items(), key=lambda item: item[1])[0]
        finalized[parent] = {
            "child_count": child_count,
            "source_locality_count": bucket["source_locality_count"],
            "source_weight": bucket["source_weight"],
            "rolled_up_smoothed_values": {
                "metrics": {
                    metric: finalize_weighted_metric(acc)["weighted_avg"]
                    for metric, acc in bucket["metrics"].items()
                },
                "budget_segments": average_shares,
                "dominant_budget_segment": dominant_segment,
                "dominant_budget_share": average_shares[dominant_segment],
                "budget_entropy": entropy(average_shares),
            },
            "cells": sorted(bucket["cells"], key=lambda item: item["hex_id"]),
        }
    return finalized


def add_locality_to_group(groups, stage_record, raw_lookup, missing_raw_ids):
    locality = safe_dict(stage_record.get("locality"))
    h3_res_8 = locality.get("h3_res_8")
    if not h3_res_8:
        return False
    try:
        if h3.get_resolution(h3_res_8) != SOURCE_H3_RESOLUTION:
            return False
        hex_id = h3.cell_to_parent(h3_res_8, H3_RESOLUTION)
    except Exception:
        return False

    locality_id = locality.get("id")
    raw_record = raw_lookup.get(locality_id)
    if raw_record is None:
        missing_raw_ids.append(locality_id)
        raw_record = {}

    support = safe_dict(stage_record.get("support"))
    inventory = safe_dict(stage_record.get("inventory"))
    market = safe_dict(stage_record.get("raw_market"))
    labels = safe_dict(stage_record.get("non_raw_labels"))
    weight = support_weight(stage_record)
    neighbourhood = raw_neighbourhood(raw_record, stage_record)
    budget_segment = labels.get("budget_segment") or "unknown"
    within_bounds = in_city_bounds(locality.get("lat"), locality.get("lon"))

    group = groups[hex_id]
    group["hex_id"] = hex_id
    group["locality_records"].append(stage_record)
    group["total_support_weight"] += weight
    group["registry_count"] += clean_numeric(support.get("registry_count")) or 0.0
    group["reviews_count"] += clean_numeric(support.get("reviews_count")) or 0.0
    group["rent_total_count"] += clean_numeric(inventory.get("rent_total_count")) or 0.0
    group["sale_total_count"] += clean_numeric(inventory.get("sale_total_count")) or 0.0
    group["buy_total_count_excluding_land"] += (
        clean_numeric(inventory.get("buy_total_count_excluding_land")) or 0.0
    )
    group["geocoding_found_count"] += 1 if support.get("geocoding_found") else 0
    group["overture_polygon_count"] += 1 if support.get("has_overture_polygon") else 0
    group["out_of_bounds_locality_count"] += 0 if within_bounds else 1

    group["budget_weights"][budget_segment] += weight
    group["neighbourhood_weights"][neighbourhood["id"]]["id"] = neighbourhood["id"]
    group["neighbourhood_weights"][neighbourhood["id"]]["name"] = neighbourhood["name"]
    group["neighbourhood_weights"][neighbourhood["id"]]["subtype"] = neighbourhood["subtype"]
    group["neighbourhood_weights"][neighbourhood["id"]]["source"] = neighbourhood["source"]
    group["neighbourhood_weights"][neighbourhood["id"]]["support_weight"] += weight
    group["neighbourhood_weights"][neighbourhood["id"]]["locality_count"] += 1

    for metric, value in {
        "market_price_per_sqft": market.get("market_price_per_sqft"),
        "rental_yield_pct": market.get("rental_yield_pct"),
        "yearly_appreciation_pct": market.get("yearly_appreciation_pct"),
        "activity_score": activity_score(stage_record),
        "premium_lens_score": premium_lens_score(stage_record),
    }.items():
        add_weighted_metric(group["metrics"][metric], value, weight)

    for tag in labels.get("tags") or []:
        tag_name = normalized_tag_name(tag)
        if tag_name:
            group["tag_weights"][tag_name] += weight

    for source_key, target_key in (
        ("rent_property_type_mix", "rent_property_type_mix"),
        ("sale_property_type_mix", "sale_property_type_mix"),
        ("buy_property_type_mix_excluding_land", "buy_property_type_mix_excluding_land"),
        ("rent_price_bucket_distribution", "rent_price_bucket_distribution"),
        ("sale_price_bucket_distribution", "sale_price_bucket_distribution"),
        ("buy_price_bucket_distribution", "buy_price_bucket_distribution"),
    ):
        for name, item in safe_dict(inventory.get(source_key)).items():
            add_count_range(group["inventory_mix"][target_key], name, item)

    for mix_name in ("rent_bhk_mix", "sale_bhk_mix", "buy_bhk_mix"):
        for name, item in safe_dict(inventory.get(mix_name)).items():
            add_count_range(group["inventory_mix"][mix_name], name, item)

    group["localities"].append(
        {
            "id": locality_id,
            "name": locality.get("name"),
            "h3_res_8": h3_res_8,
            "lat": locality.get("lat"),
            "lon": locality.get("lon"),
            "neighbourhood_id": neighbourhood["id"],
            "neighbourhood_name": neighbourhood["name"],
            "source_budget_segment": budget_segment,
            "budget_segment_source": labels.get("budget_segment_source"),
            "budget_segment_confidence": labels.get("budget_segment_confidence"),
            "support_weight": weight,
            "market_price_per_sqft": market.get("market_price_per_sqft"),
            "rental_yield_pct": market.get("rental_yield_pct"),
            "yearly_appreciation_pct": market.get("yearly_appreciation_pct"),
            "within_city_bounds": within_bounds,
            "quality_flags": [] if within_bounds else ["outside_city_metro_bounds"],
        }
    )
    return True


def group_empty():
    return {
        "locality_records": [],
        "localities": [],
        "total_support_weight": 0.0,
        "registry_count": 0.0,
        "reviews_count": 0.0,
        "rent_total_count": 0.0,
        "sale_total_count": 0.0,
        "buy_total_count_excluding_land": 0.0,
        "geocoding_found_count": 0,
        "overture_polygon_count": 0,
        "out_of_bounds_locality_count": 0,
        "budget_weights": defaultdict(float),
        "neighbourhood_weights": defaultdict(
            lambda: {
                "id": None,
                "name": None,
                "subtype": None,
                "source": None,
                "support_weight": 0.0,
                "locality_count": 0,
            }
        ),
        "tag_weights": defaultdict(float),
        "metrics": defaultdict(weighted_metric_empty),
        "inventory_mix": defaultdict(lambda: defaultdict(count_range_empty)),
    }


def budget_summary(budget_weights):
    known_total = sum(budget_weights.get(segment, 0.0) for segment in BUDGET_SEGMENTS)
    if known_total <= 0:
        shares = {segment: 0.0 for segment in BUDGET_SEGMENTS}
        return {
            "weights": {segment: budget_weights.get(segment, 0.0) for segment in BUDGET_SEGMENTS},
            "shares": shares,
            "dominant_budget_segment": "unknown",
            "dominant_budget_share": 0.0,
            "budget_entropy": 0.0,
            "budget_classification": "unknown",
        }

    shares = {
        segment: budget_weights.get(segment, 0.0) / known_total
        for segment in BUDGET_SEGMENTS
    }
    dominant_segment = max(shares.items(), key=lambda item: item[1])[0]
    dominant_share = shares[dominant_segment]
    if dominant_share >= 0.60:
        classification = dominant_segment
    elif dominant_share >= 0.45:
        classification = f"Mixed - {dominant_segment} leaning"
    else:
        classification = "Mixed/Diverse"
    return {
        "weights": {
            segment: budget_weights.get(segment, 0.0)
            for segment in BUDGET_SEGMENTS
        },
        "shares": shares,
        "dominant_budget_segment": dominant_segment,
        "dominant_budget_share": dominant_share,
        "budget_entropy": entropy(shares),
        "budget_classification": classification,
    }


def neighbourhood_summary(group):
    total_weight = group["total_support_weight"]
    rows = []
    for item in group["neighbourhood_weights"].values():
        share = item["support_weight"] / total_weight if total_weight > 0 else 0.0
        rows.append(
            {
                "id": item["id"],
                "name": item["name"],
                "subtype": item["subtype"],
                "source": item["source"],
                "locality_count": item["locality_count"],
                "support_weight": item["support_weight"],
                "share": share,
            }
        )
    return sorted(rows, key=lambda item: (-item["support_weight"], item["name"] or ""))


def composite_hex_name(neighbourhoods):
    if not neighbourhoods:
        return "Unknown"
    first = neighbourhoods[0]["name"] or "Unknown"
    if len(neighbourhoods) == 1:
        return first
    second = neighbourhoods[1]
    second_name = second["name"] or "Unknown"
    if second["share"] >= NEIGHBOURHOOD_COMPOSITE_MIN_SHARE and second_name != first:
        return f"{first}-{second_name}"
    return first


def tag_summary(group):
    total_weight = group["total_support_weight"]
    tags = []
    for tag, weight in group["tag_weights"].items():
        tags.append(
            {
                "tag": tag,
                "support_weight": weight,
                "share": weight / total_weight if total_weight > 0 else 0.0,
            }
        )
    return sorted(tags, key=lambda item: (-item["support_weight"], item["tag"]))[:15]


def finalize_group(hex_id, group, h3_8_rollups):
    neighbourhoods = neighbourhood_summary(group)
    dominant_neighbourhood = neighbourhoods[0] if neighbourhoods else None
    budgets = budget_summary(group["budget_weights"])
    localities = sorted(
        group["localities"],
        key=lambda item: (-(item.get("support_weight") or 0), item.get("name") or ""),
    )
    metrics = {
        metric: finalize_weighted_metric(group["metrics"][metric])
        for metric in DIRECT_METRICS
    }
    inventory_mix = {
        key: finalize_count_ranges(value)
        for key, value in sorted(group["inventory_mix"].items())
    }
    child_rollup = h3_8_rollups.get(
        hex_id,
        {
            "child_count": 0,
            "source_locality_count": 0,
            "source_weight": 0.0,
            "rolled_up_smoothed_values": {
                "metrics": {},
                "budget_segments": {segment: 0.0 for segment in BUDGET_SEGMENTS},
                "dominant_budget_segment": "unknown",
                "dominant_budget_share": 0.0,
                "budget_entropy": 0.0,
            },
            "cells": [],
        },
    )
    quality_flags = []
    if group["out_of_bounds_locality_count"] > 0:
        quality_flags.append("contains_out_of_bounds_localities")
    if child_rollup.get("child_count", 0) == 0:
        quality_flags.append("missing_stage1_h3_res_8_rollup")

    return {
        "hex_id": hex_id,
        "resolution": H3_RESOLUTION,
        "name": composite_hex_name(neighbourhoods),
        "dominant_neighbourhood": dominant_neighbourhood,
        "neighbourhoods": neighbourhoods,
        "localities": localities,
        "market_insights": {
            "metrics": metrics,
            "support": {
                "locality_count": len(localities),
                "total_support_weight": group["total_support_weight"],
                "registry_count": group["registry_count"],
                "reviews_count": group["reviews_count"],
                "geocoding_found_count": group["geocoding_found_count"],
                "overture_polygon_count": group["overture_polygon_count"],
            },
            "inventory": {
                "rent_total_count": group["rent_total_count"],
                "sale_total_count": group["sale_total_count"],
                "buy_total_count_excluding_land": group["buy_total_count_excluding_land"],
                "inventory_total_count": group["rent_total_count"] + group["sale_total_count"],
                "mixes": inventory_mix,
            },
        },
        "budget_segments": budgets["shares"],
        "budget_segment_weights": budgets["weights"],
        "dominant_budget_segment": budgets["dominant_budget_segment"],
        "dominant_budget_share": budgets["dominant_budget_share"],
        "budget_entropy": budgets["budget_entropy"],
        "budget_classification": budgets["budget_classification"],
        "tags": tag_summary(group),
        "child_h3_res_8": child_rollup,
        "quality": {
            "flags": quality_flags,
            "out_of_bounds_locality_count": group["out_of_bounds_locality_count"],
            "within_city_bounds_locality_count": len(localities)
            - group["out_of_bounds_locality_count"],
        },
        "provenance": {
            "stage": "1.5",
            "input_stage1_localities": str(STAGE1_LOCALITIES_PATH),
            "input_stage1_h3_res_8_cells": str(STAGE1_H3_CELLS_PATH),
            "input_raw_localities": str(RAW_LOCALITIES_PATH),
            "aggregation_method": "Direct locality evidence aggregated to H3 resolution 7 with support-weighted metrics.",
            "h3_8_rollup_method": "Existing smoothed H3 resolution 8 cells are area-averaged within each H3 resolution 7 parent and kept as continuity features.",
            "smoothing_notes": "Direct H3-7 evidence is preserved; neighbor-smoothed H3-7 fields use decay 1 / (1 + grid_distance) with k=1.",
        },
    }


def smoothing_decay(distance):
    return 1.0 / (1.0 + distance)


def smoothed_hex7_values(records):
    direct = {}
    for record in records:
        direct[record["hex_id"]] = {
            "support_weight": safe_dict(record["market_insights"].get("support")).get(
                "total_support_weight", 0.0
            ),
            "metrics": {
                metric: safe_dict(record["market_insights"]["metrics"].get(metric)).get(
                    "weighted_avg"
                )
                for metric in DIRECT_METRICS
            },
            "budget_weights": record.get("budget_segment_weights") or {},
        }

    smoothed = {}
    for cell in direct:
        metric_acc = defaultdict(weighted_metric_empty)
        budget_acc = defaultdict(float)
        source_hexes = []
        for neighbor in h3.grid_disk(cell, SMOOTHING_K):
            if neighbor not in direct:
                continue
            try:
                distance = h3.grid_distance(cell, neighbor)
            except Exception:
                distance = SMOOTHING_K
            decay = smoothing_decay(distance)
            support = direct[neighbor]["support_weight"] or 1.0
            metric_weight = support * decay
            source_hexes.append(neighbor)
            for metric, value in direct[neighbor]["metrics"].items():
                add_weighted_metric(metric_acc[metric], value, metric_weight)
            for segment, weight in direct[neighbor]["budget_weights"].items():
                budget_acc[segment] += weight * decay

        budgets = budget_summary(budget_acc)
        smoothed[cell] = {
            "smoothing_k": SMOOTHING_K,
            "source_hex_count": len(source_hexes),
            "source_hexes": sorted(source_hexes),
            "metrics": {
                metric: finalize_weighted_metric(acc)["weighted_avg"]
                for metric, acc in metric_acc.items()
            },
            "budget_segments": budgets["shares"],
            "dominant_budget_segment": budgets["dominant_budget_segment"],
            "dominant_budget_share": budgets["dominant_budget_share"],
            "budget_entropy": budgets["budget_entropy"],
            "budget_classification": budgets["budget_classification"],
        }
    return smoothed


def flatten_record(record):
    metrics = record["market_insights"]["metrics"]
    support = record["market_insights"]["support"]
    inventory = record["market_insights"]["inventory"]
    budget = record["budget_segments"]
    child_rollup = record["child_h3_res_8"]
    child_metrics = safe_dict(child_rollup.get("rolled_up_smoothed_values")).get("metrics") or {}
    smoothed = record.get("smoothed_h3_res_7") or {}
    smoothed_metrics = safe_dict(smoothed.get("metrics"))
    dominant_neighbourhood = record.get("dominant_neighbourhood") or {}
    quality = record.get("quality") or {}

    return {
        "hex_id": record["hex_id"],
        "resolution": record["resolution"],
        "name": record["name"],
        "dominant_neighbourhood_name": dominant_neighbourhood.get("name"),
        "dominant_neighbourhood_share": dominant_neighbourhood.get("share"),
        "neighbourhood_count": len(record.get("neighbourhoods") or []),
        "quality_flags": ", ".join(quality.get("flags") or []),
        "out_of_bounds_locality_count": quality.get("out_of_bounds_locality_count"),
        "locality_count": support.get("locality_count"),
        "support_weight": support.get("total_support_weight"),
        "registry_count": support.get("registry_count"),
        "reviews_count": support.get("reviews_count"),
        "rent_total_count": inventory.get("rent_total_count"),
        "sale_total_count": inventory.get("sale_total_count"),
        "buy_total_count_excluding_land": inventory.get("buy_total_count_excluding_land"),
        "market_price_per_sqft": safe_dict(metrics.get("market_price_per_sqft")).get(
            "weighted_avg"
        ),
        "rental_yield_pct": safe_dict(metrics.get("rental_yield_pct")).get("weighted_avg"),
        "yearly_appreciation_pct": safe_dict(metrics.get("yearly_appreciation_pct")).get(
            "weighted_avg"
        ),
        "activity_score": safe_dict(metrics.get("activity_score")).get("weighted_avg"),
        "premium_lens_score": safe_dict(metrics.get("premium_lens_score")).get("weighted_avg"),
        "budget_share_affordable": budget.get("Affordable"),
        "budget_share_mid_segment": budget.get("Mid-Segment"),
        "budget_share_premium": budget.get("Premium"),
        "dominant_budget_segment": record.get("dominant_budget_segment"),
        "dominant_budget_share": record.get("dominant_budget_share"),
        "budget_entropy": record.get("budget_entropy"),
        "budget_classification": record.get("budget_classification"),
        "top_tags": ", ".join(tag["tag"] for tag in record.get("tags", [])[:5]),
        "localities": ", ".join(item["name"] or "" for item in record.get("localities", [])),
        "neighbourhoods": ", ".join(
            item["name"] or "" for item in record.get("neighbourhoods", [])
        ),
        "child_h3_res_8_count": child_rollup.get("child_count"),
        "rolled_h3_8_price_sqft": child_metrics.get("price_sqft"),
        "rolled_h3_8_high_income": child_metrics.get("high_income"),
        "rolled_h3_8_rental_yield": child_metrics.get("rental_yield"),
        "rolled_h3_8_activity_score": child_metrics.get("activity_score"),
        "rolled_h3_8_premium_lens_score": child_metrics.get("premium_lens_score"),
        "smoothed_h3_7_market_price_per_sqft": smoothed_metrics.get("market_price_per_sqft"),
        "smoothed_h3_7_activity_score": smoothed_metrics.get("activity_score"),
        "smoothed_h3_7_dominant_budget_segment": smoothed.get("dominant_budget_segment"),
        "smoothed_h3_7_dominant_budget_share": smoothed.get("dominant_budget_share"),
    }


def geojson_properties(record):
    metrics = record["market_insights"]["metrics"]
    support = record["market_insights"]["support"]
    inventory = record["market_insights"]["inventory"]
    budget = record["budget_segments"]
    dominant_neighbourhood = record.get("dominant_neighbourhood") or {}
    child_rollup = record["child_h3_res_8"]
    child_metrics = safe_dict(child_rollup.get("rolled_up_smoothed_values")).get("metrics") or {}
    quality = record.get("quality") or {}

    return {
        "name": record["name"],
        "dominant_neighbourhood": dominant_neighbourhood.get("name"),
        "dominant_neighbourhood_share": dominant_neighbourhood.get("share"),
        "neighbourhoods": ", ".join(
            item["name"] or "" for item in record.get("neighbourhoods", [])[:6]
        ),
        "quality_flags": ", ".join(quality.get("flags") or []),
        "out_of_bounds_locality_count": quality.get("out_of_bounds_locality_count"),
        "localities": ", ".join(item["name"] or "" for item in record.get("localities", [])[:10]),
        "locality_count": support.get("locality_count"),
        "support_weight": support.get("total_support_weight"),
        "market_price_per_sqft": safe_dict(metrics.get("market_price_per_sqft")).get(
            "weighted_avg"
        ),
        "rental_yield_pct": safe_dict(metrics.get("rental_yield_pct")).get("weighted_avg"),
        "yearly_appreciation_pct": safe_dict(metrics.get("yearly_appreciation_pct")).get(
            "weighted_avg"
        ),
        "activity_score": safe_dict(metrics.get("activity_score")).get("weighted_avg"),
        "premium_lens_score": safe_dict(metrics.get("premium_lens_score")).get("weighted_avg"),
        "rent_total_count": inventory.get("rent_total_count"),
        "sale_total_count": inventory.get("sale_total_count"),
        "buy_total_count_excluding_land": inventory.get("buy_total_count_excluding_land"),
        "budget_share_affordable": budget.get("Affordable"),
        "budget_share_mid_segment": budget.get("Mid-Segment"),
        "budget_share_premium": budget.get("Premium"),
        "dominant_budget_segment": record.get("dominant_budget_segment"),
        "dominant_budget_share": record.get("dominant_budget_share"),
        "budget_classification": record.get("budget_classification"),
        "budget_entropy": record.get("budget_entropy"),
        "tags": ", ".join(tag["tag"] for tag in record.get("tags", [])[:5]),
        "child_h3_res_8_count": child_rollup.get("child_count"),
        "rolled_h3_8_price_sqft": child_metrics.get("price_sqft"),
        "rolled_h3_8_activity_score": child_metrics.get("activity_score"),
    }


def write_outputs(records):
    PROCESSED_DATA_DIR.mkdir(exist_ok=True)
    AUDIT_DIR.mkdir(exist_ok=True)

    OUTPUT_JSON.write_text(json.dumps(records, indent=2, ensure_ascii=False))

    flat_rows = [flatten_record(record) for record in records]
    with OUTPUT_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(flat_rows[0].keys()))
        writer.writeheader()
        writer.writerows(flat_rows)

    features = [h3_feature(record["hex_id"], geojson_properties(record)) for record in records]
    OUTPUT_GEOJSON.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2)
    )


def validate_records(records, assigned_localities):
    invalid_resolution = []
    budget_sum_failures = []
    for record in records:
        try:
            if h3.get_resolution(record["hex_id"]) != H3_RESOLUTION:
                invalid_resolution.append(record["hex_id"])
        except Exception:
            invalid_resolution.append(record["hex_id"])
        share_sum = sum(record.get("budget_segments", {}).get(segment, 0.0) for segment in BUDGET_SEGMENTS)
        if record.get("dominant_budget_segment") != "unknown" and abs(share_sum - 1.0) > 0.000001:
            budget_sum_failures.append({"hex_id": record["hex_id"], "share_sum": share_sum})

    locality_assignment_count = sum(len(record.get("localities") or []) for record in records)
    return {
        "invalid_h3_resolution_count": len(invalid_resolution),
        "invalid_h3_resolution_examples": invalid_resolution[:10],
        "budget_share_sum_failure_count": len(budget_sum_failures),
        "budget_share_sum_failure_examples": budget_sum_failures[:10],
        "assigned_locality_count": locality_assignment_count,
        "expected_assigned_locality_count": assigned_localities,
        "locality_assignment_count_matches": locality_assignment_count == assigned_localities,
    }


def write_audit(records, source_counts, validation, missing_raw_ids, duplicate_raw_ids, h3_8_rollups):
    mixed_examples = [
        {
            "hex_id": record["hex_id"],
            "name": record["name"],
            "dominant_neighbourhood_share": (
                record.get("dominant_neighbourhood") or {}
            ).get("share"),
            "neighbourhoods": [
                {"name": item["name"], "share": item["share"]}
                for item in record.get("neighbourhoods", [])[:5]
            ],
            "budget_classification": record.get("budget_classification"),
        }
        for record in records
        if len(record.get("neighbourhoods") or []) > 1
    ][:20]

    audit = {
        "stage": "1.5",
        "h3_resolution": H3_RESOLUTION,
        "source_h3_resolution": SOURCE_H3_RESOLUTION,
        "smoothing_k": SMOOTHING_K,
        "neighbourhood_composite_min_share": NEIGHBOURHOOD_COMPOSITE_MIN_SHARE,
        "city_metro_bounds": CITY_METRO_BOUNDS,
        "inputs": {
            "stage1_localities": str(STAGE1_LOCALITIES_PATH),
            "stage1_h3_res_8_cells": str(STAGE1_H3_CELLS_PATH),
            "raw_localities": str(RAW_LOCALITIES_PATH),
        },
        "outputs": {
            "json": str(OUTPUT_JSON),
            "csv": str(OUTPUT_CSV),
            "geojson": str(OUTPUT_GEOJSON),
        },
        "source_counts": source_counts,
        "h3_8_rollup_parent_cells_loaded": len(h3_8_rollups),
        "output_h3_res_7_cells": len(records),
        "missing_raw_locality_ids": missing_raw_ids[:100],
        "missing_raw_locality_count": len(missing_raw_ids),
        "duplicate_raw_locality_ids": duplicate_raw_ids[:100],
        "duplicate_raw_locality_count": len(duplicate_raw_ids),
        "validation": validation,
        "quality_summary": {
            "records_with_quality_flags": sum(1 for record in records if record.get("quality", {}).get("flags")),
            "records_missing_stage1_h3_res_8_rollup": sum(
                1
                for record in records
                if "missing_stage1_h3_res_8_rollup" in record.get("quality", {}).get("flags", [])
            ),
            "records_with_out_of_bounds_localities": sum(
                1
                for record in records
                if "contains_out_of_bounds_localities" in record.get("quality", {}).get("flags", [])
            ),
            "out_of_bounds_examples": [
                {
                    "hex_id": record["hex_id"],
                    "name": record["name"],
                    "localities": [
                        {
                            "name": locality.get("name"),
                            "lat": locality.get("lat"),
                            "lon": locality.get("lon"),
                        }
                        for locality in record.get("localities", [])
                        if not locality.get("within_city_bounds")
                    ],
                }
                for record in records
                if "contains_out_of_bounds_localities" in record.get("quality", {}).get("flags", [])
            ][:20],
        },
        "mixed_neighbourhood_examples": mixed_examples,
    }
    AUDIT_PATH.write_text(json.dumps(audit, indent=2, ensure_ascii=False))


def main():
    stage_records = load_json(STAGE1_LOCALITIES_PATH)
    raw_records = load_json(RAW_LOCALITIES_PATH)
    if not isinstance(stage_records, list):
        raise ValueError(f"{STAGE1_LOCALITIES_PATH} must contain a top-level array.")
    if not isinstance(raw_records, list):
        raise ValueError(f"{RAW_LOCALITIES_PATH} must contain a top-level array.")

    raw_lookup, duplicate_raw_ids = build_raw_lookup(raw_records)
    h3_8_rollups = child_h3_8_rollups()
    groups = defaultdict(group_empty)
    missing_raw_ids = []
    assigned_localities = 0
    skipped_localities = 0

    for stage_record in stage_records:
        if add_locality_to_group(groups, stage_record, raw_lookup, missing_raw_ids):
            assigned_localities += 1
        else:
            skipped_localities += 1

    records = [
        finalize_group(hex_id, group, h3_8_rollups)
        for hex_id, group in sorted(groups.items())
    ]

    smoothed = smoothed_hex7_values(records)
    for record in records:
        record["smoothed_h3_res_7"] = smoothed.get(record["hex_id"], {})

    records.sort(key=lambda item: item["hex_id"])
    validation = validate_records(records, assigned_localities)
    write_outputs(records)
    write_audit(
        records,
        {
            "stage1_locality_records": len(stage_records),
            "raw_locality_records": len(raw_records),
            "assigned_localities": assigned_localities,
            "skipped_localities": skipped_localities,
            "stage1_h3_res_8_cells": sum(
                1
                for record in stage_records
                if safe_dict(record.get("locality")).get("h3_res_8")
            ),
        },
        validation,
        missing_raw_ids,
        duplicate_raw_ids,
        h3_8_rollups,
    )

    print(f"Wrote {OUTPUT_JSON} ({len(records)} H3-7 records)")
    print(f"Wrote {OUTPUT_CSV}")
    print(f"Wrote {OUTPUT_GEOJSON}")
    print(f"Wrote {AUDIT_PATH}")


if __name__ == "__main__":
    main()
