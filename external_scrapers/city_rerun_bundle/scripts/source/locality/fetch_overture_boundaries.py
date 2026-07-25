#!/usr/bin/env python3
import json
import os
from pathlib import Path
import duckdb

# Config
BASE_DIR = Path(__file__).resolve().parent.parent
CITY_SLUG = os.environ.get("CITY_SLUG", "bangalore").strip().lower().replace(" ", "-")
CITY_METRO_BOUNDS = json.loads(
    os.environ.get(
        "CITY_METRO_BOUNDS_JSON",
        json.dumps({
            "min_lat": 12.5,
            "max_lat": 13.5,
            "min_lon": 77.1,
            "max_lon": 78.2,
        }),
    )
)
INPUT_FILE = BASE_DIR / "data" / "raw" / f"99acres_{CITY_SLUG}_localities.json"
OUTPUT_DIR = BASE_DIR / "data" / "processed"
OUTPUT_FILE = OUTPUT_DIR / f"99acres_{CITY_SLUG}_locality_boundaries.json"

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Load 99acres localities
    if not INPUT_FILE.exists():
        print(f"Error: Input file {INPUT_FILE} not found.")
        return
        
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        localities = json.load(f)
    print(f"Loaded {len(localities)} 99acres localities.")
    
    # Extract names and map them lowercase for matching
    name_map = {}
    for loc in localities:
        name = loc.get("localityName")
        loc_id = loc.get("id")
        if name and loc_id:
            name_map[name.lower().strip()] = {
                "id": loc_id,
                "original_name": name
            }

    # 2. Query Overture Maps via DuckDB
    print("Initializing DuckDB connection...")
    con = duckdb.connect()
    
    print("Loading spatial and httpfs extensions...")
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2';")
    
    bbox_filter = """
        bbox.xmin <= {max_lon} AND bbox.xmax >= {min_lon}
        AND bbox.ymin <= {max_lat} AND bbox.ymax >= {min_lat}
    """.format(
        min_lat=CITY_METRO_BOUNDS["min_lat"],
        max_lat=CITY_METRO_BOUNDS["max_lat"],
        min_lon=CITY_METRO_BOUNDS["min_lon"],
        max_lon=CITY_METRO_BOUNDS["max_lon"],
    )
    
    query = f"""
        SELECT 
            id AS overture_id,
            names.primary AS name,
            subtype,
            ST_AsGeoJSON(geometry) AS geojson_str,
            bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax
        FROM read_parquet('s3://overturemaps-us-west-2/release/2026-05-20.0/theme=divisions/type=division_area/*', 
                          filename=true, 
                          hive_partitioning=1)
        WHERE (subtype = 'neighborhood' OR subtype = 'locality' OR subtype = 'city')
          AND {bbox_filter}
    """
    
    print("Running Overture query on S3. This may take a minute...")
    results = con.execute(query).fetchall()
    print(f"Retrieved {len(results)} division areas from Overture Maps.")
    
    # 3. Match and correlate
    matched_records = []
    overture_divisions = []
    
    for row in results:
        ov_id, ov_name, subtype, geojson_str, xmin, xmax, ymin, ymax = row
        if not ov_name:
            continue
            
        ov_name_clean = ov_name.lower().strip()
        geojson_data = json.loads(geojson_str) if geojson_str else None
        
        overture_divisions.append({
            "overture_id": ov_id,
            "name": ov_name,
            "subtype": subtype,
            "geojson": geojson_data,
            "bbox": [xmin, ymin, xmax, ymax]
        })
        
        # Check direct match
        if ov_name_clean in name_map:
            loc_info = name_map[ov_name_clean]
            matched_records.append({
                "id": loc_info["id"],
                "localityName": loc_info["original_name"],
                "overture_name": ov_name,
                "subtype": subtype,
                "bbox": [xmin, ymin, xmax, ymax],
                "geojson": geojson_data
            })
            
    print(f"Successfully matched: {len(matched_records)} localities.")
    
    # Save the matched list
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(matched_records, f, indent=2, ensure_ascii=False)
        
    print(f"Saved results to {OUTPUT_FILE}")
    
    # Also save raw overture divisions for reference/debug
    raw_output = OUTPUT_DIR / f"{CITY_SLUG}_overture_raw_divisions.json"
    with open(raw_output, "w", encoding="utf-8") as f:
        json.dump(overture_divisions, f, indent=2, ensure_ascii=False)
    print(f"Saved all raw Overture division areas to {raw_output}")

if __name__ == "__main__":
    main()
