"""
process_bangalore.py
--------------------
Reads bangalore.jsonl, extracts + transforms property listings from
`searchResult`, and writes a normalized JSON array to processed_bangalore.json.

Usage:
    python3 process_bangalore.py
    python3 process_bangalore.py /custom/path/bangalore.jsonl /custom/output.json
"""

import json
import re
import sys
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

INPUT_PATH  = Path(sys.argv[1]) if len(sys.argv) > 1 else \
              Path(__file__).parent.parent / "data" / "raw" / "bangalore.jsonl"

OUTPUT_PATH = Path(sys.argv[2]) if len(sys.argv) > 2 else \
              Path(__file__).parent.parent / "data" / "processed" / "processed_bangalore.json"


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def g(d: dict, *keys, default=None):
    """Get first non-None value from a dict for a list of fallback keys."""
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return default


# ── 1. Price Cleaning ─────────────────────────────────────────────────────────

def clean_price(price_val) -> int | None:
    """
    Converts various price formats to integer INR.
      - "2.5 Cr"   -> 25_000_000
      - "50 Lac"   -> 5_000_000
      - "25,000"   -> 25000
      - 25000      -> 25000
    Returns None if value cannot be parsed.
    """
    if price_val is None:
        return None

    s = str(price_val).replace(",", "").strip()

    # Already a plain number (int or float stored as number in JSON)
    if isinstance(price_val, (int, float)) and not isinstance(price_val, bool):
        return int(price_val)

    # Extract numeric portion
    match = re.search(r"[\d.]+", s)
    if not match:
        return None
    num = float(match.group())

    s_lower = s.lower()
    if "cr" in s_lower or "crore" in s_lower:
        return int(num * 10_000_000)
    if "lac" in s_lower or "lakh" in s_lower:
        return int(num * 100_000)
    return int(num)


# ── 2. Coordinate Splitting ───────────────────────────────────────────────────

def split_coordinates(coord_raw) -> tuple[float | None, float | None]:
    """
    Splits "lat,lng" string into (latitude, longitude) floats.
    Returns (None, None) on failure.
    """
    if not coord_raw:
        return None, None
    try:
        parts = str(coord_raw).split(",")
        if len(parts) >= 2:
            lat = float(parts[0].strip())
            lng = float(parts[1].strip())
            # Sanity check: valid geo range
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
    except (ValueError, AttributeError):
        pass
    return None, None


# ── 3. Array Parsing ──────────────────────────────────────────────────────────

def to_list(val) -> list | None:
    """
    Ensures a value is a list.
    - If already a list, return as-is.
    - If a space- or comma-separated string, split and strip.
    - Otherwise return None.
    """
    if val is None:
        return None
    if isinstance(val, list):
        return [str(v).strip() for v in val if str(v).strip()]
    if isinstance(val, str) and val.strip():
        # Try comma-separated first, then space-separated
        sep = "," if "," in val else " "
        return [v.strip() for v in val.split(sep) if v.strip()]
    return None


# ── 4. Numeric Casting ────────────────────────────────────────────────────────

def to_int(val) -> int | None:
    """
    Cast value to int. Handles:
    - Plain int / float  -> int
    - "3 BHK"            -> 3
    - "Ground"           -> 0
    - "G"                -> 0
    """
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return int(val)
    s = str(val).strip().lower()
    if s in ("ground", "g", "g floor", "ground floor"):
        return 0
    match = re.search(r"\d+", s)
    return int(match.group()) if match else None


# ── 5. Boolean Coercion ───────────────────────────────────────────────────────

def to_bool(val) -> bool | None:
    """Coerce 'Y'/'N'/'T'/'F'/'true'/'false'/1/0 to Python bool."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ("y", "yes", "true", "1", "t"):
        return True
    if s in ("n", "no", "false", "0", "f"):
        return False
    return None


# ── 6. Date Normalisation ─────────────────────────────────────────────────────

def clean_date(val) -> str | None:
    """Return ISO-like date string, stripping trailing time noise if needed."""
    if not val:
        return None
    s = str(val).strip()
    # Trim milliseconds/timezone for readability: "2026-04-12T23:45:21.000Z" -> "2026-04-12"
    match = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return match.group(1) if match else s


# ── 7. Listing Category Derivation ──────────────────────────────────────────

COMMERCIAL_TYPES = {
    "Commercial Office Space",
    "Commercial Land",
    "Commercial Shop",
    "Commercial Showroom",
    "Commercial Building",
    "Industrial Land",
    "Industrial Building",
    "Industrial Shed",
    "Office in IT Park/ SEZ",
    "Office in IT Park/SEZ",
    "Retail Shop",
    "Showroom",
    "Warehouse / Godown",
    "Cold Storage",
}

def derive_listing_category(prop_type: str | None) -> str:
    """Returns 'Commercial' or 'Residential' based on property_type."""
    if prop_type and prop_type.strip() in COMMERCIAL_TYPES:
        return "Commercial"
    return "Residential"

def derive_transaction_category(cg_val: str | None) -> str | None:
    """Converts raw cg code to readable transaction category.
       'b' = Buy (covers Resale + New Property + Sale)
       'r' = Rent
    """
    if cg_val is None:
        return None
    mapping = {"b": "Buy", "r": "Rent"}
    return mapping.get(str(cg_val).strip().lower())


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTION & TRANSFORMATION
# ══════════════════════════════════════════════════════════════════════════════

def extract_listing(sr: dict) -> dict:
    """
    Extract, clean and transform one `searchResult` item dict
    into a flat, normalised record.
    """

    # ── Identity Segment ──────────────────────────────────────────────────────
    coord_raw  = g(sr, "ltcoordGeo")
    lat, lng   = split_coordinates(coord_raw)

    record = {
        "listing_id"    : g(sr, "id"),
        "listing_url"   : g(sr, "url"),
        "city"          : g(sr, "ctName"),
        "locality"      : g(sr, "loc", "lmtDName"),
        "latitude"      : lat,
        "longitude"     : lng,
        "project_name"  : g(sr, "prjname", "buildingName"),
        "landmark"      : g(sr, "landmark"),

        # ── Transaction Segment ───────────────────────────────────────────────
        "transaction_type"  : g(sr, "transactionTypeD"),
        "price_inr"         : clean_price(g(sr, "price")),
        "price_per_sqft"    : clean_price(g(sr, "sqFtPrice")),
        "maintenance_inr"   : clean_price(g(sr, "maintenanceCharges")),
        "booking_amount"    : clean_price(g(sr, "bookingAmtExact")),

        # ── Typology Segment ──────────────────────────────────────────────────
        "listing_category"  : derive_listing_category(g(sr, "propTypeD")),
        "transaction_category": derive_transaction_category(g(sr, "cg")),
        "property_type"     : g(sr, "propTypeD"),
        "bhk_count"         : to_int(g(sr, "bd", "bedroomD")),
        "bathroom_count"    : to_int(g(sr, "bathD")),
        "furnishing_status" : g(sr, "furnishedD"),
        "ownership_type"    : g(sr, "OwnershipTypeD"),

        # ── Dimensions Segment ────────────────────────────────────────────────
        "carpet_area"       : to_int(g(sr, "carpetArea")),
        "carpet_area_unit"  : g(sr, "carpetAreaUnit", "carpAreaUnit"),
        "covered_area"      : to_int(g(sr, "coveredArea", "ca", "caSqFt")),
        "possession_status" : g(sr, "possStatusD"),
        "age_of_property"   : g(sr, "opSnD"),
        "floor_number"      : to_int(g(sr, "floorNo")),
        "total_floors"      : to_int(g(sr, "floors")),

        # ── Metadata Segment ──────────────────────────────────────────────────
        "listed_by"           : g(sr, "userType"),
        "posted_date"         : clean_date(g(sr, "postDateT", "listSince")),
        "has_rera"            : to_bool(g(sr, "isRera")),
        "amenities_list"      : to_list(g(sr, "amenities")),
        "luxury_amenities"    : to_list(g(sr, "luxAmenitiesD")),
        "confidence_score"    : to_int(g(sr, "cScore")),
        "is_luxury"           : to_bool(g(sr, "isLuxury")),       # "T"/"F" → bool
        "is_prime_location"   : to_bool(g(sr, "isPrimeLocProp")), # "Y"/"N" → bool
        "tenant_preference"   : g(sr, "tenantsPreference"),       # "Bachelors" / "Family" / "Bachelors/Family"
    }

    return record


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def main():
    if not INPUT_PATH.exists():
        print(f"❌  Input file not found: {INPUT_PATH}")
        sys.exit(1)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n{'═' * 60}")
    print(f"  🚀  Bangalore JSONL → Processed JSON Pipeline")
    print(f"{'═' * 60}")
    print(f"  Input  : {INPUT_PATH}")
    print(f"  Output : {OUTPUT_PATH}")
    print(f"{'─' * 60}\n")

    records      = []
    page_count   = 0
    skip_count   = 0
    error_count  = 0
    seen_ids     = set()
    dup_count    = 0

    REPORT_EVERY = 5_000

    with open(INPUT_PATH, encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue

            # ── Parse line ────────────────────────────────────────────────────
            try:
                page = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"  ⚠  Line {line_no}: JSON parse error — {e}")
                error_count += 1
                continue

            page_count += 1
            search_result = page.get("searchResult")

            # ── Skip if no listings on this page ──────────────────────────────
            if not search_result or not isinstance(search_result, list):
                skip_count += 1
                continue

            # ── Process each listing on this page ─────────────────────────────
            for sr in search_result:
                if not isinstance(sr, dict):
                    continue

                try:
                    rec = extract_listing(sr)
                except Exception as e:
                    print(f"  ⚠  Extraction error on line {line_no}: {e}")
                    error_count += 1
                    continue

                # Deduplicate by listing_id
                lid = rec.get("listing_id")
                if lid and lid in seen_ids:
                    dup_count += 1
                    continue
                if lid:
                    seen_ids.add(lid)

                records.append(rec)

                if len(records) % REPORT_EVERY == 0:
                    print(f"  ✔  Processed {len(records):>7,} unique records  "
                          f"(page {page_count:,} / line {line_no:,}) …")

    # ── Write output ──────────────────────────────────────────────────────────
    print(f"\n  💾  Writing {len(records):,} records to JSON …")
    with open(OUTPUT_PATH, "w", encoding="utf-8") as out:
        json.dump(records, out, indent=2, ensure_ascii=False)

    file_mb = OUTPUT_PATH.stat().st_size / (1024 * 1024)

    print(f"\n{'═' * 60}")
    print(f"  ✅  Pipeline complete!")
    print(f"{'─' * 60}")
    print(f"  Pages processed      : {page_count:>10,}")
    print(f"  Pages skipped        : {skip_count:>10,}")
    print(f"  Parse / extract errors: {error_count:>9,}")
    print(f"  Duplicate listings   : {dup_count:>10,}")
    print(f"  ──────────────────────────────────")
    print(f"  ✨ Unique records written : {len(records):>6,}")
    print(f"  📦 Output file size  : {file_mb:>9.2f} MB")
    print(f"  📁 Saved to          : {OUTPUT_PATH}")
    print(f"{'═' * 60}\n")


if __name__ == "__main__":
    main()
