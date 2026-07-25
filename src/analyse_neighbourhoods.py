#!/usr/bin/env python3
import json
import math
import itertools
from pathlib import Path
import sys

# Try to import h3
try:
    import h3
except ImportError:
    print("Error: The 'h3' library is not installed in the python environment.", file=sys.stderr)
    sys.exit(1)

BANGALORE_CENTER = (12.9716, 77.5946)

def get_hex_latlon(hex_id):
    for func_name in ("cell_to_latlng", "cell_to_latlon", "h3_to_geo"):
        if hasattr(h3, func_name):
            return getattr(h3, func_name)(hex_id)
    raise AttributeError("No valid coordinates extraction function found in h3 library.")

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0088  # Earth's radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def load_hex_info():
    script_dir = Path(__file__).resolve().parent
    geojson_path = script_dir / "public" / "data" / "hexes.geojson"
    if not geojson_path.exists():
        geojson_path = script_dir / "data" / "hexes.geojson"

    hex_data = {}
    if geojson_path.exists():
        try:
            with open(geojson_path, "r") as f:
                data = json.load(f)
            for feat in data.get("features", []):
                props = feat.get("properties", {})
                hid = props.get("hex_id")
                if hid:
                    hex_data[hid] = {
                        "name": props.get("name", hid),
                        "score": float(props.get("final_affluence_score") or 0.0),
                        "units": float(props.get("direct_total_units") or 0.0),
                        "tam": float(props.get("countable_family_tam") or 0.0)
                    }
        except Exception as e:
            print(f"Warning: Failed to load hexes.geojson: {e}", file=sys.stderr)
    return hex_data

def get_zone_name(lat, lon, center_lat, center_lon):
    dist = haversine(lat, lon, center_lat, center_lon)
    # If within 4.0 km of the relative city centroid, classify as Central
    if dist <= 4.0:
        return "Central"
    
    dy = lat - center_lat
    dx = lon - center_lon
    angle = math.degrees(math.atan2(dy, dx))
    if angle < 0:
        angle += 360
        
    # Divide 360 degrees into 8 sectors of 45 degrees each
    # Sector mapping (centered around East, NE, North, etc.)
    if angle >= 337.5 or angle < 22.5:
        return "East"
    elif angle >= 22.5 and angle < 67.5:
        return "North-East"
    elif angle >= 67.5 and angle < 112.5:
        return "North"
    elif angle >= 112.5 and angle < 157.5:
        return "North-West"
    elif angle >= 157.5 and angle < 202.5:
        return "West"
    elif angle >= 202.5 and angle < 247.5:
        return "South-West"
    elif angle >= 247.5 and angle < 292.5:
        return "South"
    else:
        return "South-East"

def main():
    script_dir = Path(__file__).resolve().parent
    suggestions_path = script_dir / "public" / "data" / "micromarket_suggestions_8hex.json"
    
    if not suggestions_path.exists():
        print(f"Error: Suggestions file not found at {suggestions_path}", file=sys.stderr)
        sys.exit(1)
        
    with open(suggestions_path, "r") as f:
        suggestions_data = json.load(f)
        
    markets_raw = suggestions_data.get("disjoint_micro_markets", [])
    if not markets_raw:
        print("Error: No disjoint micro markets found in the suggestions JSON file.", file=sys.stderr)
        sys.exit(1)
        
    hex_info = load_hex_info()
    
    # 1. Compute Centroids and basic info for each micro-market
    markets = []
    total_lats, total_lons = 0.0, 0.0
    
    for idx, m in enumerate(markets_raw):
        hex_ids = m["hex_ids"]
        # Calculate market centroid
        lats, lons = [], []
        for hid in hex_ids:
            lat, lon = get_hex_latlon(hid)
            lats.append(lat)
            lons.append(lon)
            
        m_lat = sum(lats) / len(lats)
        m_lon = sum(lons) / len(lons)
        total_lats += m_lat
        total_lons += m_lon
        
        # Get core representative name
        core_hex = max(hex_ids, key=lambda hid: hex_info.get(hid, {}).get("score", 0.0))
        core_name = hex_info.get(core_hex, {}).get("name", f"Hex {core_hex}")
        
        markets.append({
            "id": idx + 1,
            "core_name": core_name,
            "hex_ids": hex_ids,
            "lat": m_lat,
            "lon": m_lon,
            "total_units": m["total_units"],
            "avg_score": m["avg_score"],
            "total_tam": m["total_tam"],
            "combined_score": m["combined_score"]
        })
        
    # Calculate relative center of these micro-markets to classify zones accurately
    center_lat = total_lats / len(markets)
    center_lon = total_lons / len(markets)
    
    # Classify each micro-market into a zone
    for m in markets:
        m["zone"] = get_zone_name(m["lat"], m["lon"], center_lat, center_lon)
        
    # Print out micro-markets summary
    print("=" * 110)
    print(f" RELATIVE CENTER CENTROID OF DETECTED MICRO-MARKETS: Lat {center_lat:.5f}, Lon {center_lon:.5f}")
    print("=" * 110)
    print(f"{'ID':<3} | {'Core Market Name':<28} | {'Zone':<12} | {'Units':<8} | {'Avg Score':<9} | {'Total TAM':<9} | {'Comb Score':<10}")
    print("-" * 110)
    for m in markets:
        print(f"MM{m['id']:<1} | {m['core_name']:<28} | {m['zone']:<12} | {m['total_units']:<8,.0f} | {m['avg_score']:<9.2f} | {m['total_tam']:<9,.0f} | {m['combined_score']:<10.2f}")
    print("=" * 110)
    
    # 2. Formulate all combinations of 3 micro-markets (Neighborhoods)
    # Total combinations = 8 choose 3 = 56
    neighborhoods = []
    for combo in itertools.combinations(markets, 3):
        # Calculate geographical closeness (sum of pairwise distances between centroids)
        m1, m2, m3 = combo
        d12 = haversine(m1["lat"], m1["lon"], m2["lat"], m2["lon"])
        d23 = haversine(m2["lat"], m2["lon"], m3["lat"], m3["lon"])
        d31 = haversine(m3["lat"], m3["lon"], m1["lat"], m1["lon"])
        
        sum_dist = d12 + d23 + d31
        avg_dist = sum_dist / 3.0
        max_dist = max(d12, d23, d31)
        
        # Calculate aggregated KPIs
        total_units = sum(m["total_units"] for m in combo)
        total_tam = sum(m["total_tam"] for m in combo)
        avg_score = sum(m["avg_score"] for m in combo) / 3.0
        combined_score = sum(m["combined_score"] for m in combo) / 3.0
        
        # Centroid of the neighborhood
        n_lat = sum(m["lat"] for m in combo) / 3.0
        n_lon = sum(m["lon"] for m in combo) / 3.0
        n_zone = get_zone_name(n_lat, n_lon, center_lat, center_lon)
        
        names_str = ", ".join(m["core_name"] for m in combo)
        market_ids = tuple(m["id"] for m in combo)
        
        neighborhoods.append({
            "market_ids": market_ids,
            "names": names_str,
            "lat": n_lat,
            "lon": n_lon,
            "zone": n_zone,
            "avg_dist_km": avg_dist,
            "max_dist_km": max_dist,
            "total_units": total_units,
            "total_tam": total_tam,
            "avg_score": avg_score,
            "combined_score": combined_score
        })
        
    # Sort neighborhoods by closeness (smallest average distance)
    neighborhoods.sort(key=lambda x: x["avg_dist_km"])
    
    print("\n" + "=" * 110)
    print(" TOP 10 GEOGRAPHICALLY TIGHTEST NEIGHBOURHOODS (TRIPLETS OF MICRO-MARKETS)")
    print("=" * 110)
    print(f"{'Rank':<4} | {'Micro-Markets (IDs)':<40} | {'Avg Dist (km)':<13} | {'Zone':<12} | {'Total TAM':<10} | {'Avg Score':<9}")
    print("-" * 110)
    for idx, n in enumerate(neighborhoods[:10], 1):
        ids_str = f"{n['names']} (MM {list(n['market_ids'])})"
        if len(ids_str) > 40:
            ids_str = ids_str[:37] + "..."
        print(f"#{idx:<3} | {ids_str:<40} | {n['avg_dist_km']:<13.2f} | {n['zone']:<12} | {n['total_tam']:<10,.0f} | {n['avg_score']:<9.2f}")
    print("=" * 110)

    # 3. Analyze Disjoint Pairs of Neighborhoods (covering 6 micro-markets total)
    # Total combinations of pairs of neighborhoods
    disjoint_pairs = []
    for n1, n2 in itertools.combinations(neighborhoods, 2):
        # Must be disjoint (no micro-market shared)
        set1 = set(n1["market_ids"])
        set2 = set(n2["market_ids"])
        if not set1.intersection(set2):
            # Calculate distance between neighborhood centroids
            dist_between_n = haversine(n1["lat"], n1["lon"], n2["lat"], n2["lon"])
            
            # Combine metrics
            combined_units = n1["total_units"] + n2["total_units"]
            combined_tam = n1["total_tam"] + n2["total_tam"]
            combined_avg_score = (n1["avg_score"] + n2["avg_score"]) / 2.0
            combined_score = (n1["combined_score"] + n2["combined_score"]) / 2.0
            
            # Sectors covered
            zones_covered = sorted(list({n1["zone"], n2["zone"]}))
            zones_str = " & ".join(zones_covered)
            
            disjoint_pairs.append({
                "n1_ids": n1["market_ids"],
                "n2_ids": n2["market_ids"],
                "n1_names": n1["names"],
                "n2_names": n2["names"],
                "dist_between_n_km": dist_between_n,
                "total_units": combined_units,
                "total_tam": combined_tam,
                "avg_score": combined_avg_score,
                "combined_score": combined_score,
                "zones_covered": zones_str
            })
            
    # Sort pairs of neighborhoods by combined TAM descending (higher is better)
    disjoint_pairs.sort(key=lambda x: x["total_tam"], reverse=True)
    
    print("\n" + "=" * 110)
    print(" TOP 5 PAIRS OF NEIGHBOURHOODS BY COMBINED TAM POTENTIAL (6 MICRO-MARKETS TOTAL)")
    print("=" * 110)
    print(f"{'Rank':<4} | {'Neighbourhood A':<26} | {'Neighbourhood B':<26} | {'Zones Covered':<18} | {'Total TAM':<10} | {'Score':<6}")
    print("-" * 110)
    for idx, p in enumerate(disjoint_pairs[:5], 1):
        n1_short = p["n1_names"]
        if len(n1_short) > 26:
            n1_short = n1_short[:23] + "..."
        n2_short = p["n2_names"]
        if len(n2_short) > 26:
            n2_short = n2_short[:23] + "..."
        print(f"#{idx:<3} | {n1_short:<26} | {n2_short:<26} | {p['zones_covered']:<18} | {p['total_tam']:<10,.0f} | {p['combined_score']:<6.2f}")
    print("=" * 110)

    # 4. Assess Geographic Zones
    # Group micro-markets by zone and compute stats (including empty zones)
    ALL_9_ZONES = ["Central", "North", "North-East", "East", "South-East", "South", "South-West", "West", "North-West"]
    zone_stats = {
        z: {
            "markets": [],
            "total_units": 0.0,
            "total_tam": 0.0,
            "sum_score": 0.0,
            "sum_comb_score": 0.0,
            "count": 0,
            "avg_score": 0.0,
            "avg_comb_score": 0.0
        } for z in ALL_9_ZONES
    }
    
    for m in markets:
        z = m["zone"]
        if z in zone_stats:
            zone_stats[z]["markets"].append(m["core_name"])
            zone_stats[z]["total_units"] += m["total_units"]
            zone_stats[z]["total_tam"] += m["total_tam"]
            zone_stats[z]["sum_score"] += m["avg_score"]
            zone_stats[z]["sum_comb_score"] += m["combined_score"]
        
    for z, s in zone_stats.items():
        count = len(s["markets"])
        if count > 0:
            s["avg_score"] = s["sum_score"] / count
            s["avg_comb_score"] = s["sum_comb_score"] / count
            s["count"] = count
        
    # Sort zones by TAM descending
    sorted_zones = sorted(zone_stats.items(), key=lambda x: x[1]["total_tam"], reverse=True)
    
    print("\n" + "=" * 115)
    print(" GEOGRAPHIC ZONES RANKED BY TOTAL TAM POTENTIAL (ALL 9 ZONES)")
    print("=" * 115)
    print(f"{'Rank':<4} | {'Zone':<12} | {'Markets Count':<13} | {'Total Units':<12} | {'Total TAM':<12} | {'Avg Affluence':<13} | {'Avg Comb Score':<12}")
    print("-" * 115)
    for idx, (z, s) in enumerate(sorted_zones, 1):
        print(f"#{idx:<3} | {z:<12} | {s['count']:<13} | {s['total_units']:<12,.0f} | {s['total_tam']:<12,.0f} | {s['avg_score']:<13.2f} | {s['avg_comb_score']:<12.2f}")
    print("=" * 115)
    
    # 5. Save report to markdown
    report_path = script_dir / "public" / "data" / "neighbourhood_analysis_report.md"
    report_content = f"""# Urban Neighbourhoods and Zones Analysis Report

This report presents a spatial and quantitative analysis of **Bangalore's 8 Disjoint Micro-Markets**. The objective is to identify natural **Neighbourhoods** (clusters of three micro-markets that are geographically close), evaluate **pairs of neighbourhoods** for overall city coverage, and rank **Geographic Zones** to assess where high-wealth expansion is best.

---

## 1. Input Micro-Markets & Zone Classification

Micro-markets are assigned to a zone based on their distance and bearing relative to the **data-driven center of the micro-markets** (Latitude: `{center_lat:.5f}`, Longitude: `{center_lon:.5f}`).

| ID | Core Market Name | Zone | Total Units | Avg Affluence Score | Total TAM Families | Combined Score |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
"""
    for m in markets:
        report_content += f"| MM{m['id']} | **{m['core_name']}** | {m['zone']} | {m['total_units']:,.0f} | {m['avg_score']:.2f} | {m['total_tam']:,.0f} | {m['combined_score']:.2f} |\n"
        
    report_content += f"""
---

## 2. Best Neighbourhoods (Triplets of Micro-Markets)

We evaluated all 56 possible triplets of micro-markets. The tightest neighbourhoods are ranked by their **Average Pairwise Centroid Distance (km)**:

| Rank | Neighbourhood Constituents | Avg Distance (km) | Centroid Zone | Combined TAM Families | Avg Affluence Score | Combined Score |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
"""
    for idx, n in enumerate(neighborhoods[:10], 1):
        report_content += f"| #{idx} | {n['names']} | {n['avg_dist_km']:.2f} km | {n['zone']} | {n['total_tam']:,.0f} | {n['avg_score']:.2f} | {n['combined_score']:.2f} |\n"
        
    report_content += f"""
### Key Finding (Best Neighbourhood):
The geographically tightest neighborhood is **{neighborhoods[0]['names']}** (comprising MM2, MM6, MM8), situated in the **{neighborhoods[0]['zone']}** sector of the city. It has a tiny average spacing of **{neighborhoods[0]['avg_dist_km']:.2f} km** and represents an aggregate of **{neighborhoods[0]['total_tam']:,.0f} TAM families** and **{neighborhoods[0]['avg_score']:.2f} average affluence**.

---

## 3. Top Pairs of Neighbourhoods (6 Micro-Markets Combined)

Pairs of disjoint neighbourhoods are evaluated to identify broad city partitions with maximum aggregate wealth (TAM potential). 

| Rank | Neighbourhood A | Neighbourhood B | Zones Covered | Combined TAM Families | Combined Score |
| :--- | :--- | :--- | :--- | :--- | :--- |
"""
    for idx, p in enumerate(disjoint_pairs[:5], 1):
        report_content += f"| #{idx} | {p['n1_names']} | {p['n2_names']} | {p['zones_covered']} | {p['total_tam']:,.0f} | {p['combined_score']:.2f} |\n"

    report_content += f"""
---

## 4. Geographic Zones Assessment (All 9 Zones)

We grouped the 8 micro-markets into their respective geographic zones to identify which sector of Bangalore is best, representing all 9 sectors:

| Rank | Geographic Zone | Markets Count | Total Units | Total TAM Families | Avg Affluence Score | Avg Combined Score | Included Markets |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
"""
    for idx, (z, s) in enumerate(sorted_zones, 1):
        markets_list = ", ".join(s["markets"]) if s["markets"] else "None"
        report_content += f"| #{idx} | **{z}** | {s['count']} | {s['total_units']:,.0f} | {s['total_tam']:,.0f} | {s['avg_score']:.2f} | {s['avg_comb_score']:.2f} | {markets_list} |\n"

    # Dynamically extract summary metrics
    active_zones = [z for z, s in sorted_zones if s["count"] > 0]
    top_active_zone = active_zones[0] if active_zones else "None"
    top_active_tam = zone_stats[top_active_zone]["total_tam"] if active_zones else 0
    top_active_count = zone_stats[top_active_zone]["count"] if active_zones else 0
    top_active_score = zone_stats[top_active_zone]["avg_score"] if active_zones else 0
    
    top_market = max(markets, key=lambda x: x["total_tam"])
    inactive_zones_list = [z for z, s in sorted_zones if s["count"] == 0]
    inactive_str = ", ".join(f"**{z}**" for z in inactive_zones_list) if inactive_zones_list else "None"

    report_content += f"""
## Summary & Recommendation

1. **Top Active Zone**: The **{top_active_zone}** zone leads in total volume, anchoring **{top_active_tam:,.0f} TAM families** across **{top_active_count}** active micro-market(s) with a solid average affluence score of **{top_active_score:.2f}**.
2. **Top Individual Value**: The market **{top_market['core_name']}** (located in the **{top_market['zone']}** zone) is the single highest-value micro-market with **{top_market['total_tam']:,.0f} TAM families** and a premier affluence score of **{top_market['avg_score']:.2f}**.
3. **Inactive Zones**: Zones such as {inactive_str} do not contain any of the top 8 recommended micro-markets due to lower relative affluence or residential unit counts in these specific H3 clusters.
"""
    
    with open(report_path, "w") as f:
        f.write(report_content)
        
    print(f"\nSaved detailed analysis report to: {report_path.name}")

if __name__ == "__main__":
    main()
