import json
import urllib.parse
import math
import os
from pathlib import Path
import requests
import h3
from shapely.geometry import Point, shape, Polygon as ShapelyPolygon, mapping
from shapely.ops import unary_union
from shapely.strtree import STRtree
import concurrent.futures
import threading
from http.server import BaseHTTPRequestHandler

try:
    from portal_auth import is_authorized
except ImportError:  # pragma: no cover - package import in tests/tooling
    from src.portal_auth import is_authorized

try:
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
        validate_catchment_city,
        validate_city_coordinates,
        validate_google_maps_api_key,
        validate_live_request,
    )
except ImportError:  # pragma: no cover - package import in tests/tooling
    from src.catchment_market import (
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
        validate_catchment_city,
        validate_city_coordinates,
        validate_google_maps_api_key,
        validate_live_request,
    )

# Setup Paths
SERVER_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SERVER_DIR / "runtime_data" / "catchment"

# Global cache for data
HEXES = None
SOCIETIES = None
HOSPITALS = None
SEZ_ZONES = None
OFFICES = None
MASTER_HEXES = None
METRO_STATIONS = None
Q3_HEX_RECORDS = None
MARKET_DATA = None
LOADED_CITY_ID = None
_DATA_LOAD_LOCK = threading.Lock()

# Spatial Indexing and O(1) Lookups
HEX_LOOKUP = None
HEX_GEOMS = None
HEX_TREE = None
Q3_HEX_GEOMS = None
Q3_HEX_TREE = None
HEX_TO_SOCIETIES = None
HEX_TO_HOSPITALS = None
HEX_TO_OFFICES = None

def fill_polygon_holes(geojson):
    """Remove interior holes from a GeoJSON Polygon or MultiPolygon.
    Uses a slight outward buffer to merge thin slivers, then reconstructs
    shapes using only exterior rings — eliminating lake/river cutouts."""
    if not geojson or not isinstance(geojson, dict):
        return geojson
    try:
        geom = shape(geojson)
        # buffer(0) fixes self-intersections without changing shape
        geom = geom.buffer(0)
        if geom.is_empty:
            return geojson

        # Tiny outward then inward buffer to close micro-gaps between adjacent polys
        geom = geom.buffer(0.0001).buffer(-0.0001)

        if geom.geom_type == 'Polygon':
            # Re-create from exterior only — drops all interior holes
            filled = ShapelyPolygon(geom.exterior.coords)
            return mapping(filled)
        elif geom.geom_type == 'MultiPolygon':
            # For each sub-polygon keep only its exterior (no holes)
            filled_parts = [ShapelyPolygon(p.exterior.coords) for p in geom.geoms if not p.is_empty]
            if not filled_parts:
                return geojson
            # Merge adjacent fragments that the buffer closed together
            merged = unary_union(filled_parts)
            # Final pass: strip any holes that unary_union reintroduced
            if merged.geom_type == 'Polygon':
                merged = ShapelyPolygon(merged.exterior.coords)
            elif merged.geom_type == 'MultiPolygon':
                merged = unary_union([ShapelyPolygon(p.exterior.coords) for p in merged.geoms])
            return mapping(merged)
    except Exception as e:
        print(f"fill_polygon_holes: could not fill holes: {e}")
    return geojson

def _get_maps_api_key(api_key):
    """Prefer a validated request-scoped key, then use server configuration."""
    if api_key is not None:
        return google_maps_api_key(api_key)
    try:
        return google_maps_api_key()
    except CatchmentConfigurationError:
        return ""


def _request_maps_api_key(headers):
    """Read the only supported client-key transport without retaining it."""
    value = headers.get("X-Google-Maps-Api-Key")
    return validate_google_maps_api_key(value) if value is not None else None


def _reject_query_api_keys(params):
    forbidden = {"api_key", "google_maps_api_key", "googleMapsApiKey", "google_api_key"}
    if forbidden.intersection(params):
        raise CatchmentValidationError(
            "Google Maps API keys must be sent in X-Google-Maps-Api-Key"
        )

def _parse_google_isochrone_geometry(geo):
    if not isinstance(geo, dict):
        return None
    iso = geo.get("isochrone")
    if isinstance(iso, dict):
        geojson = iso.get("geoJson") or iso.get("geojson") or iso.get("geometry")
        if geojson:
            return geojson
    return geo.get("geometry") or geo.get("polygon") or geo.get("boundary")

def _google_route_matrix_duration_minutes(lat, lon, dest_points, api_key, departure_time="now"):
    if not dest_points:
        return []
    url = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "originIndex,destinationIndex,duration,distanceMeters,status"
    }
    origins = [{"waypoint": {"location": {"latLng": {"latitude": lat, "longitude": lon}}}}]
    durations = [None] * len(dest_points)
    batch_size = 25
    for start in range(0, len(dest_points), batch_size):
        batch = dest_points[start:start + batch_size]
        destinations = [
            {"waypoint": {"location": {"latLng": {"latitude": d["lat"], "longitude": d["lon"]}}}}
            for d in batch
        ]
        payload = {
            "origins": origins,
            "destinations": destinations,
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "departureTime": departure_time
        }
        res = requests.post(url, json=payload, headers=headers, timeout=45)
        res.raise_for_status()
        rows = res.json()
        if not isinstance(rows, list):
            continue
        for row in rows:
            if row.get("originIndex") != 0:
                continue
            idx = start + int(row.get("destinationIndex", -1))
            dur = row.get("duration")
            if isinstance(dur, str) and dur.endswith("s"):
                try:
                    durations[idx] = float(dur[:-1]) / 60.0
                except ValueError:
                    pass
    return durations

def _build_google_time_catchment(
    lat, lon, time_mins, radius_km, api_key, travel_mode="DRIVE",
    live_traffic="true", smooth_edges="true", include_bands=False,
    strict_provider=False,
):
    global HEXES, HEX_LOOKUP, HEX_GEOMS, HEX_TREE
    
    def fetch_isochrone(step_mins):
        geometry, cache = get_live_drive_isochrone(
            lat, lon, step_mins,
            smooth_edges=str(smooth_edges).lower() == "true",
            api_key=api_key,
            strict=strict_provider,
        )
        return {"geometry": geometry, "cache": cache}

    step_results = {}
    requested_steps = [15, 30, 45, 60] if include_bands else [int(round(time_mins))]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(requested_steps)) as executor:
        future_to_mins = {
            executor.submit(fetch_isochrone, step_mins): step_mins
            for step_mins in requested_steps
        }
        for future in concurrent.futures.as_completed(future_to_mins):
            step_mins = future_to_mins[future]
            step_results[step_mins] = future.result()

    selected_geo = step_results[int(round(time_mins))]
    isochrone_geojson = _parse_google_isochrone_geometry(selected_geo)
    
    comparison_data = []
    matched_hex_ids = []
    matched_weights = {}
    hex_min_time = {}
    
    isochrone_geometries = {}
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

    return hex_min_time, list(hex_min_time.keys()), comparison_data, isochrone_geojson, matched_weights, isochrone_geometries, isochrone_cache

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def build_hex_polygon(hex_id):
    boundary = h3.cell_to_boundary(hex_id)
    return ShapelyPolygon([(lon, lat) for lat, lon in boundary]).buffer(0)

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

def _city_data_dir(city_id):
    city_id = validate_catchment_city(city_id)
    candidate = (DATA_DIR / city_id).resolve()
    try:
        candidate.relative_to(DATA_DIR.resolve())
    except ValueError as exc:  # defensive; validation already rejects separators
        raise CatchmentValidationError("invalid city data path") from exc
    if not candidate.is_dir():
        raise CatchmentConfigurationError(f"Catchment runtime data is unavailable for {city_id}")
    return candidate


def load_catchment_data(city_id="bengaluru", host=None):
    global HEXES, SOCIETIES, HOSPITALS, SEZ_ZONES, OFFICES, MASTER_HEXES, METRO_STATIONS, Q3_HEX_RECORDS, MARKET_DATA, LOADED_CITY_ID
    global HEX_TO_SOCIETIES, HEX_TO_HOSPITALS, HEX_TO_OFFICES
    global HEX_LOOKUP, HEX_GEOMS, HEX_TREE, Q3_HEX_GEOMS, Q3_HEX_TREE
    city_id = validate_catchment_city(city_id)
    with _DATA_LOAD_LOCK:
        if LOADED_CITY_ID == city_id and HEXES is not None and HEX_TREE is not None:
            return
        source_dir = _city_data_dir(city_id)
        try:
            with open(source_dir / "hexes.geojson", "r") as f:
                HEXES = json.load(f)["features"]
            societies_path = source_dir / "societies.json"
            with open(societies_path, "r") as f:
                SOCIETIES = json.load(f)
            MARKET_DATA = load_market_data(source_dir, city_id=city_id)
            with open(source_dir / "hospitals.json", "r") as f:
                HOSPITALS = json.load(f)
            with open(source_dir / "sez_zones.geojson", "r") as f:
                SEZ_ZONES = json.load(f)["features"]
            with open(source_dir / "sez_offices.json", "r") as f:
                OFFICES = json.load(f)
            metro_path = source_dir / "metro_stations.json"
            if not metro_path.exists():
                metro_path = source_dir / "bangalore_metro_stations.json"
            METRO_STATIONS = json.loads(metro_path.read_text(encoding="utf-8")) if metro_path.exists() else []
            master_path = source_dir / "hexes_master.json"
            if master_path.exists():
                with open(master_path, "r") as f:
                    raw_master = json.load(f)
                    if isinstance(raw_master, dict) and "hexes" in raw_master:
                        MASTER_HEXES = {r["hex_id"]: r for r in raw_master["hexes"]}
                    else:
                        MASTER_HEXES = {r["hex_id"]: r for r in raw_master}
            else:
                MASTER_HEXES = {}

            HEX_LOOKUP = {f["properties"]["hex_id"]: f["properties"] for f in HEXES}
            HEX_GEOMS = []
            for f in HEXES:
                try:
                    g = shape(f["geometry"]).buffer(0)
                except Exception:
                    g = shape(f["geometry"])
                HEX_GEOMS.append(g)

            HEX_TO_SOCIETIES = {}
            for soc in SOCIETIES:
                hid = soc.get("hex_id") or h3.latlng_to_cell(soc["lat"], soc["lon"], 7)
                HEX_TO_SOCIETIES.setdefault(hid, []).append(soc)

            HEX_TO_HOSPITALS = {}
            for hosp in HOSPITALS:
                hid = hosp.get("hex_id") or h3.latlng_to_cell(hosp["lat"], hosp["lon"], 7)
                HEX_TO_HOSPITALS.setdefault(hid, []).append(hosp)

            HEX_TO_OFFICES = {}
            for off in OFFICES:
                if "lat" in off and "lon" in off:
                    hid = off.get("hex_id") or h3.latlng_to_cell(off["lat"], off["lon"], 7)
                    HEX_TO_OFFICES.setdefault(hid, []).append(off)

            q3_hex_path = source_dir / "q3_below_hex_counts.json"
            if q3_hex_path.exists():
                with open(q3_hex_path, "r") as f:
                    raw_q3_hexes = json.load(f)
                Q3_HEX_RECORDS = raw_q3_hexes.get("hexes", []) if isinstance(raw_q3_hexes, dict) else raw_q3_hexes
            else:
                Q3_HEX_RECORDS = [
                    {"hex_id": hex_id, "q3_and_below_property_count": props.get("q3_and_below_property_count", 0)}
                    for hex_id, props in HEX_LOOKUP.items()
                    if props.get("q3_and_below_property_count", 0)
                ]
            Q3_HEX_GEOMS = []
            filtered_q3_records = []
            for row in Q3_HEX_RECORDS:
                hex_id = row.get("hex_id")
                if not hex_id:
                    continue
                try:
                    Q3_HEX_GEOMS.append(build_hex_polygon(hex_id))
                    filtered_q3_records.append(row)
                except Exception:
                    continue
            Q3_HEX_RECORDS = filtered_q3_records

            HEX_TREE = STRtree(HEX_GEOMS)
            Q3_HEX_TREE = STRtree(Q3_HEX_GEOMS)
            LOADED_CITY_ID = city_id
            return
        except (CatchmentConfigurationError, CatchmentValidationError):
            raise
        except Exception as exc:
            LOADED_CITY_ID = None
            raise CatchmentConfigurationError(
                f"Catchment runtime data could not be loaded for {city_id}"
            ) from exc

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

def get_nearest_3_metro_stations(lat, lon, api_key):
    """
    Find the 3 nearest Namma Metro stations using our local station dataset
    for accurate station locations, then compute real walk distances via the
    Google Routes API (WALK mode, not DRIVE).

    Strategy:
    1. Pre-rank all local stations by straight-line Haversine distance.
    2. Take the top 8 candidates (avoids wasting API quota on faraway stations).
    3. Call Google Routes Matrix (WALK) to get real pedestrian distance + time.
    4. Sort by walk distance, return top 3.
    5. If Routes API fails, fall back to Haversine straight-line estimates.
    """
    key = _get_maps_api_key(api_key)

    # --- Step 1: rank by straight-line distance using local data ---
    if not METRO_STATIONS:
        return {"nearest_station": "NA", "distance_km": 99.0, "score": 0.0, "stations": []}

    candidates_hl = []
    for st in METRO_STATIONS:
        st_lat = st.get("latitude") or st.get("lat")
        st_lon = st.get("longitude") or st.get("lon")
        if st_lat is None or st_lon is None:
            continue
        dist_km = haversine_km(lat, lon, float(st_lat), float(st_lon))
        candidates_hl.append({
            "name": st.get("name", "Unknown Station"),
            "line": st.get("line", "Namma Metro"),
            "lat": float(st_lat),
            "lon": float(st_lon),
            "hl_dist_km": dist_km
        })

    candidates_hl.sort(key=lambda x: x["hl_dist_km"])
    top_candidates = candidates_hl[:8]  # only route-matrix the 8 closest

    # --- Step 2: Google Routes API (WALK mode) for accurate pedestrian distance ---
    results = []
    try:
        routes_url = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
        headers_routes = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": "originIndex,destinationIndex,duration,distanceMeters,status"
        }
        destinations = [
            {"waypoint": {"location": {"latLng": {"latitude": c["lat"], "longitude": c["lon"]}}}}
            for c in top_candidates
        ]
        payload_routes = {
            "origins": [{"waypoint": {"location": {"latLng": {"latitude": lat, "longitude": lon}}}}],
            "destinations": destinations,
            "travelMode": "WALK"  # walk, not drive — metro access is pedestrian
        }
        resp = requests.post(routes_url, json=payload_routes, headers=headers_routes, timeout=10)
        resp.raise_for_status()
        matrix_rows = resp.json()

        for row in matrix_rows:
            if row.get("originIndex") != 0:
                continue
            dest_idx = int(row.get("destinationIndex", -1))
            if dest_idx < 0 or dest_idx >= len(top_candidates):
                continue
            cand = top_candidates[dest_idx]
            dist_m = row.get("distanceMeters")
            dur_s = row.get("duration")
            status = row.get("status", {})
            # Skip rows where routing failed (e.g. no walkable path found)
            if status and status.get("code", 0) != 0:
                continue
            if dist_m is not None and dist_m >= 0:
                dist_km = round(dist_m / 1000.0, 2)
                if isinstance(dur_s, str) and dur_s.endswith("s"):
                    dur_min = round(float(dur_s[:-1]) / 60.0, 1)
                else:
                    # 5 km/h walking speed fallback
                    dur_min = round((dist_km / 5.0) * 60.0, 1)
                results.append({
                    "name": cand["name"],
                    "line": cand["line"],
                    "distance_km": dist_km,
                    "duration_mins": dur_min,
                    "score": calculate_metro_score(dist_km),
                    "routing_method": "google_walk",
                    "lat": cand["lat"],
                    "lon": cand["lon"]
                })
    except Exception:
        # Provider exception text can contain request metadata. Keep the log
        # deliberately generic because a request-scoped API key may be active.
        print("get_nearest_3_metro_stations: Routes API unavailable; using Haversine fallback")

    # --- Step 3: if Routes API gave nothing, fall back to straight-line ---
    if not results:
        for cand in top_candidates:
            dist_km = round(cand["hl_dist_km"], 2)
            dur_min = round((dist_km / 5.0) * 60.0, 1)  # 5 km/h walk
            results.append({
                "name": cand["name"],
                "line": cand["line"],
                "distance_km": dist_km,
                "duration_mins": dur_min,
                "score": calculate_metro_score(dist_km),
                "routing_method": "haversine_fallback",
                "lat": cand["lat"],
                "lon": cand["lon"]
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


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not is_authorized(self.headers):
            self.send_json_response(
                {"status": "error", "error": {"code": "authentication_required"}},
                401,
            )
            return
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            _reject_query_api_keys(params)
            city_id = validate_catchment_city((params.get("city") or ["bengaluru"])[0])
            load_catchment_data(city_id, host=self.headers.get('Host'))
            client_api_key = _request_maps_api_key(self.headers)
            lat = float(params.get("lat", [0])[0])
            lon = float(params.get("lon", [0])[0])
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
            lat, lon = validate_city_coordinates(city_id, lat, lon)
            market_options = parse_market_options(params)
            market_options["city_id"] = city_id
            result = self.calculate_catchment(
                lat, lon, radius, client_api_key,
                travel_time_mins=travel_time_mins,
                travel_speed_kmh=travel_speed_kmh,
                travel_mode="DRIVE", live_traffic="true",
                smooth_edges=smooth_edges, catchment_mode="time",
                market_options=market_options,
                include_bands=include_bands,
            )
            result["canonical_city_id"] = city_id
            self.send_json_response(result)
        except (CatchmentValidationError, CatchmentProviderError, CatchmentConfigurationError) as exc:
            self.send_json_response(error_payload(exc), exc.status_code)
        except (ValueError, TypeError) as exc:
            wrapped = CatchmentValidationError(f"Invalid catchment request: {exc}")
            self.send_json_response(error_payload(wrapped), wrapped.status_code)
        except Exception:
            print("Catchment request failed")
            self.send_json_response({
                "status": "error", "schema_version": SCHEMA_VERSION,
                "message": "Catchment calculation failed",
                "error": {"code": "internal_error", "message": "Catchment calculation failed"},
            }, 500)

    def do_POST(self):
        if not is_authorized(self.headers):
            self.send_json_response(
                {"status": "error", "error": {"code": "authentication_required"}},
                401,
            )
            return
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            _reject_query_api_keys(params)
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise CatchmentValidationError("portfolio body must be between 1 byte and 1 MB")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            city_id = validate_catchment_city(
                payload.get("city") or (params.get("city") or ["bengaluru"])[0]
            )
            load_catchment_data(city_id, host=self.headers.get('Host'))
            client_api_key = _request_maps_api_key(self.headers)
            market_options = parse_market_options_payload(payload)
            market_options["city_id"] = city_id
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
                    lat, lon = validate_city_coordinates(city_id, lat, lon)
                    result = self.calculate_catchment(
                        lat, lon, 7.0, client_api_key, travel_time_mins=duration,
                        travel_mode="DRIVE", live_traffic="true", catchment_mode="time",
                        market_options=market_options, include_bands=False,
                    )
                    result["center_id"] = str(center.get("id") or f"center-{index + 1}")
                    center_results.append(result)
            portfolio = build_portfolio_result(center_results, market_options)
            self.send_json_response({
                "status": "success", "schema_version": SCHEMA_VERSION,
                "canonical_city_id": city_id,
                "data_revision": MARKET_DATA.get("data_revision"), "portfolio": portfolio,
            })
        except (CatchmentValidationError, CatchmentProviderError, CatchmentConfigurationError) as exc:
            self.send_json_response(error_payload(exc), exc.status_code)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            wrapped = CatchmentValidationError(f"Invalid portfolio request: {exc}")
            self.send_json_response(error_payload(wrapped), wrapped.status_code)
        except Exception:
            print("Portfolio request failed")
            self.send_json_response({
                "status": "error", "schema_version": SCHEMA_VERSION,
                "message": "Portfolio calculation failed",
                "error": {"code": "internal_error", "message": "Portfolio calculation failed"},
            }, 500)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def send_json_response(self, data, status_code=200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def calculate_catchment(self, lat, lon, radius_km, api_key, travel_time_mins=None, travel_speed_kmh=None, travel_mode="DRIVE", live_traffic="true", smooth_edges="true", catchment_mode="distance", market_options=None, include_bands=False):
        strict_provider = api_key is not None
        key = _get_maps_api_key(api_key)
        market_options = market_options or parse_market_options({})
        
        routing_method = "google"
        isochrone_geojson = None
        matched_hex_ids = []
        
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

        comparison_data = []

        try:
            if catchment_mode != "time" or time_mins is None:
                raise RuntimeError("Google isochrones require time mode")
            hex_min_time, matched_hex_ids, comparison_data, isochrone_geojson, matched_weights, isochrone_geometries, isochrone_cache = _build_google_time_catchment(
                lat,
                lon,
                time_mins,
                radius_km,
                api_key if strict_provider else None,
                travel_mode=travel_mode,
                live_traffic=live_traffic,
                smooth_edges=smooth_edges,
                include_bands=include_bands,
                strict_provider=strict_provider,
            )
        except (CatchmentProviderError, CatchmentConfigurationError, CatchmentValidationError):
            raise
        except Exception as exc:
            raise CatchmentProviderError("Google live isochrone request failed") from exc
        
        if not comparison_data:
            raise CatchmentProviderError("Google live isochrone request returned no usable geometry")

        matched_set = set(hex_min_time.keys())

        agg = {
            "countable_family_tam": 0.0,
            "direct_family_tam": 0.0,
            "direct_total_units": 0.0,
            "society_count": 0,
            "hospital_count": 0,
            "sez_office_spaces": 0,
            "q3_and_below_property_count": 0.0,
            "gated_community_count": 0.0,
            "q4_premium_evidence_count": 0.0,
            "full_only_99acres_society_count": 0.0,
            "full_family_proxy": 0.0,
            "q4_units_proxy": 0.0,
            "q4_family_proxy": 0.0,
            "full_only_99acres_units_proxy": 0.0,
            "full_only_99acres_family_proxy": 0.0
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
            agg["gated_community_count"] += h_props.get("gated_community_count", h_props.get("societies_direct_count", 0))
            agg["q4_premium_evidence_count"] += h_props.get("q4_premium_evidence_count", 0)
            agg["full_only_99acres_society_count"] += h_props.get("full_only_99acres_society_count", 0)
            agg["full_family_proxy"] += h_props.get("full_family_proxy", 0.0)
            agg["q4_units_proxy"] += h_props.get("q4_units_proxy", 0.0)
            agg["q4_family_proxy"] += h_props.get("q4_family_proxy", 0.0)
            agg["full_only_99acres_units_proxy"] += h_props.get("full_only_99acres_units_proxy", 0.0)
            agg["full_only_99acres_family_proxy"] += h_props.get("full_only_99acres_family_proxy", 0.0)
            
            band_time = hex_min_time.get(hid, 60)
            
            if MASTER_HEXES and hid in MASTER_HEXES:
                rec = MASTER_HEXES[hid]
                tam_sec = rec.get("tam", {})
                for band, val in tam_sec.get("income_band_family_tam", {}).items():
                    for t in [15, 30, 45, 60]:
                        if band_time <= t:
                            if band in income_bands[t]:
                                income_bands[t][band] += val.get("direct", 0.0)

        matched_societies = []
        for h_id in matched_set:
            for soc in HEX_TO_SOCIETIES.get(h_id, []):
                s_copy = soc.copy()
                s_copy["time_mins"] = hex_min_time.get(h_id, 60)
                matched_societies.append(s_copy)
        agg["society_count"] = len(matched_societies)
        matched_societies.sort(key=lambda s: s.get("tam", 0), reverse=True)

        matched_hospitals = []
        for h_id in matched_set:
            for hosp in HEX_TO_HOSPITALS.get(h_id, []):
                h_copy = hosp.copy()
                h_copy["time_mins"] = hex_min_time.get(h_id, 60)
                matched_hospitals.append(h_copy)
        agg["hospital_count"] = len(matched_hospitals)
        matched_hospitals.sort(key=lambda h: (h.get("beds", 0), h.get("rating", 0)), reverse=True)

        matched_offices = []
        for h_id in matched_set:
            for off in HEX_TO_OFFICES.get(h_id, []):
                o_copy = off.copy()
                o_copy["time_mins"] = hex_min_time.get(h_id, 60)
                matched_offices.append(o_copy)
        agg["office_count"] = len(matched_offices)
        matched_offices.sort(key=lambda o: o.get("office_rank_score", 0), reverse=True)

        for k in ["countable_family_tam", "direct_family_tam", "direct_total_units", "q3_and_below_property_count"]:
            agg[k] = round(agg[k], 2)

        selected_geometry = isochrone_geometries.get(str(int(round(time_mins)))) or isochrone_geojson
        if selected_geometry:
            agg["q3_and_below_property_count"] = round(
                sum_q3_below_for_geometry(shape(selected_geometry)),
                2,
            )
            
        for tb in income_bands:
            for k in income_bands[tb]:
                income_bands[tb][k] = round(income_bands[tb][k], 2)

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
                "provider": "google_isochrone",
                "mode": "DRIVE",
                "traffic": "LIVE",
                "duration_mins": int(time_mins),
                "cache": isochrone_cache.get(str(int(time_mins)), {}),
            },
            "radius_km": radius_km,
            "travel_time_mins": time_mins,
            "travel_speed_kmh": speed_kmh,
            "catchment_mode": catchment_mode,
            "live_traffic": live_traffic,
            "center": {"lat": lat, "lon": lon},
            "matched_hex_ids": list(hex_min_time.keys()),
            "hex_min_time": hex_min_time,
            "isochrone_geojson": isochrone_geojson,
            "isochrone_geometries": isochrone_geometries,
            "metrics": agg,
            "geography": selected_market["geography"],
            "school_market": selected_market["school_market"],
            "residential_market": selected_market["residential_market"],
            "capacity": selected_market["capacity"],
            "income_bands": income_bands,
            "societies": matched_societies[:500],
            "hospitals": matched_hospitals[:500],
            "offices": matched_offices[:500],
            "comparison": comparison_data,
            "metro": metro_data
        }
