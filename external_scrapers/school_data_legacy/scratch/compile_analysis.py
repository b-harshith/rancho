#!/usr/bin/env python3
import json
import os
from collections import Counter

def format_number(val):
    if isinstance(val, (int, float)):
        return f"{val:,}"
    return str(val)

def main():
    json_path = "data/q4_categorized_societies_bangalore.json"
    if not os.path.exists(json_path):
        print(f"Error: {json_path} does not exist yet.")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        societies = json.load(f)

    # Calculate median multiplier from cache
    med_mult = 15.79
    cache_path = "scratch/scraped_details_cache.json"
    if os.path.exists(cache_path):
        try:
            with open(cache_path) as cf:
                cache = json.load(cf)
            mults = []
            for details in cache.values():
                if details and isinstance(details, dict) and details.get("has_direct_units"):
                    u, l = details["unit_count"], details["total_listings"]
                    if isinstance(u, int) and u > 0 and l > 0:
                        m = u / l
                        if 2 <= m <= 150:
                            mults.append(m)
            if len(mults) >= 3:
                mults.sort()
                n = len(mults)
                med_mult = mults[n // 2] if n % 2 else (mults[n // 2 - 1] + mults[n // 2]) / 2
        except Exception:
            pass

    total_societies = len(societies)
    print(f"Loaded {total_societies} societies. Using multiplier: {med_mult:.2f}x")

    # 1. Construction Status Analysis
    status_counts = Counter()
    for s in societies:
        status = s.get("Construction Status", "Ready to Move")
        # normalize
        if "under construction" in status.lower():
            status_counts["Under Construction"] += 1
        elif "ready" in status.lower():
            status_counts["Ready to Move"] += 1
        else:
            status_counts[status] += 1

    # 2. TAM Aggregates by Category
    category_data = {}
    categories = ["Ultra Luxury", "Super Luxury", "Luxury", "Premium", "Aspirational Premium"]
    for cat in categories:
        category_data[cat] = {
            "count": 0,
            "total_listings": 0,
            "total_units": 0,
            "total_tam": 0,
            "under_construction": 0,
            "ready_to_move": 0
        }

    for s in societies:
        cat = s["Q4 Category"]
        if cat not in category_data:
            category_data[cat] = {
                "count": 0, "total_listings": 0, "total_units": 0, "total_tam": 0,
                "under_construction": 0, "ready_to_move": 0
            }
        
        category_data[cat]["count"] += 1
        category_data[cat]["total_listings"] += s.get("Total Active Listings", 0)
        category_data[cat]["total_units"] += s.get("Total Units", 0)
        category_data[cat]["total_tam"] += s.get("Estimated Families (TAM)", 0)
        
        status = s.get("Construction Status", "")
        if "under construction" in status.lower():
            category_data[cat]["under_construction"] += 1
        else:
            category_data[cat]["ready_to_move"] += 1

    # 3. Micro Market Aggregates
    micro_market_data = {}
    for s in societies:
        mm = s["Micro Market"]
        if mm not in micro_market_data:
            micro_market_data[mm] = {"count": 0, "total_units": 0, "total_tam": 0}
        micro_market_data[mm]["count"] += 1
        micro_market_data[mm]["total_units"] += s.get("Total Units", 0)
        micro_market_data[mm]["total_tam"] += s.get("Estimated Families (TAM)", 0)

    # 4. Locality Aggregates
    locality_data = {}
    for s in societies:
        loc = s["Locality"]
        if loc not in locality_data:
            locality_data[loc] = {"count": 0, "total_units": 0, "total_tam": 0, "micro_market": s["Micro Market"]}
        locality_data[loc]["count"] += 1
        locality_data[loc]["total_units"] += s.get("Total Units", 0)
        locality_data[loc]["total_tam"] += s.get("Estimated Families (TAM)", 0)

    # 5. Top 25 Projects by TAM
    top_projects = sorted(societies, key=lambda x: x.get("Estimated Families (TAM)", 0), reverse=True)[:25]

    # Generate q4_societies_tam_report.md
    report_path = "/Users/malleswararao/.gemini/antigravity-ide/brain/5ad9d68c-7c50-4a98-8496-16e26f027f49/q4_societies_tam_report.md"
    
    with open(report_path, "w", encoding="utf-8") as out:
        out.write("# Bangalore Premium Residential Societies: TAM & Construction Status Report\n\n")
        out.write(f"This report estimates the **Total Addressable Market (TAM) of families** living across the **{total_societies}** premium and luxury societies (stretched bracket: purchase price >= INR 1.5 Cr) in Bangalore.\n\n")
        
        out.write("## Executive Summary\n\n")
        total_units = sum(s.get("Total Units", 0) for s in societies)
        total_tam = sum(s.get("Estimated Families (TAM)", 0) for s in societies)
        total_listings = sum(s.get("Total Active Listings", 0) for s in societies)
        
        out.write(f"- **Total Premium Societies:** {total_societies}\n")
        out.write(f"- **Total Physical Unit Capacity:** {format_number(total_units)} households\n")
        out.write(f"- **Estimated Families Residing (TAM @ 85% occupancy):** **{format_number(total_tam)} families**\n")
        out.write(f"- **Total Active Listings (Resale + Rent):** {format_number(total_listings)} active ads on 99acres\n\n")
        
        out.write("## 1. Construction Status & Readiness\n\n")
        out.write("A breakdown of societies that are fully completed and occupied (\"Ready to Move\") versus those still in development (\"Under Construction\"):\n\n")
        
        out.write("| Construction Status | Number of Projects | Percentage | Total Units Capacity | Estimated Families (TAM) |\n")
        out.write("|---|---|---|---|---|\n")
        for status, cnt in status_counts.items():
            pct = (cnt / total_societies) * 100
            def match_status(s_obj):
                s_status = s_obj.get("Construction Status", "Ready to Move") or "Ready to Move"
                if "under construction" in s_status.lower():
                    return "Under Construction"
                elif "ready" in s_status.lower():
                    return "Ready to Move"
                else:
                    return s_status
            s_units = sum(s.get("Total Units", 0) for s in societies if match_status(s) == status)
            s_tam = sum(s.get("Estimated Families (TAM)", 0) for s in societies if match_status(s) == status)
            out.write(f"| **{status}** | {cnt} | {pct:.1f}% | {format_number(s_units)} | **{format_number(s_tam)}** |\n")
            
        out.write("\n## 2. TAM Aggregates by Luxury Tier\n\n")
        out.write("| Luxury Tier | Price Range | Projects | Ready | U.C. | Total Units | Active Listings | Estimated Families (TAM) |\n")
        out.write("|---|---|---|---|---|---|---|---|\n")
        for cat in categories:
            d = category_data.get(cat, {"count": 0, "total_listings": 0, "total_units": 0, "total_tam": 0, "under_construction": 0, "ready_to_move": 0})
            rng = ">= 4.5 Cr" if cat == "Ultra Luxury" else "3.0 - 4.5 Cr" if cat == "Super Luxury" else "2.6 - 3.0 Cr" if cat == "Luxury" else "2.1 - 2.6 Cr" if cat == "Premium" else "1.5 - 2.1 Cr"
            out.write(f"| **{cat}** | {rng} | {d['count']} | {d['ready_to_move']} | {d['under_construction']} | {format_number(d['total_units'])} | {format_number(d['total_listings'])} | **{format_number(d['total_tam'])}** |\n")
            
        out.write("\n## 3. Geographic Distribution of TAM\n\n")
        out.write("### Micro Market Breakdown\n\n")
        out.write("| Micro Market | Number of Projects | Total Units Capacity | Estimated Families (TAM) | % of Total TAM |\n")
        out.write("|---|---|---|---|---|\n")
        sorted_mm = sorted(micro_market_data.items(), key=lambda x: x[1]["total_tam"], reverse=True)
        for mm, d in sorted_mm:
            pct = (d["total_tam"] / total_tam) * 100
            out.write(f"| **{mm}** | {d['count']} | {format_number(d['total_units'])} | {format_number(d['total_tam'])} | {pct:.1f}% |\n")
            
        out.write("\n### Top 15 Localities by Premium TAM\n\n")
        out.write("| # | Locality | Micro Market | Number of Projects | Total Units Capacity | Estimated Families (TAM) |\n")
        out.write("|---|---|---|---|---|---|\n")
        sorted_loc = sorted(locality_data.items(), key=lambda x: x[1]["total_tam"], reverse=True)[:15]
        for idx, (loc, d) in enumerate(sorted_loc):
            out.write(f"| {idx+1} | {loc} | {d['micro_market']} | {d['count']} | {format_number(d['total_units'])} | **{format_number(d['total_tam'])}** |\n")

        out.write("\n## 4. Top 25 Largest Premium Societies by TAM\n\n")
        out.write("| # | Society Name | Locality | Category | Construction Status | Total Units | Active Listings | Estimated Families (TAM) | RERA ID |\n")
        out.write("|---|---|---|---|---|---|---|---|---|\n")
        for idx, s in enumerate(top_projects):
            out.write(f"| {idx+1} | {s['Society Name']} | {s['Locality']} | **{s['Q4 Category']}** | {s.get('Construction Status')} | {format_number(s.get('Total Units'))} | {s.get('Total Active Listings')} | **{format_number(s.get('Estimated Families (TAM)'))}** | `{s.get('RERA ID')}` |\n")

        out.write("\n## 5. Methodology & Heuristics\n\n")
        out.write("To calculate the TAM of families, we gathered granular data from 99acres project detail pages:\n")
        out.write("1. **Direct Capacities:** For projects with structured specifications, we extracted the exact physical unit counts (`unitCount` or parsed from the text descriptions).\n")
        out.write(f"2. **Listing Multiplier:** For societies where unit counts were not directly available, we calculated their size using a median listings-to-units multiplier derived from projects that had both active listings and total units. The median multiplier used is **{med_mult:.2f}** (i.e. active listings on 99acres represent ~{100/med_mult:.1f}% of a project's inventory).\n")
        out.write("3. **TAM Estimate:** Occupied households are estimated using a standard occupancy rate of **85%** for completed/near-completed projects: `Estimated Families = Total Units * 0.85`.\n")

    print(f"Generated report at {report_path}")

    # Generate updated q4_categorized_societies.md
    societies_md_path = "/Users/malleswararao/.gemini/antigravity-ide/brain/5ad9d68c-7c50-4a98-8496-16e26f027f49/q4_categorized_societies.md"
    with open(societies_md_path, "w", encoding="utf-8") as out:
        out.write(f"# Categorized Q4 Premium & Luxury Societies (Bangalore) - Stretched Bracket\n\n")
        out.write(f"This document lists the **{total_societies}** premium and luxury residential societies in Bangalore with a maximum purchase price >= **INR 1.5 Crore**, enriched with RERA numbers, listing counts, physical units, and family occupancy (TAM) estimates:\n\n")
        
        out.write("## Distribution Summary\n\n")
        out.write("| Category | Projects Count | Total Units | Active Listings | Estimated Families (TAM) |\n")
        out.write("|---|---|---|---|---|\n")
        for cat in categories:
            d = category_data.get(cat, {"count": 0, "total_listings": 0, "total_units": 0, "total_tam": 0, "under_construction": 0, "ready_to_move": 0})
            out.write(f"| **{cat}** | {d['count']} | {format_number(d['total_units'])} | {format_number(d['total_listings'])} | **{format_number(d['total_tam'])}** |\n")
            
        out.write("\n## Full Categorized Society List\n\n")
        out.write("| # | Society Name | Locality | Category | Max Price | Construction Status | Total Units | TAM (Families) | RERA ID | Configurations | Listings (Sale/Rent) | Profile |\n")
        out.write("|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        for idx, s in enumerate(societies):
            price_str = f"INR {s['Max Price']:,}"
            listings_breakdown = f"{s.get('Resale Listings Count')}/{s.get('Rental Listings Count')}"
            out.write(f"| {idx+1} | {s['Society Name']} | {s['Locality']} | **{s['Q4 Category']}** | {price_str} | {s.get('Construction Status')} | {format_number(s.get('Total Units'))} | **{format_number(s.get('Estimated Families (TAM)'))}** | `{s.get('RERA ID')}` | {s['Configurations']} | {listings_breakdown} | [Link]({s['URL']}) |\n")

    print(f"Updated full society list markdown at {societies_md_path}")

if __name__ == "__main__":
    main()
