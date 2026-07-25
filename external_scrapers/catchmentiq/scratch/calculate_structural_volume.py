import json
import os
import time
import h3
import numpy as np
from shapely.geometry import shape

def main():
    start_time = time.time()
    buildings_path = "overture/bangalore_buildings.geojson"
    out_path = "data/processed/structural_volume_h3_res7.json"
    
    if not os.path.exists(buildings_path):
        print(f"Error: Buildings file not found at {buildings_path}")
        return
        
    print(f"Reading buildings from {buildings_path}...")
    
    # Conversion factor for deg^2 to m^2 in Bangalore (lat ~12.97)
    # 111120 * 111120 * cos(12.97 deg) = 1.203e10
    DEG2_TO_M2 = 111120.0 * 111120.0 * np.cos(np.radians(12.97))
    
    volume_by_hex = {}
    count = 0
    errors = 0
    
    with open(buildings_path, "r") as f:
        # Skip first line which is the FeatureCollection start
        f.readline()
        
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.endswith(","):
                line = line[:-1]
            if line == "]}":
                continue
                
            try:
                feat = json.loads(line)
                geom_type = feat["geometry"]["type"]
                # We can do a quick check to avoid parsing point/linestring if they exist
                if geom_type not in ["Polygon", "MultiPolygon"]:
                    continue
                    
                props = feat.get("properties", {})
                
                # Get levels
                levels = None
                num_floors = props.get("num_floors")
                if num_floors is not None:
                    try:
                        levels = float(num_floors)
                    except (ValueError, TypeError):
                        pass
                
                if levels is None:
                    level = props.get("level")
                    if level is not None:
                        try:
                            levels = float(level)
                        except (ValueError, TypeError):
                            pass
                            
                if levels is None:
                    height = props.get("height")
                    if height is not None:
                        try:
                            levels = float(height) / 3.0
                        except (ValueError, TypeError):
                            pass
                            
                if levels is None or levels <= 0:
                    levels = 1.0
                
                # Parse geometry and compute area
                geom = shape(feat["geometry"])
                centroid = geom.centroid
                
                # Convert centroid to H3 Res 7
                hex_id = h3.latlng_to_cell(centroid.y, centroid.x, 7)
                
                # Area in square meters
                area_m2 = geom.area * DEG2_TO_M2
                
                # Volume = Footprint Area * Levels
                volume = area_m2 * levels
                
                volume_by_hex[hex_id] = volume_by_hex.get(hex_id, 0.0) + volume
                
                count += 1
                if count % 200000 == 0:
                    print(f"Processed {count} buildings... (elapsed: {time.time() - start_time:.1f}s)")
                    
            except Exception as e:
                errors += 1
                if errors < 10:
                    print(f"Error parsing line: {e}")
                continue
                
    print(f"Finished processing {count} buildings (errors: {errors}).")
    print(f"Found volume for {len(volume_by_hex)} unique H3 cells.")
    
    # Save results
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(volume_by_hex, f, indent=2)
        
    print(f"Saved structural volume mapping to {out_path}")
    print(f"Total execution time: {time.time() - start_time:.1f} seconds.")

if __name__ == "__main__":
    main()
