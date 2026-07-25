import json
import os
from shapely.geometry import shape, Point
from collections import defaultdict
from pyproj import Geod

def main():
    # Paths
    overture_path = 'data/processed/overture_raw_bangalore_divisions.json'
    localities_path = 'data/processed/99acres_locality_coordinates.json'
    
    # Store in separate folder and add bangalore to the name
    output_dir = 'data/processed/bangalore_mapped_data'
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = os.path.join(output_dir, 'bangalore_mapped_locality_boundaries.json')
    stats_path = os.path.join(output_dir, 'bangalore_neighborhood_stats.json')

    # WGS84 Geodesic for accurate perimeter calculation
    geod = Geod(ellps="WGS84")

    print("Loading Overture boundaries...")
    with open(overture_path, 'r', encoding='utf-8') as f:
        divisions = json.load(f)

    # Convert geometries to shapely objects
    boundaries = []
    for div in divisions:
        try:
            geom = shape(div['geojson'])
            # calculate perimeter in meters, then convert to km
            perimeter_m = geod.geometry_length(geom)
            perimeter_km = round(perimeter_m / 1000, 2)
            
            boundaries.append({
                'id': div['overture_id'],
                'name': div['name'],
                'subtype': div['subtype'],
                'geom': geom,
                'area': geom.area,
                'perimeter_km': perimeter_km,
                'geojson': div['geojson']
            })
        except Exception as e:
            pass

    print(f"Loaded {len(boundaries)} boundaries.")

    # Sort boundaries by area (smallest to largest)
    boundaries.sort(key=lambda x: x['area'])

    print("Loading localities...")
    with open(localities_path, 'r', encoding='utf-8') as f:
        localities = json.load(f)
    print(f"Loaded {len(localities)} localities.")

    # Assign neighborhoods
    assigned_count = 0
    neighborhood_counts = defaultdict(int)

    for loc in localities:
        if not loc.get('found') or 'lon' not in loc or 'lat' not in loc:
            loc['assigned_neighborhood'] = None
            continue
        
        pt = Point(loc['lon'], loc['lat'])
        
        matched_boundary = None
        for b in boundaries:
            if b['geom'].contains(pt):
                # Since boundaries are sorted by area, the first match is the smallest container
                matched_boundary = b
                break
                
        if matched_boundary:
            loc['assigned_neighborhood'] = {
                'id': matched_boundary['id'],
                'name': matched_boundary['name'],
                'subtype': matched_boundary['subtype'],
                'perimeter_km': matched_boundary['perimeter_km'],
                'perimeter_coordinates': matched_boundary['geojson']['coordinates']
            }
            assigned_count += 1
            neighborhood_counts[matched_boundary['name']] += 1
        else:
            loc['assigned_neighborhood'] = None

    print(f"Assigned {assigned_count} out of {len(localities)} localities to a neighborhood.")

    # Save localities with assignments
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(localities, f, indent=2)
    print(f"Saved updated localities to {output_path}")

    # Remove the old file if it exists to avoid confusion
    old_file_path = 'data/processed/99acres_locality_with_neighborhoods.json'
    if os.path.exists(old_file_path):
        os.remove(old_file_path)
        print(f"Deleted old file: {old_file_path}")

    # Save stats
    stats = [{"neighborhood": k, "count": v} for k, v in sorted(neighborhood_counts.items(), key=lambda x: x[1], reverse=True)]
    with open(stats_path, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2)
    print(f"Saved neighborhood stats to {stats_path}")

    # Print top 15 neighborhoods
    print("\nTop 15 Neighborhoods by locality count:")
    for stat in stats[:15]:
        print(f"  {stat['neighborhood']}: {stat['count']}")

if __name__ == '__main__':
    main()
