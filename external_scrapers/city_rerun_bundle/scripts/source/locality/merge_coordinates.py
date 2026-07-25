#!/usr/bin/env python3
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CITY_SLUG = os.environ.get("CITY_SLUG", "bangalore").strip().lower().replace(" ", "-")
LOCALITIES_FILE = BASE_DIR / "data" / "raw" / f"99acres_{CITY_SLUG}_localities.json"
COORDS_FILE = BASE_DIR / "data" / "processed" / f"99acres_{CITY_SLUG}_locality_coordinates.json"

def main():
    if not LOCALITIES_FILE.exists() or not COORDS_FILE.exists():
        print("Missing required files.")
        return

    # Load original localities
    with open(LOCALITIES_FILE, "r", encoding="utf-8") as f:
        localities = json.load(f)

    # Load coordinates mapping
    with open(COORDS_FILE, "r", encoding="utf-8") as f:
        coords_list = json.load(f)

    # Create a lookup dictionary by locality ID
    coords_map = {}
    for c in coords_list:
        if c.get("id"):
            coords_map[c["id"]] = {"lat": c.get("lat"), "lon": c.get("lon")}

    # Update localities
    updated_count = 0
    for loc in localities:
        loc_id = loc.get("id")
        if loc_id in coords_map:
            lat = coords_map[loc_id]["lat"]
            lon = coords_map[loc_id]["lon"]
            if lat is not None and lon is not None:
                loc["lat"] = lat
                loc["lon"] = lon
                updated_count += 1

    # Save back to the original file
    with open(LOCALITIES_FILE, "w", encoding="utf-8") as f:
        json.dump(localities, f, indent=2, ensure_ascii=False)

    print(f"Successfully appended coordinates to {updated_count} localities in {LOCALITIES_FILE.name}")

if __name__ == "__main__":
    main()
