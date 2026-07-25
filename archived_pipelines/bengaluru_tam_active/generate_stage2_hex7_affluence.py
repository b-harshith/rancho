import csv
import html
import json
import math
import os
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

import h3
import numpy as np
import requests
from shapely.geometry import Polygon
from shapely.ops import unary_union


DATA_DIR = Path("DATA")
STAGE2_DIR = DATA_DIR / "Stage2 processing"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
AUDIT_DIR = DATA_DIR / "audits"
MAPS_DIR = Path("maps") / "h3"

STAGE15_HEX_PATH = STAGE2_DIR / "stage1_5_hex7_spatial_budget_features.json"
SOCIETIES_PATH = STAGE2_DIR / "q4_categorized_societies_bangalore.json"
SCHOOLS_PATH = STAGE2_DIR / "Categorized Schools.json"
HOSPITALS_PATH = STAGE2_DIR / "Categorized Hospitals.json"
SEZ_KML_PATH = STAGE2_DIR / "sez_office_zones.kml"
OVERTURE_BUILDINGS_PATH = DATA_DIR / "overture" / "bangalore_buildings.geojson"

OUTPUT_JSON = PROCESSED_DATA_DIR / "stage2_hex7_affluence_master.json"
OUTPUT_CSV = PROCESSED_DATA_DIR / "stage2_hex7_affluence_master_flat.csv"
OUTPUT_GEOJSON = PROCESSED_DATA_DIR / "stage2_hex7_affluence_master.geojson"
OUTPUT_LINKS = PROCESSED_DATA_DIR / "stage2_poi_hex_links.jsonl"
ROUTING_CACHE_PATH = PROCESSED_DATA_DIR / "stage2_routing_cache.json"
HABITABILITY_CACHE_PATH = PROCESSED_DATA_DIR / "stage2_hex7_habitability_from_overture.json"
OUTPUT_KML = MAPS_DIR / "stage2_hex7_affluence_master.kml"
AUDIT_JSON = AUDIT_DIR / "stage2_hex7_affluence_audit.json"
METHODOLOGY_MD = AUDIT_DIR / "stage2_hex7_affluence_methodology.md"

H3_RESOLUTION = 7
BENGALURU_BOUNDS = {
    "min_lat": 12.45,
    "max_lat": 13.50,
    "min_lon": 77.10,
    "max_lon": 78.10,
}

OSRM_URL = os.environ.get("OSRM_URL", "http://localhost:5001").rstrip("/")  # LEGACY - no longer used
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
GOOGLE_MAPS_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
GOOGLE_MAPS_CHUNK_SIZE = 25  # Google Distance Matrix API: max 25 destinations per request
AVG_SPEED_KMPH = 35.0
MATRIX_CHUNK_SIZE = 75  # LEGACY - kept for reference only
REQUEST_TIMEOUT_SECONDS = 30

SOCIETY_RADIUS_KM = 2.0
SOCIETY_TAU_KM = 0.7
SOCIETY_CLUSTER_RADIUS_KM = 3.0
SOCIETY_CLUSTER_TAU_KM = 1.2
SCHOOL_PREFILTER_KM = 18.0
HOSPITAL_PREFILTER_KM = 12.0
SEZ_PROXIMITY_KM = 8.0
SEZ_TAU_KM = 3.0
SCHOOL_SCORE_TOP_N = 15
SCHOOL_EVIDENCE_TOP_N = 25
SCHOOL_BUS_FREE_MIN = 15.0
HABITABILITY_SCORE_GATE = 0.25

# DEPRECATED: School-based TAM estimation removed in scoring pivot
# SCHOOL_AGE_FAMILY_RATE = 0.38
# CHILDREN_PER_SCHOOL_AGE_FAMILY = 1.25

SOCIETY_CATEGORY_VALUES = {
    "Ultra Luxury": 1.00,
    "Elite Luxury": 0.90,
    "Super Luxury": 0.85,
    "Premium Luxury": 0.75,
    "Luxury": 0.70,
    "Premium": 0.55,
    "Aspirational Premium": 0.40,
}

SOCIETY_INCOME_BANDS = {
    "Ultra Luxury": "Ultra Luxury",
    "Elite Luxury": "Elite Luxury",
    "Super Luxury": "Super Luxury",
    "Premium Luxury": "Premium Luxury",
    "Luxury": "Luxury",
    "Premium": "Premium",
    "Aspirational Premium": "Aspirational Premium",
}

POI_CATEGORY_VALUES = {
    "Ultra Premium": 1.00,
    "Super Premium": 0.85,
    "Premium": 0.70,
    "Mid-Premium": 0.50,
}

SCHOOL_WINDOWS = {
    "Ultra Premium": {"max_min": 60.0, "tau_min": 30.0},
    "Super Premium": {"max_min": 55.0, "tau_min": 27.0},
    "Premium": {"max_min": 45.0, "tau_min": 22.0},
    "Mid-Premium": {"max_min": 35.0, "tau_min": 16.0},
}

HOSPITAL_WINDOWS = {
    "Ultra Premium": {"max_min": 35.0, "tau_min": 16.0},
    "Super Premium": {"max_min": 35.0, "tau_min": 14.0},
    "Premium": {"max_min": 30.0, "tau_min": 12.0},
    "Mid-Premium": {"max_min": 25.0, "tau_min": 10.0},
}

BUDGET_SEGMENT_VALUES = {
    "Ultra Premium": 1.00,
    "Premium": 0.85,
    "Premium Candidate": 0.75,
    "Mixed - Premium leaning": 0.65,
    "Mixed/Diverse": 0.55,
    "Mid-Segment": 0.45,
    "Mixed - Mid-Segment leaning": 0.40,
    "Mixed - Affordable leaning": 0.30,
    "Affordable": 0.20,
}


def load_json(path):
    with path.open("r") as f:
        return json.load(f)


def safe_dict(value):
    return value if isinstance(value, dict) else {}


def clean_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if math.isnan(float(value)):
            return None
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text.upper() in {"", "NA", "N/A", "NONE", "NULL"}:
            return None
        text = (
            text.replace(",", "")
            .replace("Rs", "")
            .replace("INR", "")
            .replace("₹", "")
            .replace("%", "")
        )
        match = re.search(r"[-+]?\d*\.\d+|[-+]?\d+", text)
        if match:
            return float(match.group())
    return None


def clamp(value, lo=0.0, hi=1.0):
    return max(lo, min(hi, value))


def valid_lat_lon(lat, lon):
    if lat is None or lon is None:
        return False
    return (
        BENGALURU_BOUNDS["min_lat"] <= lat <= BENGALURU_BOUNDS["max_lat"]
        and BENGALURU_BOUNDS["min_lon"] <= lon <= BENGALURU_BOUNDS["max_lon"]
    )


def haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def percentile(values, q):
    clean = [float(v) for v in values if v is not None and float(v) >= 0]
    if not clean:
        return None
    return float(np.percentile(clean, q))


def robust_normalized(values):
    logged = [math.log1p(max(0.0, float(v or 0.0))) for v in values]
    positives = [v for v in logged if v > 0]
    if not positives:
        return [0.0 for _ in values]
    lo = float(np.percentile(positives, 5))
    hi = float(np.percentile(positives, 95))
    if hi <= lo:
        return [1.0 if value > 0 else 0.0 for value in logged]
    return [clamp((min(max(value, lo), hi) - lo) / (hi - lo)) if value > 0 else 0.0 for value in logged]


def lon_lat_ring_area_centroid(coords):
    if not coords:
        return 0.0, None
    points = [(clean_float(lon), clean_float(lat)) for lon, lat, *_ in coords]
    points = [(lon, lat) for lon, lat in points if lon is not None and lat is not None]
    if len(points) < 3:
        return 0.0, None
    if points[0] != points[-1]:
        points.append(points[0])
    twice_area = 0.0
    cx_sum = 0.0
    cy_sum = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        cross = x1 * y2 - x2 * y1
        twice_area += cross
        cx_sum += (x1 + x2) * cross
        cy_sum += (y1 + y2) * cross
    if abs(twice_area) < 1e-15:
        avg_lon = sum(point[0] for point in points[:-1]) / max(1, len(points) - 1)
        avg_lat = sum(point[1] for point in points[:-1]) / max(1, len(points) - 1)
        return 0.0, (avg_lon, avg_lat)
    centroid = (cx_sum / (3.0 * twice_area), cy_sum / (3.0 * twice_area))
    return abs(twice_area) / 2.0, centroid


def lon_lat_polygon_area_centroid_rings(rings):
    if not rings:
        return 0.0, None
    outer_area, outer_centroid = lon_lat_ring_area_centroid(rings[0])
    if not outer_centroid:
        return 0.0, None
    holes_area = 0.0
    for ring in rings[1:]:
        area, _ = lon_lat_ring_area_centroid(ring)
        holes_area += area
    return max(0.0, outer_area - holes_area), outer_centroid


def lon_lat_geometry_area_centroid(geometry):
    if not geometry:
        return 0.0, None
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if geom_type == "Polygon":
        return lon_lat_polygon_area_centroid_rings(coords)
    if geom_type == "MultiPolygon":
        total_area = 0.0
        weighted_lon = 0.0
        weighted_lat = 0.0
        fallback_centroid = None
        for polygon in coords:
            area, centroid = lon_lat_polygon_area_centroid_rings(polygon)
            if centroid and fallback_centroid is None:
                fallback_centroid = centroid
            if area > 0 and centroid:
                total_area += area
                weighted_lon += centroid[0] * area
                weighted_lat += centroid[1] * area
        if total_area > 0:
            return total_area, (weighted_lon / total_area, weighted_lat / total_area)
        return 0.0, fallback_centroid
    return 0.0, None


def deg_area_to_sqm(area_degrees, latitude):
    meters_per_degree_lat = 111_320.0
    meters_per_degree_lon = 111_320.0 * math.cos(math.radians(latitude))
    return area_degrees * meters_per_degree_lat * meters_per_degree_lon


def hex_area_sqm(hex_id):
    area_degrees, centroid = lon_lat_ring_area_centroid(
        [(lon, lat) for lat, lon in h3.cell_to_boundary(hex_id)]
    )
    lat = centroid[1] if centroid else h3.cell_to_latlng(hex_id)[0]
    return deg_area_to_sqm(area_degrees, lat)


def hex_centroid(hex_id):
    lat, lon = h3.cell_to_latlng(hex_id)
    return {"lat": lat, "lon": lon}


def hex_polygon(hex_id):
    boundary = h3.cell_to_boundary(hex_id)
    coords = [(lon, lat) for lat, lon in boundary]
    if coords:
        coords.append(coords[0])
    return Polygon(coords)


def geojson_geometry(hex_id):
    boundary = h3.cell_to_boundary(hex_id)
    ring = [[lon, lat] for lat, lon in boundary]
    if ring:
        ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def coordinates_for_kml(hex_id):
    boundary = h3.cell_to_boundary(hex_id)
    coords = [(lon, lat) for lat, lon in boundary]
    if coords:
        coords.append(coords[0])
    return " ".join(f"{lon:.8f},{lat:.8f},0" for lon, lat in coords)


def route_key(src, dst):
    return f"{src['lat']:.6f},{src['lon']:.6f}->{dst['lat']:.6f},{dst['lon']:.6f}"


class GoogleMapsRoutingClient:
    """Google Maps Distance Matrix API routing client with persistent cache.
    Compatible with the existing OSRM routing cache format (same key format: lat,lon->lat,lon).
    """

    def __init__(self, api_key, cache_path):
        self.api_key = api_key
        self.cache_path = cache_path
        self.cache = self._load_cache()
        self.request_count = 0
        self.cache_hits = 0
        self.failures = Counter()

    def _load_cache(self):
        if not self.cache_path.exists():
            return {"metadata": {}, "routes": {}}
        with self.cache_path.open("r") as f:
            cache = json.load(f)
        if "routes" not in cache:
            cache["routes"] = {}
        return cache

    def save(self):
        self.cache["metadata"] = {
            "routing_method": "google_maps",
            "updated_at_unix": time.time(),
            "request_count": self.request_count,
            "cache_hits": self.cache_hits,
            "failures": dict(self.failures),
        }
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_path.open("w") as f:
            json.dump(self.cache, f, indent=2)

    def validate(self):
        if not self.api_key:
            raise RuntimeError(
                "GOOGLE_MAPS_API_KEY environment variable is not set.\n"
                "Set it before running:\n"
                "  export GOOGLE_MAPS_API_KEY=AIza..."
            )
        try:
            response = requests.get(
                GOOGLE_MAPS_MATRIX_URL,
                params={
                    "origins": "12.9716,77.5946",
                    "destinations": "12.9800,77.6000",
                    "mode": "driving",
                    "key": self.api_key,
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            status = data.get("status")
            if status not in ("OK", "ZERO_RESULTS"):
                raise RuntimeError(
                    f"Google Maps API validation failed: status={status}, "
                    f"message={data.get('error_message', 'no message')}"
                )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Google Maps API not reachable: {exc}\n"
                "Check your internet connection and API key."
            ) from exc
        print(f"[GoogleMapsRoutingClient] API key validated. Cache has {len(self.cache['routes'])} pre-cached routes.")

    def matrix_distances(self, source, targets):
        """Fetch drive distances and times for source -> each target.
        Results are cached. Returns dict of index -> route result.
        """
        results = {}
        pending = []
        pending_indices = []
        for index, target in enumerate(targets):
            key = route_key(source, target)
            cached = self.cache["routes"].get(key)
            if cached:
                self.cache_hits += 1
                results[index] = cached
            else:
                pending.append(target)
                pending_indices.append(index)

        for offset in range(0, len(pending), GOOGLE_MAPS_CHUNK_SIZE):
            chunk = pending[offset:offset + GOOGLE_MAPS_CHUNK_SIZE]
            chunk_indices = pending_indices[offset:offset + GOOGLE_MAPS_CHUNK_SIZE]

            origins = f"{source['lat']:.6f},{source['lon']:.6f}"
            destinations = "|".join(f"{t['lat']:.6f},{t['lon']:.6f}" for t in chunk)

            try:
                response = requests.get(
                    GOOGLE_MAPS_MATRIX_URL,
                    params={
                        "origins": origins,
                        "destinations": destinations,
                        "mode": "driving",
                        "departure_time": "now",
                        "key": self.api_key,
                    },
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                data = response.json()
                api_status = data.get("status")
                if api_status not in ("OK", "ZERO_RESULTS"):
                    self.failures[f"api_{api_status}"] += len(chunk)
                    print(f"[WARNING] Google Maps API error: {api_status} - {data.get('error_message', '')}")
                    continue
                rows = data.get("rows") or []
                elements = rows[0].get("elements", []) if rows else []
            except requests.RequestException as exc:
                self.failures["request_failed"] += len(chunk)
                print(f"[WARNING] Google Maps request failed: {exc}")
                continue

            self.request_count += 1
            for local_index, element in enumerate(elements):
                if local_index >= len(chunk):
                    break
                target = chunk[local_index]
                key = route_key(source, target)
                el_status = element.get("status")
                if el_status != "OK":
                    self.failures[f"element_{el_status}"] += 1
                    continue
                distance_m = (element.get("distance") or {}).get("value")
                # Prefer duration_in_traffic (requires departure_time=now), fall back to duration
                duration_s = (
                    (element.get("duration_in_traffic") or {}).get("value")
                    or (element.get("duration") or {}).get("value")
                )
                if distance_m is None or duration_s is None:
                    self.failures["missing_values"] += 1
                    continue
                distance_km = distance_m / 1000.0
                travel_time_min = duration_s / 60.0
                result = {
                    "distance_km": round(distance_km, 4),
                    # Field name kept for backward compat with existing scoring formula
                    "travel_time_min_at_35_kmph": round(travel_time_min, 4),
                    "method": "google_maps",
                }
                self.cache["routes"][key] = result
                results[chunk_indices[local_index]] = result

        return results

    def route_distance(self, source, target):
        """Single route fallback — wraps matrix_distances for a single target."""
        return self.matrix_distances(source, [target]).get(0)




def normalize_category(value):
    return str(value or "").strip()


def load_societies():
    records = load_json(SOCIETIES_PATH)
    cleaned = []
    invalid = []
    for row in records:
        lat = clean_float(row.get("Latitude"))
        lon = clean_float(row.get("Longitude"))
        if not valid_lat_lon(lat, lon):
            invalid.append(row.get("Society Name"))
            continue
        category = normalize_category(row.get("Q4 Category"))
        category_value = SOCIETY_CATEGORY_VALUES.get(category, 0.0)
        estimated_families = clean_float(row.get("Estimated Families (TAM)")) or 0.0
        total_units = clean_float(row.get("Total Units")) or 0.0
        avg_price = clean_float(row.get("Avg Price per SqFt"))
        rera = str(row.get("RERA ID") or "").strip()
        confidence = 0.40
        if rera and rera.upper() not in {"NA", "N/A"}:
            confidence += 0.20
        if total_units > 0:
            confidence += 0.15
        if estimated_families > 0:
            confidence += 0.15
        if avg_price:
            confidence += 0.10
        cleaned.append(
            {
                "name": row.get("Society Name"),
                "url": row.get("URL"),
                "locality": row.get("Locality"),
                "micro_market": row.get("Micro Market"),
                "lat": lat,
                "lon": lon,
                "hex_id": h3.latlng_to_cell(lat, lon, H3_RESOLUTION),
                "category": category,
                "category_value": category_value,
                "income_band": SOCIETY_INCOME_BANDS.get(category, "unknown"),
                "min_price": clean_float(row.get("Min Price")),
                "max_price": clean_float(row.get("Max Price")),
                "avg_price_per_sqft": avg_price,
                "listed_units_count": clean_float(row.get("Listed Units Count")) or 0.0,
                "appreciation_1y_pct": clean_float(row.get("Appreciation 1Y (%)")),
                "resale_listings_count": clean_float(row.get("Resale Listings Count")) or 0.0,
                "rental_listings_count": clean_float(row.get("Rental Listings Count")) or 0.0,
                "total_active_listings": clean_float(row.get("Total Active Listings")) or 0.0,
                "total_units": total_units,
                "estimated_families_tam": estimated_families,
                "rera_id": row.get("RERA ID"),
                "construction_status": row.get("Construction Status"),
                "towers": clean_float(row.get("Towers")),
                "floors": clean_float(row.get("Floors")),
                "confidence": clamp(confidence),
            }
        )
    return cleaned, invalid


def load_schools():
    records = load_json(SCHOOLS_PATH)
    cleaned = []
    invalid = []
    for row in records:
        lat = clean_float(row.get("Latitude"))
        lon = clean_float(row.get("Longitude"))
        if not valid_lat_lon(lat, lon):
            invalid.append(row.get("School Name"))
            continue
        category = normalize_category(row.get("Q4 Category"))
        cleaned.append(
            {
                "name": row.get("School Name"),
                "url": row.get("URL"),
                "lat": lat,
                "lon": lon,
                "category": category,
                "category_value": POI_CATEGORY_VALUES.get(category, 0.0),
                "board": row.get("Board"),
                "annual_fee": clean_float(row.get("Average Fee (Annual)")) or 0.0,
                "computed_student_count": clean_float(row.get("Computed Student Count")) or 0.0,
                "estimated_2nd_9th_student_count": clean_float(row.get("Est. 2nd-9th Student Count"))
                or 0.0,
                "teacher_count": clean_float(row.get("Teacher Count")),
                "student_teacher_ratio": row.get("Student-Teacher Ratio"),
                "starting_class": row.get("Starting Class"),
                "ending_class": row.get("Ending Class"),
                "pincode": row.get("Pincode"),
            }
        )
    return cleaned, invalid


def load_hospitals():
    records = load_json(HOSPITALS_PATH)
    cleaned = []
    invalid = []
    for row in records:
        lat = clean_float(row.get("Latitude"))
        lon = clean_float(row.get("Longitude"))
        if not valid_lat_lon(lat, lon):
            invalid.append(row.get("Hospital Name"))
            continue
        category = normalize_category(row.get("Q4 Category"))
        cleaned.append(
            {
                "name": row.get("Hospital Name"),
                "slug": row.get("Slug"),
                "url": row.get("URL"),
                "locality": row.get("Locality"),
                "lat": lat,
                "lon": lon,
                "category": category,
                "category_value": POI_CATEGORY_VALUES.get(category, 0.0),
                "min_consultation_fee": clean_float(row.get("Min Consultation Fee")) or 0.0,
                "max_consultation_fee": clean_float(row.get("Max Consultation Fee")) or 0.0,
                "doctors_count": clean_float(row.get("Doctors Count")) or 0.0,
                "extracted_beds": clean_float(row.get("Extracted Beds")) or 0.0,
                "rating": clean_float(row.get("Rating")),
                "reviews_count": clean_float(row.get("Reviews Count")) or 0.0,
                "multispeciality_text": row.get("Multispeciality Text"),
            }
        )
    return cleaned, invalid


def parse_kml_coordinates(text):
    coords = []
    for token in (text or "").split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        lon = clean_float(parts[0])
        lat = clean_float(parts[1])
        if lat is not None and lon is not None:
            coords.append((lon, lat))
    if coords and coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def strip_html(value):
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_sez_zones():
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    root = ET.parse(SEZ_KML_PATH).getroot()
    zones = []
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
        geometry = unary_union(polygons)
        clean_description = strip_html(description)
        office_match = re.search(r"Office spaces:\s*(\d+)", clean_description)
        office_spaces = int(office_match.group(1)) if office_match else 0
        zones.append(
            {
                "name": name.replace(" SEZ boundary", ""),
                "raw_name": name,
                "description": clean_description,
                "office_spaces": office_spaces,
                "geometry": geometry,
                "centroid_lat": geometry.centroid.y,
                "centroid_lon": geometry.centroid.x,
            }
        )
    return zones


def metric_avg(record, metric):
    return safe_dict(safe_dict(record.get("market_insights")).get("metrics")).get(metric, {}).get(
        "weighted_avg"
    )


def support_metric(record, metric):
    return safe_dict(safe_dict(record.get("market_insights")).get("support")).get(metric)


def inventory_metric(record, metric):
    return safe_dict(safe_dict(record.get("market_insights")).get("inventory")).get(metric)


def stage15_market(record):
    refined_segment = record.get("refined_budget_segment") or record.get("budget_classification")
    return {
        "name": record.get("name"),
        "market_price_per_sqft": metric_avg(record, "market_price_per_sqft"),
        "rental_yield_pct": metric_avg(record, "rental_yield_pct"),
        "yearly_appreciation_pct": metric_avg(record, "yearly_appreciation_pct"),
        "activity_score": metric_avg(record, "activity_score"),
        "premium_lens_score": metric_avg(record, "premium_lens_score"),
        "dominant_budget_segment": record.get("dominant_budget_segment"),
        "dominant_budget_share": record.get("dominant_budget_share"),
        "budget_entropy": record.get("budget_entropy"),
        "refined_budget_segment": refined_segment,
        "premium_candidate_score": record.get("premium_candidate_score"),
        "spatial_confidence": record.get("spatial_confidence"),
        "locality_count": support_metric(record, "locality_count"),
        "support_weight": support_metric(record, "total_support_weight"),
        "sale_total_count": inventory_metric(record, "sale_total_count"),
    }


def default_habitability(hex_id):
    area_sqm = hex_area_sqm(hex_id)
    return {
        "source": "overture_buildings",
        "building_count": 0,
        "building_footprint_area_sqm": 0.0,
        "hex_area_sqm": round(area_sqm, 2),
        "building_coverage_ratio": 0.0,
        "building_density_per_sqkm": 0.0,
        "habitability_score": 0.0,
        "habitability_class": "inhabitable",
        "habitable_for_residential_tam": False,
        "classification_basis": "no_overture_building_footprints_assigned",
    }


def classify_habitability(score, building_count, coverage_ratio):
    if building_count <= 0 or score < 0.05 or coverage_ratio <= 0:
        return "inhabitable"
    if score < 0.25:
        return "low_building_evidence"
    if score < 0.50:
        return "sparse_habitable"
    if score < 0.75:
        return "habitable"
    return "dense_habitable"


def build_habitability_from_overture(hex_ids):
    hex_ids = sorted(hex_ids)
    stats = {hex_id: default_habitability(hex_id) for hex_id in hex_ids}
    cells = set(hex_ids)
    processed = 0
    assigned = 0
    skipped_underground = 0
    skipped_invalid = 0

    if not OVERTURE_BUILDINGS_PATH.exists():
        return {
            "metadata": {
                "source": str(OVERTURE_BUILDINGS_PATH),
                "source_exists": False,
                "processed_buildings": 0,
                "assigned_buildings": 0,
            },
            "hexes": stats,
        }

    with OVERTURE_BUILDINGS_PATH.open("r") as f:
        data = json.load(f)

    for feature in data.get("features", []):
        processed += 1
        props = safe_dict(feature.get("properties"))
        if props.get("is_underground") is True:
            skipped_underground += 1
            continue
        area_degrees, centroid = lon_lat_geometry_area_centroid(feature.get("geometry"))
        if not centroid:
            skipped_invalid += 1
            continue
        lon, lat = centroid
        if not valid_lat_lon(lat, lon):
            skipped_invalid += 1
            continue
        hex_id = h3.latlng_to_cell(lat, lon, H3_RESOLUTION)
        if hex_id not in cells:
            continue
        area_sqm = deg_area_to_sqm(area_degrees, lat)
        if area_sqm <= 0:
            skipped_invalid += 1
            continue
        stats[hex_id]["building_count"] += 1
        stats[hex_id]["building_footprint_area_sqm"] += area_sqm
        assigned += 1

    coverage_values = []
    density_values = []
    count_values = []
    for hex_id in hex_ids:
        item = stats[hex_id]
        hex_area = item["hex_area_sqm"] or 1.0
        item["building_coverage_ratio"] = item["building_footprint_area_sqm"] / hex_area
        item["building_density_per_sqkm"] = item["building_count"] / (hex_area / 1_000_000.0)
        coverage_values.append(item["building_coverage_ratio"])
        density_values.append(item["building_density_per_sqkm"])
        count_values.append(item["building_count"])

    coverage_norm = dict(zip(hex_ids, robust_normalized(coverage_values)))
    density_norm = dict(zip(hex_ids, robust_normalized(density_values)))
    count_norm = dict(zip(hex_ids, robust_normalized(count_values)))
    for hex_id in hex_ids:
        item = stats[hex_id]
        score = (
            0.45 * coverage_norm[hex_id]
            + 0.35 * density_norm[hex_id]
            + 0.20 * count_norm[hex_id]
        )
        item["building_footprint_area_sqm"] = round(item["building_footprint_area_sqm"], 2)
        item["building_coverage_ratio"] = round(item["building_coverage_ratio"], 6)
        item["building_density_per_sqkm"] = round(item["building_density_per_sqkm"], 2)
        item["habitability_score"] = round(clamp(score), 6)
        item["habitability_class"] = classify_habitability(
            item["habitability_score"],
            item["building_count"],
            item["building_coverage_ratio"],
        )
        item["habitable_for_residential_tam"] = item["habitability_score"] >= HABITABILITY_SCORE_GATE
        item["classification_basis"] = (
            "building_coverage_density_count"
            if item["building_count"] > 0
            else "no_overture_building_footprints_assigned"
        )

    source_stat = OVERTURE_BUILDINGS_PATH.stat()
    return {
        "metadata": {
            "source": str(OVERTURE_BUILDINGS_PATH),
            "source_exists": True,
            "source_size_bytes": source_stat.st_size,
            "source_mtime": source_stat.st_mtime,
            "hex_count": len(hex_ids),
            "processed_buildings": processed,
            "assigned_buildings": assigned,
            "skipped_underground": skipped_underground,
            "skipped_invalid": skipped_invalid,
            "habitability_score_gate": HABITABILITY_SCORE_GATE,
        },
        "hexes": stats,
    }


def load_or_build_habitability(hex_ids):
    source_exists = OVERTURE_BUILDINGS_PATH.exists()
    source_stat = OVERTURE_BUILDINGS_PATH.stat() if source_exists else None
    if HABITABILITY_CACHE_PATH.exists():
        with HABITABILITY_CACHE_PATH.open("r") as f:
            cached = json.load(f)
        metadata = safe_dict(cached.get("metadata"))
        cached_hexes = safe_dict(cached.get("hexes"))
        if (
            metadata.get("source_exists") == source_exists
            and metadata.get("source_size_bytes") == (source_stat.st_size if source_stat else None)
            and metadata.get("source_mtime") == (source_stat.st_mtime if source_stat else None)
            and set(cached_hexes) >= set(hex_ids)
        ):
            return cached

    result = build_habitability_from_overture(hex_ids)
    HABITABILITY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HABITABILITY_CACHE_PATH.open("w") as f:
        json.dump(result, f, indent=2)
    return result


def apply_habitability(raw_by_hex, habitability):
    hexes = safe_dict(habitability.get("hexes"))
    for hex_id, raw in raw_by_hex.items():
        raw["habitability"] = hexes.get(hex_id) or default_habitability(hex_id)


def apply_habitability_overrides(raw_by_hex):
    for raw in raw_by_hex.values():
        habitability = raw["habitability"]
        if raw["direct_family_tam"] > 0 and not habitability["habitable_for_residential_tam"]:
            habitability["habitable_for_residential_tam"] = True
            habitability["classification_basis"] += "+direct_society_override"


def empty_raw(hex_id, centroid, record):
    market = stage15_market(record)
    flags = list(safe_dict(record.get("quality")).get("flags") or [])
    return {
        "hex_id": hex_id,
        "centroid": centroid,
        "source_record": record,
        "stage1_5_market": market,
        "quality_flags": flags,
        "habitability": default_habitability(hex_id),
        "society_links": [],
        "school_links": [],
        "hospital_links": [],
        "sez_links": [],
        "societies_direct_count": 0,
        "societies_nearby_count": 0,
        "schools_nearby_count": 0,
        "effective_school_score_count": 0,
        "hospitals_nearby_count": 0,
        "sez_nearby_count": 0,
        "direct_family_tam": 0.0,
        "direct_luxury_society_tam": 0.0,
        "nearby_family_tam_weighted": 0.0,
        "society_cluster_tam_weighted": 0.0,
        "surrounding_affluent_cluster_tam_weighted": 0.0,
        "income_band_family_tam": defaultdict(lambda: {"direct": 0.0, "nearby_weighted": 0.0}),
        "luxury_family_tam_density": 0.0,
        "society_units_density": 0.0,
        "society_category_density": 0.0,
        "direct_total_units": 0.0,
        "society_cluster_mass": 0.0,
        "surrounding_society_cluster_mass": 0.0,
        "society_cluster_ultra_super_density": 0.0,
        "society_cluster_count_weighted": 0.0,
        "society_cluster_project_count": 0,
        "project_confidence_sum": 0.0,
        "project_confidence_weight": 0.0,
        "resale_rental_liquidity": 0.0,
        "premium_school_travel_access": 0.0,
        "annual_fee_travel_weighted": 0.0,
        "student_tam_travel_weighted": 0.0,
        "top_school_count_access": 0.0,
        "premium_hospital_travel_access": 0.0,
        "doctor_capacity_travel_weighted": 0.0,
        "review_rating_confidence_sum": 0.0,
        "review_rating_confidence_weight": 0.0,
        "hospital_count_access": 0.0,
        "sez_overlap_area": 0.0,
        "sez_proximity_access": 0.0,
        "market_price_per_sqft": market.get("market_price_per_sqft") or 0.0,
        "premium_lens_score": market.get("premium_lens_score") or 0.0,
        "sale_inventory_depth": market.get("sale_total_count") or 0.0,
        "locality_support_weight": market.get("support_weight") or 0.0,
        "budget_segment_score": BUDGET_SEGMENT_VALUES.get(market.get("refined_budget_segment"), 0.0),
    }


def add_society_links(raw_by_hex, societies):
    max_radius = max(SOCIETY_RADIUS_KM, SOCIETY_CLUSTER_RADIUS_KM)
    for raw in raw_by_hex.values():
        src = raw["centroid"]
        for society in societies:
            distance = haversine_km(src["lat"], src["lon"], society["lat"], society["lon"])
            direct = society["hex_id"] == raw["hex_id"]
            if not direct and distance > max_radius:
                continue
            tam = society["estimated_families_tam"]
            category_value = society["category_value"]
            confidence = society["confidence"]

            cluster_decay = 1.0 if direct else math.exp(-distance / SOCIETY_CLUSTER_TAU_KM)
            cluster_mass = tam * category_value * confidence * cluster_decay
            raw["society_cluster_tam_weighted"] += tam * cluster_decay
            raw["society_cluster_mass"] += cluster_mass
            raw["society_cluster_count_weighted"] += category_value * cluster_decay
            raw["society_cluster_project_count"] += 1
            if category_value >= SOCIETY_CATEGORY_VALUES["Super Luxury"]:
                raw["society_cluster_ultra_super_density"] += tam * confidence * cluster_decay
            if not direct:
                raw["surrounding_affluent_cluster_tam_weighted"] += cluster_mass
                raw["surrounding_society_cluster_mass"] += cluster_mass

            if not direct and distance > SOCIETY_RADIUS_KM:
                continue

            decay = 1.0 if direct else math.exp(-distance / SOCIETY_TAU_KM)
            contribution = category_value * math.log1p(tam) * decay
            liquidity = (
                society["resale_listings_count"]
                + society["rental_listings_count"]
                + society["total_active_listings"]
            )
            link = {
                "poi_type": "society",
                "name": society["name"],
                "category": society["category"],
                "category_value": round(category_value, 4),
                "income_band": society["income_band"],
                "locality": society["locality"],
                "distance_km": round(distance, 3),
                "decay": round(decay, 4),
                "direct_in_hex": direct,
                "estimated_families_tam": round(tam, 2),
                "avg_price_per_sqft": society["avg_price_per_sqft"],
                "min_price": society["min_price"],
                "max_price": society["max_price"],
                "total_units": society["total_units"],
                "rera_id": society["rera_id"],
                "construction_status": society["construction_status"],
                "url": society["url"],
                "contribution": round(contribution, 6),
            }
            raw["society_links"].append(link)
            raw["societies_nearby_count"] += 1
            raw["nearby_family_tam_weighted"] += tam * decay
            raw["income_band_family_tam"][society["income_band"]]["nearby_weighted"] += tam * decay
            raw["luxury_family_tam_density"] += tam * category_value * decay
            raw["society_category_density"] += category_value * decay
            raw["resale_rental_liquidity"] += math.log1p(liquidity) * decay
            raw["project_confidence_sum"] += society["confidence"] * decay
            raw["project_confidence_weight"] += decay
            raw["society_units_density"] += society["total_units"] * category_value * decay
            if direct:
                raw["societies_direct_count"] += 1
                raw["direct_family_tam"] += tam
                raw["direct_total_units"] += society["total_units"]
                raw["income_band_family_tam"][society["income_band"]]["direct"] += tam
                if category_value >= SOCIETY_CATEGORY_VALUES["Luxury"]:
                    raw["direct_luxury_society_tam"] += tam


def school_bus_decay(travel_time, tau_min):
    effective_minutes = max(0.0, travel_time - SCHOOL_BUS_FREE_MIN)
    return math.exp(-effective_minutes / tau_min)


def route_poi_links(raw_by_hex, pois, client, prefilter_km, windows, poi_type):
    route_failures = 0
    for raw in raw_by_hex.values():
        source = raw["centroid"]
        candidates = []
        for poi in pois:
            straight_distance = haversine_km(source["lat"], source["lon"], poi["lat"], poi["lon"])
            if straight_distance <= prefilter_km:
                candidates.append((poi, straight_distance))
        route_targets = [{"lat": poi["lat"], "lon": poi["lon"]} for poi, _ in candidates]
        routed = client.matrix_distances(source, route_targets)
        school_links_for_hex = []

        for index, (poi, straight_distance) in enumerate(candidates):
            route = routed.get(index)
            if not route:
                route_failures += 1
                continue
            window = windows.get(poi["category"])
            if not window:
                continue
            travel_time = route["travel_time_min_at_35_kmph"]
            if travel_time > window["max_min"]:
                continue
            category_value = poi["category_value"]

            if poi_type == "school":
                decay = school_bus_decay(travel_time, window["tau_min"])
                student_tam = poi["estimated_2nd_9th_student_count"] or poi["computed_student_count"]
                contribution = category_value * (math.log1p(poi["annual_fee"]) + math.log1p(student_tam)) * decay
                school_links_for_hex.append(
                    {
                        "poi_type": "school",
                        "name": poi["name"],
                        "category": poi["category"],
                        "category_value": round(category_value, 4),
                        "board": poi["board"],
                        "annual_fee": poi["annual_fee"],
                        "estimated_student_count": student_tam,
                        "straight_line_distance_km": round(straight_distance, 3),
                        "route_distance_km": round(route["distance_km"], 3),
                        "travel_time_min_at_35_kmph": round(travel_time, 1),
                        "school_bus_decay": round(decay, 4),
                        "decay": round(decay, 4),
                        "url": poi["url"],
                        "contribution": round(contribution, 6),
                    }
                )
            else:
                decay = math.exp(-travel_time / window["tau_min"])
                capacity = poi["doctors_count"] + poi["extracted_beds"]
                rating_confidence = ((poi["rating"] or 0.0) / 5.0) * math.log1p(poi["reviews_count"])
                contribution = category_value * (math.log1p(capacity) + rating_confidence) * decay
                raw["premium_hospital_travel_access"] += category_value * decay
                raw["doctor_capacity_travel_weighted"] += capacity * category_value * decay
                raw["review_rating_confidence_sum"] += rating_confidence * decay
                raw["review_rating_confidence_weight"] += decay
                raw["hospital_count_access"] += category_value * decay
                raw["hospitals_nearby_count"] += 1
                raw["hospital_links"].append(
                    {
                        "poi_type": "hospital",
                        "name": poi["name"],
                        "category": poi["category"],
                        "category_value": round(category_value, 4),
                        "locality": poi["locality"],
                        "doctors_count": poi["doctors_count"],
                        "extracted_beds": poi["extracted_beds"],
                        "rating": poi["rating"],
                        "reviews_count": poi["reviews_count"],
                        "straight_line_distance_km": round(straight_distance, 3),
                        "route_distance_km": round(route["distance_km"], 3),
                        "travel_time_min_at_35_kmph": round(travel_time, 1),
                        "decay": round(decay, 4),
                        "url": poi["url"],
                        "contribution": round(contribution, 6),
                    }
                )

        if poi_type == "school":
            school_links_for_hex.sort(key=lambda item: item["contribution"], reverse=True)
            raw["schools_nearby_count"] += len(school_links_for_hex)
            scoring_links = school_links_for_hex[:SCHOOL_SCORE_TOP_N]
            raw["effective_school_score_count"] += len(scoring_links)
            for link in scoring_links:
                category_value = link["category_value"]
                decay = link["decay"]
                annual_fee = link["annual_fee"]
                student_tam = link["estimated_student_count"]
                raw["premium_school_travel_access"] += category_value * decay
                raw["annual_fee_travel_weighted"] += annual_fee * category_value * decay
                raw["student_tam_travel_weighted"] += student_tam * category_value * decay
                raw["top_school_count_access"] += category_value * decay
            raw["school_links"].extend(school_links_for_hex[:SCHOOL_EVIDENCE_TOP_N])
    return route_failures


def add_sez_links(raw_by_hex, zones):
    for raw in raw_by_hex.values():
        hex_poly = hex_polygon(raw["hex_id"])
        hex_area = hex_poly.area or 1.0
        for zone in zones:
            overlap_area = 0.0
            overlap_ratio = 0.0
            if hex_poly.intersects(zone["geometry"]):
                overlap_area = hex_poly.intersection(zone["geometry"]).area
                overlap_ratio = overlap_area / hex_area
            distance = haversine_km(
                raw["centroid"]["lat"],
                raw["centroid"]["lon"],
                zone["centroid_lat"],
                zone["centroid_lon"],
            )
            if overlap_ratio <= 0 and distance > SEZ_PROXIMITY_KM:
                continue
            proximity_decay = 1.0 if overlap_ratio > 0 else math.exp(-distance / SEZ_TAU_KM)
            contribution = (0.60 * overlap_ratio + 0.40 * proximity_decay) * math.log1p(
                zone["office_spaces"]
            )
            raw["sez_overlap_area"] += overlap_area
            raw["sez_proximity_access"] += proximity_decay * math.log1p(zone["office_spaces"])
            raw["sez_nearby_count"] += 1
            raw["sez_links"].append(
                {
                    "poi_type": "sez_workplace",
                    "name": zone["name"],
                    "office_spaces": zone["office_spaces"],
                    "distance_km": round(distance, 3),
                    "overlap_ratio": round(overlap_ratio, 5),
                    "proximity_decay": round(proximity_decay, 4),
                    "contribution": round(contribution, 6),
                    "description": zone["description"][:800],
                }
            )


def finalize_raw_features(raw_by_hex):
    for raw in raw_by_hex.values():
        if raw["project_confidence_weight"] > 0:
            raw["project_confidence"] = (
                raw["project_confidence_sum"] / raw["project_confidence_weight"]
            )
        else:
            raw["project_confidence"] = 0.0
        if raw["review_rating_confidence_weight"] > 0:
            raw["review_rating_confidence"] = (
                raw["review_rating_confidence_sum"] / raw["review_rating_confidence_weight"]
            )
        else:
            raw["review_rating_confidence"] = 0.0
        raw["income_band_family_tam"] = {
            band: {
                "direct": round(values["direct"], 2),
                "nearby_weighted": round(values["nearby_weighted"], 2),
            }
            for band, values in sorted(raw["income_band_family_tam"].items())
        }
        raw["society_links"].sort(key=lambda item: item["contribution"], reverse=True)
        raw["school_links"].sort(key=lambda item: item["contribution"], reverse=True)
        raw["hospital_links"].sort(key=lambda item: item["contribution"], reverse=True)
        raw["sez_links"].sort(key=lambda item: item["contribution"], reverse=True)


def apply_normalized_scores(raw_by_hex):
    hex_ids = list(raw_by_hex.keys())
    features = [
        "luxury_family_tam_density",
        "society_units_density",
        "society_category_density",
        "society_cluster_mass",
        "surrounding_society_cluster_mass",
        "society_cluster_ultra_super_density",
        "society_cluster_count_weighted",
        "project_confidence",
        "resale_rental_liquidity",
        # DEPRECATED: School features removed from scoring
        # "premium_school_travel_access",
        # "annual_fee_travel_weighted",
        # "student_tam_travel_weighted",
        # "top_school_count_access",
        "premium_hospital_travel_access",
        "doctor_capacity_travel_weighted",
        "review_rating_confidence",
        "hospital_count_access",
        "market_price_per_sqft",
        "premium_lens_score",
        "sale_inventory_depth",
        "locality_support_weight",
        "sez_overlap_area",
        "sez_proximity_access",
    ]
    normalized = {}
    for feature in features:
        values = [raw_by_hex[hex_id].get(feature, 0.0) for hex_id in hex_ids]
        scores = robust_normalized(values)
        normalized[feature] = dict(zip(hex_ids, scores))

    for hex_id in hex_ids:
        raw = raw_by_hex[hex_id]
        direct_nearby_society_score = (
            0.55 * normalized["luxury_family_tam_density"][hex_id]
            + 0.20 * normalized["society_category_density"][hex_id]
            + 0.15 * normalized["society_units_density"][hex_id]
            + 0.10 * normalized["project_confidence"][hex_id]
        )
        society_cluster_score = (
            0.55 * normalized["society_cluster_mass"][hex_id]
            + 0.25 * normalized["surrounding_society_cluster_mass"][hex_id]
            + 0.15 * normalized["society_cluster_ultra_super_density"][hex_id]
            + 0.05 * normalized["society_cluster_count_weighted"][hex_id]
        )
        society_score = (
            0.62 * direct_nearby_society_score
            + 0.28 * society_cluster_score
            + 0.10 * normalized["resale_rental_liquidity"][hex_id]
        )
        # DEPRECATED: School score removed from scoring pipeline
        school_score = 0.0
        hospital_score = (
            0.35 * normalized["premium_hospital_travel_access"][hex_id]
            + 0.25 * normalized["doctor_capacity_travel_weighted"][hex_id]
            + 0.20 * normalized["review_rating_confidence"][hex_id]
            + 0.20 * normalized["hospital_count_access"][hex_id]
        )
        market_score = (
            0.35 * normalized["market_price_per_sqft"][hex_id]
            + 0.20 * normalized["premium_lens_score"][hex_id]
            + 0.20 * raw["budget_segment_score"]
            + 0.15 * normalized["sale_inventory_depth"][hex_id]
            + 0.10 * normalized["locality_support_weight"][hex_id]
        )
        residential_anchor_strength = max(
            society_score,
            0.75 * society_cluster_score,
            0.60 * market_score,
        )
        residential_school_fit_score = 0.0  # DEPRECATED
        sez_score = min(
            1.0,
            0.60 * normalized["sez_overlap_area"][hex_id]
            + 0.40 * normalized["sez_proximity_access"][hex_id],
        )
        # Updated weights: school removed, SEZ/office boosted as primary wealth signal
        base_score = 100.0 * (
            0.50 * society_score
            + 0.10 * hospital_score
            + 0.22 * market_score
            + 0.18 * sez_score
        )
        habitability = raw["habitability"]
        if not habitability["habitable_for_residential_tam"] and raw["direct_family_tam"] <= 0:
            base_score *= 0.45
        evidence_confidence = (
            0.40
            * max(
                min(1.0, raw["societies_nearby_count"] / 5.0),
                0.75 * min(1.0, raw["society_cluster_project_count"] / 6.0),
            )
            + 0.20 * min(1.0, (raw["stage1_5_market"].get("locality_count") or 0.0) / 3.0)
            + 0.20 * min(1.0, raw["sez_nearby_count"] / 2.0)
            + 0.15 * min(1.0, raw["hospitals_nearby_count"] / 2.0)
            + 0.05 * (0.6 if raw["quality_flags"] else 1.0)
        )
        raw["component_scores"] = {
            "society_score": round(society_score, 6),
            "society_direct_nearby_score": round(direct_nearby_society_score, 6),
            "society_cluster_score": round(society_cluster_score, 6),
            "school_score": 0.0,  # DEPRECATED
            "school_access_score": 0.0,  # DEPRECATED
            "residential_school_fit_score": 0.0,  # DEPRECATED
            "residential_anchor_strength": round(residential_anchor_strength, 6),
            "hospital_score": round(hospital_score, 6),
            "market_score": round(market_score, 6),
            "sez_workplace_score": round(sez_score, 6),
            "habitability_score": round(habitability["habitability_score"], 6),
        }
        raw["base_affluence_score"] = round(base_score, 4)
        raw["confidence_score"] = round(clamp(evidence_confidence), 4)


def final_tier(score):
    if score >= 70:
        return "Premium / Luxury Affluence"
    if score >= 55:
        return "Upper-Mid / Emerging Affluence"
    if score >= 40:
        return "Mixed / Watchlist"
    return "Low Evidence"


def apply_spatial_adjustment(raw_by_hex):
    base_scores = {hex_id: raw["base_affluence_score"] for hex_id, raw in raw_by_hex.items()}
    cells = set(raw_by_hex)
    direct_luxury_values = [
        raw["direct_luxury_society_tam"]
        for raw in raw_by_hex.values()
        if raw["direct_luxury_society_tam"] > 0
    ]
    luxury_p50 = percentile(direct_luxury_values, 50) or 0.0

    for hex_id, raw in raw_by_hex.items():
        neighbors = [cell for cell in h3.grid_disk(hex_id, 1) if cell != hex_id and cell in cells]
        neighbor_scores = [base_scores[cell] for cell in neighbors]
        neighbor_mean = sum(neighbor_scores) / len(neighbor_scores) if neighbor_scores else 0.0
        high_neighbor_count = sum(1 for score in neighbor_scores if score >= 70.0)
        base_score = raw["base_affluence_score"]
        spatial_score = 0.85 * base_score + 0.15 * neighbor_mean
        island_penalty = 0.0
        cluster_boost = 0.0
        independent_anchor = False

        if base_score >= 75 and neighbor_mean < 60:
            independent_anchor = (
                raw["confidence_score"] >= 0.65
                or raw["direct_luxury_society_tam"] >= luxury_p50
            )
            if not independent_anchor:
                island_penalty = min(8.0, 0.20 * (base_score - neighbor_mean))

        if (
            55 <= base_score < 75
            and neighbor_mean >= 75
            and high_neighbor_count >= 2
            and raw["confidence_score"] >= 0.55
        ):
            cluster_boost = min(5.0, 0.10 * (neighbor_mean - base_score))

        final_score = clamp(spatial_score - island_penalty + cluster_boost, 0.0, 100.0)
        if final_score < 40 or raw["confidence_score"] < 0.25:
            relation = "low_evidence"
        elif base_score >= 75 and neighbor_mean >= 75:
            relation = "core_cluster"
        elif cluster_boost > 0 or (base_score < 75 and neighbor_mean >= 75):
            relation = "cluster_edge"
        elif island_penalty > 0:
            relation = "isolated_high"
        elif independent_anchor:
            relation = "independent_anchor"
        else:
            relation = "local_signal"

        raw["spatial_adjustment"] = {
            "neighbor_hex_count": len(neighbors),
            "neighbor_mean_score": round(neighbor_mean, 4),
            "high_neighbor_count": high_neighbor_count,
            "spatial_score_before_penalty_boost": round(spatial_score, 4),
            "island_penalty": round(island_penalty, 4),
            "cluster_boost": round(cluster_boost, 4),
            "direct_luxury_society_tam_p50": round(luxury_p50, 4),
        }
        raw["component_scores"]["spatial_adjustment"] = round(cluster_boost - island_penalty, 6)
        raw["final_affluence_score"] = round(final_score, 4)
        raw["affluence_tier"] = final_tier(final_score)
        raw["spatial_relation"] = relation


def build_master_records(raw_by_hex):
    sorted_hexes = sorted(
        raw_by_hex,
        key=lambda cell: raw_by_hex[cell]["final_affluence_score"],
        reverse=True,
    )
    records = []
    for rank, hex_id in enumerate(sorted_hexes, start=1):
        raw = raw_by_hex[hex_id]
        direct_family_tam = raw["direct_family_tam"]
        # DEPRECATED: School-based TAM estimation removed
        school_age_families = 0.0
        school_age_children = 0.0
        wealthy_school_children = 0.0
        habitability = raw["habitability"]
        habitable_for_tam = bool(habitability["habitable_for_residential_tam"])
        countable_direct_family_tam = direct_family_tam if habitable_for_tam else 0.0
        countable_school_age_families = 0.0
        countable_school_age_children = 0.0
        countable_wealthy_school_children = 0.0
        quality_flags = list(raw["quality_flags"])
        if raw["direct_family_tam"] <= 0:
            quality_flags.append("no_direct_society_tam")
        if not habitable_for_tam:
            quality_flags.append("low_overture_building_habitability")
        if raw["societies_nearby_count"] == 0 and raw["sez_nearby_count"] == 0:
            quality_flags.append("low_residential_office_poi_evidence")

        record = {
            "hex_id": hex_id,
            "resolution": H3_RESOLUTION,
            "name": raw["stage1_5_market"].get("name"),
            "rank": rank,
            "base_affluence_score": raw["base_affluence_score"],
            "final_affluence_score": raw["final_affluence_score"],
            "affluence_tier": raw["affluence_tier"],
            "spatial_relation": raw["spatial_relation"],
            "confidence_score": raw["confidence_score"],
            "component_scores": raw["component_scores"],
            "spatial_adjustment": raw["spatial_adjustment"],
            "habitability": habitability,
            "tam": {
                "direct_family_tam": round(direct_family_tam, 2),
                "direct_total_units": round(raw["direct_total_units"], 2),
                "countable_direct_family_tam": round(countable_direct_family_tam, 2),
                "nearby_family_tam_weighted": round(raw["nearby_family_tam_weighted"], 2),
                "society_cluster_tam_weighted": round(raw["society_cluster_tam_weighted"], 2),
                "surrounding_affluent_cluster_tam_weighted": round(
                    raw["surrounding_affluent_cluster_tam_weighted"], 2
                ),
                "direct_luxury_society_tam": round(raw["direct_luxury_society_tam"], 2),
                "income_band_family_tam": raw["income_band_family_tam"],
                "estimated_school_age_families": round(school_age_families, 2),
                "estimated_school_age_children": round(school_age_children, 2),
                "countable_school_age_families": round(countable_school_age_families, 2),
                "countable_school_age_children": round(countable_school_age_children, 2),
                "estimated_wealthy_school_families": round(
                    school_age_families * 0.0, 2
                ),  # DEPRECATED: school_access_score removed from scoring
                "estimated_wealthy_school_children": round(wealthy_school_children, 2),
                "countable_wealthy_school_children": round(
                    countable_wealthy_school_children, 2
                ),
            },
            "stage1_5_market": raw["stage1_5_market"],
            "poi_summary": {
                "societies_direct_count": raw["societies_direct_count"],
                "societies_nearby_count": raw["societies_nearby_count"],
                "society_cluster_project_count": raw["society_cluster_project_count"],
                "schools_nearby_count": raw["schools_nearby_count"],
                "eligible_school_routes_count": raw["schools_nearby_count"],
                "effective_school_score_count": raw["effective_school_score_count"],
                "hospitals_nearby_count": raw["hospitals_nearby_count"],
                "sez_nearby_count": raw["sez_nearby_count"],
            },
            "top_evidence": {
                "societies": raw["society_links"][:10],
                "schools": raw["school_links"][:SCHOOL_EVIDENCE_TOP_N],
                "hospitals": raw["hospital_links"][:10],
                "sez_workplaces": raw["sez_links"][:5],
            },
            "routing": {
                "method": "google_maps",
                "avg_speed_kmph": AVG_SPEED_KMPH,
            },
            "quality_flags": sorted(set(quality_flags)),
        }
        records.append(record)
    return records


def flat_record(record):
    market = record["stage1_5_market"]
    scores = record["component_scores"]
    tam = record["tam"]
    summary = record["poi_summary"]
    spatial = record["spatial_adjustment"]
    habitability = record["habitability"]
    return {
        "hex_id": record["hex_id"],
        "rank": record["rank"],
        "name": record["name"],
        "final_affluence_score": record["final_affluence_score"],
        "base_affluence_score": record["base_affluence_score"],
        "affluence_tier": record["affluence_tier"],
        "spatial_relation": record["spatial_relation"],
        "confidence_score": record["confidence_score"],
        "society_score": scores["society_score"],
        "society_direct_nearby_score": scores["society_direct_nearby_score"],
        "society_cluster_score": scores["society_cluster_score"],
        "school_score": scores["school_score"],
        "school_access_score": scores["school_access_score"],
        "residential_school_fit_score": scores["residential_school_fit_score"],
        "residential_anchor_strength": scores["residential_anchor_strength"],
        "hospital_score": scores["hospital_score"],
        "market_score": scores["market_score"],
        "sez_workplace_score": scores["sez_workplace_score"],
        "habitability_score": scores["habitability_score"],
        "habitability_class": habitability["habitability_class"],
        "habitable_for_residential_tam": habitability["habitable_for_residential_tam"],
        "building_count": habitability["building_count"],
        "building_footprint_area_sqm": habitability["building_footprint_area_sqm"],
        "building_coverage_ratio": habitability["building_coverage_ratio"],
        "building_density_per_sqkm": habitability["building_density_per_sqkm"],
        "neighbor_mean_score": spatial["neighbor_mean_score"],
        "island_penalty": spatial["island_penalty"],
        "cluster_boost": spatial["cluster_boost"],
        "direct_family_tam": tam["direct_family_tam"],
        "direct_total_units": tam.get("direct_total_units", 0.0),
        "countable_direct_family_tam": tam["countable_direct_family_tam"],
        "nearby_family_tam_weighted": tam["nearby_family_tam_weighted"],
        "society_cluster_tam_weighted": tam["society_cluster_tam_weighted"],
        "surrounding_affluent_cluster_tam_weighted": tam[
            "surrounding_affluent_cluster_tam_weighted"
        ],
        "direct_luxury_society_tam": tam["direct_luxury_society_tam"],
        "estimated_school_age_families": tam["estimated_school_age_families"],
        "estimated_school_age_children": tam["estimated_school_age_children"],
        "countable_school_age_families": tam["countable_school_age_families"],
        "countable_school_age_children": tam["countable_school_age_children"],
        "estimated_wealthy_school_families": tam["estimated_wealthy_school_families"],
        "estimated_wealthy_school_children": tam["estimated_wealthy_school_children"],
        "countable_wealthy_school_children": tam["countable_wealthy_school_children"],
        "market_price_per_sqft": market.get("market_price_per_sqft"),
        "rental_yield_pct": market.get("rental_yield_pct"),
        "yearly_appreciation_pct": market.get("yearly_appreciation_pct"),
        "refined_budget_segment": market.get("refined_budget_segment"),
        "premium_candidate_score": market.get("premium_candidate_score"),
        "societies_direct_count": summary["societies_direct_count"],
        "societies_nearby_count": summary["societies_nearby_count"],
        "society_cluster_project_count": summary["society_cluster_project_count"],
        "schools_nearby_count": summary["schools_nearby_count"],
        "eligible_school_routes_count": summary["eligible_school_routes_count"],
        "effective_school_score_count": summary["effective_school_score_count"],
        "hospitals_nearby_count": summary["hospitals_nearby_count"],
        "sez_nearby_count": summary["sez_nearby_count"],
        "top_societies": "; ".join(item["name"] for item in record["top_evidence"]["societies"][:5]),
        "top_schools": "; ".join(item["name"] for item in record["top_evidence"]["schools"][:5]),
        "top_hospitals": "; ".join(item["name"] for item in record["top_evidence"]["hospitals"][:5]),
        "quality_flags": ", ".join(record["quality_flags"]),
    }


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)


def write_csv(records):
    rows = [flat_record(record) for record in records]
    with OUTPUT_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_geojson(records):
    features = []
    for record in records:
        props = flat_record(record)
        features.append(
            {
                "type": "Feature",
                "geometry": geojson_geometry(record["hex_id"]),
                "properties": props,
            }
        )
    write_json(OUTPUT_GEOJSON, {"type": "FeatureCollection", "features": features})


def write_links(records):
    with OUTPUT_LINKS.open("w") as f:
        for record in records:
            for group_name, items in record["top_evidence"].items():
                for item in items:
                    f.write(
                        json.dumps(
                            {
                                "hex_id": record["hex_id"],
                                "rank": record["rank"],
                                "evidence_group": group_name,
                                **item,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )


def esc(value):
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def cdata(value):
    return str(value).replace("]]>", "]]]]><![CDATA[>")


def fmt_number(value, decimals=0):
    if value is None:
        return "NA"
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return esc(value)


def hex_to_kml_color(hex_color, alpha):
    color = hex_color.lstrip("#")
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)
    return f"{alpha:02x}{b:02x}{g:02x}{r:02x}"


def score_color(score):
    if score >= 90:
        return "#14532d"
    if score >= 80:
        return "#15803d"
    if score >= 70:
        return "#65a30d"
    if score >= 55:
        return "#f59e0b"
    if score >= 40:
        return "#f97316"
    return "#94a3b8"


def kml_style(record, mode):
    highlight = mode == "highlight"
    alpha = 218 if highlight else 176
    line = "#111827" if highlight else "#f8fafc"
    width = "2.2" if highlight else "0.8"
    return f"""
    <Style id="hex7_{record['hex_id']}_{mode}">
      <LineStyle><color>{hex_to_kml_color(line, 235)}</color><width>{width}</width></LineStyle>
      <PolyStyle><color>{hex_to_kml_color(score_color(record['final_affluence_score']), alpha)}</color><fill>1</fill><outline>1</outline></PolyStyle>
    </Style>"""


def kml_style_map(record):
    return f"""
    <StyleMap id="hex7_{record['hex_id']}_stylemap">
      <Pair><key>normal</key><styleUrl>#hex7_{record['hex_id']}_normal</styleUrl></Pair>
      <Pair><key>highlight</key><styleUrl>#hex7_{record['hex_id']}_highlight</styleUrl></Pair>
    </StyleMap>"""


def poi_pin_style(style_id, color, scale=0.85):
    return f"""
    <Style id="{style_id}">
      <IconStyle>
        <color>{hex_to_kml_color(color, 255)}</color>
        <scale>{scale}</scale>
        <Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon>
      </IconStyle>
      <LabelStyle><scale>0.72</scale></LabelStyle>
    </Style>"""


def point_placemark(name, lat, lon, style_id, description):
    return f"""
      <Placemark>
        <name>{esc(name)}</name>
        <styleUrl>#{style_id}</styleUrl>
        <description><![CDATA[{cdata(description)}]]></description>
        <Point><coordinates>{float(lon):.8f},{float(lat):.8f},0</coordinates></Point>
      </Placemark>"""


def stat_cell(label, value):
    return f"""
      <td style="border:1px solid #e5e7eb;padding:8px 9px;background:#ffffff;vertical-align:top;">
        <div style="font-size:10px;letter-spacing:.04em;text-transform:uppercase;color:#6b7280;">{esc(label)}</div>
        <div style="font-size:13px;color:#111827;font-weight:700;margin-top:2px;">{value}</div>
      </td>"""


def mini_table(headers, rows):
    if not rows:
        return '<div style="font-size:12px;color:#6b7280;">No data</div>'
    header = "".join(
        f'<th style="border-bottom:1px solid #e5e7eb;padding:6px;text-align:left;font-size:10px;color:#6b7280;text-transform:uppercase;">{esc(h)}</th>'
        for h in headers
    )
    body = []
    for row in rows:
        body.append(
            "<tr>"
            + "".join(
                f'<td style="border-bottom:1px solid #f1f5f9;padding:6px;font-size:11px;color:#111827;">{cell}</td>'
                for cell in row
            )
            + "</tr>"
        )
    return f'<table style="border-collapse:collapse;width:100%;margin-top:4px;"><thead><tr>{header}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def section(title, body):
    return f"""
      <div style="margin-top:14px;">
        <div style="font-size:12px;font-weight:700;color:#111827;margin-bottom:6px;">{esc(title)}</div>
        {body}
      </div>"""


def poi_description(title, rows):
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;color:#111827;">
      <h2 style="margin:0 0 8px 0;font-size:16px;">{esc(title)}</h2>
      {mini_table(["Metric", "Value"], rows)}
    </div>
    """


def kml_description(record):
    market = record["stage1_5_market"]
    tam = record["tam"]
    scores = record["component_scores"]
    habitability = record["habitability"]
    society_rows = [
        [
            esc(item["name"]),
            esc(item["category"]),
            fmt_number(item.get("estimated_families_tam")),
            fmt_number(item.get("total_units")),
            fmt_number(item.get("avg_price_per_sqft")),
            fmt_number(item.get("distance_km"), 2),
        ]
        for item in record["top_evidence"]["societies"][:5]
    ]
    school_rows = [
        [
            esc(item["name"]),
            esc(item["category"]),
            fmt_number(item.get("annual_fee")),
            fmt_number(item.get("estimated_student_count")),
            fmt_number(item.get("travel_time_min_at_35_kmph"), 1),
        ]
        for item in record["top_evidence"]["schools"][:5]
    ]
    hospital_rows = [
        [
            esc(item["name"]),
            esc(item["category"]),
            fmt_number(item.get("doctors_count")),
            fmt_number(item.get("reviews_count")),
            fmt_number(item.get("travel_time_min_at_35_kmph"), 1),
        ]
        for item in record["top_evidence"]["hospitals"][:5]
    ]
    sez_rows = [
        [
            esc(item["name"]),
            fmt_number(item.get("office_spaces")),
            fmt_number(item.get("distance_km"), 2),
            fmt_number(item.get("overlap_ratio"), 3),
        ]
        for item in record["top_evidence"]["sez_workplaces"][:5]
    ]
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:760px;color:#111827;">
      <h2 style="margin:0 0 4px 0;font-size:18px;">#{record['rank']} {esc(record['name'])}</h2>
      <div style="font-size:11px;color:#6b7280;">{esc(record['hex_id'])}</div>
      <table style="border-collapse:collapse;width:100%;margin-top:10px;"><tr>
        {stat_cell("Final score", fmt_number(record["final_affluence_score"], 1))}
        {stat_cell("Tier", esc(record["affluence_tier"]))}
        {stat_cell("Confidence", fmt_number(record["confidence_score"], 2))}
        {stat_cell("Spatial relation", esc(record["spatial_relation"]))}
      </tr><tr>
        {stat_cell("Society", fmt_number(scores["society_score"], 2))}
        {stat_cell("Soc. cluster", fmt_number(scores.get("society_cluster_score"), 2))}
        {stat_cell("School fit", fmt_number(scores["school_score"], 2))}
        {stat_cell("School access", fmt_number(scores.get("school_access_score"), 2))}
      </tr><tr>
        {stat_cell("Hospital", fmt_number(scores["hospital_score"], 2))}
        {stat_cell("Market", fmt_number(scores["market_score"], 2))}
        {stat_cell("SEZ", fmt_number(scores["sez_workplace_score"], 2))}
        {stat_cell("Habitable", esc(habitability["habitability_class"]))}
      </tr></table>
      {section("Market", mini_table(["Metric", "Value"], [
        ["Price/sqft", fmt_number(market.get("market_price_per_sqft"))],
        ["Budget segment", esc(market.get("refined_budget_segment"))],
        ["Premium candidate score", fmt_number(market.get("premium_candidate_score"), 2)],
        ["Rental yield", fmt_number(market.get("rental_yield_pct"), 2)]
      ]))}
      {section("TAM", mini_table(["Metric", "Value"], [
        ["Direct family TAM", fmt_number(tam["direct_family_tam"])],
        ["Direct total units", fmt_number(tam.get("direct_total_units", 0.0))],
        ["Countable direct family TAM", fmt_number(tam["countable_direct_family_tam"])],
        ["Nearby family TAM weighted", fmt_number(tam["nearby_family_tam_weighted"])],
        ["Society cluster TAM weighted", fmt_number(tam["society_cluster_tam_weighted"])],
        ["Surrounding affluent cluster TAM weighted", fmt_number(tam["surrounding_affluent_cluster_tam_weighted"])],
        ["School-age families", fmt_number(tam["estimated_school_age_families"])],
        ["Wealthy-school children", fmt_number(tam["estimated_wealthy_school_children"])],
        ["Countable wealthy-school children", fmt_number(tam["countable_wealthy_school_children"])]
      ]))}
      {section("Habitability", mini_table(["Metric", "Value"], [
        ["Class", esc(habitability["habitability_class"])],
        ["Habitable for TAM", esc(habitability["habitable_for_residential_tam"])],
        ["Score", fmt_number(habitability["habitability_score"], 2)],
        ["Buildings", fmt_number(habitability["building_count"])],
        ["Footprint sqm", fmt_number(habitability["building_footprint_area_sqm"])],
        ["Coverage ratio", fmt_number(habitability["building_coverage_ratio"], 4)]
      ]))}
      {section("Top societies", mini_table(["Society", "Category", "TAM", "Units", "Price/sqft", "Km"], society_rows))}
      {section("Top schools", mini_table(["School", "Category", "Fee", "Students", "Min"], school_rows))}
      {section("Top hospitals", mini_table(["Hospital", "Category", "Doctors", "Reviews", "Min"], hospital_rows))}
      {section("SEZ context", mini_table(["Zone", "Offices", "Km", "Overlap"], sez_rows))}
      {section("Quality flags", "<div style='font-size:12px;color:#374151;'>" + esc(", ".join(record["quality_flags"]) or "None") + "</div>")}
    </div>
    """


def society_pin_placemark(society):
    title = society["name"]
    rows = [
        ["Category", esc(society["category"])],
        ["Income band", esc(society["income_band"])],
        ["Locality", esc(society["locality"])],
        ["Estimated families TAM", fmt_number(society["estimated_families_tam"])],
        ["Avg price/sqft", fmt_number(society["avg_price_per_sqft"])],
        ["Total units", fmt_number(society["total_units"])],
        ["Construction", esc(society["construction_status"])],
        ["URL", f'<a href="{esc(society["url"])}">source</a>' if society.get("url") else "NA"],
    ]
    return point_placemark(title, society["lat"], society["lon"], "poi_society", poi_description(title, rows))


def school_pin_placemark(school):
    title = school["name"]
    rows = [
        ["Category", esc(school["category"])],
        ["Board", esc(school["board"])],
        ["Annual fee", fmt_number(school["annual_fee"])],
        ["Computed students", fmt_number(school["computed_student_count"])],
        ["Est. 2nd-9th students", fmt_number(school["estimated_2nd_9th_student_count"])],
        ["Pincode", esc(school["pincode"])],
        ["URL", f'<a href="{esc(school["url"])}">source</a>' if school.get("url") else "NA"],
    ]
    return point_placemark(title, school["lat"], school["lon"], "poi_school", poi_description(title, rows))


def hospital_pin_placemark(hospital):
    title = hospital["name"]
    rows = [
        ["Category", esc(hospital["category"])],
        ["Locality", esc(hospital["locality"])],
        ["Doctors", fmt_number(hospital["doctors_count"])],
        ["Beds", fmt_number(hospital["extracted_beds"])],
        ["Rating", fmt_number(hospital["rating"], 1)],
        ["Reviews", fmt_number(hospital["reviews_count"])],
        ["URL", f'<a href="{esc(hospital["url"])}">source</a>' if hospital.get("url") else "NA"],
    ]
    return point_placemark(title, hospital["lat"], hospital["lon"], "poi_hospital", poi_description(title, rows))


def write_kml(records, societies, schools, hospitals):
    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    styles = []
    placemarks = []
    for record in records:
        styles.append(kml_style(record, "normal"))
        styles.append(kml_style(record, "highlight"))
        styles.append(kml_style_map(record))
        placemarks.append(
            f"""
      <Placemark>
        <name>#{record['rank']} {esc(record['name'])} - {esc(record['affluence_tier'])}</name>
        <styleUrl>#hex7_{record['hex_id']}_stylemap</styleUrl>
        <description><![CDATA[{cdata(kml_description(record))}]]></description>
        <Polygon>
          <outerBoundaryIs><LinearRing><coordinates>{coordinates_for_kml(record['hex_id'])}</coordinates></LinearRing></outerBoundaryIs>
        </Polygon>
      </Placemark>"""
        )
    pin_styles = [
        poi_pin_style("poi_society", "#16a34a", 0.9),
        poi_pin_style("poi_school", "#2563eb", 0.85),
        poi_pin_style("poi_hospital", "#dc2626", 0.85),
    ]
    society_pins = [society_pin_placemark(item) for item in societies]
    school_pins = [school_pin_placemark(item) for item in schools]
    hospital_pins = [hospital_pin_placemark(item) for item in hospitals]
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Stage 2 Hex-7 Affluent Family TAM Ranking</name>
    {''.join(styles)}
    {''.join(pin_styles)}
    <Folder>
      <name>Ranked H3-7 Affluence Hexes</name>
      {''.join(placemarks)}
    </Folder>
    <Folder>
      <name>POI Pins</name>
      <Folder>
        <name>Societies ({len(society_pins)})</name>
        {''.join(society_pins)}
      </Folder>
      <Folder>
        <name>Schools ({len(school_pins)})</name>
        {''.join(school_pins)}
      </Folder>
      <Folder>
        <name>Hospitals ({len(hospital_pins)})</name>
        {''.join(hospital_pins)}
      </Folder>
    </Folder>
  </Document>
</kml>
"""
    OUTPUT_KML.write_text(kml)


def write_methodology():
    text = f"""# Stage 2 Hex-7 Affluent Family TAM Methodology

This pipeline uses Google Maps Distance Matrix API for routing.

## Final score

`base_affluence_score = 100 * (0.50 society + 0.10 hospital + 0.22 market + 0.18 SEZ)`

The society component separates direct/nearby residential evidence from cluster context:

`society_score = 0.62 * society_direct_nearby_score + 0.28 * society_cluster_score + 0.10 * resale_rental_liquidity`

Direct/nearby society evidence uses societies inside the hex or within `{SOCIETY_RADIUS_KM}` km.
Society cluster evidence uses societies within `{SOCIETY_CLUSTER_RADIUS_KM}` km with softer spatial decay:

`society_cluster_decay = exp(-distance_km / {SOCIETY_CLUSTER_TAU_KM})`

`society_cluster_mass = society_family_tam * society_category_value * project_confidence * society_cluster_decay`

`direct_family_tam` remains the non-duplicated in-hex residential TAM. Cluster TAM fields are influence
signals and should not be summed as unique households.

## Overture habitability layer

Overture building footprints are aggregated to each H3-7 hex using building centroid assignment and polygon
footprint area. The output includes building count, footprint area, coverage ratio, density, habitability score,
and habitability class.

Hexes with low Overture building evidence are flagged and their base score is reduced unless direct society TAM
overrides the building weakness. `countable_*` TAM fields should be used when Stage 3 needs habitable-only totals.

The final score is spatially adjusted after the base score:

`spatial_score = 0.85 * base_score + 0.15 * neighbor_mean_score`

Island penalties and cluster boosts are then applied with the thresholds encoded in
`scripts/active/generate_stage2_hex7_affluence.py`.

## Routing

Travel time is computed using Google Maps routing matrix with `{AVG_SPEED_KMPH}` km/h average fallback:

`travel_time_min = route_distance_km / 35 * 60`

## TAM assumptions

`Estimated Families (TAM)` from societies is treated as the strongest observed residential TAM source.
"""
    METHODOLOGY_MD.write_text(text)


def write_audit(records, invalid, route_failures, client, input_counts):
    top25 = [
        {
            "rank": record["rank"],
            "hex_id": record["hex_id"],
            "name": record["name"],
            "final_affluence_score": record["final_affluence_score"],
            "affluence_tier": record["affluence_tier"],
            "direct_family_tam": record["tam"]["direct_family_tam"],
            "society_cluster_score": record["component_scores"]["society_cluster_score"],
            "surrounding_affluent_cluster_tam_weighted": record["tam"][
                "surrounding_affluent_cluster_tam_weighted"
            ],
            "top_society": (record["top_evidence"]["societies"] or [{}])[0].get("name"),
            "top_school": (record["top_evidence"]["schools"] or [{}])[0].get("name"),
        }
        for record in records[:25]
    ]
    audit = {
        "inputs": input_counts,
        "outputs": {
            "json": str(OUTPUT_JSON),
            "csv": str(OUTPUT_CSV),
            "geojson": str(OUTPUT_GEOJSON),
            "links": str(OUTPUT_LINKS),
            "routing_cache": str(ROUTING_CACHE_PATH),
            "kml": str(OUTPUT_KML),
            "methodology": str(METHODOLOGY_MD),
        },
        "routing": {
            "method": "google_maps",
            "avg_speed_kmph": AVG_SPEED_KMPH,
            "request_count": client.request_count,
            "cache_hits": client.cache_hits,
            "failures": dict(client.failures),
            "route_failures": route_failures,
        },
        "invalid_coordinate_counts": {key: len(value) for key, value in invalid.items()},
        "invalid_coordinate_examples": {key: value[:10] for key, value in invalid.items()},
        "tier_counts": Counter(record["affluence_tier"] for record in records),
        "spatial_relation_counts": Counter(record["spatial_relation"] for record in records),
        "habitability_class_counts": Counter(
            record["habitability"]["habitability_class"] for record in records
        ),
        "habitable_for_residential_tam_count": sum(
            1 for record in records if record["habitability"]["habitable_for_residential_tam"]
        ),
        "top25": top25,
    }
    write_json(AUDIT_JSON, audit)


def build_pipeline():
    start_time = time.time()
    def log_stage(stage_name, details=""):
        elapsed = time.time() - start_time
        time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        print(f"[{time_str}] [STAGE: {stage_name}] {details} (Elapsed: {elapsed:.2f}s)")

    log_stage("Load Input Data", "Loading Stage 1.5 hexes, societies, schools, hospitals, and SEZ zones...")
    stage_records = load_json(STAGE15_HEX_PATH)
    stage_records = [r for r in stage_records if r.get("hex_id") != "87618eb26ffffff"]
    if not isinstance(stage_records, list):
        raise ValueError(f"{STAGE15_HEX_PATH} must contain a top-level list.")
    societies, invalid_societies = load_societies()
    schools, invalid_schools = load_schools()
    hospitals, invalid_hospitals = load_hospitals()
    sez_zones = load_sez_zones()
    log_stage("Load Input Data Completed", f"Loaded {len(stage_records)} hexes, {len(societies)} societies, {len(schools)} schools, {len(hospitals)} hospitals, and {len(sez_zones)} SEZ zones.")

    log_stage("Initialize Google Maps Routing Client", f"API key set: {'YES' if GOOGLE_MAPS_API_KEY else 'NO — set GOOGLE_MAPS_API_KEY env var'}")
    client = GoogleMapsRoutingClient(GOOGLE_MAPS_API_KEY, ROUTING_CACHE_PATH)
    client.validate()
    log_stage("Google Maps Routing Client Ready", f"Cache pre-loaded with {len(client.cache['routes'])} existing routes (OSRM + Google Maps compatible).")

    log_stage("Initialize Hex Map")
    raw_by_hex = {}
    for record in stage_records:
        hex_id = record["hex_id"]
        raw_by_hex[hex_id] = empty_raw(hex_id, hex_centroid(hex_id), record)
    log_stage("Initialize Hex Map Completed")

    log_stage("Habitability Analysis", "Processing/Loading Overture building footprints...")
    habitability = load_or_build_habitability(raw_by_hex.keys())
    apply_habitability(raw_by_hex, habitability)
    log_stage("Habitability Analysis Completed")

    log_stage("Society Analysis", "Processing and linking societies...")
    add_society_links(raw_by_hex, societies)
    apply_habitability_overrides(raw_by_hex)
    log_stage("Society Analysis Completed")

    log_stage("School Routing Analysis", "SKIPPED — school scoring deprecated; school_score=0 in new formula. No routing API calls made.")
    # School routing is skipped entirely. Schools still loaded for evidence display in top_evidence,
    # but their routing costs are not calculated since school_score = 0 in build_pipeline.
    route_failures = 0
    log_stage("School Routing Analysis Completed", "Skipped — 0 API calls made.")

    log_stage("Hospital Routing Analysis", "Computing and linking hospital accessibility routing via OSRM...")
    hospital_route_failures = route_poi_links(
        raw_by_hex,
        hospitals,
        client,
        HOSPITAL_PREFILTER_KM,
        HOSPITAL_WINDOWS,
        "hospital",
    )
    route_failures += hospital_route_failures
    log_stage("Hospital Routing Analysis Completed", f"Hospital routing failures in this stage: {hospital_route_failures}, cumulative routing failures: {route_failures}")

    log_stage("SEZ Office Analysis", "Processing and overlaying SEZ office zones...")
    add_sez_links(raw_by_hex, sez_zones)
    log_stage("SEZ Office Analysis Completed")

    log_stage("Finalizing Features", "Aggregating and sorting linked POI lists...")
    finalize_raw_features(raw_by_hex)
    log_stage("Finalizing Features Completed")

    log_stage("Scoring", "Normalizing features and computing component/base affluence scores...")
    apply_normalized_scores(raw_by_hex)
    log_stage("Scoring Completed")

    log_stage("Spatial Adjustment", "Applying neighborhood spatial smoothing, penalties, and boosts...")
    apply_spatial_adjustment(raw_by_hex)
    log_stage("Spatial Adjustment Completed")

    log_stage("Build Master Records", "Constructing final ranked master records...")
    records = build_master_records(raw_by_hex)
    log_stage("Build Master Records Completed")

    log_stage("Write Output Files", "Writing output files (JSON, CSV, GeoJSON, Links, KML, Methodology, Audit)...")
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT_JSON, records)
    write_csv(records)
    write_geojson(records)
    write_links(records)
    write_kml(records, societies, schools, hospitals)
    write_methodology()
    client.save()
    write_audit(
        records,
        {
            "societies": invalid_societies,
            "schools": invalid_schools,
            "hospitals": invalid_hospitals,
        },
        route_failures,
        client,
        {
            "stage1_5_hexes": len(stage_records),
            "societies_loaded": len(societies),
            "schools_loaded": len(schools),
            "hospitals_loaded": len(hospitals),
            "sez_zones_loaded": len(sez_zones),
            "overture_buildings_processed": safe_dict(habitability.get("metadata")).get(
                "processed_buildings"
            ),
            "overture_buildings_assigned": safe_dict(habitability.get("metadata")).get(
                "assigned_buildings"
            ),
        },
    )
    log_stage("Write Output Files Completed", "Successfully wrote all pipeline outputs.")
    return records


def main():
    records = build_pipeline()
    print(f"Wrote {OUTPUT_JSON} ({len(records)} H3-7 records)")
    print(f"Wrote {OUTPUT_CSV}")
    print(f"Wrote {OUTPUT_GEOJSON}")
    print(f"Wrote {OUTPUT_LINKS}")
    print(f"Wrote {ROUTING_CACHE_PATH}")
    print(f"Wrote {OUTPUT_KML}")
    print(f"Wrote {AUDIT_JSON}")
    print(f"Wrote {METHODOLOGY_MD}")


if __name__ == "__main__":
    main()
