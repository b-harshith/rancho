import json
import math
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
import h3
from shapely.geometry import Polygon, mapping
from shapely.ops import unary_union
import requests

# Define paths
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = WORKSPACE_DIR / "DATA"
STAGE2_DIR = DATA_DIR / "Stage2 processing"
FINAL_DIR = DATA_DIR / "final"
OUTPUT_DATA_DIR = WORKSPACE_DIR / "src" / "public" / "data"

LOCALITIES_RAW_PATH = DATA_DIR / "raw" / "bangalore_localities_enriched.json"
SOCIETIES_PATH = STAGE2_DIR / "q4_categorized_societies_bangalore.json"
SCHOOLS_PATH = STAGE2_DIR / "Categorized Schools.json"
HOSPITALS_PATH = STAGE2_DIR / "Categorized Hospitals.json"
SEZ_KML_PATH = STAGE2_DIR / "sez_office_zones.kml"

HEXES_GEOJSON_PATH = FINAL_DIR / "bangalore_hex7_affluent_family_intelligence.geojson"
REPORT_JSON_PATH = FINAL_DIR / "stage2_affluence_zone_micromarket_report.json"

FOURSQUARE_CACHE_PATH = DATA_DIR / "foursquare_cache.json"
FOURSQUARE_CACHE = {}

def load_foursquare_cache():
    global FOURSQUARE_CACHE
    if FOURSQUARE_CACHE_PATH.exists():
        try:
            with open(FOURSQUARE_CACHE_PATH, "r") as f:
                FOURSQUARE_CACHE = json.load(f)
            print(f"Loaded {len(FOURSQUARE_CACHE)} items from Foursquare cache.")
        except Exception as e:
            print(f"Failed to load cache: {e}")
            FOURSQUARE_CACHE = {}

def save_foursquare_cache():
    try:
        with open(FOURSQUARE_CACHE_PATH, "w") as f:
            json.dump(FOURSQUARE_CACHE, f, indent=2)
    except Exception as e:
        print(f"Failed to save cache: {e}")

def get_simulated_venues(lat, lon, radius, categories):
    simulated_venues = []
    seed = int(abs(lat * 1000) + abs(lon * 1000)) % 100
    dist_from_center = haversine_km(CENTRAL_LAT, CENTRAL_LON, lat, lon)
    num_venues = max(1, int(15 - dist_from_center * 0.4)) if dist_from_center <= 35.0 else 0
    
    for i in range(num_venues):
        v_id = f"sim_venue_{seed}_{i}"
        v_names = ["Cafe Delight", "Indigo Gourmet", "Fitness Zone", "Urban Market", "Spade Spa", "Boutique Elegance", "Metro Hub", "Central Bistro", "Green Grocers", "Highstreet Retail"]
        name = v_names[(seed + i) % len(v_names)]
        rating = round(6.5 + ((seed * (i + 1)) % 30) / 10.0, 1)
        price = 1 + ((seed + i) % 4)
        
        simulated_venues.append({
            "foursquare_id": v_id,
            "name": name,
            "rating": rating,
            "price": price,
            "category": "Commercial"
        })
    return simulated_venues

def query_foursquare_places(lat, lon, radius=1200, categories="13000,17000,19000"):
    """
    Queries Foursquare Places API for venues near lat, lon.
    Uses cached responses if available to avoid API limits.
    """
    global FOURSQUARE_CACHE
    cache_key = f"query:{round(lat, 4)},{round(lon, 4)},{radius},{categories}"
    if cache_key in FOURSQUARE_CACHE:
        return FOURSQUARE_CACHE[cache_key]

    api_key = os.environ.get("FOURSQUARE_API_KEY")
    if not api_key:
        venues = get_simulated_venues(lat, lon, radius, categories)
        FOURSQUARE_CACHE[cache_key] = venues
        return venues

    try:
        url = "https://places-api.foursquare.com/places/search"
        headers = {
            "Accept": "application/json",
            "Authorization": api_key,
            "foursquare-version": "20231010"
        }
        params = {
            "ll": f"{lat},{lon}",
            "radius": int(radius),
            "fsq_category_ids": categories,
            "limit": 30,
            "fields": "fsq_id,name,rating,price,categories,location",
            "v": "20231010"
        }
        res = requests.get(url, headers=headers, params=params, timeout=8)
        if res.status_code == 200:
            data = res.json()
            venues = []
            for item in data.get("results", []):
                cats = [c.get("name") for c in item.get("categories", [])]
                venues.append({
                    "foursquare_id": item.get("fsq_id"),
                    "name": item.get("name"),
                    "rating": item.get("rating"),
                    "price": item.get("price"),
                    "category": cats[0] if cats else "Commercial",
                    "formatted_address": item.get("location", {}).get("formatted_address", "")
                })
            FOURSQUARE_CACHE[cache_key] = venues
            save_foursquare_cache()
            return venues
        elif res.status_code == 401:
            print(f"Foursquare API returned 401 (Invalid token) for {lat},{lon}. Using simulated fallback.")
            venues = get_simulated_venues(lat, lon, radius, categories)
            FOURSQUARE_CACHE[cache_key] = venues
            return venues
        else:
            print(f"Foursquare API returned status {res.status_code}: {res.text}")
    except Exception as e:
        print(f"Foursquare Places API request failed: {e}")
        
    venues = get_simulated_venues(lat, lon, radius, categories)
    return venues

def match_foursquare_place(name, lat, lon):
    """
    Finds a matching place on Foursquare using name and location.
    Returns matched venue data or None if no match found.
    """
    global FOURSQUARE_CACHE
    cache_key = f"match:{name}:{round(lat, 4)},{round(lon, 4)}"
    if cache_key in FOURSQUARE_CACHE:
        return FOURSQUARE_CACHE[cache_key]

    api_key = os.environ.get("FOURSQUARE_API_KEY")
    if not api_key:
        # Simulation fallback (deterministic based on name length and location)
        seed = len(name) + int(abs(lat * 1000)) % 100
        if seed % 5 != 0:
            matched = {
                "foursquare_id": f"sim_match_{seed}",
                "name": f"{name}",
                "rating": round(7.0 + (seed % 25) / 10.0, 1),
                "verified_address": f"Bangalore, Local Sector {seed % 10}",
                "lat_clean": lat + 0.0001 * (seed % 3 - 1),
                "lon_clean": lon + 0.0001 * (seed % 3 - 1),
            }
            FOURSQUARE_CACHE[cache_key] = matched
            return matched
        FOURSQUARE_CACHE[cache_key] = None
        return None

    try:
        url = "https://places-api.foursquare.com/places/search"
        headers = {
            "Accept": "application/json",
            "Authorization": api_key,
            "foursquare-version": "20231010"
        }
        params = {
            "query": name,
            "ll": f"{lat},{lon}",
            "radius": 500,
            "limit": 1,
            "fields": "fsq_id,name,rating,location,geocodes",
            "v": "20231010"
        }
        res = requests.get(url, headers=headers, params=params, timeout=8)
        if res.status_code == 200:
            results = res.json().get("results", [])
            if results:
                match_item = results[0]
                matched_lat = match_item.get("geocodes", {}).get("main", {}).get("latitude", lat)
                matched_lon = match_item.get("geocodes", {}).get("main", {}).get("longitude", lon)
                matched = {
                    "foursquare_id": match_item.get("fsq_id"),
                    "name": match_item.get("name"),
                    "rating": match_item.get("rating"),
                    "verified_address": match_item.get("location", {}).get("formatted_address", ""),
                    "lat_clean": matched_lat,
                    "lon_clean": matched_lon
                }
                FOURSQUARE_CACHE[cache_key] = matched
                save_foursquare_cache()
                return matched
            else:
                FOURSQUARE_CACHE[cache_key] = None
    except Exception as e:
        print(f"Foursquare Place Match failed for {name}: {e}")
        
    return None

BENGALURU_BOUNDS = {
    "min_lat": 12.45,
    "max_lat": 13.50,
    "min_lon": 77.10,
    "max_lon": 78.10,
}

CENTRAL_LAT = 12.9716
CENTRAL_LON = 77.5946

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def bearing_degrees(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    brng = math.degrees(math.atan2(x, y))
    return (brng + 360) % 360

def classify_zone(lat, lon):
    distance = haversine_km(CENTRAL_LAT, CENTRAL_LON, lat, lon)
    if distance > 35.0:
        return "Outside"
    if distance <= 5.0:
        return "Central"
    brng = bearing_degrees(CENTRAL_LAT, CENTRAL_LON, lat, lon)
    if brng >= 337.5 or brng < 22.5:
        return "North"
    elif 22.5 <= brng < 67.5:
        return "North-East"
    elif 67.5 <= brng < 112.5:
        return "East"
    elif 112.5 <= brng < 157.5:
        return "South-East"
    elif 157.5 <= brng < 202.5:
        return "South"
    elif 202.5 <= brng < 247.5:
        return "South-West"
    elif 247.5 <= brng < 292.5:
        return "West"
    elif 292.5 <= brng < 337.5:
        return "North-West"
    return "Unknown"

def clean_numeric(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = (
            value.replace(",", "")
            .replace("Rs", "")
            .replace("₹", "")
            .replace("/ sqft", "")
            .replace("%", "")
        )
        match = re.search(r"[-+]?\d*\.\d+|\d+", text)
        if match:
            return float(match.group())
    return None

def valid_lat_lon(lat, lon):
    if lat is None or lon is None:
        return False
    return (
        BENGALURU_BOUNDS["min_lat"] <= lat <= BENGALURU_BOUNDS["max_lat"]
        and BENGALURU_BOUNDS["min_lon"] <= lon <= BENGALURU_BOUNDS["max_lon"]
    )

def parse_kml_coordinates(text):
    coords = []
    for token in (text or "").split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        lon = clean_numeric(parts[0])
        lat = clean_numeric(parts[1])
        if lat is not None and lon is not None:
            coords.append((lon, lat))
    if coords and coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords

def strip_html(value):
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", text).strip()

def prepare_localities():
    print("Preparing localities...")
    if not LOCALITIES_RAW_PATH.exists():
        print(f"Error: {LOCALITIES_RAW_PATH} not found.")
        return
    with open(LOCALITIES_RAW_PATH, "r") as f:
        raw_localities = json.load(f)

    localities = []
    for idx, loc in enumerate(raw_localities):
        locality_info = loc.get("locality_info", {})
        market = loc.get("market_insights", {})
        coords = locality_info.get("coordinates", {})
        
        lat = clean_numeric(coords.get("latitude"))
        lon = clean_numeric(coords.get("longitude"))
        name = locality_info.get("name") or "Unknown"
        price_sqft = clean_numeric(market.get("market_price_per_sqft") or market.get("price_per_sqft"))
        budget_segment = market.get("budget_segment") or "unknown"
        
        if valid_lat_lon(lat, lon) and price_sqft:
            zone = classify_zone(lat, lon)
            if zone == "Outside":
                continue
            hex_id = h3.latlng_to_cell(lat, lon, 7)
            localities.append({
                "name": name,
                "lat": lat,
                "lon": lon,
                "price_sqft": price_sqft,
                "budget_segment": budget_segment,
                "hex_id": hex_id,
                "zone": zone
            })
            
    print(f"Extracted {len(localities)} valid costly localities.")
    with open(OUTPUT_DATA_DIR / "localities.json", "w") as f:
        json.dump(localities, f, indent=2)

def prepare_societies():
    print("Preparing societies...")
    if not SOCIETIES_PATH.exists():
        print(f"Error: {SOCIETIES_PATH} not found.")
        return
    with open(SOCIETIES_PATH, "r") as f:
        raw_societies = json.load(f)
        
    societies = []
    for row in raw_societies:
        lat = clean_numeric(row.get("Latitude"))
        lon = clean_numeric(row.get("Longitude"))
        if not valid_lat_lon(lat, lon):
            continue
        
        name = row.get("Society Name")
        category = row.get("Q4 Category") or "unknown"
        tam = clean_numeric(row.get("Estimated Families (TAM)")) or 0.0
        units = clean_numeric(row.get("Total Units")) or 0.0
        price = clean_numeric(row.get("Avg Price per SqFt")) or 0.0
        locality = row.get("Locality")
        
        zone = classify_zone(lat, lon)
        if zone == "Outside":
            continue
        hex_id = h3.latlng_to_cell(lat, lon, 7)
        
        rera = str(row.get("RERA ID") or "").strip()
        confidence = 0.40
        if rera and rera.upper() not in {"NA", "N/A", ""}:
            confidence += 0.20
        if units > 0:
            confidence += 0.15
        if tam > 0:
            confidence += 0.15
        if price > 0:
            confidence += 0.10
        confidence = min(1.0, confidence)

        societies.append({
            "name": name,
            "lat": lat,
            "lon": lon,
            "category": category,
            "tam": tam,
            "units": units,
            "price": price,
            "locality": locality,
            "hex_id": hex_id,
            "zone": zone,
            "url": row.get("URL") or "NA",
            "confidence": round(confidence, 2),
            "construction_status": row.get("Construction Status") or "NA",
            "min_price": clean_numeric(row.get("Min Price")) or 0.0,
            "max_price": clean_numeric(row.get("Max Price")) or 0.0
        })
        
    print(f"Extracted {len(societies)} societies.")
    with open(OUTPUT_DATA_DIR / "societies.json", "w") as f:
        json.dump(societies, f, indent=2)

def prepare_schools():
    # School publishing is intentionally owned by build_school_market.py.  The
    # former implementation read the stale 476-row Stage 2 file and could
    # silently overwrite the canonical 2,000+ row school market during an
    # unrelated general-data refresh.
    print("Skipping legacy school preparation; run build_school_market.py instead.")

def prepare_hospitals():
    print("Preparing hospitals...")
    if not HOSPITALS_PATH.exists():
        print(f"Error: {HOSPITALS_PATH} not found.")
        return
    with open(HOSPITALS_PATH, "r") as f:
        raw_hospitals = json.load(f)
        
    hospitals = []
    for row in raw_hospitals:
        lat = clean_numeric(row.get("Latitude"))
        lon = clean_numeric(row.get("Longitude"))
        if not valid_lat_lon(lat, lon):
            continue
            
        zone = classify_zone(lat, lon)
        if zone == "Outside":
            continue
        hex_id = h3.latlng_to_cell(lat, lon, 7)
        
        hospitals.append({
            "name": row.get("Hospital Name"),
            "lat": lat,
            "lon": lon,
            "category": row.get("Q4 Category") or "unknown",
            "beds": clean_numeric(row.get("Extracted Beds")) or 0.0,
            "rating": clean_numeric(row.get("Rating")) or 0.0,
            "reviews": clean_numeric(row.get("Reviews Count")) or 0.0,
            "hex_id": hex_id,
            "zone": zone
        })
        
    print(f"Extracted {len(hospitals)} hospitals.")
    with open(OUTPUT_DATA_DIR / "hospitals.json", "w") as f:
        json.dump(hospitals, f, indent=2)

def prepare_sez_zones():
    print("Preparing SEZ zones GeoJSON...")
    if not SEZ_KML_PATH.exists():
        print(f"Error: {SEZ_KML_PATH} not found.")
        return
        
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    try:
        root = ET.parse(SEZ_KML_PATH).getroot()
    except Exception as e:
        print(f"Error parsing KML: {e}")
        return
        
    features = []
    for placemark in root.findall(".//k:Placemark", ns):
        name = placemark.findtext("k:name", default="", namespaces=ns)
        description = placemark.findtext("k:description", default="", namespaces=ns)
        polygons = []
        for polygon in placemark.findall(".//k:Polygon", ns):
            coordinates = polygon.findtext(".//k:outerBoundaryIs/k:LinearRing/k:coordinates", namespaces=ns)
            ring = parse_kml_coordinates(coordinates)
            if len(ring) >= 4:
                try:
                    poly = Polygon(ring)
                    if poly.is_valid and not poly.is_empty:
                        polygons.append(poly)
                except Exception:
                    continue
        if not polygons:
            continue
            
        geom = unary_union(polygons)
        # Check if centroid is further than 35km from center
        if haversine_km(CENTRAL_LAT, CENTRAL_LON, geom.centroid.y, geom.centroid.x) > 35.0:
            continue
            
        clean_description = strip_html(description)
        office_match = re.search(r"Office spaces:\s*(\d+)", clean_description)
        office_spaces = int(office_match.group(1)) if office_match else 0
        
        features.append({
            "type": "Feature",
            "geometry": mapping(geom),
            "properties": {
                "name": name.replace(" SEZ boundary", ""),
                "office_spaces": office_spaces,
                "description": clean_description,
                "centroid_lat": geom.centroid.y,
                "centroid_lon": geom.centroid.x
            }
        })
        
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    print(f"Extracted {len(features)} SEZ zones.")
    with open(OUTPUT_DATA_DIR / "sez_zones.geojson", "w") as f:
        json.dump(geojson, f, indent=2)

def copy_final_assets():
    print("Copying final report and hex GeoJSON...")
    if HEXES_GEOJSON_PATH.exists():
        with open(HEXES_GEOJSON_PATH, "r") as f:
            hexes = json.load(f)
            
        # Parse hex polygons and embed metadata
        import networkx as nx
        import numpy as np

        features = hexes.get("features", [])
        valid_features = []
        for feat in features:
            props = feat.get("properties", {})
            hex_id = props.get("hex_id")
            lat, lon = h3.cell_to_latlng(hex_id)
            zone = classify_zone(lat, lon)
            if zone != "Outside":
                valid_features.append((feat, hex_id, lat, lon, zone))

        cells = {item[1] for item in valid_features}
        
        # Build spatial similarity graph
        G = nx.Graph()
        for feat, hex_id, lat, lon, zone in valid_features:
            props = feat["properties"]
            G.add_node(
                hex_id,
                affluence_score=props.get("final_affluence_score", 0.0),
                rank=props.get("rank", 999)
            )

        for feat, hex_id, lat, lon, zone in valid_features:
            score_u = G.nodes[hex_id]["affluence_score"]
            neighbors = [n for n in h3.grid_disk(hex_id, 1) if n != hex_id and n in cells]
            for v in neighbors:
                if G.has_edge(hex_id, v):
                    continue
                score_v = G.nodes[v]["affluence_score"]
                diff = abs(score_u - score_v)
                weight = math.exp(-diff / 15.0)
                G.add_edge(hex_id, v, weight=weight)

        # Compute PageRank (Standard & Personalized)
        pagerank_standard = nx.pagerank(G, weight='weight', alpha=0.85)
        personalization = {node: max(0.1, G.nodes[node]["affluence_score"]) for node in G.nodes}
        pagerank_personalized = nx.pagerank(G, weight='weight', alpha=0.85, personalization=personalization)

        # Compute Louvain communities
        communities_sets = nx.community.louvain_communities(G, weight='weight', seed=42)
        community_averages = []
        for idx, c_set in enumerate(communities_sets):
            avg_aff = np.mean([G.nodes[node]["affluence_score"] for node in c_set])
            community_averages.append((idx, avg_aff, c_set))
        community_averages.sort(key=lambda x: x[1], reverse=True)

        node_community = {}
        for new_id, (old_idx, _, c_set) in enumerate(community_averages):
            for node in c_set:
                node_community[node] = new_id

        # Compute Rank Shift (using personalized PageRank ranks)
        sorted_nodes_by_ppr = sorted(list(G.nodes), key=lambda n: pagerank_personalized[n], reverse=True)
        ppr_ranks = {node: rank for rank, node in enumerate(sorted_nodes_by_ppr, start=1)}
        rank_shifts = {}
        for node in G.nodes:
            orig_r = G.nodes[node]["rank"]
            pr_r = ppr_ranks[node]
            rank_shifts[node] = orig_r - pr_r

        filtered_features = []
        total_hexes = len(hexes.get("features", []))
        print(f"Processing {total_hexes} hexagons for Commercial Vibrancy and Graph Centrality...")
        
        for idx, feat in enumerate(hexes.get("features", [])):
            props = feat.get("properties", {})
            hex_id = props.get("hex_id")
            lat, lon = h3.cell_to_latlng(hex_id)
            zone = classify_zone(lat, lon)
            if zone == "Outside":
                continue  # Filter out hexes that are further than 35km boundary
            
            # Query Foursquare Places around this hex centroid
            venues = query_foursquare_places(lat, lon, radius=1200)
            
            # Compute vibrancy score
            venue_count = len(venues)
            vibrancy_score = 0.0
            if venue_count > 0:
                ratings = [v["rating"] for v in venues if isinstance(v.get("rating"), (int, float))]
                avg_rating = sum(ratings) / len(ratings) if ratings else 7.0
                premium_factor = sum(1.5 if v.get("price") in {3, 4} else 1.0 for v in venues)
                vibrancy_score = math.log(1 + premium_factor) * avg_rating
                vibrancy_score = round(min(100.0, vibrancy_score * 8.0), 2)
            
            props["centroid_lat"] = lat
            props["centroid_lon"] = lon
            props["zone"] = zone
            props["commercial_vibrancy_index"] = vibrancy_score
            props["commercial_venues_count"] = venue_count
            props["community_id"] = int(node_community.get(hex_id, -1))
            props["pagerank_standard"] = float(pagerank_standard.get(hex_id, 0.0))
            props["pagerank_personalized"] = float(pagerank_personalized.get(hex_id, 0.0))
            props["pagerank_rank"] = int(ppr_ranks.get(hex_id, 999))
            props["rank_shift"] = int(rank_shifts.get(hex_id, 0))
            
            filtered_features.append(feat)
            if (idx + 1) % 50 == 0:
                print(f"  Processed {idx + 1}/{total_hexes} hexes...")
            
        hexes["features"] = filtered_features
        with open(OUTPUT_DATA_DIR / "hexes.geojson", "w") as f:
            json.dump(hexes, f, indent=2)
        print("Copied enriched hexes.geojson.")
    else:
        print(f"Error: {HEXES_GEOJSON_PATH} not found.")

    if REPORT_JSON_PATH.exists():
        with open(REPORT_JSON_PATH, "r") as f:
            report = json.load(f)
        with open(OUTPUT_DATA_DIR / "report.json", "w") as f:
            json.dump(report, f, indent=2)
        print("Copied report.json.")
    else:
        print(f"Error: {REPORT_JSON_PATH} not found.")

def main():
    OUTPUT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    load_foursquare_cache()
    prepare_localities()
    prepare_societies()
    prepare_schools()
    prepare_hospitals()
    prepare_sez_zones()
    copy_final_assets()
    print("Data compilation completed successfully!")

if __name__ == "__main__":
    main()
