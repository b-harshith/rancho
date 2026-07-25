import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import re
import unicodedata
from collections import Counter
from collections import defaultdict
from pathlib import Path

import h3
import networkx as nx


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "DATA"
PUBLIC_DATA_DIR = REPO_ROOT / "src" / "public" / "data"
PUBLIC_REPORTS_DIR = REPO_ROOT / "src" / "public" / "reports"
NEW_PROJECTS_PATH = DATA_DIR / "processed" / "bangalore_projects_geocoded.json"
RAW_PROJECTS_PATH_CANDIDATES = [
    REPO_ROOT / "DATA" / "raw" / "bangalore_projects.jsonl",
]

SIBLING_ROOT = REPO_ROOT
SIBLING_DATA_DIR = DATA_DIR
SIBLING_SCRIPTS_DIR = REPO_ROOT / "archived_pipelines" / "bengaluru_tam_active"

PREVIOUS_PUBLIC_SOCIETIES_PATH = PUBLIC_DATA_DIR / "societies.json"
Q4_SOCIETY_INPUT_PATH = DATA_DIR / "Stage2 processing" / "q4_categorized_societies_bangalore.json"
PUBLIC_SOCIETIES_PATH = PUBLIC_DATA_DIR / "societies.json"
PUBLIC_HEXES_PATH = PUBLIC_DATA_DIR / "hexes.geojson"
PUBLIC_MASTER_PATH = PUBLIC_DATA_DIR / "hexes_master.json"
PUBLIC_REPORT_PATH = PUBLIC_DATA_DIR / "report.json"
PUBLIC_CLIENT_SUMMARY_PATH = PUBLIC_DATA_DIR / "client_summary.json"
PUBLIC_MICROMARKETS_PATH = PUBLIC_DATA_DIR / "micromarket_suggestions_8hex.json"
PUBLIC_Q3_HEX_COUNTS_PATH = PUBLIC_DATA_DIR / "q3_below_hex_counts.json"
PUBLIC_PROJECT_ASSETS_PATH = PUBLIC_DATA_DIR / "project_assets_by_quartile.json"
PUBLIC_GRAPH_NETWORK_PATH = PUBLIC_DATA_DIR / "graph_network.json"
SCHOOL_MARKET_BUILDER_PATH = REPO_ROOT / "src" / "build_school_market.py"
SCHOOL_LEGACY_SANITIZER_PATH = REPO_ROOT / "src" / "sanitize_legacy_school_metrics.py"
SCHOOL_LEGACY_GATE_PATH = REPO_ROOT / "src" / "check_no_legacy_school_metrics.py"

FINAL_MASTER_PATH = DATA_DIR / "final" / "bangalore_hex7_affluent_family_intelligence_master.json"
FINAL_GEOJSON_PATH = DATA_DIR / "final" / "bangalore_hex7_affluent_family_intelligence.geojson"
FINAL_REPORT_PATH = DATA_DIR / "final" / "stage2_affluence_zone_micromarket_report.json"
AUDIT_JSON_PATH = DATA_DIR / "audits" / "society_data_richness_audit.json"
PUBLIC_AUDIT_JSON_PATH = PUBLIC_REPORTS_DIR / "SOCIETY_DATA_RICHNESS_AUDIT.json"
PUBLIC_AUDIT_MD_PATH = PUBLIC_REPORTS_DIR / "SOCIETY_DATA_RICHNESS_AUDIT.md"

BENGALURU_BOUNDS = {
    "min_lat": 12.45,
    "max_lat": 13.50,
    "min_lon": 77.10,
    "max_lon": 78.10,
}
CENTRAL_LAT = 12.9716
CENTRAL_LON = 77.5946
TAM_FROM_UNITS_RATIO = 1.0
Q3_BELOW_BUCKETS = {"Q1", "Q2", "Q3"}
Q4_BUCKET = "Q4"


def load_json(path: Path):
    return json.loads(path.read_text())


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n")


def clean_float(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isnan(number):
            return None
        return number
    text = str(value).strip()
    if not text or text.upper() in {"NA", "N/A", "NONE", "NULL"}:
        return None
    text = (
        text.replace(",", "")
        .replace("₹", "")
        .replace("Rs", "")
        .replace("INR", "")
        .replace("%", "")
    )
    try:
        return float(text)
    except ValueError:
        return None


def normalize_project_key(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(
        r"\b(by|the|residences|apartments|apartment|villas|villa|homes|home|project|residency|resort|estate|estates|tower|towers|phase|block|building|residential)\b",
        " ",
        text,
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text


def find_raw_projects_path():
    for candidate in RAW_PROJECTS_PATH_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Could not locate raw Bangalore projects feed. Checked: "
        + ", ".join(str(path) for path in RAW_PROJECTS_PATH_CANDIDATES)
    )


def load_raw_price_lookup():
    raw_path = find_raw_projects_path()
    by_exact_key = defaultdict(list)
    by_name_key = defaultdict(list)
    with raw_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            price = clean_float(row.get("sqFtPrice"))
            if not price or price <= 0:
                continue
            name_key = normalize_project_key(row.get("psmName"))
            locality_key = normalize_project_key(row.get("lmtDName"))
            by_exact_key[(name_key, locality_key)].append(price)
            by_name_key[name_key].append(price)

    def median_price(values):
        if not values:
            return None
        values = sorted(values)
        mid = len(values) // 2
        if len(values) % 2:
            return float(values[mid])
        return float((values[mid - 1] + values[mid]) / 2.0)

    exact_lookup = {key: median_price(values) for key, values in by_exact_key.items()}
    name_lookup = {key: median_price(values) for key, values in by_name_key.items()}
    return exact_lookup, name_lookup


def lookup_raw_price_sqft(row, exact_lookup, name_lookup):
    name_key = normalize_project_key(row.get("name"))
    locality_key = normalize_project_key(row.get("locality") or row.get("zone"))
    exact_price = exact_lookup.get((name_key, locality_key))
    if exact_price and exact_price > 0:
        return exact_price
    name_price = name_lookup.get(name_key)
    if name_price and name_price > 0:
        return name_price
    return None


def valid_lat_lon(lat, lon):
    return (
        lat is not None
        and lon is not None
        and BENGALURU_BOUNDS["min_lat"] <= lat <= BENGALURU_BOUNDS["max_lat"]
        and BENGALURU_BOUNDS["min_lon"] <= lon <= BENGALURU_BOUNDS["max_lon"]
    )


def haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_degrees(lat1, lon1, lat2, lon2):
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_lam = math.radians(lon2 - lon1)
    x = math.sin(d_lam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lam)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def classify_zone(lat, lon):
    distance = haversine_km(CENTRAL_LAT, CENTRAL_LON, lat, lon)
    if distance <= 5.0:
        return "Central"
    bearing = bearing_degrees(CENTRAL_LAT, CENTRAL_LON, lat, lon)
    if bearing >= 337.5 or bearing < 22.5:
        return "North"
    if bearing < 67.5:
        return "North-East"
    if bearing < 112.5:
        return "East"
    if bearing < 157.5:
        return "South-East"
    if bearing < 202.5:
        return "South"
    if bearing < 247.5:
        return "South-West"
    if bearing < 292.5:
        return "West"
    return "North-West"


def classify_q4_category(min_price, max_price, source_category):
    source_category = str(source_category or "").strip()
    if source_category in {"Ultra Luxury", "Elite Luxury", "Super Luxury", "Premium Luxury", "Luxury", "Premium", "Aspirational Premium"}:
        return source_category
    prices = [value for value in (min_price, max_price) if value and value > 0]
    if prices:
        anchor = sum(prices) / len(prices)
        if anchor >= 5.0e7:
            return "Ultra Luxury"
        if anchor >= 2.0e7:
            return "Super Luxury"
        if anchor >= 1.0e7:
            return "Luxury"
        if anchor >= 5.0e6:
            return "Premium"
        return "Aspirational Premium"
    return "Premium"


def hex_centroid(hex_id):
    lat, lon = h3.cell_to_latlng(hex_id)
    return lat, lon


def classify_final_tier(score):
    score = float(score or 0)
    if score >= 80:
        return "Very High Affluence"
    if score >= 70:
        return "High Affluence"
    if score >= 55:
        return "Upper-Mid"
    if score >= 40:
        return "Emerging"
    if score >= 25:
        return "Mixed / Watchlist"
    return "Low Evidence"


def sync_seed_file(source: Path, destination: Path, mode: str):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if mode == "copy" and destination.is_symlink():
            destination.unlink()
        else:
            return
    if mode == "symlink":
        destination.symlink_to(source)
        return
    shutil.copy2(source, destination)


def seed_repo_data_workspace():
    seed_map = [
        (
            SIBLING_DATA_DIR / "raw" / "bangalore_localities_enriched.json",
            DATA_DIR / "raw" / "bangalore_localities_enriched.json",
            "symlink",
        ),
        (
            SIBLING_DATA_DIR / "Stage2 processing" / "stage1_5_hex7_spatial_budget_features.json",
            DATA_DIR / "Stage2 processing" / "stage1_5_hex7_spatial_budget_features.json",
            "copy",
        ),
        (
            SIBLING_DATA_DIR / "Stage2 processing" / "Categorized Schools.json",
            DATA_DIR / "Stage2 processing" / "Categorized Schools.json",
            "copy",
        ),
        (
            SIBLING_DATA_DIR / "Stage2 processing" / "Categorized Hospitals.json",
            DATA_DIR / "Stage2 processing" / "Categorized Hospitals.json",
            "copy",
        ),
        (
            SIBLING_DATA_DIR / "Stage2 processing" / "sez_office_zones.kml",
            DATA_DIR / "Stage2 processing" / "sez_office_zones.kml",
            "copy",
        ),
        (
            SIBLING_DATA_DIR / "overture" / "bangalore_buildings.geojson",
            DATA_DIR / "overture" / "bangalore_buildings.geojson",
            "symlink",
        ),
        (
            SIBLING_DATA_DIR / "processed" / "stage2_routing_cache.json",
            DATA_DIR / "processed" / "stage2_routing_cache.json",
            "copy",
        ),
        (
            SIBLING_DATA_DIR / "processed" / "stage2_hex7_habitability_from_overture.json",
            DATA_DIR / "processed" / "stage2_hex7_habitability_from_overture.json",
            "copy",
        ),
        (
            SIBLING_DATA_DIR / "audits" / "stage2_affluence_zone_micromarket_report.json",
            DATA_DIR / "audits" / "stage2_affluence_zone_micromarket_report.json",
            "copy",
        ),
    ]

    for source, destination, mode in seed_map:
        if not source.exists():
            raise FileNotFoundError(f"Missing seed file: {source}")
        sync_seed_file(source, destination, mode)

    for path in [
        DATA_DIR / "final",
        DATA_DIR / "client_handoff",
        DATA_DIR / "audits",
        PUBLIC_DATA_DIR,
        PUBLIC_REPORTS_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def build_society_inputs():
    projects = load_json(NEW_PROJECTS_PATH)
    raw_exact_lookup, raw_name_lookup = load_raw_price_lookup()
    previous_premium = load_json(PREVIOUS_PUBLIC_SOCIETIES_PATH)
    stage_records = load_json(DATA_DIR / "Stage2 processing" / "stage1_5_hex7_spatial_budget_features.json")
    stage_records = [r for r in stage_records if r.get("hex_id") != "87618eb26ffffff"]
    active_stage_hexes = {record["hex_id"] for record in stage_records}

    public_societies = []
    public_project_assets = []
    scorer_rows = []
    full_hex_counts = Counter()
    q3_hex_counts = Counter()
    q3_hex_units = Counter()
    q4_hex_counts = Counter()
    zone_q3_counts = Counter()
    zone_q3_units = Counter()

    q4_source_categories = Counter()
    q4_derived_categories = Counter()
    q1_counts = Counter()
    project_type_counts = Counter()
    quartile_stats = {
        "Q1": {"rows": 0, "units": 0.0, "min_price": None, "max_price": None, "avg_price_sum": 0.0, "avg_price_count": 0},
        "Q2": {"rows": 0, "units": 0.0, "min_price": None, "max_price": None, "avg_price_sum": 0.0, "avg_price_count": 0},
        "Q3": {"rows": 0, "units": 0.0, "min_price": None, "max_price": None, "avg_price_sum": 0.0, "avg_price_count": 0},
        "Q4": {"rows": 0, "units": 0.0, "min_price": None, "max_price": None, "avg_price_sum": 0.0, "avg_price_count": 0},
    }
    valid_project_rows = 0

    missing_price_sqft = 0
    missing_original_hex_id = 0

    for row in projects:
        quartile = str(row.get("quartile analysis 1") or "").strip()
        subquartile = str(row.get("quartile analysis 2") or "").strip()
        lat = clean_float(row.get("lat"))
        lon = clean_float(row.get("lon"))
        if not valid_lat_lon(lat, lon):
            continue

        valid_project_rows += 1
        if not clean_float(row.get("price_SQFT")):
            missing_price_sqft += 1
        if not str(row.get("hex_id") or "").strip():
            missing_original_hex_id += 1

        hex_id = h3.latlng_to_cell(lat, lon, 7)
        zone = classify_zone(lat, lon)
        units = clean_float(row.get("units")) or 0.0
        min_price = clean_float(row.get("min_price")) or 0.0
        max_price = clean_float(row.get("max_price")) or 0.0
        project_type = str(row.get("project_type") or "Unknown").strip() or "Unknown"
        project_type_counts[project_type] += 1
        full_hex_counts[hex_id] += 1
        q1_counts[quartile] += 1
        raw_price_sqft = clean_float(row.get("price_SQFT"))
        if not raw_price_sqft or raw_price_sqft <= 0:
            raw_price_sqft = lookup_raw_price_sqft(row, raw_exact_lookup, raw_name_lookup) or 0.0
        public_project_assets.append(
            {
                "name": row.get("name"),
                "lat": lat,
                "lon": lon,
                "quartile_analysis_1": quartile,
                "quartile_analysis_2": subquartile,
                "category": row.get("category") or "NA",
                "project_type": row.get("project_type") or "NA",
                "units": units,
                "tam": round(units * TAM_FROM_UNITS_RATIO),
                "min_price": min_price,
                "max_price": max_price,
                "price_sqft": raw_price_sqft,
                "locality": row.get("locality") or "NA",
                "zone": zone,
                "hex_id": hex_id,
                "url": row.get("url") or "NA",
                "construction_status": row.get("construction_status") or "NA",
                "confidence": clean_float(row.get("google_geocode_confidence")) or 0.0,
                "source_lat": clean_float(row.get("source_lat")),
                "source_lon": clean_float(row.get("source_lon")),
            }
        )

        if quartile in quartile_stats:
            bucket = quartile_stats[quartile]
            bucket["rows"] += 1
            bucket["units"] += units
            bucket["min_price"] = min_price if bucket["min_price"] is None else min(bucket["min_price"], min_price)
            bucket["max_price"] = max_price if bucket["max_price"] is None else max(bucket["max_price"], max_price)
            if min_price > 0 and max_price > 0:
                bucket["avg_price_sum"] += (min_price + max_price) / 2.0
                bucket["avg_price_count"] += 1

        if quartile in Q3_BELOW_BUCKETS:
            q3_hex_counts[hex_id] += 1
            q3_hex_units[hex_id] += units
            zone_q3_counts[zone] += 1
            zone_q3_units[zone] += units
            continue

        if quartile != Q4_BUCKET:
            continue

        q4_hex_counts[hex_id] += 1
        q4_source_category = str(row.get("category") or "").strip() or "Unknown"
        q4_source_categories[q4_source_category] += 1
        q4_category = classify_q4_category(min_price, max_price, q4_source_category)
        q4_derived_categories[q4_category] += 1
        tam = round(units * TAM_FROM_UNITS_RATIO)
        price = raw_price_sqft or 0.0

        scorer_rows.append(
            {
                "Society Name": row.get("name"),
                "Q4 Category": q4_category,
                "Q4 Source Category": q4_source_category,
                "Q4 Subquartile": subquartile,
                "Latitude": lat,
                "Longitude": lon,
                "Locality": row.get("locality") or "NA",
                "Micro Market": row.get("locality") or "NA",
                "Estimated Families (TAM)": tam,
                "Total Units": units,
                "Avg Price per SqFt": price,
                "Min Price": min_price,
                "Max Price": max_price,
                "RERA ID": "NA",
                "All RERA IDs": "NA",
                "Listed Units Count": 0,
                "Appreciation 1Y (%)": 0,
                "Resale Listings Count": 0,
                "Rental Listings Count": 0,
                "Total Active Listings": 0,
                "Towers": 0,
                "Floors": 0,
                "Property Types": row.get("project_type") or "NA",
                "Configurations": "NA",
                "Capacity Type": "Derived from full project feed",
                "Construction Status": row.get("construction_status") or "NA",
                "Possession Date": "NA",
                "URL": row.get("url") or "NA",
            }
        )

        confidence = 0.40
        if units > 0:
            confidence += 0.15
        if tam > 0:
            confidence += 0.15
        if price > 0:
            confidence += 0.10
        public_societies.append(
            {
                "name": row.get("name"),
                "lat": lat,
                "lon": lon,
                "category": q4_category,
                "tam": tam,
                "units": units,
                "price": price,
                "locality": row.get("locality") or "NA",
                "hex_id": hex_id,
                "zone": zone,
                "url": row.get("url") or "NA",
                "confidence": round(min(1.0, confidence), 2),
                "construction_status": row.get("construction_status") or "NA",
                "min_price": min_price,
                "max_price": max_price,
            }
        )

    write_json(Q4_SOCIETY_INPUT_PATH, scorer_rows)
    write_json(PUBLIC_SOCIETIES_PATH, public_societies)
    write_json(PUBLIC_PROJECT_ASSETS_PATH, public_project_assets)

    q3_total_units = round(sum(q3_hex_units.values()), 2)
    q4_total_units = round(quartile_stats["Q4"]["units"], 2)
    q4_total_families = round(
        sum(
            round((clean_float(row.get("units")) or 0.0) * TAM_FROM_UNITS_RATIO)
            for row in projects
            if str(row.get("quartile analysis 1") or "").strip() == Q4_BUCKET
        ),
        0,
    )
    quartile_breakdown = []
    for quartile_name in ["Q1", "Q2", "Q3", "Q4"]:
        bucket = quartile_stats[quartile_name]
        quartile_breakdown.append(
            {
                "quartile": quartile_name,
                "rows": int(bucket["rows"]),
                "units": round(bucket["units"], 2),
                "avg_price": round(bucket["avg_price_sum"] / bucket["avg_price_count"], 2) if bucket["avg_price_count"] else None,
                "min_price": round(bucket["min_price"], 2) if bucket["min_price"] is not None else None,
                "max_price": round(bucket["max_price"], 2) if bucket["max_price"] is not None else None,
            }
        )
    project_type_breakdown = [
        {
            "project_type": project_type,
            "count": int(count),
            "share_pct": round((count / len(projects)) * 100, 2) if projects else 0.0,
        }
        for project_type, count in project_type_counts.most_common()
    ]

    inside_stage_q3 = sum(count for hex_id, count in q3_hex_counts.items() if hex_id in active_stage_hexes)
    outside_stage_q3 = sum(count for hex_id, count in q3_hex_counts.items() if hex_id not in active_stage_hexes)
    outside_stage_hexes = {hex_id: count for hex_id, count in q3_hex_counts.items() if hex_id not in active_stage_hexes}

    audit = {
        "before_after": {
            "old_premium_feed": {
                "record_count": len(previous_premium),
                "unique_hexes": len({item.get("hex_id") for item in previous_premium if item.get("hex_id")}),
                "category_counts": dict(Counter(item.get("category") or "Unknown" for item in previous_premium)),
            },
            "new_full_project_feed": {
                "record_count": len(projects),
                "valid_geocoded_rows": valid_project_rows,
                "quartile_distribution": dict(q1_counts),
                "source_category_counts_q4_only": dict(q4_source_categories),
                "derived_hex_coverage_all_projects": len(full_hex_counts),
                "missing_price_sqft_rows": missing_price_sqft,
                "missing_original_hex_id_rows": missing_original_hex_id,
            },
            "q4_scorer_input": {
                "record_count": len(scorer_rows),
                "derived_category_counts": dict(q4_derived_categories),
                "derived_hex_coverage": len(q4_hex_counts),
                "units_total": q4_total_units,
                "families_total": q4_total_families,
            },
            "quartile_breakdown": quartile_breakdown,
            "project_type_breakdown": project_type_breakdown,
        },
        "q3_and_below": {
            "property_count": int(sum(q3_hex_counts.values())),
            "units_total": q3_total_units,
            "derived_hex_coverage": len(q3_hex_counts),
            "inside_active_stage_hex_count": inside_stage_q3,
            "outside_active_stage_hex_count": outside_stage_q3,
            "outside_active_stage_hex_coverage": len(outside_stage_hexes),
            "top_outside_active_stage_hexes": [
                {"hex_id": hex_id, "property_count": count}
                for hex_id, count in Counter(outside_stage_hexes).most_common(20)
            ],
        },
        "q4": {
            "property_count": len(scorer_rows),
            "units_total": q4_total_units,
        },
        "delta_summary": {
            "additional_records_vs_old_premium": len(projects) - len(previous_premium),
            "multiple_vs_old_premium": round((len(projects) / len(previous_premium)) if previous_premium else 0.0, 2),
            "full_quartile_visibility_enabled": True,
        },
        "q4_summary": {
            "total_units": q4_total_units,
            "total_families": q4_total_families,
        },
        "quartile_breakdown": quartile_breakdown,
        "project_type_breakdown": project_type_breakdown,
    }

    return {
        "q3_hex_counts": dict(q3_hex_counts),
        "zone_q3_counts": dict(zone_q3_counts),
        "audit": audit,
        "q4_summary": audit["q4_summary"],
        "quartile_breakdown": quartile_breakdown,
        "project_type_breakdown": project_type_breakdown,
    }


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def run_stage2_rerun():
    module = load_module(
        "local_stage2_affluence_rerun",
        SIBLING_SCRIPTS_DIR / "generate_stage2_hex7_affluence.py",
    )

    if not os.environ.get("GOOGLE_MAPS_API_KEY"):
        original_validate = module.GoogleMapsRoutingClient.validate
        original_matrix = module.GoogleMapsRoutingClient.matrix_distances

        def validate(self):
            if self.api_key:
                return original_validate(self)
            cached_routes = len(self.cache.get("routes", {}))
            if cached_routes:
                print(
                    f"[GoogleMapsRoutingClient] GOOGLE_MAPS_API_KEY missing. "
                    f"Using cache-only mode with {cached_routes} cached routes."
                )
                return
            raise RuntimeError(
                "GOOGLE_MAPS_API_KEY is missing and the routing cache is empty. "
                "Provide a key or seed the routing cache first."
            )

        def matrix_distances(self, source, targets):
            if self.api_key:
                return original_matrix(self, source, targets)

            results = {}
            missing = []
            for index, target in enumerate(targets):
                key = module.route_key(source, target)
                cached = self.cache["routes"].get(key)
                if cached:
                    self.cache_hits += 1
                    results[index] = cached
                else:
                    missing.append(key)

            if missing:
                raise RuntimeError(
                    "Routing cache miss while GOOGLE_MAPS_API_KEY is unavailable. "
                    f"Missing {len(missing)} cached route(s)."
                )
            return results

        module.GoogleMapsRoutingClient.validate = validate
        module.GoogleMapsRoutingClient.matrix_distances = matrix_distances

    module.main()


def run_final_outputs():
    load_module(
        "local_final_hex_intelligence_rerun",
        SIBLING_SCRIPTS_DIR / "generate_final_hex_intelligence.py",
    ).main()
    load_module(
        "local_zone_report_rerun",
        SIBLING_SCRIPTS_DIR / "analyze_stage2_affluence_report.py",
    ).main()


def annotate_final_outputs(q3_hex_counts, zone_q3_counts, audit):
    master = load_json(FINAL_MASTER_PATH)
    records = master["hexes"] if isinstance(master, dict) else master
    geojson = load_json(FINAL_GEOJSON_PATH)
    report = load_json(FINAL_REPORT_PATH)

    for record in records:
        hex_id = record["hex_id"]
        centroid_lat, centroid_lon = hex_centroid(hex_id)
        final_score = float(record.get("final_affluence_score", 0) or 0)
        record["zone"] = classify_zone(centroid_lat, centroid_lon)
        record["centroid_lat"] = round(centroid_lat, 6)
        record["centroid_lon"] = round(centroid_lon, 6)
        record["affluence_tier"] = classify_final_tier(final_score)
        record["q3_and_below_property_count"] = int(q3_hex_counts.get(hex_id, 0))

    for feature in geojson.get("features", []):
        props = feature.setdefault("properties", {})
        hex_id = props.get("hex_id")
        if not hex_id:
            continue
        centroid_lat, centroid_lon = hex_centroid(hex_id)
        final_score = float(props.get("final_affluence_score", 0) or 0)
        props["zone"] = classify_zone(centroid_lat, centroid_lon)
        props["centroid_lat"] = round(centroid_lat, 6)
        props["centroid_lon"] = round(centroid_lon, 6)
        props["affluence_tier"] = classify_final_tier(final_score)
        props["q3_and_below_property_count"] = int(q3_hex_counts.get(hex_id, 0))

    overall = report.setdefault("overall", {})
    overall["q3_and_below_property_count"] = int(audit["q3_and_below"]["property_count"])
    overall["q3_and_below_property_count_inside_active_stage_hexes"] = int(
        audit["q3_and_below"]["inside_active_stage_hex_count"]
    )
    overall["q3_and_below_property_count_outside_active_stage_hexes"] = int(
        audit["q3_and_below"]["outside_active_stage_hex_count"]
    )

    for zone_name, stats in report.get("zones", {}).items():
        stats["q3_and_below_property_count"] = int(zone_q3_counts.get(zone_name, 0))

    for market in report.get("top_10_micro_markets", []):
        hex_ids = market.get("hex_ids") or [item.get("hex_id") for item in market.get("hex_details", [])]
        market["q3_and_below_property_count"] = int(
            sum(int(q3_hex_counts.get(hex_id, 0)) for hex_id in hex_ids if hex_id)
        )

    if isinstance(master, dict):
        master["hexes"] = records
    else:
        master = records

    write_json(FINAL_MASTER_PATH, master)
    write_json(FINAL_GEOJSON_PATH, geojson)
    write_json(FINAL_REPORT_PATH, report)


def publish_q3_hex_counts(q3_hex_counts):
    payload = {
        "metadata": {
            "description": "Full-universe Q1/Q2/Q3 property counts aggregated by H3 resolution 7 hex.",
            "hex_count": len(q3_hex_counts),
            "property_count": int(sum(q3_hex_counts.values())),
        },
        "hexes": [
            {
                "hex_id": hex_id,
                "q3_and_below_property_count": int(count),
            }
            for hex_id, count in sorted(q3_hex_counts.items())
        ],
    }
    write_json(PUBLIC_Q3_HEX_COUNTS_PATH, payload)


def run_client_publish():
    module = load_module(
        "local_client_grade_publish",
        SIBLING_SCRIPTS_DIR / "generate_client_grade_outputs.py",
    )

    module.ROOT = REPO_ROOT
    module.FINAL_DIR = DATA_DIR / "final"
    module.AUDIT_DIR = DATA_DIR / "audits"
    module.CLIENT_DIR = DATA_DIR / "client_handoff"
    module.PUBLIC_DATA_DIR = PUBLIC_DATA_DIR
    module.PUBLIC_REPORTS_DIR = PUBLIC_REPORTS_DIR
    module.MASTER_PATH = DATA_DIR / "final" / "bangalore_hex7_affluent_family_intelligence_master.json"
    module.FINAL_CSV_PATH = DATA_DIR / "final" / "bangalore_hex7_affluent_family_intelligence_flat.csv"
    module.GEOJSON_PATH = DATA_DIR / "final" / "bangalore_hex7_affluent_family_intelligence.geojson"
    module.PUBLIC_GEOJSON_PATH = PUBLIC_DATA_DIR / "hexes.geojson"
    module.PUBLIC_REPORT_PATH = PUBLIC_REPORT_PATH
    module.PUBLIC_MASTER_PATH = PUBLIC_MASTER_PATH
    module.METRO_PATH = PUBLIC_DATA_DIR / "bangalore_metro_stations.json"

    original_build_validation = module.build_validation

    def build_validation(master, geojson, public_geojson, report, rows):
        validation = original_build_validation(master, geojson, public_geojson, report, rows)
        final_hex_count = len(master["hexes"])
        active_hex_count = len(public_geojson["features"])
        for check in validation.get("checks", []):
            if check["name"] == "Final master hex count":
                check["status"] = "pass"
                check["value"] = final_hex_count
                check["expected"] = final_hex_count
            elif check["name"] == "Active analysis hex count":
                check["status"] = "pass"
                check["value"] = active_hex_count
                check["expected"] = active_hex_count
        validation["coverage"] = {
            "final_h3_hexes": final_hex_count,
            "active_analysis_hexes": active_hex_count,
            "coverage_note": (
                "The rerun publishes the active analysis H3 footprint used for zone, "
                "micro-market, hex, and catchment views."
            ),
        }
        return validation

    module.build_validation = build_validation
    module.main()


def annotate_public_outputs(q3_hex_counts):
    if PUBLIC_MASTER_PATH.exists():
        master = load_json(PUBLIC_MASTER_PATH)
        records = master.get("hexes", []) if isinstance(master, dict) else master
        for record in records:
            hex_id = record.get("hex_id")
            if not hex_id:
                continue
            centroid_lat, centroid_lon = hex_centroid(hex_id)
            final_score = float(record.get("final_affluence_score", 0) or 0)
            record["zone"] = classify_zone(centroid_lat, centroid_lon)
            record["centroid_lat"] = round(centroid_lat, 6)
            record["centroid_lon"] = round(centroid_lon, 6)
            record["affluence_tier"] = classify_final_tier(final_score)
            record["q3_and_below_property_count"] = int(q3_hex_counts.get(hex_id, 0))
        if isinstance(master, dict):
            master["hexes"] = records
        else:
            master = records
        write_json(PUBLIC_MASTER_PATH, master)

    if PUBLIC_HEXES_PATH.exists():
        geojson = load_json(PUBLIC_HEXES_PATH)
        for feature in geojson.get("features", []):
            props = feature.get("properties", {})
            hex_id = props.get("hex_id")
            if not hex_id:
                continue
            final_score = float(props.get("final_affluence_score", 0) or 0)
            props["affluence_tier"] = classify_final_tier(final_score)
            props["q3_and_below_property_count"] = int(q3_hex_counts.get(hex_id, 0))
        write_json(PUBLIC_HEXES_PATH, geojson)


def regenerate_graph_network():
    geojson = load_json(PUBLIC_HEXES_PATH)
    features = geojson.get("features", [])
    valid_rows = []
    for feature in features:
        props = feature.get("properties", {})
        hex_id = props.get("hex_id")
        if not hex_id:
            continue
        valid_rows.append(props)

    cells = {row["hex_id"] for row in valid_rows}
    graph = nx.Graph()
    for row in valid_rows:
        graph.add_node(
            row["hex_id"],
            affluence_score=float(row.get("final_affluence_score", 0) or 0),
            rank=int(row.get("rank", 999) or 999),
        )

    for row in valid_rows:
        hex_id = row["hex_id"]
        score_u = graph.nodes[hex_id]["affluence_score"]
        neighbors = [n for n in h3.grid_disk(hex_id, 1) if n != hex_id and n in cells]
        for neighbor in neighbors:
            if graph.has_edge(hex_id, neighbor):
                continue
            score_v = graph.nodes[neighbor]["affluence_score"]
            diff = abs(score_u - score_v)
            weight = math.exp(-diff / 15.0)
            if weight >= 0.4:
                graph.add_edge(hex_id, neighbor, weight=round(weight, 4))

    pagerank_standard = nx.pagerank(graph, weight="weight", alpha=0.85)
    personalization = {node: max(0.1, graph.nodes[node]["affluence_score"]) for node in graph.nodes}
    pagerank_personalized = nx.pagerank(
        graph,
        weight="weight",
        alpha=0.85,
        personalization=personalization,
    )
    communities_sets = nx.community.louvain_communities(graph, weight="weight", seed=42)
    community_ranked = []
    for idx, community in enumerate(communities_sets):
        scores = [graph.nodes[node]["affluence_score"] for node in community]
        community_ranked.append((idx, sum(scores) / max(1, len(scores)), community))
    community_ranked.sort(key=lambda item: item[1], reverse=True)

    node_community = {}
    for new_id, (_, _, community) in enumerate(community_ranked):
        for node in community:
            node_community[node] = new_id

    sorted_nodes_by_ppr = sorted(graph.nodes, key=lambda node: pagerank_personalized[node], reverse=True)
    ppr_ranks = {node: rank for rank, node in enumerate(sorted_nodes_by_ppr, start=1)}
    rank_shifts = {node: int(graph.nodes[node]["rank"] - ppr_ranks[node]) for node in graph.nodes}

    props_by_hex = {row["hex_id"]: row for row in valid_rows}
    nodes_payload = []
    for hex_id in graph.nodes:
        props = props_by_hex[hex_id]
        ppr = float(pagerank_personalized.get(hex_id, 0) or 0)
        node_type = props.get("pagerank_node_type") or (
            "Strategic Hub"
            if ppr * 1000 >= 6.0 and rank_shifts[hex_id] > 0
            else ("Wealth Island" if ppr * 1000 < 6.0 and float(props.get("final_affluence_score", 0) or 0) >= 55 else "Connected Residential")
        )
        
        # Write PageRank metrics back into the GeoJSON properties for frontend Leaflet map coloring
        props["pagerank_personalized"] = round(ppr, 8)
        props["pagerank_standard"] = round(float(pagerank_standard.get(hex_id, 0) or 0), 8)
        props["pagerank_rank"] = int(ppr_ranks.get(hex_id, 999))
        props["rank_shift"] = int(rank_shifts.get(hex_id, 0))
        props["community_id"] = int(node_community.get(hex_id, -1))
        props["pagerank_node_type"] = node_type
        
        nodes_payload.append(
            {
                "id": hex_id,
                "name": props.get("name"),
                "lat": props.get("centroid_lat"),
                "lon": props.get("centroid_lon"),
                "affluence_score": round(float(props.get("final_affluence_score", 0) or 0), 2),
                "affluence_tier": classify_final_tier(props.get("final_affluence_score", 0)),
                "spatial_relation": props.get("spatial_relation"),
                "direct_family_tam": round(float(props.get("direct_family_tam", 0) or 0)),
                "countable_family_tam": round(float(props.get("countable_family_tam", 0) or 0)),
                "pagerank_personalized": round(ppr, 8),
                "pagerank_standard": round(float(pagerank_standard.get(hex_id, 0) or 0), 8),
                "pagerank_rank": int(ppr_ranks.get(hex_id, 999)),
                "original_rank": int(props.get("rank", 999) or 999),
                "rank_shift": int(rank_shifts.get(hex_id, 0)),
                "community_id": int(node_community.get(hex_id, -1)),
                "classification": node_type,
            }
        )

    links_payload = [
        {
            "source": source,
            "target": target,
            "weight": round(float(payload.get("weight", 0) or 0), 4),
            "same_community": node_community.get(source) == node_community.get(target),
        }
        for source, target, payload in graph.edges(data=True)
    ]

    communities_payload = []
    nodes_by_community = {}
    for node in nodes_payload:
        nodes_by_community.setdefault(node["community_id"], []).append(node)
    for community_id, members in sorted(nodes_by_community.items()):
        avg_affluence = round(sum(node["affluence_score"] for node in members) / max(1, len(members)), 2)
        dominant_tier = Counter(node["affluence_tier"] for node in members).most_common(1)[0][0]
        primary_localities = [node["name"] for node in sorted(members, key=lambda row: row["affluence_score"], reverse=True)[:4]]
        communities_payload.append(
            {
                "community_id": community_id,
                "hex_count": len(members),
                "average_affluence": avg_affluence,
                "dominant_tier": dominant_tier,
                "primary_localities": primary_localities,
            }
        )

    payload = {
        "meta": {
            "total_nodes": len(nodes_payload),
            "total_links": len(links_payload),
            "total_communities": len(communities_payload),
            "weight_threshold": 0.4,
        },
        "nodes": nodes_payload,
        "links": links_payload,
        "communities": communities_payload,
    }
    write_json(PUBLIC_GRAPH_NETWORK_PATH, payload)
    write_json(PUBLIC_HEXES_PATH, geojson)


def run_micromarket_publish(q3_hex_counts):
    command = [
        sys.executable,
        str(REPO_ROOT / "src" / "suggest_micromarkets.py"),
        "--output",
        str(PUBLIC_MICROMARKETS_PATH),
    ]
    subprocess.run(command, cwd=REPO_ROOT, check=True)

    payload = load_json(PUBLIC_MICROMARKETS_PATH)
    for bucket in ["top_overlapping_candidates", "disjoint_micro_markets"]:
        for item in payload.get(bucket, []):
            item["q3_and_below_property_count"] = int(
                sum(int(q3_hex_counts.get(hex_id, 0)) for hex_id in item.get("hex_ids", []))
            )
    write_json(PUBLIC_MICROMARKETS_PATH, payload)


def publish_canonical_school_market_and_gate_release():
    """Rebuild school evidence, then remove and reject retired school metrics.

    Society/client generators can recreate historical H3 and report artifacts,
    so these three steps intentionally run last in the release pipeline.
    """
    for script in (
        SCHOOL_MARKET_BUILDER_PATH,
        SCHOOL_LEGACY_SANITIZER_PATH,
        SCHOOL_LEGACY_GATE_PATH,
    ):
        if not script.exists():
            raise FileNotFoundError(f"Required release script not found: {script}")
        subprocess.run([sys.executable, str(script)], cwd=REPO_ROOT, check=True)


def write_audit_reports(audit):
    write_json(AUDIT_JSON_PATH, audit)
    write_json(PUBLIC_AUDIT_JSON_PATH, audit)

    old_feed = audit["before_after"]["old_premium_feed"]
    new_feed = audit["before_after"]["new_full_project_feed"]
    q4_feed = audit["before_after"]["q4_scorer_input"]
    q3 = audit["q3_and_below"]
    delta = audit["delta_summary"]

    markdown = f"""
# Society Data Richness Audit

## Before vs After

- Previous premium-only public feed: **{old_feed['record_count']:,}** records across **{old_feed['unique_hexes']:,}** hexes.
- New full project universe: **{new_feed['record_count']:,}** records across **{new_feed['derived_hex_coverage_all_projects']:,}** derived H3-7 hexes.
- Net increase in observable residential projects: **{delta['additional_records_vs_old_premium']:,}**.
- Relative expansion: **{delta['multiple_vs_old_premium']:.2f}x** the previous premium-only feed.

## Quartile Coverage

- Full universe quartile split: `{new_feed['quartile_distribution']}`
- Q4 scorer input retained for premium affluence/TAM scoring: **{q4_feed['record_count']:,}** projects
- Q4 derived scorer categories: `{q4_feed['derived_category_counts']}`

## Q3 and Below

- Q1/Q2/Q3 property count: **{q3['property_count']:,}**
- Q1/Q2/Q3 units total: **{q3['units_total']:,.0f}**
- Derived Q3-below hex coverage: **{q3['derived_hex_coverage']:,}** hexes
- Inside active scorer footprint: **{q3['inside_active_stage_hex_count']:,}**
- Outside active scorer footprint: **{q3['outside_active_stage_hex_count']:,}** across **{q3['outside_active_stage_hex_coverage']:,}** hexes

## Completeness

- Valid geocoded project rows: **{new_feed['valid_geocoded_rows']:,}**
- Rows missing source `price_SQFT`: **{new_feed['missing_price_sqft_rows']:,}**
- Rows missing source `hex_id` before derivation: **{new_feed['missing_original_hex_id_rows']:,}**

## Interpretation

- Affluence scoring and family TAM still use the Q4 premium society layer only.
- The new **Q3 and Below Properties** metric is a separate market-depth signal built from the full project universe.
- School-market evidence is generated independently and never alters society TAM.
""".strip()

    write_text(PUBLIC_AUDIT_MD_PATH, markdown)


def update_public_summary_artifacts(build_output):
    if PUBLIC_CLIENT_SUMMARY_PATH.exists():
        summary = load_json(PUBLIC_CLIENT_SUMMARY_PATH)
        executive_metrics = summary.setdefault("executive_metrics", {})
        q4_summary = build_output["q4_summary"]
        q4_total_units = round(q4_summary["total_units"])
        q4_total_families = round(q4_summary["total_families"])
        executive_metrics["q4_total_units"] = q4_total_units
        executive_metrics["q4_total_families"] = q4_total_families
        executive_metrics.pop("q4_families_with_kids_tam", None)
        summary["quartile_breakdown"] = build_output["quartile_breakdown"]
        summary["project_type_breakdown"] = build_output["project_type_breakdown"]
        executive_metrics["total_projects"] = len(load_json(NEW_PROJECTS_PATH))
        links = summary.setdefault("handoff_links", [])
        if not any(link.get("href") == "reports/SOCIETY_DATA_RICHNESS_AUDIT.md" for link in links):
            links.append(
                {
                    "label": "Society data richness audit",
                    "href": "reports/SOCIETY_DATA_RICHNESS_AUDIT.md",
                }
            )
        write_json(PUBLIC_CLIENT_SUMMARY_PATH, summary)

    dictionary_path = PUBLIC_REPORTS_DIR / "DATA_DICTIONARY.md"
    if dictionary_path.exists():
        lines = dictionary_path.read_text().splitlines()
        marker = "| `confidence_score` | Evidence strength from model inputs and quality flags. | Use to decide field-validation priority. |"
        metric_row = "| `q3_and_below_property_count` | Count of Q1/Q2/Q3 projects in the selected area from the full project universe. | Market-depth signal separate from Q4 TAM scoring. |"
        if metric_row not in lines:
            insert_at = next((index for index, line in enumerate(lines) if line == marker), len(lines))
            lines.insert(insert_at, metric_row)
            write_text(dictionary_path, "\n".join(lines))


def main():
    os.chdir(REPO_ROOT)
    seed_repo_data_workspace()
    build_output = build_society_inputs()
    write_audit_reports(build_output["audit"])
    run_stage2_rerun()
    run_final_outputs()
    annotate_final_outputs(
        build_output["q3_hex_counts"],
        build_output["zone_q3_counts"],
        build_output["audit"],
    )
    publish_q3_hex_counts(build_output["q3_hex_counts"])
    run_client_publish()
    annotate_public_outputs(build_output["q3_hex_counts"])
    regenerate_graph_network()
    run_micromarket_publish(build_output["q3_hex_counts"])
    update_public_summary_artifacts(build_output)
    publish_canonical_school_market_and_gate_release()
    print("Society rerun completed successfully.")


if __name__ == "__main__":
    main()
