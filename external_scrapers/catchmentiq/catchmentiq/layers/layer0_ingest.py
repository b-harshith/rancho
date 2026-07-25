import os
import json
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from datetime import datetime
from catchmentiq.utils.geo_helpers import is_within_bbox, gdf_to_geojson_dict


# BHK code lookup — derived empirically from URL cross-referencing against MagicBricks dataset.
# e.g. bhk_count=11700 in the raw data → 1 BHK (confirmed by "1-BHK" in listing_url)
BHK_CODE_MAP = {
    11700: 1, 11701: 2, 11702: 3, 11703: 4,
    11704: 5, 11705: 6, 11706: 7, 11707: 8,
    11708: 9, 11709: 10
}

# Board confidence → first-class signal for school partnership scoring.
# IB/IGCSE parents are almost definitionally Rancho Labs' audience.
BOARD_CONFIDENCE = {
    "IB": 1.0, "IGCSE": 1.0, "Cambridge": 0.85,
    "ICSE": 0.75, "CBSE": 0.5, "State": 0.2
}

# Grade levels order for proportional student count estimation
GRADE_ORDER = {
    "toddler": -3,
    "playgroup": -2,
    "pre nursery": -2,
    "pre-nursery": -2,
    "nursery": -1,
    "lkg": 0,
    "ukg": 1,
    "1": 2, "1 class": 2,
    "2": 3, "2 class": 3,
    "3": 4, "3 class": 4,
    "4": 5, "4 class": 5,
    "5": 6, "5 class": 6,
    "6": 7, "6 class": 7,
    "7": 8, "7 class": 8,
    "8": 9, "8 class": 9,
    "9": 10, "9 class": 10,
    "10": 11, "10 class": 11,
    "11": 12, "11 class": 12,
    "12": 13, "12 class": 13
}

def _parse_class_level(class_str) -> int:
    if not class_str or not isinstance(class_str, str):
        return None
    c_clean = class_str.lower().strip()
    
    if c_clean in GRADE_ORDER:
        return GRADE_ORDER[c_clean]
        
    import re
    m = re.match(r'^(\d+)', c_clean)
    if m:
        val = int(m.group(1))
        return val + 1  # Map Class 1 to index 2, etc.
        
    if "toddler" in c_clean: return -3
    if "play" in c_clean: return -2
    if "pre" in c_clean: return -2
    if "nurs" in c_clean: return -1
    if "lkg" in c_clean: return 0
    if "ukg" in c_clean: return 1
    if "kg" in c_clean: return 1
    
    return None


def _infer_bhk_from_area(area) -> int:
    """Fallback BHK estimate from covered area (sqft)."""
    try:
        area = float(area)
    except (TypeError, ValueError):
        return 2
    if area < 600:   return 1
    elif area < 1000: return 2
    elif area < 1500: return 3
    elif area < 2200: return 4
    else:             return 5


def _decode_bhk(bhk_raw, area) -> int:
    """Decode raw bhk_count field to integer BHK value."""
    try:
        bhk_int = int(bhk_raw)
    except (TypeError, ValueError):
        return _infer_bhk_from_area(area)

    if bhk_int in BHK_CODE_MAP:
        return BHK_CODE_MAP[bhk_int]
    elif bhk_int <= 10:       # Already a real BHK count
        return bhk_int
    else:                     # Unknown code — fall back to area
        return _infer_bhk_from_area(area)


def run(city_config: dict, logger) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """
    Load, clean, and validate school and real estate data.
    
    Real estate source: processed_bangalore.json (root directory)
    Key field semantics:
      listing_category   → "Residential" | "Commercial"  (we only keep Residential)
      transaction_category → "Rent" | "Buy"              (the true intent field)
      transaction_type   → "Resale" | "New Property" etc (MagicBricks category, NOT used)
      bhk_count          → encoded int (11700–11709) decoded via BHK_CODE_MAP
      price_per_sqft     → per-sqft *rent rate* for Rent; *sale rate* for Buy
    """
    logger.layer_start(0, "Data Ingest & Cleaning")

    bbox = city_config["city"]["bounding_box"]
    max_age_days = city_config["realestate"]["max_listing_age_days"]

    # ────────────────────────────────────────────────────────────
    # 1. Schools Ingest
    # ────────────────────────────────────────────────────────────
    schools_path = "data/raw/schools.json"
    logger.log(f"Loading schools data from {schools_path}...")

    if not os.path.exists(schools_path):
        raise FileNotFoundError(f"Schools raw data not found at {schools_path}")

    with open(schools_path) as f:
        schools_data = json.load(f)

    cleaned_schools = []
    invalid_schools_coords = 0

    for s in schools_data:
        try:
            name = s.get("School Name", "Unnamed School")

            # Board cleaning
            board_str = s.get("Board", "")
            boards = [b.strip() for b in board_str.split(",") if b.strip()] \
                     if isinstance(board_str, str) else []

            # Board confidence — first-class signal flowing into School Partnership Score
            board_scores = [BOARD_CONFIDENCE.get(b, 0.3) for b in boards]
            board_confidence = max(board_scores) if board_scores else 0.3

            # Student count estimation scaling by number of grades
            try:
                student_count_raw = float(s.get("Computed Student Count", 500))
            except (ValueError, TypeError):
                student_count_raw = 500.0

            is_estimated = (s.get("Is Student Count Estimated", "Yes") == "Yes")
            starting_class = s.get("Starting Class")
            ending_class = s.get("Ending Class")
            
            if is_estimated:
                start_lvl = _parse_class_level(starting_class)
                end_lvl = _parse_class_level(ending_class)
                if start_lvl is not None and end_lvl is not None and end_lvl >= start_lvl:
                    num_grades = end_lvl - start_lvl + 1
                    # A full school (Nursery to 12) has 15 grades (level -1 to 13)
                    student_count = int(round(student_count_raw * (num_grades / 15.0)))
                else:
                    student_count = int(round(student_count_raw))
            else:
                student_count = int(round(student_count_raw))

            # Average annual fee
            try:
                avg_fee = float(s.get("Average Fee (Annual)", 0.0))
            except (ValueError, TypeError):
                avg_fee = 0.0

            lat_raw = s.get("Latitude")
            lon_raw = s.get("Longitude")
            if lat_raw is None or lon_raw is None or lat_raw == "NA" or lon_raw == "NA":
                invalid_schools_coords += 1
                continue

            lat, lon = float(lat_raw), float(lon_raw)
            if not is_within_bbox(lat, lon, bbox):
                invalid_schools_coords += 1
                continue

            import hashlib
            school_id = hashlib.md5(f"{name}_{lat}_{lon}".encode()).hexdigest()[:12]

            cleaned_schools.append({
                "id": school_id,
                "name": name,
                "board": boards,
                "board_confidence": board_confidence,
                "student_count": student_count,
                "avg_fee": avg_fee,
                "fee_is_estimated": s.get("Is Fee Estimated", "Yes") == "Yes",
                "student_count_is_estimated": s.get("Is Student Count Estimated", "Yes") == "Yes",
                "starting_class": s.get("Starting Class", "NA"),
                "ending_class": s.get("Ending Class", "NA"),
                "geometry": Point(lon, lat)
            })
        except Exception:
            continue

    schools_gdf = gpd.GeoDataFrame(cleaned_schools, geometry="geometry", crs="EPSG:4326")
    logger.log(
        f"Loaded {len(schools_data)} schools. "
        f"{len(schools_gdf)} valid, {invalid_schools_coords} dropped (bad coords/outside boundary)."
    )

    # Push to live dashboard
    logger.add_points("Schools", gdf_to_geojson_dict(schools_gdf), style={
        "color": "#FF6B35",
        "radius": 5,
        "popup_fields": ["name", "board", "board_confidence", "avg_fee", "student_count"]
    })

    # ────────────────────────────────────────────────────────────
    # 2. Real Estate Ingest — processed_bangalore.json
    # ────────────────────────────────────────────────────────────
    # Field semantics (updated dataset):
    #   listing_category   → "Residential" | "Commercial"
    #   transaction_category → "Rent" | "Buy"  ← use THIS for sale vs rent
    #   transaction_type   → "Resale" | "New Property" | "Rent" (MagicBricks internal, ignore)
    # ────────────────────────────────────────────────────────────
    re_path = "processed_bangalore.json"
    logger.log(f"Loading real estate listings from {re_path}...")

    if not os.path.exists(re_path):
        raise FileNotFoundError(
            f"Real estate data not found at {re_path}. "
            "Expected processed_bangalore.json in project root."
        )

    with open(re_path) as f:
        re_data = json.load(f)

    total_raw = len(re_data)
    commercial_dropped = 0
    invalid_re_coords = 0
    age_filtered_count = 0
    corrected_bhk_count = 0
    cleaned_re = []

    current_date = datetime(2026, 6, 7)

    for item in re_data:
        try:
            # ── Residential-only filter (hard gate, applied first) ──
            listing_category = item.get("listing_category")
            if listing_category != "Residential":
                commercial_dropped += 1
                continue

            # ── Coordinate validation ──
            lat_raw = item.get("latitude")
            lon_raw = item.get("longitude")
            if lat_raw is None or lon_raw is None:
                invalid_re_coords += 1
                continue

            lat, lon = float(lat_raw), float(lon_raw)
            if not is_within_bbox(lat, lon, bbox):
                invalid_re_coords += 1
                continue

            # ── Listing age filter ──
            posted_date_str = item.get("posted_date")
            if posted_date_str:
                try:
                    posted_date = datetime.strptime(str(posted_date_str), "%Y-%m-%d")
                    if (current_date - posted_date).days > max_age_days:
                        age_filtered_count += 1
                        continue
                except ValueError:
                    pass  # keep if date unparseable

            # ── Transaction type — use transaction_category, not transaction_type ──
            # "Buy" → "Sale" for consistency with Layer 3 filter logic
            txn_cat = item.get("transaction_category", "Rent")
            if txn_cat == "Buy":
                transaction_type = "Sale"
            elif txn_cat == "Rent":
                transaction_type = "Rent"
            else:
                continue  # skip ambiguous "Other" records

            # ── BHK decode ──
            bhk_raw = item.get("bhk_count")
            area = item.get("covered_area") or item.get("carpet_area")
            bhk = _decode_bhk(bhk_raw, area)
            if bhk_raw and str(bhk_raw) != str(bhk):
                corrected_bhk_count += 1

            # ── Price ──
            price = float(item.get("price_inr") or 0.0)
            ppsqft = float(item.get("price_per_sqft") or 0.0)

            cleaned_re.append({
                "listing_id":       item.get("listing_id"),
                "transaction_type": transaction_type,       # "Sale" or "Rent"
                "listing_category": "Residential",          # always (commercial dropped)
                "price_inr":        price,
                "price_per_sqft":   ppsqft,
                "bhk":              bhk,
                "covered_area":     area,
                "property_type":    item.get("property_type", "Apartment"),
                "locality":         item.get("locality"),
                "furnishing_status":item.get("furnishing_status", "Semi-Furnished"),
                "is_luxury":        bool(item.get("is_luxury", False)),
                "is_prime_location":bool(item.get("is_prime_location", False)),
                "confidence_score": float(item.get("confidence_score") or 100.0),
                "posted_date":      posted_date_str,
                "geometry":         Point(lon, lat),
                "data_source":      "magicbricks"
            })

        except Exception:
            continue

    re_gdf = gpd.GeoDataFrame(cleaned_re, geometry="geometry", crs="EPSG:4326")

    sale_count = len(re_gdf[re_gdf["transaction_type"] == "Sale"])
    rent_count = len(re_gdf[re_gdf["transaction_type"] == "Rent"])

    logger.log(
        f"Loaded {total_raw} raw listings. "
        f"{commercial_dropped} commercial dropped → {len(re_gdf)} residential kept "
        f"({sale_count} sale, {rent_count} rent)."
    )
    logger.log(f"Filtered out {age_filtered_count} listings older than {max_age_days} days.")
    logger.log(f"BHK codes decoded/corrected: {corrected_bhk_count} records.")

    # Price-per-sqft summary for validation
    re_ppsqft = re_gdf[re_gdf["price_per_sqft"] > 0]["price_per_sqft"]
    if not re_ppsqft.empty:
        logger.log(
            f"price_per_sqft (residential): "
            f"median={re_ppsqft.median():.0f}, "
            f"p75={re_ppsqft.quantile(0.75):.0f}, "
            f"p90={re_ppsqft.quantile(0.90):.0f}"
        )

    # Downsample for dashboard rendering (cap at 1000 points)
    sample_size = min(1000, len(re_gdf))
    re_sample = re_gdf.sample(n=sample_size, random_state=42)
    logger.log(f"Sending {sample_size} sampled listings to map visualisation...")
    logger.add_points("Real Estate (Residential)", gdf_to_geojson_dict(re_sample), style={
        "color": "#3498DB",
        "radius": 3,
        "popup_fields": ["price_inr", "price_per_sqft", "bhk", "property_type", "transaction_type"]
    })

    # Cache to processed/
    os.makedirs("data/processed", exist_ok=True)
    schools_gdf.to_parquet("data/processed/schools_processed.parquet")
    re_gdf.to_parquet("data/processed/realestate_processed.parquet")
    logger.log("Layer 0 results cached to data/processed/", "success")

    logger.layer_end(0, f"{len(schools_gdf)} schools, {len(re_gdf)} residential listings cached")
    return schools_gdf, re_gdf
