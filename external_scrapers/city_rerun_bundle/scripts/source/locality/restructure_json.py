#!/usr/bin/env python3
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CITY_SLUG = os.environ.get("CITY_SLUG", "bangalore").strip().lower().replace(" ", "-")
CITY_NAME = os.environ.get("CITY_NAME", CITY_SLUG.replace("-", " ").title())
INPUT_FILE = BASE_DIR / "data" / "raw" / f"99acres_{CITY_SLUG}_localities.json"
OUTPUT_FILE = BASE_DIR / "data" / "raw" / f"99acres_{CITY_SLUG}_localities_restructured.json"

def clean_int(val):
    if val is None:
        return None
    if isinstance(val, int):
        return val
    try:
        # remove commas, spaces
        cleaned = str(val).replace(",", "").strip()
        return int(cleaned)
    except ValueError:
        return val

def clean_float(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = str(val).replace(",", "").strip()
        return float(cleaned)
    except ValueError:
        return val

def parse_tags(tags_str):
    if not tags_str:
        return []
    return [t.strip() for t in tags_str.split(",") if t.strip()]

def restructure_entry(loc):
    # 1. Locality Info
    locality_info = {
        "id": loc.get("id"),
        "name": loc.get("localityName") or loc.get("label") or loc.get("displayLabel"),
        "city": loc.get("cityName", CITY_NAME),
        "zone": {
            "id": loc.get("zoneId"),
            "name": loc.get("zoneName")
        },
        "coordinates": {
            "latitude": clean_float(loc.get("lat")),
            "longitude": clean_float(loc.get("lon"))
        }
    }

    # 2. Market Insights
    rei = loc.get("reiStatus") or {}
    market_insights = {
        "rating": clean_float(loc.get("rating")),
        "reviews_count": clean_int(loc.get("reviewsCount")),
        "registry_count": clean_int(loc.get("numericRegistryCounts") or loc.get("registryCount")),
        "budget_segment": loc.get("budgetRange"),
        "budget_segment_source": loc.get("budgetRange_source"),
        "budget_segment_confidence": clean_float(loc.get("budgetRange_confidence")),
        "price_per_sqft": loc.get("pricePerSqFt"),
        "market_price_per_sqft": clean_int(loc.get("marketPrice")),
        "yearly_appreciation": loc.get("appreciation"),
        "rental_yield": loc.get("rentalYield"),
        "tags": parse_tags(loc.get("tags")),
        "rankings": {
            "resale_rank": clean_int(rei.get("resaleRank")),
            "rental_rank": clean_int(rei.get("rentalRank")),
            "commercial_resale_rank": clean_int(rei.get("comResaleRank")),
            "commercial_rental_rank": clean_int(rei.get("comRentalRank")),
            "is_live": rei.get("reiLiveStatus")
        }
    }

    # 3. Income Analytics
    income_analytics = {
        "dominant_income_bracket": loc.get("dominant_income_bracket"),
        "distribution": loc.get("income_distribution"),
        "source": loc.get("income_dist_source")
    }

    # 4. Trends
    # propWisePrice typically maps BHK size to avg price per sqft or total price
    # propYearWiseAppreciation maps BHK size to YoY appreciation percentages for 1, 3, 5, 10 years
    appreciation_data = {}
    raw_appr = loc.get("propYearWiseAppreciation") or {}
    for bhk_key, timeline in raw_appr.items():
        appreciation_data[f"bhk_{bhk_key}"] = {
            "1_year_pct": clean_float(timeline.get("1")),
            "3_years_pct": clean_float(timeline.get("3")),
            "5_years_pct": clean_float(timeline.get("5")),
            "10_years_pct": clean_float(timeline.get("10"))
        }

    trends = {
        "average_price_by_bhk": loc.get("propWisePrice"),
        "appreciation_history": appreciation_data
    }

    # 5. Inventory
    inventory = {}
    prop_count_raw = loc.get("propCount") or {}
    for raw_key, mode_name in [("R", "rent"), ("S", "sale")]:
        mode_data = prop_count_raw.get(raw_key) or {}
        
        # Property types clean up
        types_clean = {}
        for ptype, pinfo in (mode_data.get("propType") or {}).items():
            if pinfo:
                types_clean[ptype] = {
                    "count": clean_int(pinfo.get("count")),
                    "price_range": pinfo.get("price")
                }
            
        # BHK details clean up
        bhk_clean = {}
        for bhk_num, bhk_info in (mode_data.get("bhk") or {}).items():
            if not bhk_info:
                continue
            posted_by_clean = {}
            for poster, poster_info in (bhk_info.get("postedBy") or {}).items():
                if poster_info:
                    poster_name = "agent" if poster == "A" else "owner" if poster == "O" else poster
                    posted_by_clean[poster_name] = {
                        "count": clean_int(poster_info.get("count")),
                        "price_range": poster_info.get("price")
                    }
                
            price_buckets_clean = {}
            for bucket_name, bucket_info in (bhk_info.get("priceBucket") or {}).items():
                if bucket_info:
                    price_buckets_clean[bucket_name] = {
                        "count": clean_int(bucket_info.get("count")),
                        "price_range": bucket_info.get("price")
                    }
                
            bhk_clean[f"bhk_{bhk_num}"] = {
                "total_count": clean_int(bhk_info.get("count")),
                "price_range": bhk_info.get("price"),
                "posted_by": posted_by_clean,
                "price_buckets": price_buckets_clean
            }

        inventory[mode_name] = {
            "total_count": clean_int(mode_data.get("count")),
            "property_types": types_clean,
            "bhk_details": bhk_clean
        }

    # 6. Navigation and Metadata
    rlp = loc.get("rlpDataUrls") or {}
    navigation_urls = {
        "overview_page": loc.get("localityPageCriteria", {}).get("url") or (loc.get("localityPageUrl") if loc.get("localityPageUrl") else None),
        "reviews_page": rlp.get("RNR") or loc.get("locPageUrlRNR"),
        "price_trends_page": rlp.get("PRT"),
        "registry_records_page": rlp.get("RGR"),
        "city_reviews_page": loc.get("cityPageUrl"),
        "images": {
            "default": loc.get("imageUrl"),
            "square": loc.get("defaultSquareImageUrl")
        },
        "search_parameters": loc.get("srpCriteria"),
        "quick_links": loc.get("quickLinks")
    }

    # 7. Help Disclaimers & Info (global or static reference info if needed, or we keep it nested)
    disclaimers = {
        "price_calculation_info": loc.get("priceRateInfo"),
        "rental_yield_info": loc.get("rentalYieldInfo"),
        "transaction_rate_info": loc.get("transactionRateInfo")
    }

    return {
        "locality_info": locality_info,
        "market_insights": market_insights,
        "income_analytics": income_analytics,
        "trends": trends,
        "inventory": inventory,
        "navigation_urls": navigation_urls,
        "disclaimers": disclaimers
    }

if __name__ == "__main__":
    import shutil
    
    # 1. Create a backup of the original file
    backup_file = INPUT_FILE.with_suffix(".json.bak")
    print(f"Creating backup at {backup_file.name}...")
    shutil.copy2(INPUT_FILE, backup_file)
    
    # 2. Load and process
    print(f"Loading data from {INPUT_FILE.name}...")
    with open(INPUT_FILE, encoding="utf-8") as f:
        data = json.load(f)
    
    print(f"Restructuring {len(data)} localities...")
    restructured_data = [restructure_entry(loc) for loc in data]
    
    # 3. Save to output
    print(f"Writing restructured data back to {INPUT_FILE.name}...")
    with open(INPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(restructured_data, f, indent=2, ensure_ascii=False)
        
    print("Successfully completed restructuring!")
