import json

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
    with open("data/99acres_bangalore_societies.json", "r", encoding="utf-8") as f:
        societies = json.load(f)
        
    q4_names = set()
    q4 = [s for s in societies if "rei" in s and "sale" in s["rei"] and "price" in s["rei"]["sale"] and "max" in s["rei"]["sale"]["price"] and s["rei"]["sale"]["price"]["max"] is not None and s["rei"]["sale"]["price"]["max"] >= 21000000.0]
    for s in q4:
        q4_names.add(s["name"])
        
    excluded = []
    for s in societies:
        sale_seg = s.get("rei", {}).get("sale", {}).get("microMarket", {}).get("segmentation")
        rent_seg = s.get("rei", {}).get("rent", {}).get("microMarket", {}).get("segmentation")
        is_prem = (sale_seg == "PREMIUM" or rent_seg == "PREMIUM")
        
        if is_prem and s["name"] not in q4_names:
            location_info = s.get("location", {})
            max_p = s.get("rei", {}).get("sale", {}).get("price", {}).get("max")
            
            # Exclusion reason
            if max_p is None or max_p <= 0:
                reason = "No Sale Price Data"
            else:
                reason = f"Max Price < 2.1 Cr (INR {max_p/10000000:.2f} Cr)"
                
            # Rent price range
            rent_min = s.get("rei", {}).get("rent", {}).get("price", {}).get("min")
            rent_max = s.get("rei", {}).get("rent", {}).get("price", {}).get("max")
            if rent_min is not None and rent_max is not None:
                rent_range = f"INR {rent_min:,.0f} - {rent_max:,.0f}"
            else:
                rent_range = "NA"
                
            price_sqft = s.get("rei", {}).get("sale", {}).get("pricePerSqFt") or s.get("priceTrends", {}).get("resaleIncome") or "NA"
            
            excluded.append({
                "Society Name": s["name"],
                "URL": f"https://www.99acres.com{s['seoContent']['url']}" if s.get("seoContent", {}).get("url") else "NA",
                "Locality": location_info.get("localityName", "NA"),
                "Micro Market": location_info.get("microMarketName", "NA"),
                "Latitude": location_info.get("latitude", "NA"),
                "Longitude": location_info.get("longitude", "NA"),
                "Max Sale Price": max_p if max_p else "NA",
                "Avg Price per SqFt": price_sqft,
                "Rent Range (Monthly)": rent_range,
                "Sale Tag": sale_seg or "None",
                "Rent Tag": rent_seg or "None",
                "Exclusion Reason": reason,
                "Listed Units Count": parse_listed_count(s)
            })
            
    # Sort by listed units count or max sale price
    excluded.sort(key=lambda x: (x["Max Sale Price"] if isinstance(x["Max Sale Price"], (int, float)) else 0), reverse=True)
    
    # Save as JSON document
    json_output_path = "data/excluded_premium_societies_bangalore.json"
    with open(json_output_path, "w", encoding="utf-8") as jf:
        json.dump(excluded, jf, indent=2)
        
    # Save as Markdown Artifact
    artifact_path = "/Users/malleswararao/.gemini/antigravity-ide/brain/5ad9d68c-7c50-4a98-8496-16e26f027f49/excluded_premium_societies.md"
    with open(artifact_path, "w", encoding="utf-8") as out:
        out.write(f"# Excluded Premium Societies (Bangalore)\n\n")
        out.write(f"This document lists all **{len(excluded)}** societies that are tagged as **`PREMIUM`** (for Sale or Rent) by 99acres but did not meet the Q4 Max Purchase Price threshold of **INR 2.1 Crore** (or lacked valid transaction price data).\n\n")
        
        out.write("## Reasons for Exclusion\n\n")
        no_price = sum(1 for x in excluded if x["Exclusion Reason"] == "No Sale Price Data")
        low_price = sum(1 for x in excluded if "Max Price < 2.1 Cr" in x["Exclusion Reason"])
        out.write(f"* **No Sale Price Data:** {no_price} societies (typically rental-only or rental-dominated listings)\n")
        out.write(f"* **Max Price < 2.1 Cr:** {low_price} societies (prices fall in Q1-Q3 of transaction values)\n\n")
        
        out.write("## Society List\n\n")
        out.write("| # | Society Name | Locality | Micro Market | Max Sale Price | Rent Range (Monthly) | Sale Tag | Rent Tag | Exclusion Reason | Listed Units |\n")
        out.write("|---|---|---|---|---|---|---|---|---|---|\n")
        for idx, h in enumerate(excluded):
            price_str = f"INR {h['Max Sale Price']:,}" if isinstance(h['Max Sale Price'], (int, float)) else "NA"
            out.write(f"| {idx+1} | {h['Society Name']} | {h['Locality']} | {h['Micro Market']} | {price_str} | {h['Rent Range (Monthly)']} | {h['Sale Tag']} | {h['Rent Tag']} | {h['Exclusion Reason']} | {h['Listed Units Count']} |\n")
            
    print(f"Analysis completed: {len(excluded)} excluded premium societies written to JSON and Markdown.")

if __name__ == "__main__":
    main()
