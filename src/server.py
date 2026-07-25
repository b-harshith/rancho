import http.server
import socketserver
import json
import urllib.parse
import math
import os
from pathlib import Path
import requests
import h3
from shapely.geometry import Point, shape, Polygon
from shapely.strtree import STRtree
import concurrent.futures
from api.listings import handler as ListingsHandler
from api.multicity import handler as MulticityHandler
from api.auth import handler as AuthHandler
from portal_auth import is_authorized
from catchment_market import (
    SCHEMA_VERSION,
    CatchmentConfigurationError,
    CatchmentProviderError,
    CatchmentValidationError,
    build_market_ledger,
    build_portfolio_result,
    error_payload,
    get_live_drive_isochrone,
    google_maps_api_key,
    load_market_data,
    parse_market_options,
    parse_market_options_payload,
    validate_live_request,
)

# Setup Paths
PORT = int(os.environ.get("PORT", "8050"))
SERVER_DIR = Path(__file__).resolve().parent
STATIC_DIR = SERVER_DIR / "public"
DATA_DIR = STATIC_DIR / "data"
SUPPORTED_CITY_IDS = frozenset({"delhi_ncr", "bengaluru", "hyderabad", "mumbai"})
LEGACY_CATCHMENT_CITY_ID = "bengaluru"
CITY_LEGACY_DATA_DIR = DATA_DIR / "city_legacy"
CITY_COORDINATE_WINDOWS = {
    "delhi_ncr": (27.0, 76.0, 29.9, 78.8),
    "bengaluru": (12.0, 76.7, 14.1, 78.5),
    "hyderabad": (16.5, 77.5, 18.5, 79.6),
    "mumbai": (18.6, 72.6, 19.9, 73.7),
}

# Load precompiled data for catchment queries
HEXES = None
SOCIETIES = None
# DEPRECATED: SCHOOLS data removed from scoring pipeline
# SCHOOLS = None
HOSPITALS = None
SEZ_ZONES = None
MASTER_HEXES = None
METRO_STATIONS = None
SOCIETY_HEX_METRICS = None
Q3_HEX_RECORDS = None
MARKET_DATA = None
ACTIVE_CATCHMENT_CITY_ID = None

# Spatial Indexing and O(1) Lookups
HEX_LOOKUP = None
HEX_GEOMS = None
HEX_TREE = None
Q3_HEX_GEOMS = None
Q3_HEX_TREE = None

def get_maps_api_key(api_key):
    """Compatibility wrapper; client-provided keys are intentionally ignored."""
    try:
        return google_maps_api_key()
    except Exception:
        return ""

def _parse_google_isochrone_geometry(payload):
    if not isinstance(payload, dict):
        return None
    iso = payload.get("isochrone")
    if isinstance(iso, dict):
        for key in ("geoJson", "geojson", "geometry"):
            geom = iso.get(key)
            if geom:
                return geom
    for key in ("geometry", "polygon", "boundary"):
        geom = payload.get(key)
        if geom:
            return geom
    return None

def _google_isochrone_request(lat, lon, mins, travel_mode, live_traffic, smooth_edges, api_key):
    geometry, cache = get_live_drive_isochrone(
        lat, lon, mins, smooth_edges=str(smooth_edges).lower() == "true"
    )
    return {"geometry": geometry, "cache": cache}

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def build_hex_polygon(hex_id):
    boundary = h3.cell_to_boundary(hex_id)
    return Polygon([(lon, lat) for lat, lon in boundary]).buffer(0)

def sum_q3_below_for_geometry(area_shape):
    if area_shape is None or Q3_HEX_TREE is None or not Q3_HEX_RECORDS:
        return 0.0
    try:
        area_shape = area_shape.buffer(0)
    except Exception:
        pass
    total = 0.0
    for idx in Q3_HEX_TREE.query(area_shape):
        hex_shape = Q3_HEX_GEOMS[idx]
        if not hex_shape.intersects(area_shape):
            continue
        try:
            inter = hex_shape.intersection(area_shape)
            if inter.is_empty:
                continue
            overlap = max(0.0, inter.area / max(hex_shape.area, 1e-12))
        except Exception:
            overlap = 1.0 if area_shape.contains(hex_shape.representative_point()) else 0.0
        if overlap >= 0.25:
            total += float(Q3_HEX_RECORDS[idx].get("q3_and_below_property_count", 0) or 0)
    return total

def _json_or_default(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _city_catchment_data_dir(city_id):
    city_id = validate_portal_city(city_id)
    generated = CITY_LEGACY_DATA_DIR / city_id
    if (generated / "hexes.geojson").is_file():
        return generated
    if city_id == LEGACY_CATCHMENT_CITY_ID:
        return DATA_DIR
    raise FileNotFoundError(f"Generated catchment bundle is unavailable for {city_id}")


def load_catchment_data(city_id=LEGACY_CATCHMENT_CITY_ID):
    global HEXES, SOCIETIES, HOSPITALS, SEZ_ZONES, OFFICES, MASTER_HEXES, METRO_STATIONS, SOCIETY_HEX_METRICS, Q3_HEX_RECORDS, MARKET_DATA
    global HEX_TO_SOCIETIES, HEX_TO_HOSPITALS, HEX_TO_OFFICES, ACTIVE_CATCHMENT_CITY_ID
    global HEX_LOOKUP, HEX_GEOMS, HEX_TREE, Q3_HEX_GEOMS, Q3_HEX_TREE
    city_id = validate_portal_city(city_id)
    if ACTIVE_CATCHMENT_CITY_ID == city_id and HEXES is not None:
        return
    source_dir = _city_catchment_data_dir(city_id)
    print(f"Loading catchment datasets for {city_id} from {source_dir}...")

    HEXES = _json_or_default(source_dir / "hexes.geojson", {"features": []}).get("features", [])
    SOCIETIES = _json_or_default(source_dir / "societies.json", [])
    if isinstance(SOCIETIES, dict):
        SOCIETIES = SOCIETIES.get("societies", [])
    HOSPITALS = _json_or_default(source_dir / "hospitals.json", [])
    if isinstance(HOSPITALS, dict):
        HOSPITALS = HOSPITALS.get("hospitals", [])
    raw_sez = _json_or_default(source_dir / "sez_zones.geojson", {"features": []})
    SEZ_ZONES = raw_sez.get("features", []) if isinstance(raw_sez, dict) else []
    OFFICES = _json_or_default(source_dir / "sez_offices.json", [])
    if isinstance(OFFICES, dict):
        OFFICES = OFFICES.get("offices", [])
    METRO_STATIONS = _json_or_default(
        source_dir / "metro_stations.json",
        _json_or_default(source_dir / "bangalore_metro_stations.json", []),
    )
    raw_society_metrics = _json_or_default(source_dir / "society_hex_metrics.json", {"hexes": []})
    SOCIETY_HEX_METRICS = {
        row["hex_id"]: row for row in raw_society_metrics.get("hexes", []) if row.get("hex_id")
    }
    raw_master = _json_or_default(source_dir / "hexes_master.json", {"hexes": []})
    master_rows = raw_master.get("hexes", []) if isinstance(raw_master, dict) else raw_master
    MASTER_HEXES = {row["hex_id"]: row for row in master_rows if row.get("hex_id")}
    MARKET_DATA = load_market_data(source_dir)

    HEX_LOOKUP = {feature["properties"]["hex_id"]: feature["properties"] for feature in HEXES}
    HEX_GEOMS = []
    valid_features = []
    for feature in HEXES:
        try:
            HEX_GEOMS.append(shape(feature["geometry"]).buffer(0))
            valid_features.append(feature)
        except Exception:
            continue
    HEXES = valid_features
    HEX_TREE = STRtree(HEX_GEOMS)

    def build_lookup(rows):
        lookup = {}
        for row in rows:
            lat = row.get("lat", row.get("latitude"))
            lon = row.get("lon", row.get("longitude"))
            if lat is None or lon is None:
                continue
            try:
                hid = row.get("hex_id") or h3.latlng_to_cell(float(lat), float(lon), 7)
            except (TypeError, ValueError):
                continue
            lookup.setdefault(hid, []).append(row)
        return lookup

    HEX_TO_SOCIETIES = build_lookup(SOCIETIES)
    HEX_TO_HOSPITALS = build_lookup(HOSPITALS)
    HEX_TO_OFFICES = build_lookup(OFFICES)

    raw_q3_hexes = _json_or_default(source_dir / "q3_below_hex_counts.json", {"hexes": []})
    Q3_HEX_RECORDS = raw_q3_hexes.get("hexes", []) if isinstance(raw_q3_hexes, dict) else raw_q3_hexes
    if not Q3_HEX_RECORDS:
        Q3_HEX_RECORDS = [
            {"hex_id": hex_id, "q3_and_below_property_count": props.get("q3_and_below_property_count", 0)}
            for hex_id, props in HEX_LOOKUP.items()
            if props.get("q3_and_below_property_count", 0)
        ]
    Q3_HEX_GEOMS, valid_q3 = [], []
    for row in Q3_HEX_RECORDS:
        try:
            Q3_HEX_GEOMS.append(build_hex_polygon(row["hex_id"]))
            valid_q3.append(row)
        except Exception:
            continue
    Q3_HEX_RECORDS = valid_q3
    Q3_HEX_TREE = STRtree(Q3_HEX_GEOMS)
    ACTIVE_CATCHMENT_CITY_ID = city_id
    print(f"Catchment data ready for {city_id}: {len(HEXES)} H3 cells")

def calculate_metro_score(distance):
    if distance <= 0.5:
        return 100.0
    elif distance <= 1.0:
        return 92.0
    elif distance <= 2.0:
        return 78.0
    elif distance <= 3.5:
        return 62.0
    elif distance <= 5.0:
        return 42.0
    else:
        return round(max(8.0, 35.0 - (distance - 5.0) * 3.5), 2)


def static_metro_response(lat, lon):
    stations = []
    for row in METRO_STATIONS or []:
        station_lat = row.get("lat", row.get("latitude"))
        station_lon = row.get("lon", row.get("longitude"))
        if station_lat is None or station_lon is None:
            continue
        distance = round(haversine_km(lat, lon, float(station_lat), float(station_lon)), 2)
        stations.append({
            "name": row.get("name") or row.get("station_name") or "Metro station",
            "line": row.get("line") or "Metro",
            "distance_km": distance,
            "duration_mins": None,
            "score": calculate_metro_score(distance),
            "routing_method": "static_straight_line",
            "lat": float(station_lat),
            "lon": float(station_lon),
        })
    stations.sort(key=lambda row: (row["distance_km"], row["name"]))
    stations = stations[:3]
    primary = stations[0] if stations else {"name": "Unavailable", "distance_km": None, "score": None}
    return {
        "nearest_station": primary["name"],
        "distance_km": primary["distance_km"],
        "score": primary["score"],
        "stations": stations,
        "warning": "live_metro_routing_unavailable" if stations else "metro_layer_unavailable",
    }

def get_nearest_3_metro_stations(lat, lon, api_key):
    key = get_maps_api_key(api_key)
    if not key:
        return static_metro_response(lat, lon)
    
    # 1. Search for nearby subway stations via Places API
    places_url = "https://places.googleapis.com/v1/places:searchNearby"
    headers_places = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.location"
    }
    payload_places = {
        "includedTypes": ["subway_station"],
        "maxResultCount": 10,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": 15000.0
            }
        }
    }
    
    try:
        response_places = requests.post(places_url, json=payload_places, headers=headers_places, timeout=10)
        response_places.raise_for_status()
    except requests.RequestException:
        return static_metro_response(lat, lon)
    candidates = response_places.json().get("places", [])
    
    if not candidates:
        return {
            "nearest_station": "NA",
            "distance_km": 99.0,
            "score": 0.0,
            "stations": []
        }
        
    # 2. Compute route matrix via Routes API
    routes_url = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
    headers_routes = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "originIndex,destinationIndex,duration,distanceMeters,status"
    }
    destinations = [
        {"waypoint": {"location": {"latLng": {"latitude": c["location"]["latitude"], "longitude": c["location"]["longitude"]}}}}
        for c in candidates
    ]
    payload_routes = {
        "origins": [{"waypoint": {"location": {"latLng": {"latitude": lat, "longitude": lon}}}}],
        "destinations": destinations,
        "travelMode": "DRIVE"
    }
    
    try:
        response_routes = requests.post(routes_url, json=payload_routes, headers=headers_routes, timeout=10)
        response_routes.raise_for_status()
    except requests.RequestException:
        return static_metro_response(lat, lon)
    matrix_rows = response_routes.json()
    
    results = []
    for row in matrix_rows:
        if row.get("originIndex") != 0:
            continue
        dest_idx = int(row.get("destinationIndex", -1))
        if dest_idx < 0 or dest_idx >= len(candidates):
            continue
        cand = candidates[dest_idx]
        dist_m = row.get("distanceMeters")
        dur_s = row.get("duration")
        if dist_m is not None and dist_m >= 0:
            dist_km = round(dist_m / 1000.0, 2)
            if isinstance(dur_s, str) and dur_s.endswith("s"):
                dur_min = round(float(dur_s[:-1]) / 60.0, 1)
            else:
                dur_min = round((dist_km / 20.0) * 60, 1)
            results.append({
                "name": cand["displayName"]["text"],
                "line": "Metro",
                "distance_km": dist_km,
                "duration_mins": dur_min,
                "score": calculate_metro_score(dist_km),
                "routing_method": "google_api",
                "lat": cand["location"]["latitude"],
                "lon": cand["location"]["longitude"]
            })
            
    results.sort(key=lambda x: x["distance_km"])
    stations_out = results[:3]
    
    primary = stations_out[0] if stations_out else {"name": "NA", "distance_km": 99.0, "score": 0.0}
    
    return {
        "nearest_station": primary.get("name", "NA"),
        "distance_km": primary.get("distance_km", 99.0),
        "score": primary.get("score", 0.0),
        "stations": stations_out
    }


def validate_portal_city(value, *, required=False):
    if value in (None, ""):
        if required:
            raise ValueError("city is required")
        return LEGACY_CATCHMENT_CITY_ID
    city = str(value).strip()
    if city not in SUPPORTED_CITY_IDS:
        raise ValueError(f"Unknown canonical city ID: {city}")
    return city


def validate_city_coordinates(city, lat, lon):
    south, west, north, east = CITY_COORDINATE_WINDOWS[city]
    if not (south <= float(lat) <= north and west <= float(lon) <= east):
        raise CatchmentValidationError(f"Origin coordinates are outside the configured {city} market window")
    return float(lat), float(lon)


def reject_fee_thresholds(params):
    forbidden = sorted(
        key for key in params
        if "fee" in str(key).lower() or "threshold" in str(key).lower()
    )
    if forbidden:
        raise CatchmentValidationError(
            "Annual-fee thresholds are unavailable; use a supplied school category bucket"
        )


def unsupported_legacy_city_payload(city):
    return {
        "status": "error",
        "schema_version": SCHEMA_VERSION,
        "error": {
            "code": "city_not_supported_by_legacy_catchment",
            "message": (
                "Catchment calculations are city-scoped across the four supported markets; live routing falls back to a labeled proxy when no provider key is configured."
            ),
        },
        "requested_city_id": city,
        "legacy_catchment_available_city_ids": [LEGACY_CATCHMENT_CITY_ID],
        "warnings": ["legacy_catchment_unavailable_for_city"],
    }


class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def request_path(self):
        return urllib.parse.urlsplit(self.path).path.rstrip("/") or "/"

    def translate_path(self, path):
        # Map URL path to static directory
        clean_path = urllib.parse.unquote(urllib.parse.urlsplit(path).path)
        if clean_path.startswith("/"):
            clean_path = clean_path[1:]
        if not clean_path:
            clean_path = "multicity.html"
        elif clean_path.rstrip("/") == "bangalore":
            clean_path = "index.html"
        elif clean_path.rstrip("/") == "bengaluru":
            clean_path = "index.html"
        elif clean_path.startswith("city/") or clean_path.startswith("cities/"):
            parts = clean_path.rstrip("/").split("/")
            if len(parts) == 2 and parts[1] in SUPPORTED_CITY_IDS:
                clean_path = "multicity.html"
            else:
                clean_path = "__invalid_path__"
        candidate = (STATIC_DIR / clean_path).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            # Translate traversal attempts to a guaranteed-missing static path.
            candidate = STATIC_DIR / "__invalid_path__"
        return str(candidate)

    def do_GET(self):
        route = self.request_path()
        if route == "/api/auth":
            AuthHandler.do_GET(self)
        elif route in {"/city/pune", "/cities/pune"}:
            self.send_response(308)
            self.send_header("Location", "/")
            self.end_headers()
        elif (route.startswith("/data/") or route.startswith("/reports/")) and not is_authorized(self.headers):
            self.send_json_response(
                {"status": "error", "error": "authentication_required"},
                401,
            )
        elif route.startswith("/api/") and not is_authorized(self.headers):
            self.send_json_response(
                {"status": "error", "error": "authentication_required"},
                401,
            )
        elif route == "/api/catchment":
            self.handle_catchment()
        elif route == "/api/listings":
            ListingsHandler.do_GET(self)
        elif route == "/api/multicity":
            MulticityHandler.do_GET(self)
        else:
            super().do_GET()

    def do_POST(self):
        route = self.request_path()
        if route == "/api/auth":
            AuthHandler.do_POST(self)
        elif route.startswith("/api/") and not is_authorized(self.headers):
            self.send_json_response(
                {"status": "error", "error": "authentication_required"},
                401,
            )
        elif route == "/api/listings":
            ListingsHandler.do_POST(self)
        elif route == "/api/catchment":
            self.handle_catchment_portfolio()
        elif route == "/api/multicity":
            MulticityHandler.do_POST(self)
        else:
            super().do_POST()

    def do_DELETE(self):
        if not is_authorized(self.headers):
            self.send_json_response(
                {"status": "error", "error": "authentication_required"},
                401,
            )
        elif self.request_path() == "/api/listings":
            ListingsHandler.do_DELETE(self)
        else:
            super().do_DELETE()

    def do_OPTIONS(self):
        route = self.request_path()
        if route == "/api/auth":
            AuthHandler.do_OPTIONS(self)
        elif route == "/api/listings":
            ListingsHandler.do_OPTIONS(self)
        elif route == "/api/multicity":
            MulticityHandler.do_OPTIONS(self)
        elif route == "/api/catchment":
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
        else:
            super().do_OPTIONS()

    def send_json_response(self, data, status_code=200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _send_json(self, payload, status=200, cookie=None):
        AuthHandler._send_json(self, payload, status, cookie)

    def send_json(self, payload, status=200):
        MulticityHandler.send_json(self, payload, status)

    def handle_catchment(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            city = validate_portal_city(params.get("city", [None])[0])
            reject_fee_thresholds(params)
            category = params.get("category", ["premium_plus"])[0]
            if category not in {"super_premium", "premium", "affordable", "budget", "premium_plus", "affordable_plus", "all_private"}:
                raise CatchmentValidationError("Unknown school category")
            load_catchment_data(city)
            lat = float(params.get("lat", [0])[0])
            lon = float(params.get("lon", [0])[0])
            lat, lon = validate_city_coordinates(city, lat, lon)
            radius = float(params.get("radius", [7.0])[0])
            travel_time_mins = params.get("travel_time_mins", [None])[0]
            travel_speed_kmh = params.get("travel_speed_kmh", [None])[0]
            travel_mode = params.get("travel_mode", ["DRIVE"])[0]
            live_traffic = params.get("live_traffic", ["true"])[0]
            smooth_edges = params.get("smooth_edges", ["true"])[0]
            include_bands = params.get("include_bands", ["false"])[0].lower() == "true"
            catchment_mode = params.get("catchment_mode", ["time"])[0]
            lat, lon, travel_time_mins = validate_live_request(
                lat=lat, lon=lon, catchment_mode=catchment_mode,
                travel_mode=travel_mode, live_traffic=live_traffic,
                duration=travel_time_mins,
            )
            market_options = parse_market_options(params)
            market_options["fee_sensitivity_thresholds"] = []
            market_options["category"] = category
            result = self.calculate_catchment(
                lat, lon, radius, None,
                travel_time_mins=travel_time_mins,
                travel_speed_kmh=travel_speed_kmh,
                travel_mode="DRIVE", live_traffic="true",
                smooth_edges=smooth_edges, catchment_mode="time",
                market_options=market_options,
                include_bands=include_bands,
            )
            result["canonical_city_id"] = city
            result["category_id"] = category
            result["warnings"] = sorted(set(result.get("warnings", []) + ["bucket_based_school_market", "annual_fee_filter_unavailable"]))
            self.send_json_response(result)
        except (CatchmentValidationError, CatchmentProviderError, CatchmentConfigurationError) as exc:
            self.send_json_response(error_payload(exc), exc.status_code)
        except (ValueError, TypeError) as exc:
            wrapped = CatchmentValidationError(f"Invalid catchment request: {exc}")
            self.send_json_response(error_payload(wrapped), wrapped.status_code)
        except Exception as exc:
            print(f"Catchment request failed: {exc}")
            self.send_json_response({
                "status": "error", "schema_version": SCHEMA_VERSION,
                "message": "Catchment calculation failed",
                "error": {"code": "internal_error", "message": "Catchment calculation failed"},
            }, 500)

    def handle_catchment_portfolio(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise CatchmentValidationError("portfolio body must be between 1 byte and 1 MB")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            city = validate_portal_city(payload.get("city"))
            reject_fee_thresholds(payload)
            category = payload.get("category", "premium_plus")
            if category not in {"super_premium", "premium", "affordable", "budget", "premium_plus", "affordable_plus", "all_private"}:
                raise CatchmentValidationError("Unknown school category")
            load_catchment_data(city)
            market_options = parse_market_options_payload(payload)
            market_options["fee_sensitivity_thresholds"] = []
            market_options["category"] = category
            center_results = payload.get("center_results")
            if center_results is None:
                centers = payload.get("centers")
                if not isinstance(centers, list) or not centers:
                    raise CatchmentValidationError("centers must contain at least one origin")
                if len(centers) > 10:
                    raise CatchmentValidationError("portfolio accepts at most 10 centers")
                center_results = []
                for index, center in enumerate(centers):
                    if not isinstance(center, dict):
                        raise CatchmentValidationError("each center must be an object")
                    duration = center.get("travel_time_mins", payload.get("travel_time_mins", 30))
                    lat, lon, duration = validate_live_request(
                        lat=center.get("lat"), lon=center.get("lon"), catchment_mode="time",
                        travel_mode="DRIVE", live_traffic="true", duration=duration,
                    )
                    lat, lon = validate_city_coordinates(city, lat, lon)
                    result = self.calculate_catchment(
                        lat, lon, 7.0, None, travel_time_mins=duration,
                        travel_mode="DRIVE", live_traffic="true", catchment_mode="time",
                        market_options=market_options, include_bands=False,
                    )
                    result["center_id"] = str(center.get("id") or f"center-{index + 1}")
                    center_results.append(result)
            portfolio = build_portfolio_result(center_results, market_options)
            self.send_json_response({
                "status": "success", "schema_version": SCHEMA_VERSION,
                "canonical_city_id": city,
                "category_id": category,
                "warnings": ["bucket_based_school_market", "annual_fee_filter_unavailable"],
                "data_revision": MARKET_DATA.get("data_revision"), "portfolio": portfolio,
            })
        except (CatchmentValidationError, CatchmentProviderError, CatchmentConfigurationError) as exc:
            self.send_json_response(error_payload(exc), exc.status_code)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            wrapped = CatchmentValidationError(f"Invalid portfolio request: {exc}")
            self.send_json_response(error_payload(wrapped), wrapped.status_code)
        except Exception as exc:
            print(f"Portfolio request failed: {exc}")
            self.send_json_response({
                "status": "error", "schema_version": SCHEMA_VERSION,
                "message": "Portfolio calculation failed",
                "error": {"code": "internal_error", "message": "Portfolio calculation failed"},
            }, 500)

    def calculate_catchment(self, lat, lon, radius_km, api_key, travel_time_mins=None, travel_speed_kmh=None, travel_mode="DRIVE", live_traffic="true", smooth_edges="true", catchment_mode="distance", market_options=None, include_bands=False):
        key = get_maps_api_key(api_key)
        market_options = market_options or parse_market_options({})
        routing_method = "google"
        isochrone_geojson = None
        matched_hex_ids = []
        matched_weights = {}
        isochrone_geometries = {}

        if catchment_mode == "time" and travel_time_mins is not None:
            try:
                time_mins = max(1.0, float(travel_time_mins))
            except (TypeError, ValueError):
                time_mins = 15.0
            try:
                speed_kmh = max(1.0, float(travel_speed_kmh or 20.0))
            except (TypeError, ValueError):
                speed_kmh = 20.0
            radius_km = max(1.0, round(speed_kmh * (time_mins / 60.0), 1))
        else:
            time_mins = None
            speed_kmh = None

        r_list = sorted(list(set([r for r in [radius_km - 1.0, radius_km, radius_km + 1.0, radius_km + 2.0] if r >= 1.0])))
        comparison_data = []

        try:
            if catchment_mode != "time" or time_mins is None:
                raise RuntimeError("Google isochrones require time mode")
            
            step_results = {}
            requested_steps = [15, 30, 45, 60] if include_bands else [int(round(time_mins))]
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(requested_steps)) as executor:
                future_to_mins = {
                    executor.submit(_google_isochrone_request, lat, lon, step_mins, travel_mode, live_traffic, smooth_edges, key): step_mins
                    for step_mins in requested_steps
                }
                for future in concurrent.futures.as_completed(future_to_mins):
                    step_mins = future_to_mins[future]
                    step_results[step_mins] = future.result()

            selected_geo = step_results[int(round(time_mins))]
            geometry = _parse_google_isochrone_geometry(selected_geo)
            if not geometry:
                raise RuntimeError("No geometry returned in Google isochrone response")
            isochrone_geojson = geometry
            comparison_data = []
            matched_hex_ids = []
            matched_weights = {}
            hex_min_time = {}
            isochrone_cache = {}
            
            for step_mins in requested_steps:
                step_geo = step_results[step_mins]
                step_geometry = _parse_google_isochrone_geometry(step_geo)
                isochrone_geometries[str(step_mins)] = step_geometry
                isochrone_cache[str(step_mins)] = step_geo.get("cache", {})
                step_shape = shape(step_geometry) if step_geometry else None
                if step_shape is None:
                    continue
                try:
                    step_shape = step_shape.buffer(0)
                except Exception:
                    pass
                
                step_hex_ids = []
                # Fast spatial query
                possible_indices = HEX_TREE.query(step_shape)
                for idx in possible_indices:
                    hex_shape = HEX_GEOMS[idx]
                    props = HEXES[idx]["properties"]
                    if not hex_shape.intersects(step_shape):
                        continue
                    try:
                        inter = hex_shape.intersection(step_shape)
                        if inter.is_empty:
                            continue
                        overlap = max(0.0, inter.area / max(hex_shape.area, 1e-12))
                    except Exception:
                        overlap = 1.0 if step_shape.contains(hex_shape.representative_point()) else 0.0
                    
                    if overlap >= 0.25:
                        step_hex_ids.append(props["hex_id"])
                        if props["hex_id"] not in hex_min_time:
                            hex_min_time[props["hex_id"]] = step_mins
                            
                        if step_mins == int(round(time_mins)):
                            matched_hex_ids.append(props["hex_id"])
                            matched_weights[props["hex_id"]] = 1.0
                            
                comparison_data.append({
                    "radius": round(max(1.0, radius_km * (step_mins / max(time_mins, 1.0))), 1),
                    "time_mins": step_mins,
                    "hex_count": len(step_hex_ids),
                    "matched_hex_ids": step_hex_ids,
                    "family_tam": round(sum(HEX_LOOKUP[h_id].get("countable_family_tam", 0) for h_id in step_hex_ids), 2),
                    "direct_total_units": round(sum(HEX_LOOKUP[h_id].get("direct_total_units", 0) for h_id in step_hex_ids), 2),
                    "society_count": sum(len(HEX_TO_SOCIETIES.get(h_id, [])) for h_id in step_hex_ids),
                    "hospital_count": sum(len(HEX_TO_HOSPITALS.get(h_id, [])) for h_id in step_hex_ids),
                    "office_count": sum(len(HEX_TO_OFFICES.get(h_id, [])) for h_id in step_hex_ids),
                    "q3_and_below_property_count": round(sum_q3_below_for_geometry(step_shape), 2),
                })
            selected_cache = isochrone_cache.get(str(int(round(time_mins))), {})
            routing_method = selected_cache.get("provider") or "google_isochrone"
        except (CatchmentProviderError, CatchmentConfigurationError, CatchmentValidationError):
            raise
        except Exception as e:
            print(f"Isochrone API call failed: {e}.")
            raise CatchmentProviderError(f"Google live isochrone request failed: {e}") from e

        if not comparison_data:
            raise CatchmentProviderError("Google live isochrone request returned no usable geometry")

        matched_set = set(hex_min_time.keys())

        agg = {
            "countable_family_tam": 0.0,
            "direct_family_tam": 0.0,
            "direct_total_units": 0.0,
            "q3_and_below_property_count": 0.0,
            "society_count": 0,
            "gated_community_count": 0,
            "q4_premium_evidence_count": 0,
            "full_only_99acres_society_count": 0,
            "full_family_proxy": 0.0,
            "q4_units_proxy": 0.0,
            "q4_family_proxy": 0.0,
            "full_only_99acres_units_proxy": 0.0,
            "full_only_99acres_family_proxy": 0.0,
            "hospital_count": 0,
            "sez_office_spaces": 0
        }
        full_society_metrics = {
            "full_society_count": 0,
            "full_residential_units_proxy": 0.0,
            "full_family_proxy": 0.0,
            "non_premium_family_proxy": 0.0,
            "premium_society_count": 0,
            "premium_family_tam": 0.0
        }
        
        income_bands = {15: {}, 30: {}, 45: {}, 60: {}}
        for b in [15, 30, 45, 60]:
            income_bands[b] = {
                "1.5Cr+": 0.0,
                "60L-1.5Cr": 0.0,
                "30L-60L": 0.0,
                "15L-30L": 0.0,
                "8L-15L": 0.0
            }

        for hid in matched_set:
            h_props = HEX_LOOKUP.get(hid, {})
            if not h_props:
                continue
            
            # Global Aggregations (Optional, keeping for legacy compatibility if needed)
            agg["countable_family_tam"] += h_props.get("countable_family_tam", 0.0)
            agg["direct_family_tam"] += h_props.get("direct_family_tam", 0.0)
            agg["direct_total_units"] += h_props.get("direct_total_units", 0.0)
            band_time = hex_min_time.get(hid, 60)
            
            if hid in MASTER_HEXES:
                rec = MASTER_HEXES[hid]
                tam_sec = rec.get("tam", {})
                band_values = tam_sec.get("income_band_family_tam", {}) or rec.get("income_bands", {})
                for band, val in band_values.items():
                    for t in [15, 30, 45, 60]:
                        if band_time <= t:
                            if band in income_bands[t]:
                                income_bands[t][band] += val.get("direct", 0.0) if isinstance(val, dict) else (val or 0.0)
            
            if hid in SOCIETY_HEX_METRICS:
                rec = SOCIETY_HEX_METRICS[hid]
                for key in full_society_metrics:
                    full_society_metrics[key] += rec.get(key, 0.0)

        # Societies
        matched_societies = []
        for h_id in matched_set:
            for soc in HEX_TO_SOCIETIES.get(h_id, []):
                s_copy = soc.copy()
                s_copy["time_mins"] = hex_min_time.get(h_id, 60)
                matched_societies.append(s_copy)
        agg["society_count"] = len(matched_societies)
        full_society_metrics["full_society_count"] = len(matched_societies)
        full_society_metrics["full_residential_units_proxy"] = sum(float(row.get("units", 0) or 0) for row in matched_societies)
        full_society_metrics["full_family_proxy"] = sum(float(row.get("tam", row.get("family_proxy", 0)) or 0) for row in matched_societies)
        full_society_metrics["premium_society_count"] = sum(row.get("category") in {"Luxury", "Super Luxury", "Ultra Luxury"} for row in matched_societies)
        full_society_metrics["premium_family_tam"] = sum(
            float(row.get("tam", row.get("family_proxy", 0)) or 0)
            for row in matched_societies
            if row.get("category") in {"Luxury", "Super Luxury", "Ultra Luxury"}
        )
        matched_societies.sort(key=lambda s: s.get("tam", 0), reverse=True)

        # Hospitals
        matched_hospitals = []
        for h_id in matched_set:
            for hosp in HEX_TO_HOSPITALS.get(h_id, []):
                h_copy = hosp.copy()
                h_copy["time_mins"] = hex_min_time.get(h_id, 60)
                matched_hospitals.append(h_copy)
        agg["hospital_count"] = len(matched_hospitals)
        matched_hospitals.sort(key=lambda h: (h.get("beds", 0), h.get("rating", 0)), reverse=True)

        # Offices
        matched_offices = []
        for h_id in matched_set:
            for off in HEX_TO_OFFICES.get(h_id, []):
                o_copy = off.copy()
                o_copy["time_mins"] = hex_min_time.get(h_id, 60)
                matched_offices.append(o_copy)
        agg["office_count"] = len(matched_offices)
        matched_offices.sort(key=lambda o: o.get("office_rank_score", 0), reverse=True)

        for k in [
            "countable_family_tam",
            "direct_family_tam",
            "direct_total_units",
            "q3_and_below_property_count",
            "full_family_proxy",
            "q4_units_proxy",
            "q4_family_proxy",
            "full_only_99acres_units_proxy",
            "full_only_99acres_family_proxy",
        ]:
            agg[k] = round(agg[k], 2)

        selected_geometry = isochrone_geometries.get(str(int(round(time_mins)))) or isochrone_geojson
        if selected_geometry:
            agg["q3_and_below_property_count"] = round(sum_q3_below_for_geometry(shape(selected_geometry)), 2)
        if selected_geometry:
            agg["q3_and_below_property_count"] = round(
                sum_q3_below_for_geometry(shape(selected_geometry)),
                2,
            )
            
         # Round income bands
        for tb in income_bands:
            for k in income_bands[tb]:
                income_bands[tb][k] = round(income_bands[tb][k], 2)
        for k in full_society_metrics:
            full_society_metrics[k] = round(full_society_metrics[k], 2)

        metro_data = get_nearest_3_metro_stations(lat, lon, api_key)

        selected_market = build_market_ledger(
            geometry=selected_geometry,
            center_lat=lat,
            center_lon=lon,
            market_data=MARKET_DATA,
            options=market_options,
        )
        for row in comparison_data:
            band_geometry = isochrone_geometries.get(str(int(row["time_mins"])))
            if not band_geometry:
                continue
            band_market = build_market_ledger(
                geometry=band_geometry,
                center_lat=lat,
                center_lon=lon,
                market_data=MARKET_DATA,
                options=market_options,
            )
            row["school_market"] = {
                "direct": band_market["school_market"]["direct"],
                "reachable": band_market["school_market"]["reachable"],
            }
            row["residential_market"] = band_market["residential_market"]["inside_isochrone"]

        return {
            "status": "success",
            "schema_version": SCHEMA_VERSION,
            "data_revision": MARKET_DATA.get("data_revision"),
            "routing_method": routing_method,
            "routing": {
                "provider": routing_method,
                "mode": "DRIVE",
                "traffic": "LIVE" if routing_method == "google_isochrone" else "PROXY",
                "duration_mins": int(time_mins),
                "cache": isochrone_cache.get(str(int(time_mins)), {}),
            },
            "radius_km": radius_km,
            "travel_time_mins": time_mins,
            "travel_speed_kmh": speed_kmh,
            "catchment_mode": catchment_mode,
            "live_traffic": live_traffic,
            "center": {"lat": lat, "lon": lon},
            "hex_min_time": hex_min_time,
            "matched_hex_ids": list(hex_min_time.keys()),
            "isochrone_geojson": isochrone_geojson,
            "isochrone_geometries": isochrone_geometries,
            "metrics": agg,
            "geography": selected_market["geography"],
            "school_market": selected_market["school_market"],
            "residential_market": selected_market["residential_market"],
            "capacity": selected_market["capacity"],
            "full_society_metrics": full_society_metrics,
            "income_bands": income_bands,
            "societies": matched_societies[:500],
            "hospitals": matched_hospitals[:500],
            "offices": matched_offices[:500],
            "comparison": comparison_data,
            "metro": metro_data
        }

def start_server():
    load_catchment_data()
    
    # Configure socket server reuse
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), CustomHandler) as httpd:
        print(f"============================================================")
        print(f"RanchoLabs Multi-City Platform Server is running at:")
        print(f"http://localhost:{PORT}")
        print(f"============================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")

if __name__ == "__main__":
    start_server()
