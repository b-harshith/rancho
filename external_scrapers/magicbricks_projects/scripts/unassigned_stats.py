import json
import csv
import math
from shapely.geometry import shape, Point
from shapely.ops import nearest_points

def haversine(lon1, lat1, lon2, lat2):
    # Radius of earth in kilometers.
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

def main():
    with open('data/processed/overture_raw_bangalore_divisions.json', 'r', encoding='utf-8') as f:
        divisions = json.load(f)
    
    boundaries = []
    for div in divisions:
        try:
            geom = shape(div['geojson'])
            boundaries.append({
                'name': div['name'],
                'geom': geom
            })
        except:
            pass

    with open('data/processed/99acres_locality_with_neighborhoods.json', 'r', encoding='utf-8') as f:
        localities = json.load(f)
    
    unassigned = [loc for loc in localities if loc.get('assigned_neighborhood') is None and loc.get('found') and 'lon' in loc]

    # Load bangalore.csv for listings stats
    listings_by_loc = {}
    with open('data/processed/bangalore.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            loc = (row.get('locality', '') + ' ' + row.get('sublocality', '')).lower()
            price_sqft = row.get('price_per_sqft', '')
            if price_sqft:
                try:
                    price_sqft = float(price_sqft)
                except ValueError:
                    price_sqft = None
            else:
                price_sqft = None

            # Add to matching localities
            # We will evaluate against unassigned ones below
            for u in unassigned:
                name = u['localityName'].lower()
                if name in loc:
                    if name not in listings_by_loc:
                        listings_by_loc[name] = []
                    if price_sqft is not None:
                        listings_by_loc[name].append(price_sqft)

    results = []
    for u in unassigned:
        pt = Point(u['lon'], u['lat'])
        
        # Find closest boundary
        min_dist = float('inf')
        closest_name = ""
        closest_dist_km = 0
        
        for b in boundaries:
            dist = pt.distance(b['geom'])
            if dist < min_dist:
                min_dist = dist
                p1, p2 = nearest_points(pt, b['geom'])
                closest_dist_km = haversine(p1.x, p1.y, p2.x, p2.y)
                closest_name = b['name']
        
        name_lower = u['localityName'].lower()
        prices = listings_by_loc.get(name_lower, [])
        inventory = len(prices)
        avg_price = sum(prices) / len(prices) if prices else 0
        
        results.append({
            'Locality': u['localityName'],
            'Closest Neighborhood': closest_name,
            'Distance (km)': f"{closest_dist_km:.2f}",
            'Avg Price/Sqft': f"₹{avg_price:.2f}" if inventory > 0 else "N/A",
            'Inventory Count': inventory
        })

    # Sort by distance
    results.sort(key=lambda x: float(x['Distance (km)']), reverse=True)

    # Print markdown table
    print("| Locality | Closest Neighborhood | Distance (km) | Avg Price/Sqft | Inventory Count |")
    print("|---|---|---|---|---|")
    for r in results:
        print(f"| {r['Locality']} | {r['Closest Neighborhood']} | {r['Distance (km)']} | {r['Avg Price/Sqft']} | {r['Inventory Count']} |")

if __name__ == '__main__':
    main()
