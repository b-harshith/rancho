"""
kpi_bangalore.py
----------------
Computes KPIs and stats for the Bangalore real estate dataset (bangalore.jsonl).
All listings are extracted from the `searchResult` array in each record.
"""

import json
import math
from pathlib import Path
from collections import Counter, defaultdict

JSONL_PATH = Path(__file__).parent.parent / "data" / "raw" / "bangalore.jsonl"

# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_float(v):
    try:
        f = float(v)
        return f if math.isfinite(f) and f > 0 else None
    except (TypeError, ValueError):
        return None

def median(lst):
    s = sorted(lst)
    n = len(s)
    return (s[n // 2 - 1] + s[n // 2]) / 2 if n % 2 == 0 else s[n // 2]

def percentile(lst, p):
    s = sorted(lst)
    idx = int(len(s) * p / 100)
    return s[min(idx, len(s) - 1)]

def bar(label, count, total, width=30):
    filled = int(width * count / total) if total else 0
    pct = 100 * count / total if total else 0
    return f"  {label:<35} │{'█' * filled}{' ' * (width - filled)}│ {count:>6,} ({pct:5.1f}%)"

def section(title):
    print(f"\n{'━' * 65}")
    print(f"  {title}")
    print(f"{'━' * 65}")

# ── Load all listings ─────────────────────────────────────────────────────────

print(f"\n📂  Reading {JSONL_PATH.name} …")

listings = []
page_count = 0

with open(JSONL_PATH, encoding="utf-8") as f:
    for raw in f:
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        page_count += 1
        for item in rec.get("searchResult", []) or []:
            if isinstance(item, dict):
                listings.append(item)

total = len(listings)
print(f"✅  Pages: {page_count:,}  |  Total listings: {total:,}\n")

# ── Collect fields ────────────────────────────────────────────────────────────

prices, areas, sqft_prices = [], [], []
transaction_types = Counter()
property_types = Counter()
bedrooms = Counter()
furnished = Counter()
posted_by = Counter()
localities = Counter()
facings = Counter()
floors = Counter()
availability = Counter()
tenants = Counter()
amenity_counts = []

seen_ids = set()
duplicates = 0

for l in listings:
    # Deduplication
    lid = l.get("id") or l.get("encId")
    if lid in seen_ids:
        duplicates += 1
        continue
    seen_ids.add(lid)

    # Price
    p = safe_float(l.get("price"))
    if p:
        prices.append(p)

    # Area (carpet area in sqft)
    a = safe_float(l.get("ca") or l.get("caSqFt") or l.get("carpetArea"))
    if a:
        areas.append(a)

    # Price per sqft
    sp = safe_float(l.get("sqFtPrice") or l.get("sqFtPrD"))
    if sp:
        sqft_prices.append(sp)

    # Categorical
    transaction_types[l.get("transactionTypeD") or l.get("transType") or "Unknown"] += 1
    property_types[l.get("propTypeD") or "Unknown"] += 1
    bedrooms[str(l.get("bedroomD") or "Unknown")] += 1
    furnished[l.get("furnishedD") or "Unknown"] += 1
    posted_by[l.get("userType") or "Unknown"] += 1
    localities[l.get("lmtDName") or l.get("locSeoName") or "Unknown"] += 1
    facings[l.get("facingD") or "Unknown"] += 1
    availability[l.get("possStatusD") or "Unknown"] += 1
    tenants[l.get("tenantsPreference") or "N/A"] += 1

    # Amenities count
    amen = l.get("amenities")
    if amen and isinstance(amen, str):
        amenity_counts.append(len(amen.split()))

unique_total = len(seen_ids)

# ── Print KPIs ────────────────────────────────────────────────────────────────

print("╔" + "═" * 63 + "╗")
print("║" + "  📊  BANGALORE REAL ESTATE — DATASET KPIs".center(63) + "║")
print("╚" + "═" * 63 + "╝")

# ── 1. Overview ───────────────────────────────────────────────────────────────
section("1. OVERVIEW")
print(f"  {'Pages (JSONL records)':<40} {page_count:>10,}")
print(f"  {'Total listing rows':<40} {total:>10,}")
print(f"  {'Unique listings (by ID)':<40} {unique_total:>10,}")
print(f"  {'Duplicate rows':<40} {duplicates:>10,}")

# ── 2. Price Stats ────────────────────────────────────────────────────────────
section("2. PRICE STATS  (₹)")
if prices:
    print(f"  {'Listings with price':<40} {len(prices):>10,}")
    print(f"  {'Min price':<40} ₹{min(prices):>12,.0f}")
    print(f"  {'Max price':<40} ₹{max(prices):>12,.0f}")
    print(f"  {'Mean price':<40} ₹{sum(prices)/len(prices):>12,.0f}")
    print(f"  {'Median price':<40} ₹{median(prices):>12,.0f}")
    print(f"  {'25th percentile':<40} ₹{percentile(prices, 25):>12,.0f}")
    print(f"  {'75th percentile':<40} ₹{percentile(prices, 75):>12,.0f}")
    print(f"  {'90th percentile':<40} ₹{percentile(prices, 90):>12,.0f}")

# ── 3. Area Stats ─────────────────────────────────────────────────────────────
section("3. AREA STATS  (sq ft)")
if areas:
    print(f"  {'Listings with area':<40} {len(areas):>10,}")
    print(f"  {'Min area':<40} {min(areas):>10,.0f} sq ft")
    print(f"  {'Max area':<40} {max(areas):>10,.0f} sq ft")
    print(f"  {'Mean area':<40} {sum(areas)/len(areas):>10,.0f} sq ft")
    print(f"  {'Median area':<40} {median(areas):>10,.0f} sq ft")

# ── 4. Price per sq ft ────────────────────────────────────────────────────────
section("4. PRICE PER SQ FT  (₹)")
if sqft_prices:
    print(f"  {'Listings with ₹/sqft data':<40} {len(sqft_prices):>10,}")
    print(f"  {'Min':<40} ₹{min(sqft_prices):>8,.0f}/sqft")
    print(f"  {'Max':<40} ₹{max(sqft_prices):>8,.0f}/sqft")
    print(f"  {'Mean':<40} ₹{sum(sqft_prices)/len(sqft_prices):>8,.0f}/sqft")
    print(f"  {'Median':<40} ₹{median(sqft_prices):>8,.0f}/sqft")

# ── 5. Transaction Type ───────────────────────────────────────────────────────
section("5. TRANSACTION TYPE")
for label, cnt in transaction_types.most_common():
    print(bar(label, cnt, unique_total))

# ── 6. Property Type ─────────────────────────────────────────────────────────
section("6. PROPERTY TYPE  (Top 15)")
for label, cnt in property_types.most_common(15):
    print(bar(label, cnt, unique_total))

# ── 7. Bedroom Config ─────────────────────────────────────────────────────────
section("7. BEDROOM CONFIGURATION")
for label, cnt in sorted(bedrooms.items(), key=lambda x: (x[0] == "Unknown", x[0])):
    print(bar(f"{label} BHK", cnt, unique_total))

# ── 8. Furnished Status ───────────────────────────────────────────────────────
section("8. FURNISHED STATUS")
for label, cnt in furnished.most_common():
    print(bar(label, cnt, unique_total))

# ── 9. Posted By ──────────────────────────────────────────────────────────────
section("9. LISTED BY")
for label, cnt in posted_by.most_common():
    print(bar(label, cnt, unique_total))

# ── 10. Availability ──────────────────────────────────────────────────────────
section("10. AVAILABILITY / POSSESSION STATUS")
for label, cnt in availability.most_common(10):
    print(bar(label, cnt, unique_total))

# ── 11. Top Localities ────────────────────────────────────────────────────────
section("11. TOP 20 LOCALITIES")
for label, cnt in localities.most_common(20):
    print(bar(label, cnt, unique_total))

# ── 12. Facing Direction ─────────────────────────────────────────────────────
section("12. FACING DIRECTION")
for label, cnt in facings.most_common():
    print(bar(label, cnt, unique_total))

# ── 13. Tenant Preference ─────────────────────────────────────────────────────
section("13. TENANT PREFERENCE  (Rental listings)")
for label, cnt in tenants.most_common():
    print(bar(label, cnt, unique_total))

# ── 14. Amenity Coverage ──────────────────────────────────────────────────────
section("14. AMENITIES COVERAGE")
if amenity_counts:
    print(f"  {'Listings with amenities data':<40} {len(amenity_counts):>10,}")
    print(f"  {'Avg amenities per listing':<40} {sum(amenity_counts)/len(amenity_counts):>10.1f}")
    print(f"  {'Max amenities in a listing':<40} {max(amenity_counts):>10,}")

# ── 15. Data Quality ──────────────────────────────────────────────────────────
section("15. DATA QUALITY / COMPLETENESS")
fields_to_check = {
    "price": "price", "area (ca)": "ca", "locality": "lmtDName",
    "property type": "propTypeD", "bedrooms": "bedroomD", "furnished": "furnishedD",
    "facing": "facingD", "floor": "floorD", "description": "dtldesc",
    "amenities": "amenities", "image count": "imgCt", "latitude": "pmtLat",
}
for label, field in fields_to_check.items():
    count = sum(1 for l in listings if l.get(field) not in (None, "", 0, "0"))
    print(bar(label, count, total))

print(f"\n{'━' * 65}")
print(f"  ✅  KPI analysis complete  |  {unique_total:,} unique listings")
print(f"{'━' * 65}\n")
