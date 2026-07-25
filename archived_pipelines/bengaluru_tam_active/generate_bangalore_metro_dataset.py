import requests
import json
import csv
from pathlib import Path

# Define Output Paths
WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = WORKSPACE_DIR / "DATA" / "final"
OUTPUT_JSON_PATH = OUTPUT_DIR / "bangalore_metro_stations.json"
OUTPUT_CSV_PATH = OUTPUT_DIR / "bangalore_metro_stations.csv"

def fetch_metro_stations():
    print("Querying Overpass API for all metro stations in Bangalore...")
    
    # Bounding box covering Bangalore Metropolitan Area
    # (min_lat, min_lon, max_lat, max_lon)
    bbox = "12.80,77.40,13.15,77.80"
    
    query = f"""
    [out:json][timeout:90];
    (
      node["railway"="station"]["station"="subway"]({bbox});
      node["railway"="station"]["subway"="yes"]({bbox});
      node["railway"="station"]["operator"~"BMRCL|Namma Metro|Metro",i]({bbox});
      
      way["railway"="station"]["station"="subway"]({bbox});
      way["railway"="station"]["subway"="yes"]({bbox});
      way["railway"="station"]["operator"~"BMRCL|Namma Metro|Metro",i]({bbox});
      
      relation["railway"="station"]["station"="subway"]({bbox});
      relation["railway"="station"]["subway"="yes"]({bbox});
      relation["railway"="station"]["operator"~"BMRCL|Namma Metro|Metro",i]({bbox});
    );
    out center;
    """
    
    url = "https://overpass-api.de/api/interpreter"
    headers = {
        "User-Agent": "BangaloreMetroDatasetGenerator/1.0 (contact@rancholabs.com)",
        "Content-Type": "text/plain"
    }
    try:
        response = requests.post(url, data=query, headers=headers, timeout=90)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error querying Overpass API: {e}")
        return None

def process_and_clean_stations(data):
    if not data or "elements" not in data:
        print("No elements found in Overpass response.")
        return []
    
    stations = {}
    
    for element in data["elements"]:
        tags = element.get("tags", {})
        name = tags.get("name")
        
        # Fallback names
        if not name:
            name = tags.get("name:en") or tags.get("official_name")
            
        if not name:
            continue
            
        # Clean name: remove duplicates, normalize
        name = name.strip()
        
        # Extract lat/lon
        lat = element.get("lat") or (element.get("center", {}).get("lat") if "center" in element else None)
        lon = element.get("lon") or (element.get("center", {}).get("lon") if "center" in element else None)
        
        if lat is None or lon is None:
            continue
            
        # Standardize station name suffix
        clean_name = name
        if not (clean_name.endswith("Metro Station") or clean_name.endswith("metro station")):
            # If name has "Metro", just clean it, else append "Metro Station"
            if "metro" in clean_name.lower():
                pass
            else:
                clean_name = f"{clean_name} Metro Station"
                
        # Deduplicate stations by name or coordinates (if very close)
        # We can round coordinates to 3 decimal places (~110 meters) for duplicate detection
        coord_key = (round(lat, 3), round(lon, 3))
        
        station_data = {
            "name": clean_name,
            "original_name": name,
            "latitude": lat,
            "longitude": lon,
            "line": tags.get("line") or tags.get("route_ref") or tags.get("colour") or "Unknown",
            "operator": tags.get("operator") or "BMRCL",
            "wikipedia": tags.get("wikipedia") or "N/A",
            "osm_id": f"{element['type']}/{element['id']}"
        }
        
        # If coord_key is already present, keep the one with tags/railway=station info
        if coord_key in stations:
            # Overwrite if current name contains "Metro Station" and previous didn't
            if "Metro Station" in clean_name and "Metro Station" not in stations[coord_key]["name"]:
                stations[coord_key] = station_data
        else:
            stations[coord_key] = station_data
            
    # Also deduplicate by name
    unique_stations = {}
    for st in stations.values():
        name_key = st["name"].lower()
        if name_key not in unique_stations:
            unique_stations[name_key] = st
        else:
            # Keep the one with more tags (like route_ref or wikipedia)
            existing = unique_stations[name_key]
            if st["line"] != "Unknown" and existing["line"] == "Unknown":
                unique_stations[name_key] = st
                
    return sorted(list(unique_stations.values()), key=lambda x: x["name"])

def save_datasets(stations):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Save JSON
    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(stations, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(stations)} metro stations to {OUTPUT_JSON_PATH}")
    
    # Save CSV
    with open(OUTPUT_CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "original_name", "latitude", "longitude", "line", "operator", "wikipedia", "osm_id"])
        writer.writeheader()
        writer.writerows(stations)
    print(f"Saved {len(stations)} metro stations to {OUTPUT_CSV_PATH}")

def main():
    raw_data = fetch_metro_stations()
    if raw_data:
        stations = process_and_clean_stations(raw_data)
        save_datasets(stations)
    else:
        print("Failed to fetch data.")

if __name__ == "__main__":
    main()
