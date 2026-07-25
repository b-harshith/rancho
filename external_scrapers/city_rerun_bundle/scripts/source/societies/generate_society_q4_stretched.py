import json
import os
import re
from pathlib import Path

import numpy as np

CITY_SLUG = os.environ.get("CITY_SLUG", "bangalore").strip().lower().replace(" ", "-")
CITY_NAME = os.environ.get("CITY_NAME", CITY_SLUG.replace("-", " ").title())

def parse_configurations(s):
    prop_count = s.get("propCount") or {}
    bhk_keys = set()
    for mode in ["S", "R"]:
        bhk_dict = prop_count.get(mode, {}).get("bhk")
        if isinstance(bhk_dict, dict):
            for k in bhk_dict.keys():
                if k != "0" and k.isdigit():
                    bhk_keys.add(int(k))
    if bhk_keys:
        return ", ".join(f"{k} BHK" for k in sorted(list(bhk_keys)))
    return "NA"

def parse_property_types(s):
    prop_count = s.get("propCount") or {}
    types = set()
    for mode in ["S", "R"]:
        ptype_dict = prop_count.get(mode, {}).get("propType")
        if isinstance(ptype_dict, dict):
            for k in ptype_dict.keys():
                if k:
                    types.add(k)
    if types:
        return ", ".join(sorted(list(types)))
    return "NA"

def parse_listed_count(s):
    prop_count = s.get("propCount") or {}
    s_count = 0
    r_count = 0
    if isinstance(prop_count.get("S"), dict):
        s_count = prop_count["S"].get("count") or 0
    if isinstance(prop_count.get("R"), dict):
        r_count = prop_count["R"].get("count") or 0
    return s_count + r_count

def main():
    json_path = f"data/99acres_{CITY_SLUG}_societies.json"
    with open(json_path, "r", encoding="utf-8") as f:
        societies = json.load(f)
        
    valid_societies = []
    max_prices = []
    for s in societies:
        max_p = s.get("rei", {}).get("sale", {}).get("price", {}).get("max")
        if max_p is not None and max_p > 0:
            valid_societies.append(s)
            max_prices.append(max_p)
            
    if not max_prices:
        print("No valid sale prices found.")
        return
        
    original_q3 = 21000000.0 # original threshold
    new_threshold = 15000000.0 # 1.5 Cr
    
    # Filter by new stretched threshold
    stretched_societies = [s for s in valid_societies if s["rei"]["sale"]["price"]["max"] >= new_threshold]
    # Sort descending by max price
    stretched_societies.sort(key=lambda x: x["rei"]["sale"]["price"]["max"], reverse=True)
    
    # Categorize:
    # - Ultra Luxury: >= 4.5 Cr
    # - Super Luxury: 3.0 Cr - 4.5 Cr
    # - Luxury: 2.6 Cr - 3.0 Cr
    # - Premium: 2.1 Cr - 2.6 Cr
    # - Stretched Premium (Special Tag: "Aspirational Premium"): 1.5 Cr - 2.1 Cr
    categorized = []
    for s in stretched_societies:
        max_p = s["rei"]["sale"]["price"]["max"]
        if max_p >= 45000000.0:
            cat = "Ultra Luxury"
        elif max_p >= 30000000.0:
            cat = "Super Luxury"
        elif max_p >= 26000000.0:
            cat = "Luxury"
        elif max_p >= original_q3:
            cat = "Premium"
        else:
            cat = "Aspirational Premium" # Special Tag for Stretched Segment
            
        s["Q4 Category"] = cat
        categorized.append(s)
        
    # Write to JSON (Overwrite)
    json_output_path = f"data/q4_categorized_societies_{CITY_SLUG}.json"
    json_data = []
    for s in categorized:
        location_info = s.get("location", {})
        price_sqft = s.get("rei", {}).get("sale", {}).get("pricePerSqFt") or s.get("priceTrends", {}).get("resaleIncome") or "NA"
        
        json_data.append({
            "Society Name": s["name"],
            "URL": f"https://www.99acres.com{s['seoContent']['url']}" if s.get("seoContent", {}).get("url") else "NA",
            "Locality": location_info.get("localityName", "NA"),
            "Micro Market": location_info.get("microMarketName", "NA"),
            "Latitude": location_info.get("latitude", "NA"),
            "Longitude": location_info.get("longitude", "NA"),
            "Min Price": s["rei"]["sale"]["price"].get("min", 0),
            "Max Price": s["rei"]["sale"]["price"].get("max", 0),
            "Avg Price per SqFt": price_sqft,
            "Listed Units Count": parse_listed_count(s),
            "Configurations": parse_configurations(s),
            "Property Types": parse_property_types(s),
            "Q4 Category": s["Q4 Category"],
            "Appreciation 1Y (%)": s.get("priceTrends", {}).get("appreciationY", "NA")
        })
        
    with open(json_output_path, "w", encoding="utf-8") as jf:
        json.dump(json_data, jf, indent=2)
        
    # Write to Markdown Artifact (Overwrite)
    artifact_path = Path("reports") / f"{CITY_SLUG}_q4_categorized_societies_stretched.md"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Calculate counts and units
    counts = {"Ultra Luxury": 0, "Super Luxury": 0, "Luxury": 0, "Premium": 0, "Aspirational Premium": 0}
    units_counts = {"Ultra Luxury": 0, "Super Luxury": 0, "Luxury": 0, "Premium": 0, "Aspirational Premium": 0}
    
    for s in json_data:
        cat = s["Q4 Category"]
        counts[cat] += 1
        units_counts[cat] += s["Listed Units Count"]
        
    with open(artifact_path, "w", encoding="utf-8") as out:
        out.write(f"# Categorized Q4 Premium & Luxury Societies ({CITY_NAME}) - Stretched Bracket\n\n")
        out.write(f"This document breaks down the **{len(json_data)}** residential societies inside our stretched premium bracket (Max listing price >= **INR 1.5 Crore**) into five luxury tiers. This includes the special **Aspirational Premium** segment added by stretching the boundary from 2.1 Cr down to 1.5 Cr:\n\n")
        out.write(f"1. **Ultra Luxury** (Max Purchase Price >= INR 4.5 Crore)\n")
        out.write(f"2. **Super Luxury** (Max Purchase Price INR 3.0 Crore - 4.5 Crore)\n")
        out.write(f"3. **Luxury** (Max Purchase Price INR 2.6 Crore - 3.0 Crore)\n")
        out.write(f"4. **Premium** (Max Purchase Price INR 2.1 Crore - 2.6 Crore)\n")
        out.write(f"5. **Aspirational Premium** (Special Tag - Stretched Segment: Max Purchase Price INR 1.5 Crore - 2.1 Crore)\n\n")
        
        out.write("## Distribution Summary\n\n")
        out.write("| Category | Price Range | Count of Societies | Total Listed Units |\n")
        out.write("|---|---|---|---|\n")
        for cat in ["Ultra Luxury", "Super Luxury", "Luxury", "Premium", "Aspirational Premium"]:
            rng = ">= 4.5 Crore" if cat == "Ultra Luxury" else "3.0 - 4.5 Crore" if cat == "Super Luxury" else "2.6 - 3.0 Crore" if cat == "Luxury" else "2.1 - 2.6 Crore" if cat == "Premium" else "1.5 - 2.1 Crore"
            out.write(f"| **{cat}** | Max Price: {rng} | {counts[cat]} | {units_counts[cat]:,} units |\n")
            
        out.write("\n## Full Categorized Society List\n\n")
        out.write("| # | Society Name | Locality | Micro Market | Max Price | Category | Price/SqFt (Avg) | Configurations | Listed Units | Latitude | Longitude | Profile URL |\n")
        out.write("|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        for idx, h in enumerate(json_data):
            price_sqft_str = f"INR {h['Avg Price per SqFt']:,}" if isinstance(h['Avg Price per SqFt'], (int, float)) else "NA"
            out.write(f"| {idx+1} | {h['Society Name']} | {h['Locality']} | {h['Micro Market']} | INR {h['Max Price']:,} | **{h['Q4 Category']}** | {price_sqft_str} | {h['Configurations']} | {h['Listed Units Count']} | {h['Latitude']} | {h['Longitude']} | [99acres Profile]({h['URL']}) |\n")
            
    print(f"Stretched society analysis completed: {len(json_data)} societies written to JSON and Markdown.")

if __name__ == "__main__":
    main()
