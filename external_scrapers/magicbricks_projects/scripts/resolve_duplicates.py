#!/usr/bin/env python3
import json
import os
import math
from difflib import SequenceMatcher
from collections import defaultdict

CLASSIFIED_FILE = "data/processed/bangalore_projects_classified.json"
BACKUP_FILE = "data/processed/bangalore_projects_classified.json.bak"

# Hierarchy of categories for picking the highest one
CATEGORY_ORDER = [
    "Affordable",
    "Mid-Range",
    "Aspire / Upper-Mid",
    "Premium Luxury",
    "Super Luxury",
    "Ultra Luxury",
    "Elite Luxury"
]

def get_category_rank(cat):
    if cat in CATEGORY_ORDER:
        return CATEGORY_ORDER.index(cat)
    return -1

def haversine_distance_m(lat1, lon1, lat2, lon2):
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

def name_similarity(n1, n2):
    return SequenceMatcher(None, n1.lower(), n2.lower()).ratio()

class UnionFind:
    def __init__(self, size):
        self.parent = list(range(size))
        
    def find(self, i):
        if self.parent[i] == i:
            return i
        self.parent[i] = self.find(self.parent[i])
        return self.parent[i]
        
    def union(self, i, j):
        root_i = self.find(i)
        root_j = self.find(j)
        if root_i != root_j:
            self.parent[root_i] = root_j
            return True
        return False

def merge_group(group_projects):
    # Primary record is the one with the most filled details, or just the first
    # Let's count non-null fields
    def score(p):
        cnt = 0
        if p.get("name"): cnt += 1
        if p.get("locality"): cnt += 1
        if p.get("price_SQFT"): cnt += 1
        if p.get("min_price"): cnt += 1
        if p.get("max_price"): cnt += 1
        if p.get("url") and "magicbricks" in p.get("url"): cnt += 2
        return cnt
        
    sorted_group = sorted(group_projects, key=score, reverse=True)
    primary = sorted_group[0]
    
    # 1. Name: Pick shortest name to avoid "Phase 2" suffixes if we have a shorter clean version
    names = [p.get("name") for p in group_projects if p.get("name")]
    shortest_name = min(names, key=len) if names else primary.get("name")
    
    # 2. Coordinates: average
    lats = [float(p["lat"]) for p in group_projects if p.get("lat") is not None]
    lons = [float(p["lon"]) for p in group_projects if p.get("lon") is not None]
    avg_lat = sum(lats) / len(lats) if lats else primary.get("lat")
    avg_lon = sum(lons) / len(lons) if lons else primary.get("lon")
    
    # 3. Prices
    min_prices = [p["min_price"] for p in group_projects if p.get("min_price")]
    max_prices = [p["max_price"] for p in group_projects if p.get("max_price")]
    sqfts = [p["price_SQFT"] for p in group_projects if p.get("price_SQFT")]
    
    merged_min = min(min_prices) if min_prices else primary.get("min_price")
    merged_max = max(max_prices) if max_prices else primary.get("max_price")
    merged_sqft = sum(sqfts) / len(sqfts) if sqfts else primary.get("price_SQFT")
    
    # 4. Units (should be the same, but let's take max/first)
    units_list = [p["units"] for p in group_projects if p.get("units") is not None]
    merged_units = units_list[0] if units_list else primary.get("units")
    
    # 5. Category (highest luxury rank)
    categories = [p.get("category") for p in group_projects if p.get("category")]
    best_cat = max(categories, key=get_category_rank) if categories else primary.get("category")
    
    # 6. Construction status: if any is "Under Construction", keep it
    statuses = [p.get("construction_status") for p in group_projects if p.get("construction_status")]
    merged_status = "Under Construction" if "Under Construction" in statuses else "Ready To Move"
    
    # 7. URL: Prefer magicbricks URL if available
    urls = [p.get("url") for p in group_projects if p.get("url")]
    mb_urls = [u for u in urls if "magicbricks" in u]
    merged_url = mb_urls[0] if mb_urls else (urls[0] if urls else "")
    
    # 8. Locality: first non-empty
    localities = [p.get("locality") for p in group_projects if p.get("locality")]
    merged_locality = localities[0] if localities else primary.get("locality")
    
    return {
        "name": shortest_name,
        "lat": avg_lat,
        "lon": avg_lon,
        "category": best_cat,
        "quartile analysis 1": primary.get("quartile analysis 1"),
        "quartile analysis 2": primary.get("quartile analysis 2"),
        "price_SQFT": merged_sqft,
        "locality": merged_locality,
        "units": merged_units,
        "hex_id": "",
        "url": merged_url,
        "construction_status": merged_status,
        "min_price": merged_min,
        "max_price": merged_max
    }

def main():
    if not os.path.exists(CLASSIFIED_FILE):
        print(f"Error: {CLASSIFIED_FILE} does not exist.")
        return
        
    # Backup original file
    if not os.path.exists(BACKUP_FILE):
        import shutil
        shutil.copy(CLASSIFIED_FILE, BACKUP_FILE)
        print(f"Backed up original file to {BACKUP_FILE}")
        
    with open(CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        projects = json.load(f)
        
    n = len(projects)
    print(f"Loaded {n} projects from database.")
    
    # Spatial Indexing
    GRID_CELL_SIZE = 0.0001
    spatial_grid = defaultdict(list)
    
    for idx, p in enumerate(projects):
        lat = p.get("lat")
        lon = p.get("lon")
        if lat is None or lon is None:
            continue
        cell_lat = int(float(lat) / GRID_CELL_SIZE)
        cell_lon = int(float(lon) / GRID_CELL_SIZE)
        spatial_grid[(cell_lat, cell_lon)].append((idx, p))
        
    uf = UnionFind(n)
    duplicate_pairs = 0
    checked_pairs = set()
    
    for (cell_lat, cell_lon), cell_records in spatial_grid.items():
        for dl_lat in [-1, 0, 1]:
            for dl_lon in [-1, 0, 1]:
                neighbor_cell = (cell_lat + dl_lat, cell_lon + dl_lon)
                if neighbor_cell not in spatial_grid:
                    continue
                    
                for idx1, r1 in cell_records:
                    for idx2, r2 in spatial_grid[neighbor_cell]:
                        if idx1 >= idx2:
                            continue
                            
                        pair_key = (idx1, idx2)
                        if pair_key in checked_pairs:
                            continue
                        checked_pairs.add(pair_key)
                        
                        dist = haversine_distance_m(r1['lat'], r1['lon'], r2['lat'], r2['lon'])
                        if dist <= 5.0:
                            u1 = r1.get("units")
                            u2 = r2.get("units")
                            if u1 is not None and u2 is not None and u1 == u2 and u1 != 0:
                                sim = name_similarity(r1['name'], r2['name'])
                                if sim >= 0.8:
                                    uf.union(idx1, idx2)
                                    duplicate_pairs += 1
                                    
    print(f"Identified {duplicate_pairs} duplicate relationships.")
    
    # Group by UnionFind parents
    groups = defaultdict(list)
    for idx in range(n):
        parent = uf.find(idx)
        groups[parent].append(projects[idx])
        
    merged_projects = []
    consolidated_count = 0
    
    for parent, group in groups.items():
        if len(group) > 1:
            consolidated_count += len(group) - 1
            merged_rec = merge_group(group)
            merged_projects.append(merged_rec)
            
            # Print example of merged records
            if len(merged_projects) <= 15:
                print(f"\nMerged Group of {len(group)}:")
                for p in group:
                    print(f"  - Name: '{p['name']}' | Locality: '{p['locality']}' | Units: {p['units']} | Price: {p.get('min_price')/1e7 if p.get('min_price') else 0:.2f} Cr")
                print(f"  ==> Result: '{merged_rec['name']}' | Locality: '{merged_rec['locality']}' | Price SQFT: {merged_rec.get('price_SQFT')} | Min Price: {merged_rec.get('min_price')/1e7 if merged_rec.get('min_price') else 0:.2f} Cr")
        else:
            merged_projects.append(group[0])
            
    print(f"\nConsolidation Summary:")
    print(f"  - Original count: {n}")
    print(f"  - Removed duplicates: {consolidated_count}")
    print(f"  - De-duplicated count: {len(merged_projects)}")
    
    # Save the de-duplicated array
    with open(CLASSIFIED_FILE, "w", encoding="utf-8") as f:
        json.dump(merged_projects, f, indent=2, ensure_ascii=False)
    print(f"Successfully saved de-duplicated dataset to {CLASSIFIED_FILE}")

if __name__ == "__main__":
    main()
