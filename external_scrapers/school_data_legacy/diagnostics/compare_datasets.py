import json
import csv
import os
import re

def normalize_name(name):
    if not name:
        return ""
    name = name.lower()
    name = re.sub(r'[^a-z0-9\s]', ' ', name)
    stop_words = {'school', 'public', 'private', 'the', 'of', 'and', 'for', 'in', 'high', 'primary', 'secondary', 'composite', 'co', 'education', 'junior', 'college'}
    words = [w for w in name.split() if w not in stop_words]
    return " ".join(words)

def clean_float(val):
    if val is None or val == "NA":
        return None
    try:
        return float(val)
    except ValueError:
        return None

def main():
    json_path = "school_averages_summary_bangalore.json"
    if not os.path.exists(json_path):
        json_path = "school_averages_summary.json"
        
    csv_path = "unique_schools_details.csv"
    
    if not os.path.exists(json_path):
        print(f"Error: JSON summary not found at {json_path}")
        return
    if not os.path.exists(csv_path):
        print(f"Error: unique_schools_details.csv not found at {csv_path}")
        return
        
    print(f"Loading school averages JSON ({json_path})...")
    with open(json_path, 'r', encoding='utf-8') as f:
        averages = json.load(f)
        
    print(f"Loading unique schools details CSV ({csv_path})...")
    unique_schools = []
    with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.DictReader(f)
        for row in reader:
            unique_schools.append(row)
            
    print(f"\nDataset Statistics:")
    print(f" - School Averages Summary: {len(averages)} schools")
    print(f" - Unique Schools Details: {len(unique_schools)} schools")
    
    averages_processed = []
    for idx, s in enumerate(averages):
        lat = clean_float(s.get("Latitude"))
        lon = clean_float(s.get("Longitude"))
        name = s.get("School Name", "")
        averages_processed.append({
            'idx': idx,
            'name': name,
            'norm_name': normalize_name(name),
            'lat': lat,
            'lon': lon,
            'board': s.get("Board", ""),
            'raw': s
        })
        
    unique_processed = []
    for idx, s in enumerate(unique_schools):
        lat = clean_float(s.get("Latitude"))
        lon = clean_float(s.get("Longitude"))
        name = s.get("Name", "")
        unique_processed.append({
            'idx': idx,
            'name': name,
            'norm_name': normalize_name(name),
            'lat': lat,
            'lon': lon,
            'board': s.get("Board", ""),
            'raw': s
        })
        
    matched_unique_idxs = set()
    matched_averages_idxs = set()
    name_matches = 0
    coord_matches = 0
    
    print("\nMatching process...")
    for u in unique_processed:
        u_idx = u['idx']
        u_name = u['name']
        u_norm = u['norm_name']
        u_lat = u['lat']
        u_lon = u['lon']
        
        found = False
        for av in averages_processed:
            if u_norm == av['norm_name'] and u_norm != "":
                matched_unique_idxs.add(u_idx)
                matched_averages_idxs.add(av['idx'])
                name_matches += 1
                found = True
                break
                
        if found:
            continue
            
        if u_lat is not None and u_lon is not None:
            for av in averages_processed:
                if av['lat'] is not None and av['lon'] is not None:
                    dist_sq = (u_lat - av['lat'])**2 + (u_lon - av['lon'])**2
                    if dist_sq < 0.00000025:
                        u_words = set(u_norm.split())
                        av_words = set(av['norm_name'].split())
                        if u_words.intersection(av_words) or dist_sq < 1e-10:
                            matched_unique_idxs.add(u_idx)
                            matched_averages_idxs.add(av['idx'])
                            coord_matches += 1
                            found = True
                            break
                            
    total_matched = len(matched_unique_idxs)
    unmatched_unique = [u for u in unique_processed if u['idx'] not in matched_unique_idxs]
    unmatched_averages = [av for av in averages_processed if av['idx'] not in matched_averages_idxs]
    
    print(f"\nComparison Results:")
    print(f" - Total Matched Schools: {total_matched}")
    print(f"   * Matched via name/normalized name: {name_matches}")
    print(f"   * Matched via close coordinates & keywords: {coord_matches}")
    print(f" - Schools in Unique Dataset but NOT in School Averages: {len(unmatched_unique)}")
    print(f" - Schools in School Averages but NOT in Unique Dataset: {len(unmatched_averages)}")

if __name__ == "__main__":
    main()
