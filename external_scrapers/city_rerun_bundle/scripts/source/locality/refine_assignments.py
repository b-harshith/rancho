import json
import os
import math
import time
from shapely.geometry import shape, Point
from shapely.ops import nearest_points
from pyproj import Geod
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

CITY_SLUG = os.environ.get("CITY_SLUG", "bangalore").strip().lower().replace(" ", "-")
CITY_NAME = os.environ.get("CITY_NAME", CITY_SLUG.replace("-", " ").title())
CITY_GEOCODE_CONTEXT = os.environ.get("CITY_GEOCODE_CONTEXT", CITY_NAME)

def haversine(lon1, lat1, lon2, lat2):
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def geocode_locality(geolocator, name):
    try:
        # Search with the configured city appended
        query = f"{name}, {CITY_GEOCODE_CONTEXT}"
        location = geolocator.geocode(query, timeout=5)
        if location:
            return location.longitude, location.latitude
    except GeocoderTimedOut:
        pass
    except Exception:
        pass
    return None, None

def main():
    overture_path = f"data/processed/{CITY_SLUG}_overture_raw_divisions.json"
    mapped_path = f"data/processed/{CITY_SLUG}_mapped_data/{CITY_SLUG}_mapped_locality_boundaries.json"
    output_path = f"data/processed/{CITY_SLUG}_mapped_data/{CITY_SLUG}_mapped_locality_boundaries_refined.json"

    print("Loading Overture boundaries...")
    with open(overture_path, 'r', encoding='utf-8') as f:
        divisions = json.load(f)

    geod = Geod(ellps="WGS84")
    boundaries = []
    for div in divisions:
        try:
            geom = shape(div['geojson'])
            perimeter_m = geod.geometry_length(geom)
            boundaries.append({
                'id': div['overture_id'],
                'name': div['name'],
                'subtype': div['subtype'],
                'geom': geom,
                'area': geom.area,
                'perimeter_km': round(perimeter_m / 1000, 2),
                'geojson': div['geojson']
            })
        except:
            pass

    # Sort boundaries by area
    boundaries.sort(key=lambda x: x['area'])

    print("Loading mapped localities...")
    with open(mapped_path, 'r', encoding='utf-8') as f:
        localities = json.load(f)

    geolocator = Nominatim(user_agent=f"{CITY_SLUG}_mapper_script")

    refined_count = 0
    distance_assigned_count = 0

    unmapped = [loc for loc in localities if not loc.get('assigned_neighborhood')]
    print(f"Found {len(unmapped)} unmapped localities to refine.")

    for i, loc in enumerate(unmapped):
        name = loc['localityName']
        print(f"[{i+1}/{len(unmapped)}] Refining {name}...")
        
        # 1. Geocode
        lon, lat = geocode_locality(geolocator, name)
        time.sleep(1) # rate limit
        
        assigned = False
        pt = None
        if lon and lat:
            loc['lon'] = lon
            loc['lat'] = lat
            loc['found'] = True
            loc['details']['lon'] = lon
            loc['details']['lat'] = lat
            loc['details']['display_name'] += " (Refined via Geocoding)"
            
            pt = Point(lon, lat)
            
            # Check strict containment
            for b in boundaries:
                if b['geom'].contains(pt):
                    loc['assigned_neighborhood'] = {
                        'id': b['id'],
                        'name': b['name'],
                        'subtype': b['subtype'],
                        'perimeter_km': b['perimeter_km'],
                        'perimeter_coordinates': b['geojson']['coordinates']
                    }
                    assigned = True
                    refined_count += 1
                    print(f"  -> Contained in {b['name']} after geocoding")
                    break
        
        # 2. If still not assigned, check distance < 1km
        if not assigned:
            # use new pt if found, else original pt
            if 'lon' in loc and 'lat' in loc:
                pt = Point(loc['lon'], loc['lat'])
            
            if pt:
                min_dist = float('inf')
                closest_b = None
                
                for b in boundaries:
                    dist_deg = pt.distance(b['geom'])
                    if dist_deg < min_dist:
                        min_dist = dist_deg
                        closest_b = b
                
                if closest_b:
                    p1, p2 = nearest_points(pt, closest_b['geom'])
                    dist_km = haversine(p1.x, p1.y, p2.x, p2.y)
                    
                    if dist_km <= 1.0:
                        loc['assigned_neighborhood'] = {
                            'id': closest_b['id'],
                            'name': closest_b['name'],
                            'subtype': closest_b['subtype'],
                            'perimeter_km': closest_b['perimeter_km'],
                            'perimeter_coordinates': closest_b['geojson']['coordinates']
                        }
                        distance_assigned_count += 1
                        print(f"  -> Assigned to {closest_b['name']} based on distance ({dist_km:.2f} km)")
                    else:
                        print(f"  -> Still unmapped. Closest is {closest_b['name']} at {dist_km:.2f} km")

    print(f"\nSummary:")
    print(f"Total unmapped initially: {len(unmapped)}")
    print(f"Assigned by geocoding: {refined_count}")
    print(f"Assigned by <1km distance: {distance_assigned_count}")

    # Save to the original file path to overwrite
    with open(mapped_path, 'w', encoding='utf-8') as f:
        json.dump(localities, f, indent=2)
    print(f"Saved refined localities to {mapped_path}")

if __name__ == '__main__':
    main()
