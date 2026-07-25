#!/usr/bin/env python3
import json
import os
import math
from collections import defaultdict

import sys

DEFAULT_FILE = "data/raw/bangalore_projects_enriched.jsonl"

# Bounding box for Greater Bangalore area
LAT_MIN, LAT_MAX = 12.70, 13.30
LON_MIN, LON_MAX = 77.30, 77.95

def haversine_distance_m(lat1, lon1, lat2, lon2):
    # Earth radius in meters
    R = 6371000.0
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi / 2.0)**2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0)**2
    
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def main():
    target_file = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FILE
    if not os.path.exists(target_file):
        print(f"Error: {target_file} does not exist.")
        return

    print(f"=== Processing Validation on: {target_file} ===\n")
    
    total_records = 0
    missing_coords = 0
    out_of_bounds = []
    
    # Tracking duplicates/identities
    psm_ids = {}         # psmid -> list of records
    name_localities = {} # (psmName, lmtDName) -> list of records
    
    # Spatial indexing for 10-meter collision check
    # 0.00009 degrees is roughly 10 meters. We will group by cells.
    # Grid cell size = 0.0001 degrees (~11 meters)
    GRID_CELL_SIZE = 0.0001
    spatial_grid = defaultdict(list)
    valid_coords_list = []
    
    cards = []
    if target_file.endswith(".json"):
        with open(target_file, "r", encoding="utf-8") as f:
            try:
                cards = json.load(f)
            except Exception as e:
                print(f"Error parsing JSON: {e}")
                return
    else:
        with open(target_file, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    cards.append(json.loads(line))
                except Exception as e:
                    print(f"Line {idx}: JSON parse error: {e}")
                    continue

    for idx, card in enumerate(cards, 1):
        total_records += 1
        psmid = card.get("psmid")
        name = card.get("name") or card.get("psmName") or card.get("devName") or "Unknown"
        locality = card.get("locality") or card.get("lmtDName") or "Unknown"
        lat = card.get("lat") if "lat" in card else card.get("latitude")
        lon = card.get("lon") if "lon" in card else card.get("longitude")
        
        # 1. Geolocation Check
        if lat is None or lon is None:
            missing_coords += 1
        else:
            try:
                lat_f = float(lat)
                lon_f = float(lon)
                if not (LAT_MIN <= lat_f <= LAT_MAX) or not (LON_MIN <= lon_f <= LON_MAX):
                    out_of_bounds.append({
                        "line": idx,
                        "psmid": psmid,
                        "name": name,
                        "locality": locality,
                        "lat": lat_f,
                        "lon": lon_f
                    })
                else:
                    record_info = {
                        "line": idx,
                        "psmid": psmid,
                        "name": name,
                        "locality": locality,
                        "lat": lat_f,
                        "lon": lon_f
                    }
                    valid_coords_list.append(record_info)
                    
                    # Index into spatial grid
                    cell_lat = int(lat_f / GRID_CELL_SIZE)
                    cell_lon = int(lon_f / GRID_CELL_SIZE)
                    spatial_grid[(cell_lat, cell_lon)].append(record_info)
            except (ValueError, TypeError):
                missing_coords += 1

        # 2. Tracking duplicates by psmid
        if psmid:
            if psmid not in psm_ids:
                psm_ids[psmid] = []
            psm_ids[psmid].append((idx, name, locality))
            
        # 3. Tracking duplicates by name + locality
        key = (name.strip().lower(), locality.strip().lower())
        if key not in name_localities:
            name_localities[key] = []
            name_localities[key].append((idx, psmid))
        else:
            name_localities[key].append((idx, psmid))

    # --- Print Summary Statistics ---
    print(f"Total projects processed: {total_records}")
    print(f"Projects missing coordinates: {missing_coords} ({missing_coords/total_records*100:.2f}%)")
    print(f"Projects with valid coordinates: {total_records - missing_coords} ({(total_records - missing_coords)/total_records*100:.2f}%)")
    print(f"Projects out-of-bounds (outside Bangalore): {len(out_of_bounds)} ({len(out_of_bounds)/total_records*100:.2f}%)")
    
    # Print sample out-of-bounds
    if out_of_bounds:
        print("\n--- Out-of-bounds Sample (first 10) ---")
        for item in out_of_bounds[:10]:
            print(f"Line {item['line']} | ID: {item['psmid']} | '{item['name']}' in {item['locality']} -> ({item['lat']}, {item['lon']})")
        if len(out_of_bounds) > 10:
            print(f"... and {len(out_of_bounds) - 10} more.")

    # --- Duplicate ID check ---
    duplicate_ids = {k: v for k, v in psm_ids.items() if len(v) > 1}
    print(f"\nDuplicate psmid entries (same ID listed multiple times): {len(duplicate_ids)}")
    if duplicate_ids:
        print("Sample duplicates (first 5 IDs):")
        for psmid, occurrences in list(duplicate_ids.items())[:5]:
            occ_str = ", ".join([f"line {occ[0]} ('{occ[1]}')" for occ in occurrences])
            print(f"  ID {psmid} occurs {len(occurrences)} times: {occ_str}")
            
    # --- Duplicate project check (Name + Locality match) ---
    duplicate_names = {k: v for k, v in name_localities.items() if len(v) > 1}
    print(f"\nDuplicate project listings (same Project Name + Locality): {len(duplicate_names)}")
    if duplicate_names:
        print("Sample duplicate name + locality matches (first 5):")
        for (name, locality), occurrences in list(duplicate_names.items())[:5]:
            occ_str = ", ".join([f"line {occ[0]} (ID: {occ[1]})" for occ in occurrences])
            print(f"  '{name.title()}' in '{locality.title()}' occurs {len(occurrences)} times: {occ_str}")

    # --- 10-Meter Proximity / Collision Check ---
    print("\n=== Checking for spatial listings within 10 meters of each other ===")
    close_pairs = []
    checked_pairs = set()
    
    for (cell_lat, cell_lon), cell_records in spatial_grid.items():
        # Check within the same cell and 8 neighboring cells
        for dl_lat in [-1, 0, 1]:
            for dl_lon in [-1, 0, 1]:
                neighbor_cell = (cell_lat + dl_lat, cell_lon + dl_lon)
                if neighbor_cell not in spatial_grid:
                    continue
                
                for r1 in cell_records:
                    for r2 in spatial_grid[neighbor_cell]:
                        if r1['line'] >= r2['line']:
                            continue  # Avoid checking same pair twice or self-checks
                            
                        pair_key = (r1['line'], r2['line'])
                        if pair_key in checked_pairs:
                            continue
                        checked_pairs.add(pair_key)
                        
                        dist = haversine_distance_m(r1['lat'], r1['lon'], r2['lat'], r2['lon'])
                        if dist <= 10.0:
                            close_pairs.append((r1, r2, dist))

    print(f"Found {len(close_pairs)} pairs of listings within 10 meters of each other.")
    if close_pairs:
        print("\nSample of close proximity listings (first 10):")
        for r1, r2, dist in close_pairs[:10]:
            print(f"Distance: {dist:.1f}m")
            print(f"  - Project A: Line {r1['line']} | '{r1['name']}' in {r1['locality']} ({r1['lat']}, {r1['lon']})")
            print(f"  - Project B: Line {r2['line']} | '{r2['name']}' in {r2['locality']} ({r2['lat']}, {r2['lon']})")
            print("-" * 40)
        if len(close_pairs) > 10:
            print(f"... and {len(close_pairs) - 10} more close pairs.")

if __name__ == "__main__":
    main()
