#!/usr/bin/env python3
import json
import os
import h3
from pathlib import Path
from collections import defaultdict

RAW_DIR = Path("/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/DATA/raw")
OUT_DIR = Path("/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/src/static/data")

CITIES = ["delhi_ncr", "mumbai", "hyderabad", "chennai", "kolkata", "pune"]

def get_budget_segment(price):
    if price is None or price == 0:
        return "Mid-Segment"
    if price < 5000:
        return "Value"
    elif price < 10000:
        return "Mid-Segment"
    elif price < 20000:
        return "Premium"
    else:
        return "Luxury"

def get_zone_placeholder(lat, lon, city_id):
    # Simple coordinates based zone estimation as fallback
    # In a real environment, this can be mapped using boundary polygons or H3 resolution
    return "Central"

def process_city(city_id):
    input_file = RAW_DIR / f"{city_id}_projects_enriched_and_geocoded.jsonl"
    output_file = OUT_DIR / f"localities_{city_id}.json"

    if not input_file.exists():
        print(f"[Error] Enriched projects file {input_file} not found. Skipping.")
        return

    # Group projects by locality name
    locality_data = defaultdict(list)
    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                project = json.loads(line)
                loc_name = project.get("lmtDName")
                if loc_name:
                    locality_data[loc_name].append(project)

    localities_list = []
    for loc_name, projects in locality_data.items():
        # Filter projects with valid coordinates
        valid_coords = [p for p in projects if p.get("latitude") is not None and p.get("longitude") is not None]
        if not valid_coords:
            continue

        # Centroid
        avg_lat = sum(float(p["latitude"]) for p in valid_coords) / len(valid_coords)
        avg_lon = sum(float(p["longitude"]) for p in valid_coords) / len(valid_coords)

        # Average price
        prices = []
        for p in projects:
            price = p.get("sqFtPrice") or p.get("sqFtPrMx") or p.get("minPrice") or p.get("maxPrice")
            # If price is large (e.g. total project price), ignore or normalize, we want sqft price
            sqft_p = p.get("sqFtPrice") or p.get("sqFtPrMx")
            if sqft_p and sqft_p > 0:
                prices.append(float(sqft_p))

        avg_price = sum(prices) / len(prices) if prices else None
        
        # H3 hex resolution (resolution 8, typical for localities)
        hex_id = h3.latlng_to_cell(avg_lat, avg_lon, 8)

        localities_list.append({
            "name": loc_name,
            "lat": round(avg_lat, 5),
            "lon": round(avg_lon, 5),
            "price_sqft": round(avg_price, 2) if avg_price else None,
            "budget_segment": get_budget_segment(avg_price),
            "hex_id": hex_id,
            "zone": get_zone_placeholder(avg_lat, avg_lon, city_id)
        })

    # Save to src/static/data/localities_<city_id>.json
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(localities_list, f, indent=2)

    print(f"Generated {len(localities_list)} localities for {city_id} -> {output_file}")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for city in CITIES:
        process_city(city)

if __name__ == "__main__":
    main()
