import json
import os
import re
from pathlib import Path

import numpy as np

CITY_SLUG = os.environ.get("CITY_SLUG", "bangalore").strip().lower().replace(" ", "-")
CITY_NAME = os.environ.get("CITY_NAME", CITY_SLUG.replace("-", " ").title())

def extract_beds(desc):
    if not desc:
        return "NA"
    m1 = re.search(r"(\d+)\s*-?\s*bedded", desc, re.IGNORECASE)
    m2 = re.search(r"capacity of\s*(\d+)\s*bed", desc, re.IGNORECASE)
    m3 = re.search(r"(\d+)\s*beds?\b", desc, re.IGNORECASE)
    if m1:
        return int(m1.group(1))
    elif m2:
        return int(m2.group(1))
    elif m3:
        val = int(m3.group(1))
        if 5 <= val <= 2000:
            return val
    return "NA"

def main():
    json_path = f"data/practo_hospitals_{CITY_SLUG}.json"
    with open(json_path, "r", encoding="utf-8") as f:
        hospitals = json.load(f)
        
    valid_hospitals = []
    prices = []
    for h in hospitals:
        max_p = h.get("max_price")
        if max_p is not None and max_p > 0:
            valid_hospitals.append(h)
            prices.append(max_p)
            
    if not prices:
        print("No valid prices found.")
        return
        
    q3 = np.percentile(prices, 75)
    print(f"Global Q3 threshold (75th percentile of max consultation fee): INR {q3:,.2f}")
    
    q4_hospitals = [h for h in valid_hospitals if h["max_price"] >= q3]
    # Sort descending by max price
    q4_hospitals.sort(key=lambda x: (x["max_price"], x.get("doctors_count", 0)), reverse=True)
    
    # Categorize based on max consultation fee:
    # - Ultra Premium: >= 1500
    # - Super Premium: 1200 - 1499
    # - Premium: 1050 - 1199
    # - Mid-Premium: exactly 1000
    categorized = []
    for h in q4_hospitals:
        fee = h["max_price"]
        if fee >= 1500:
            cat = "Ultra Premium"
        elif fee >= 1200:
            cat = "Super Premium"
        elif fee >= 1050:
            cat = "Premium"
        else:
            cat = "Mid-Premium"
            
        desc = h.get("schema", {}).get("description", "") or ""
        beds = extract_beds(desc)
        
        h["Q4 Category"] = cat
        h["Extracted Beds"] = beds
        categorized.append(h)
        
    # Write to JSON
    json_output_path = f"data/q4_categorized_hospitals_{CITY_SLUG}.json"
    json_data = []
    for h in categorized:
        json_data.append({
            "Hospital Name": h["name"],
            "Slug": h["slug"],
            "URL": f"https://www.practo.com{h['profile_url']}" if h.get("profile_url") else "NA",
            "Locality": h.get("locality", "NA"),
            "Latitude": h.get("latitude", "NA"),
            "Longitude": h.get("longitude", "NA"),
            "Min Consultation Fee": h.get("min_price", 0),
            "Max Consultation Fee": h.get("max_price", 0),
            "Doctors Count": h.get("doctors_count", 0),
            "Extracted Beds": h["Extracted Beds"],
            "Q4 Category": h["Q4 Category"],
            "Rating": h.get("rating", "NA"),
            "Reviews Count": h.get("reviews_count", 0),
            "Multispeciality Text": h.get("multispeciality_text", "NA"),
            "Timings": h.get("practice_timings", "NA")
        })
        
    with open(json_output_path, "w", encoding="utf-8") as jf:
        json.dump(json_data, jf, indent=2)
        
    # Write to Markdown Artifact
    artifact_path = Path("reports") / f"{CITY_SLUG}_q4_categorized_hospitals.md"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Calculate counts, doctors, and beds
    counts = {"Ultra Premium": 0, "Super Premium": 0, "Premium": 0, "Mid-Premium": 0}
    docs_counts = {"Ultra Premium": 0, "Super Premium": 0, "Premium": 0, "Mid-Premium": 0}
    beds_counts = {"Ultra Premium": 0, "Super Premium": 0, "Premium": 0, "Mid-Premium": 0}
    beds_known_schools = {"Ultra Premium": 0, "Super Premium": 0, "Premium": 0, "Mid-Premium": 0}
    
    for h in json_data:
        cat = h["Q4 Category"]
        counts[cat] += 1
        docs_counts[cat] += h["Doctors Count"]
        if h["Extracted Beds"] != "NA":
            beds_counts[cat] += h["Extracted Beds"]
            beds_known_schools[cat] += 1
            
    with open(artifact_path, "w", encoding="utf-8") as out:
        out.write(f"# Categorized Q4 Premium Hospitals ({CITY_NAME})\n\n")
        out.write(f"This document breaks down the **{len(json_data)}** Q4 hospitals (top 25% by consultation fee, threshold: **>= INR {q3:,.2f}**) into four sub-quartiles with corresponding premium labels:\n\n")
        out.write(f"1. **Ultra Premium** (Max Consultation Fee >= INR 1,500)\n")
        out.write(f"2. **Super Premium** (Max Consultation Fee INR 1,200 - 1,499)\n")
        out.write(f"3. **Premium** (Max Consultation Fee INR 1,050 - 1,199)\n")
        out.write(f"4. **Mid-Premium** (Max Consultation Fee exactly INR 1,000)\n\n")
        
        out.write("## Distribution Summary\n\n")
        out.write("| Category | Fee Range (Annual Max Fee equivalent) | Count of Hospitals | Total Doctors | Known Beds Sum (Hospitals count) |\n")
        out.write("|---|---|---|---|---|\n")
        for cat in ["Ultra Premium", "Super Premium", "Premium", "Mid-Premium"]:
            out.write(f"| **{cat}** | Max Fee: {'>= INR 1,500' if cat == 'Ultra Premium' else 'INR 1,200 - 1,499' if cat == 'Super Premium' else 'INR 1,050 - 1,199' if cat == 'Premium' else 'INR 1,000'} | {counts[cat]} | {docs_counts[cat]:,} | {beds_counts[cat]:,} beds ({beds_known_schools[cat]} hospitals) |\n")
            
        out.write("\n## Full Categorized Hospital List\n\n")
        out.write("| # | Hospital Name | Locality | Max Consultation Fee | Category | Doctors Count | Bed Count (Est.) | Rating | Reviews | Latitude | Longitude | Practo Profile URL |\n")
        out.write("|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        for idx, h in enumerate(json_data):
            out.write(f"| {idx+1} | {h['Hospital Name']} | {h['Locality']} | INR {h['Max Consultation Fee']:,} | **{h['Q4 Category']}** | {h['Doctors Count']} | {h['Extracted Beds']} | {h['Rating']} | {h['Reviews Count']} | {h['Latitude']} | {h['Longitude']} | [Practo Profile]({h['URL']}) |\n")
            
    print(f"Hospital analysis completed: {len(json_data)} premium hospitals written.")

if __name__ == "__main__":
    main()
