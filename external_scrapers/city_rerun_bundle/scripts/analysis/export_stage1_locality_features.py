import csv
import json
import os
import re
from pathlib import Path

import h3


CITY_SLUG = os.environ.get("CITY_SLUG", "bangalore").strip().lower().replace(" ", "-")
DATA_DIR = Path("DATA")
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
AUDIT_DIR = DATA_DIR / "audits"
LOCALITIES_PATH = RAW_DATA_DIR / f"{CITY_SLUG}_localities_enriched.json"
H3_CELLS_PATH = PROCESSED_DATA_DIR / f"{CITY_SLUG}_h3_heatmap_cells.geojson"
OUTPUT_JSONL = PROCESSED_DATA_DIR / f"{CITY_SLUG}_stage1_locality_features.jsonl"
OUTPUT_JSON = PROCESSED_DATA_DIR / f"{CITY_SLUG}_stage1_locality_features.json"
OUTPUT_CSV = PROCESSED_DATA_DIR / f"{CITY_SLUG}_stage1_locality_features_flat.csv"
AUDIT_PATH = AUDIT_DIR / f"{CITY_SLUG}_stage1_locality_features_audit.json"


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


def parse_range(value):
    if value is None:
        return {"min": None, "max": None, "raw": None}
    if isinstance(value, (int, float)):
        number = float(value)
        return {"min": number, "max": number, "raw": value}
    if isinstance(value, str):
        matches = re.findall(r"\d+", value.replace(",", ""))
        if len(matches) >= 2:
            return {"min": float(matches[0]), "max": float(matches[1]), "raw": value}
        if len(matches) == 1:
            number = float(matches[0])
            return {"min": number, "max": number, "raw": value}
    return {"min": None, "max": None, "raw": value}


def load_h3_scores():
    if not H3_CELLS_PATH.exists():
        return {}
    with H3_CELLS_PATH.open("r") as f:
        feature_collection = json.load(f)

    scores = {}
    for feature in feature_collection.get("features", []):
        props = dict(feature.get("properties") or {})
        cell = props.get("h3_cell")
        if not cell:
            continue
        for key in ("budget_weights", "budget_shares"):
            if isinstance(props.get(key), str):
                try:
                    props[key] = json.loads(props[key])
                except json.JSONDecodeError:
                    props[key] = {}
        scores[cell] = props
    return scores


def extract_count_range_map(section):
    output = {}
    for name, item in safe_dict(section).items():
        item = safe_dict(item)
        output[name] = {
            "count": clean_numeric(item.get("count")),
            "price_range": parse_range(item.get("price_range")),
        }
    return output


def exclude_property_types(mix, excluded_types):
    excluded_normalized = {item.lower() for item in excluded_types}
    return {
        name: value
        for name, value in safe_dict(mix).items()
        if str(name).lower() not in excluded_normalized
    }


def sum_mix_counts(mix):
    total = 0.0
    for item in safe_dict(mix).values():
        count = clean_numeric(safe_dict(item).get("count"))
        if count is not None:
            total += count
    return total


def extract_bhk_mix(transaction_section):
    output = {}
    for bhk, item in safe_dict(safe_dict(transaction_section).get("bhk_details")).items():
        item = safe_dict(item)
        output[bhk] = {
            "total_count": clean_numeric(item.get("total_count")),
            "price_range": parse_range(item.get("price_range")),
            "posted_by": extract_count_range_map(item.get("posted_by")),
            "price_buckets": extract_count_range_map(item.get("price_buckets")),
        }
    return output


def extract_price_bucket_distribution(transaction_section):
    bhk_0 = safe_dict(safe_dict(safe_dict(transaction_section).get("bhk_details")).get("bhk_0"))
    return extract_count_range_map(bhk_0.get("price_buckets"))


def build_record(raw_record, idx, h3_scores):
    locality_info = safe_dict(raw_record.get("locality_info"))
    market = safe_dict(raw_record.get("market_insights"))
    income = safe_dict(raw_record.get("income_analytics"))
    inventory = safe_dict(raw_record.get("inventory"))
    trends = safe_dict(raw_record.get("trends"))
    geocoding = safe_dict(raw_record.get("geocoding_details"))
    overture = safe_dict(raw_record.get("overture_neighborhood"))

    locality_id = locality_info.get("id") or locality_info.get("locality_id") or f"loc_{idx}"
    coords = safe_dict(locality_info.get("coordinates"))
    lat = clean_numeric(coords.get("latitude"))
    lon = clean_numeric(coords.get("longitude"))
    h3_res_8 = None
    h3_scores_res_8 = {}
    if lat is not None and lon is not None:
        h3_res_8 = h3.latlng_to_cell(lat, lon, 8)
        h3_scores_res_8 = h3_scores.get(h3_res_8, {})
    else:
        h3_scores_res_8 = {}

    h3_budget_segment = {
        "dominant_budget_segment": h3_scores_res_8.get("dominant_budget_segment"),
        "dominant_budget_share": h3_scores_res_8.get("dominant_budget_share"),
        "budget_entropy": h3_scores_res_8.get("budget_entropy"),
        "budget_shares": {
            "Affordable": h3_scores_res_8.get("budget_share_affordable"),
            "Mid-Segment": h3_scores_res_8.get("budget_share_mid_segment"),
            "Premium": h3_scores_res_8.get("budget_share_premium"),
        },
        "budget_weights": h3_scores_res_8.get("budget_weights"),
    }

    rent = safe_dict(inventory.get("rent"))
    sale = safe_dict(inventory.get("sale"))
    sale_property_type_mix = extract_count_range_map(sale.get("property_types"))
    buy_property_type_mix_excluding_land = exclude_property_types(
        sale_property_type_mix,
        {"Land"},
    )
    buy_total_count_excluding_land = sum_mix_counts(buy_property_type_mix_excluding_land)

    record = {
        "locality": {
            "id": locality_id,
            "name": locality_info.get("name"),
            "city": locality_info.get("city"),
            "zone": safe_dict(locality_info.get("zone")).get("name"),
            "zone_id": safe_dict(locality_info.get("zone")).get("id"),
            "lat": lat,
            "lon": lon,
            "h3_res_8": h3_res_8,
        },
        "raw_market": {
            "price_per_sqft_raw": market.get("price_per_sqft"),
            "market_price_per_sqft": clean_numeric(
                market.get("market_price_per_sqft") or market.get("price_per_sqft")
            ),
            "rental_yield_raw": market.get("rental_yield"),
            "rental_yield_pct": clean_numeric(
                market.get("rental_yield_pct") or market.get("rental_yield")
            ),
            "yearly_appreciation_raw": market.get("yearly_appreciation"),
            "yearly_appreciation_pct": clean_numeric(
                market.get("yearly_appreciation_pct") or market.get("yearly_appreciation")
            ),
        },
        "support": {
            "registry_count": clean_numeric(market.get("registry_count")),
            "reviews_count": clean_numeric(market.get("reviews_count")),
            "geocoding_found": geocoding.get("found"),
            "has_overture_polygon": bool(overture.get("perimeter_coordinates")),
        },
        "inventory": {
            "rent_total_count": clean_numeric(rent.get("total_count")),
            "sale_total_count": clean_numeric(sale.get("total_count")),
            "rent_property_type_mix": extract_count_range_map(rent.get("property_types")),
            "sale_property_type_mix": sale_property_type_mix,
            "rent_bhk_mix": extract_bhk_mix(rent),
            "sale_bhk_mix": extract_bhk_mix(sale),
            "rent_price_bucket_distribution": extract_price_bucket_distribution(rent),
            "sale_price_bucket_distribution": extract_price_bucket_distribution(sale),
            "buy_total_count_excluding_land": buy_total_count_excluding_land,
            "buy_property_type_mix_excluding_land": buy_property_type_mix_excluding_land,
            "buy_bhk_mix": extract_bhk_mix(sale),
            "buy_price_bucket_distribution": extract_price_bucket_distribution(sale),
            "buy_excluded_property_types": ["Land"],
        },
        "h3_hex_scores": h3_scores_res_8,
        "h3_budget_segment": h3_budget_segment,
        "non_raw_labels": {
            "budget_segment": market.get("budget_segment"),
            "budget_segment_source": market.get("budget_segment_source"),
            "budget_segment_confidence": clean_numeric(market.get("budget_segment_confidence")),
            "income_distribution": income.get("distribution"),
            "dominant_income_bracket": income.get("dominant_income_bracket"),
            "income_analytics_source": income.get("source"),
            "average_price_by_bhk": safe_dict(trends.get("average_price_by_bhk")),
            "appreciation_history": safe_dict(trends.get("appreciation_history")),
            "tags": market.get("tags"),
            "rankings": market.get("rankings"),
        },
        "provenance": {
            "source_file": str(LOCALITIES_PATH),
            "h3_score_source_file": str(H3_CELLS_PATH),
            "notes": [
                "income_analytics is a derived/pseudo-label field, not raw ground truth.",
                "budget_segment is mixed provenance; inspect budget_segment_source before training.",
                "h3_res_8 is the only exported H3 ID because current hex scoring is computed at resolution 8.",
                "h3_hex_scores and h3_budget_segment are smoothed/derived features from generate_h3_heatmaps.py.",
            ],
        },
    }
    return record


def flatten_record(record):
    locality = record["locality"]
    raw_market = record["raw_market"]
    support = record["support"]
    inventory = record["inventory"]
    labels = record["non_raw_labels"]
    h3_scores = safe_dict(record["h3_hex_scores"])
    h3_budget = safe_dict(record.get("h3_budget_segment"))
    h3_budget_shares = safe_dict(h3_budget.get("budget_shares"))
    income_distribution = safe_dict(labels.get("income_distribution"))

    return {
        "locality_id": locality.get("id"),
        "locality_name": locality.get("name"),
        "city": locality.get("city"),
        "zone": locality.get("zone"),
        "zone_id": locality.get("zone_id"),
        "lat": locality.get("lat"),
        "lon": locality.get("lon"),
        "h3_res_8": locality.get("h3_res_8"),
        "market_price_per_sqft": raw_market.get("market_price_per_sqft"),
        "rental_yield_pct": raw_market.get("rental_yield_pct"),
        "yearly_appreciation_pct": raw_market.get("yearly_appreciation_pct"),
        "rent_total_count": inventory.get("rent_total_count"),
        "sale_total_count": inventory.get("sale_total_count"),
        "buy_total_count_excluding_land": inventory.get("buy_total_count_excluding_land"),
        "registry_count": support.get("registry_count"),
        "reviews_count": support.get("reviews_count"),
        "geocoding_found": support.get("geocoding_found"),
        "has_overture_polygon": support.get("has_overture_polygon"),
        "budget_segment": labels.get("budget_segment"),
        "budget_segment_source": labels.get("budget_segment_source"),
        "budget_segment_confidence": labels.get("budget_segment_confidence"),
        "dominant_income_bracket": labels.get("dominant_income_bracket"),
        "income_analytics_source": labels.get("income_analytics_source"),
        "income_low": income_distribution.get("low"),
        "income_lower_middle": income_distribution.get("lower_middle"),
        "income_middle": income_distribution.get("middle"),
        "income_upper_middle": income_distribution.get("upper_middle"),
        "income_high": income_distribution.get("high"),
        "h3_price_sqft": h3_scores.get("price_sqft"),
        "h3_high_income": h3_scores.get("high_income"),
        "h3_rental_yield": h3_scores.get("rental_yield"),
        "h3_activity_score": h3_scores.get("activity_score"),
        "h3_premium_lens_score": h3_scores.get("premium_lens_score"),
        "h3_budget_segment": h3_budget.get("dominant_budget_segment"),
        "h3_dominant_budget_segment": h3_budget.get("dominant_budget_segment"),
        "h3_dominant_budget_share": h3_budget.get("dominant_budget_share"),
        "h3_budget_entropy": h3_budget.get("budget_entropy"),
        "h3_budget_share_affordable": h3_budget_shares.get("Affordable"),
        "h3_budget_share_mid_segment": h3_budget_shares.get("Mid-Segment"),
        "h3_budget_share_premium": h3_budget_shares.get("Premium"),
    }


def write_outputs(records):
    OUTPUT_JSONL.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n")
    OUTPUT_JSON.write_text(json.dumps(records, indent=2, ensure_ascii=False))

    flat_rows = [flatten_record(record) for record in records]
    with OUTPUT_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(flat_rows[0].keys()))
        writer.writeheader()
        writer.writerows(flat_rows)


def main():
    with LOCALITIES_PATH.open("r") as f:
        raw_localities = json.load(f)
    if not isinstance(raw_localities, list):
        raise ValueError(f"{LOCALITIES_PATH} must contain a top-level array.")

    h3_scores = load_h3_scores()
    records = [
        build_record(raw_record, idx, h3_scores)
        for idx, raw_record in enumerate(raw_localities)
    ]
    write_outputs(records)

    audit = {
        "source_records": len(raw_localities),
        "exported_records": len(records),
        "h3_score_cells_loaded": len(h3_scores),
        "outputs": {
            "jsonl": str(OUTPUT_JSONL),
            "json": str(OUTPUT_JSON),
            "csv": str(OUTPUT_CSV),
        },
        "schema_notes": {
            "jsonl_json": "Nested model-ready locality records with raw inputs, inventory mixes, H3 res 8 ID, H3 scores, H3 budget segment, and provenance.",
            "csv": "Flattened inspection table; nested mix distributions remain in JSON/JSONL.",
            "h3_resolution": "Only H3 resolution 8 is exported because the active H3 scoring pipeline is computed at res 8.",
            "buy_inventory": "buy_* fields are derived from inventory.sale with Land excluded from property type totals/mixes.",
        },
    }
    AUDIT_PATH.write_text(json.dumps(audit, indent=2))
    print(f"Wrote {OUTPUT_JSONL}")
    print(f"Wrote {OUTPUT_JSON}")
    print(f"Wrote {OUTPUT_CSV}")
    print(f"Wrote {AUDIT_PATH}")


if __name__ == "__main__":
    main()
