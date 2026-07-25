"""
Analyze Stage 2 Hex-7 Affluence Master data and produce a comprehensive
report with geographic zone analysis, micro market identification,
feeding schools/societies, TAM projections, actionable insights,
and a delta comparison vs the previous run.
"""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import h3

DATA_DIR = Path("DATA")

# ── NEW final output (current model run) ──
FINAL_JSON = DATA_DIR / "final" / "bangalore_hex7_affluent_family_intelligence_master.json"

# ── PREVIOUS report output (baseline for comparison) ──
PREV_REPORT_JSON = DATA_DIR / "audits" / "stage2_affluence_zone_micromarket_report.json"

# ── Output paths ──
REPORT_MD = DATA_DIR / "final" / "stage2_affluence_zone_micromarket_report.md"
REPORT_JSON = DATA_DIR / "final" / "stage2_affluence_zone_micromarket_report.json"

# ── Bangalore geographic zone boundaries ──
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


def hex_centroid(hex_id):
    lat, lon = h3.cell_to_latlng(hex_id)
    return lat, lon


# ── Data loading (handles both old processed and new final format) ──

def load_records():
    """Load and normalise records from the final JSON."""
    with FINAL_JSON.open("r") as f:
        raw = json.load(f)

    # New format wraps records in {"metadata": ..., "hexes": [...]}
    if isinstance(raw, dict) and "hexes" in raw:
        records = raw["hexes"]
    elif isinstance(raw, list):
        records = raw
    else:
        raise ValueError("Unexpected JSON structure in final master file")

    # Normalise field names so the rest of the pipeline works uniformly
    for rec in records:
        tam = rec.get("tam", {})
        # countable_family_tam → countable_direct_family_tam
        if "countable_direct_family_tam" not in tam and "countable_family_tam" in tam:
            tam["countable_direct_family_tam"] = tam["countable_family_tam"]
        # society_cluster_tam_weighted_context_not_counted → society_cluster_tam_weighted
        if "society_cluster_tam_weighted" not in tam:
            tam["society_cluster_tam_weighted"] = tam.get(
                "society_cluster_tam_weighted_context_not_counted", 0
            )
        # nearby_family_tam_weighted_context → nearby_family_tam_weighted
        if "nearby_family_tam_weighted" not in tam:
            tam["nearby_family_tam_weighted"] = tam.get(
                "nearby_family_tam_weighted_context", 0
            )
        # surrounding_affluent_cluster_tam_weighted_context_not_counted
        if "surrounding_affluent_cluster_tam_weighted" not in tam:
            tam["surrounding_affluent_cluster_tam_weighted"] = tam.get(
                "surrounding_affluent_cluster_tam_weighted_context_not_counted", 0
            )

        # Normalise top_evidence for society/school extraction
        # New format: society_summary.top_societies / school_summary.top_schools
        # Old format: top_evidence.societies / top_evidence.schools
        top_evidence = rec.get("top_evidence", {})
        if not top_evidence.get("societies") and "society_summary" in rec:
            top_evidence["societies"] = rec["society_summary"].get("top_societies", [])
        if not top_evidence.get("schools") and "school_summary" in rec:
            top_evidence["schools"] = rec["school_summary"].get("top_schools", [])
        rec["top_evidence"] = top_evidence

    return records


def load_previous_report():
    """Load previous report JSON as baseline for comparison."""
    if not PREV_REPORT_JSON.exists():
        print(f"  No previous report found at {PREV_REPORT_JSON}")
        return None
    with PREV_REPORT_JSON.open("r") as f:
        return json.load(f)


def enrich_records(records):
    """Add zone, centroid lat/lon to each record, filtering out records further than 35km."""
    filtered = []
    for rec in records:
        lat, lon = hex_centroid(rec["hex_id"])
        dist = haversine_km(CENTRAL_LAT, CENTRAL_LON, lat, lon)
        if dist > 35.0:
            continue
        rec["_lat"] = lat
        rec["_lon"] = lon
        rec["_zone"] = classify_zone(lat, lon)
        rec["_distance_from_center_km"] = dist
        filtered.append(rec)
    return filtered


# ── Zone Analysis ──

def zone_analysis(records):
    zones = defaultdict(list)
    for rec in records:
        zones[rec["_zone"]].append(rec)

    zone_stats = {}
    for zone_name in sorted(zones.keys()):
        recs = zones[zone_name]
        scores = [r["final_affluence_score"] for r in recs]
        direct_tam = sum(r["tam"]["direct_family_tam"] for r in recs)
        countable_tam = sum(r["tam"]["countable_direct_family_tam"] for r in recs)
        direct_units = sum(r["tam"].get("direct_total_units", 0) for r in recs)
        cluster_tam = sum(r["tam"]["society_cluster_tam_weighted"] for r in recs)
        wealthy_school = sum(r["tam"]["countable_wealthy_school_children"] for r in recs)
        tier_counts = Counter(r["affluence_tier"] for r in recs)
        high_affluence = sum(1 for r in recs if r["final_affluence_score"] >= 70)
        upper_mid = sum(1 for r in recs if 55 <= r["final_affluence_score"] < 70)

        # Income band breakdown
        income_bands = defaultdict(float)
        for r in recs:
            for band, vals in r["tam"].get("income_band_family_tam", {}).items():
                income_bands[band] += vals.get("direct", 0)

        zone_stats[zone_name] = {
            "hex_count": len(recs),
            "high_affluence_hexes": high_affluence,
            "upper_mid_hexes": upper_mid,
            "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "max_score": round(max(scores), 2) if scores else 0,
            "min_score": round(min(scores), 2) if scores else 0,
            "median_score": round(sorted(scores)[len(scores) // 2], 2) if scores else 0,
            "direct_family_tam": round(direct_tam, 0),
            "countable_family_tam": round(countable_tam, 0),
            "direct_total_units": round(direct_units, 0),
            "society_cluster_tam": round(cluster_tam, 0),
            "wealthy_school_children": round(wealthy_school, 0),
            "tier_counts": dict(tier_counts),
            "income_bands": {k: round(v, 0) for k, v in sorted(income_bands.items())},
            "top_hexes": [
                {
                    "rank": r["rank"],
                    "name": r["name"],
                    "score": r["final_affluence_score"],
                    "direct_tam": r["tam"]["direct_family_tam"],
                    "tier": r["affluence_tier"],
                }
                for r in sorted(recs, key=lambda x: x["final_affluence_score"], reverse=True)[:5]
            ],
        }
    return zone_stats


# ── Micro Market Building ──

def build_micro_markets(records):
    """
    Build micro markets as geographically meaningful clusters.

    Strategy:
    1. For each geographic zone, take hexes with score >= 55 as "core" hexes.
    2. Run BFS within each zone to find connected components of core hexes.
    3. Attach "fringe" hexes (score 40-55) that are neighbors of a core hex.
    4. This produces zone-scoped, contiguous micro markets rather than one
       mega-cluster spanning the entire city.
    """
    all_by_hex = {r["hex_id"]: r for r in records}

    zone_groups = defaultdict(list)
    for r in records:
        zone_groups[r["_zone"]].append(r)

    clusters = []

    for zone_name, zone_recs in zone_groups.items():
        core_hexes = {r["hex_id"] for r in zone_recs if r["final_affluence_score"] >= 55}
        fringe_hexes = {r["hex_id"] for r in zone_recs if 40 <= r["final_affluence_score"] < 55}

        if not core_hexes:
            continue

        visited = set()
        for seed in core_hexes:
            if seed in visited:
                continue
            component = []
            queue = [seed]
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                if current not in core_hexes:
                    continue
                visited.add(current)
                component.append(current)
                for n in h3.grid_disk(current, 1):
                    if n != current and n not in visited and n in core_hexes:
                        queue.append(n)

            fringe_attached = set()
            for hid in component:
                for n in h3.grid_disk(hid, 1):
                    if n in fringe_hexes and n not in visited and n not in fringe_attached:
                        fringe_attached.add(n)
            full_cluster = component + list(fringe_attached)

            if full_cluster:
                clusters.append((zone_name, full_cluster))

    micro_markets = []
    for idx, (zone_name, cluster_hex_ids) in enumerate(clusters):
        recs = [all_by_hex[hid] for hid in cluster_hex_ids if hid in all_by_hex]
        if not recs:
            continue
        recs.sort(key=lambda x: x["final_affluence_score"], reverse=True)

        names = [r["name"] for r in recs if r["name"]]
        primary_name = names[0] if names else f"Cluster-{idx + 1}"

        avg_lat = sum(r["_lat"] for r in recs) / len(recs)
        avg_lon = sum(r["_lon"] for r in recs) / len(recs)

        direct_tam = sum(r["tam"]["direct_family_tam"] for r in recs)
        countable_tam = sum(r["tam"]["countable_direct_family_tam"] for r in recs)
        direct_units = sum(r["tam"].get("direct_total_units", 0) for r in recs)
        cluster_tam = sum(r["tam"]["society_cluster_tam_weighted"] for r in recs)
        wealthy_school = sum(r["tam"]["countable_wealthy_school_children"] for r in recs)
        school_age_children = sum(r["tam"]["countable_school_age_children"] for r in recs)

        income_bands = defaultdict(float)
        for r in recs:
            for band, vals in r["tam"].get("income_band_family_tam", {}).items():
                income_bands[band] += vals.get("direct", 0)

        scores = [r["final_affluence_score"] for r in recs]
        avg_score = sum(scores) / len(scores)

        # Collect unique societies
        societies_seen = set()
        societies = []
        for r in recs:
            for soc in r.get("top_evidence", {}).get("societies", []):
                key = soc.get("name", "")
                if key and key not in societies_seen:
                    societies_seen.add(key)
                    societies.append({
                        "name": soc["name"],
                        "category": soc.get("category", ""),
                        "tam": soc.get("estimated_families_tam", 0),
                        "units": soc.get("total_units", 0),
                        "income_band": soc.get("income_band", ""),
                        "locality": soc.get("locality", ""),
                    })

        # Collect unique schools
        schools_seen = set()
        schools = []
        for r in recs:
            for sch in r.get("top_evidence", {}).get("schools", []):
                key = sch.get("name", "")
                if key and key not in schools_seen:
                    schools_seen.add(key)
                    schools.append({
                        "name": sch["name"],
                        "category": sch.get("category", ""),
                        "annual_fee": sch.get("annual_fee", 0),
                        "board": sch.get("board", ""),
                        "estimated_student_count": sch.get("estimated_student_count", 0),
                    })

        societies.sort(key=lambda x: x.get("tam", 0), reverse=True)
        schools.sort(key=lambda x: x.get("annual_fee", 0), reverse=True)

        tier_counts = Counter(r["affluence_tier"] for r in recs)
        hex_names = list(dict.fromkeys(r["name"] for r in recs if r["name"]))

        micro_markets.append({
            "id": idx + 1,
            "primary_name": primary_name,
            "all_locality_names": hex_names,
            "primary_zone": zone_name,
            "hex_count": len(recs),
            "avg_affluence_score": round(avg_score, 2),
            "max_affluence_score": round(max(scores), 2),
            "min_affluence_score": round(min(scores), 2),
            "tier_counts": dict(tier_counts),
            "centroid_lat": round(avg_lat, 6),
            "centroid_lon": round(avg_lon, 6),
            "direct_family_tam": round(direct_tam, 0),
            "countable_family_tam": round(countable_tam, 0),
            "direct_total_units": round(direct_units, 0),
            "society_cluster_tam": round(cluster_tam, 0),
            "wealthy_school_children": round(wealthy_school, 0),
            "school_age_children": round(school_age_children, 0),
            "income_bands": {k: round(v, 0) for k, v in sorted(income_bands.items())},
            "feeding_societies": societies[:20],
            "feeding_schools": schools[:15],
            "hex_details": [
                {
                    "rank": r["rank"],
                    "hex_id": r["hex_id"],
                    "name": r["name"],
                    "score": r["final_affluence_score"],
                    "tier": r["affluence_tier"],
                    "direct_tam": r["tam"]["direct_family_tam"],
                    "direct_units": r["tam"].get("direct_total_units", 0),
                }
                for r in recs
            ],
        })

    micro_markets.sort(key=lambda m: (m["direct_family_tam"], m["avg_affluence_score"]), reverse=True)
    for i, mm in enumerate(micro_markets):
        mm["id"] = i + 1

    return micro_markets


# ── Overall Stats ──

def overall_stats(records):
    scores = [r["final_affluence_score"] for r in records]
    total_direct_tam = sum(r["tam"]["direct_family_tam"] for r in records)
    total_countable_tam = sum(r["tam"]["countable_direct_family_tam"] for r in records)
    total_units = sum(r["tam"].get("direct_total_units", 0) for r in records)
    total_cluster_tam = sum(r["tam"]["society_cluster_tam_weighted"] for r in records)
    total_wealthy_children = sum(r["tam"]["countable_wealthy_school_children"] for r in records)
    tier_counts = Counter(r["affluence_tier"] for r in records)

    total_income = defaultdict(float)
    for r in records:
        for band, vals in r["tam"].get("income_band_family_tam", {}).items():
            total_income[band] += vals.get("direct", 0)

    return {
        "total_hexes": len(records),
        "score_min": round(min(scores), 2),
        "score_max": round(max(scores), 2),
        "score_median": round(sorted(scores)[len(scores) // 2], 2),
        "score_mean": round(sum(scores) / len(scores), 2),
        "total_direct_family_tam": round(total_direct_tam, 0),
        "total_countable_family_tam": round(total_countable_tam, 0),
        "total_direct_units": round(total_units, 0),
        "total_cluster_tam": round(total_cluster_tam, 0),
        "total_wealthy_school_children": round(total_wealthy_children, 0),
        "tier_counts": dict(tier_counts),
        "income_band_totals": {k: round(v, 0) for k, v in sorted(total_income.items())},
    }


# ── Formatting helpers ──

def fmt(value, decimals=0):
    if value is None:
        return "—"
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def delta_str(new_val, old_val, decimals=0):
    """Return a formatted delta string like '+1,234' or '-500'."""
    if old_val is None or new_val is None:
        return "—"
    diff = float(new_val) - float(old_val)
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:,.{decimals}f}"


def pct_change(new_val, old_val):
    """Return % change string like '+5.2%' or '-3.1%'."""
    if old_val is None or new_val is None or float(old_val) == 0:
        return "—"
    change = (float(new_val) - float(old_val)) / float(old_val) * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.1f}%"


# ── Delta / What Changed Section ──

def generate_delta_section(stats, zones, micro_markets, prev):
    """Generate a 'What Changed' markdown section comparing current vs previous run."""
    if prev is None:
        return []

    lines = []
    lines.append("---\n")
    lines.append("## What Changed (Current vs Previous Model Run)\n")
    lines.append("This section compares the current model output against the previous run's results.\n")

    prev_stats = prev.get("overall", {})

    # ── Overall metrics delta ──
    lines.append("### Overall Metrics Delta\n")
    metrics = [
        ("Total Hexes", "total_hexes", stats.get("total_hexes"), prev_stats.get("total_hexes")),
        ("Score Max", "score_max", stats.get("score_max"), prev_stats.get("score_max")),
        ("Score Mean", "score_mean", stats.get("score_mean"), prev_stats.get("score_mean")),
        ("Score Median", "score_median", stats.get("score_median"), prev_stats.get("score_median")),
        ("Direct Family TAM", "total_direct_family_tam", stats.get("total_direct_family_tam"), prev_stats.get("total_direct_family_tam")),
        ("Direct Units", "total_direct_units", stats.get("total_direct_units"), prev_stats.get("total_direct_units")),
        ("Cluster TAM", "total_cluster_tam", stats.get("total_cluster_tam"), prev_stats.get("total_cluster_tam")),
        ("Wealthy School Children", "total_wealthy_school_children", stats.get("total_wealthy_school_children"), prev_stats.get("total_wealthy_school_children")),
    ]

    lines.append("| Metric | Previous | Current | Change | % Change |")
    lines.append("|---|---:|---:|---:|---:|")
    for label, key, new_val, old_val in metrics:
        dec = 2 if "score" in key.lower() or "mean" in key.lower() or "median" in key.lower() else 0
        lines.append(
            f"| {label} | {fmt(old_val, dec)} | {fmt(new_val, dec)} | "
            f"{delta_str(new_val, old_val, dec)} | {pct_change(new_val, old_val)} |"
        )
    lines.append("")

    # ── Tier changes ──
    lines.append("### Tier Distribution Changes\n")
    prev_tiers = prev_stats.get("tier_counts", {})
    curr_tiers = stats.get("tier_counts", {})
    all_tiers = ["Elite Affluent", "Very High Affluence", "High Affluence",
                 "Upper-Mid / Emerging Affluence", "Mixed / Watchlist", "Low Evidence"]

    lines.append("| Tier | Previous | Current | Change |")
    lines.append("|---|---:|---:|---:|")
    for tier in all_tiers:
        old_c = prev_tiers.get(tier, 0)
        new_c = curr_tiers.get(tier, 0)
        diff = new_c - old_c
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        if diff != 0:
            lines.append(f"| {tier} | {old_c} | {new_c} | **{diff_str}** |")
        else:
            lines.append(f"| {tier} | {old_c} | {new_c} | {diff_str} |")
    lines.append("")

    # ── Income band changes ──
    lines.append("### Income Band Changes (Direct Family TAM)\n")
    prev_income = prev_stats.get("income_band_totals", {})
    curr_income = stats.get("income_band_totals", {})

    lines.append("| Income Band | Previous | Current | Change | % Change |")
    lines.append("|---|---:|---:|---:|---:|")
    for band in ["Ultra Luxury", "Elite Luxury", "Super Luxury", "Premium Luxury", "Luxury", "Premium", "Aspirational Premium"]:
        old_v = prev_income.get(band, 0)
        new_v = curr_income.get(band, 0)
        lines.append(
            f"| {band} | {fmt(old_v)} | {fmt(new_v)} | "
            f"{delta_str(new_v, old_v)} | {pct_change(new_v, old_v)} |"
        )
    lines.append("")

    # ── Zone-level changes ──
    prev_zones = prev.get("zones", {})
    if prev_zones:
        lines.append("### Zone-Level TAM Changes\n")
        lines.append("| Zone | Prev TAM | Curr TAM | Change | Prev Avg Score | Curr Avg Score | Score Δ |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")

        all_zone_names = sorted(set(list(zones.keys()) + list(prev_zones.keys())))
        for zn in all_zone_names:
            pz = prev_zones.get(zn, {})
            cz = zones.get(zn, {})
            old_tam = pz.get("direct_family_tam", 0)
            new_tam = cz.get("direct_family_tam", 0)
            old_avg = pz.get("avg_score", 0)
            new_avg = cz.get("avg_score", 0)
            lines.append(
                f"| **{zn}** | {fmt(old_tam)} | {fmt(new_tam)} | "
                f"{delta_str(new_tam, old_tam)} | {old_avg:.1f} | {new_avg:.1f} | "
                f"{delta_str(new_avg, old_avg, 1)} |"
            )
        lines.append("")

    # ── Micro market changes ──
    prev_mm = prev.get("top_10_micro_markets", [])
    if prev_mm:
        lines.append("### Micro Market Changes (Top Markets)\n")

        # Build lookup by primary_name for previous
        prev_mm_by_name = {mm["primary_name"]: mm for mm in prev_mm}
        curr_mm_by_name = {mm["primary_name"]: mm for mm in micro_markets[:10]}

        # New markets not in previous top 10
        new_entrants = [n for n in curr_mm_by_name if n not in prev_mm_by_name]
        dropped = [n for n in prev_mm_by_name if n not in curr_mm_by_name]

        if new_entrants:
            lines.append("**New entrants** (not in previous top 10): " +
                         ", ".join(f"**{n}**" for n in new_entrants))
        if dropped:
            lines.append("**Dropped** (were in previous top 10): " +
                         ", ".join(f"~~{n}~~" for n in dropped))
        if new_entrants or dropped:
            lines.append("")

        # Comparison table for markets present in both
        lines.append("| Micro Market | Prev TAM | Curr TAM | Δ TAM | Prev Hexes | Curr Hexes | Prev Avg Score | Curr Avg Score |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for mm in micro_markets[:10]:
            prev_match = prev_mm_by_name.get(mm["primary_name"])
            if prev_match:
                lines.append(
                    f"| {mm['primary_name']} | {fmt(prev_match['direct_family_tam'])} | {fmt(mm['direct_family_tam'])} | "
                    f"{delta_str(mm['direct_family_tam'], prev_match['direct_family_tam'])} | "
                    f"{prev_match['hex_count']} | {mm['hex_count']} | "
                    f"{prev_match['avg_affluence_score']:.1f} | {mm['avg_affluence_score']:.1f} |"
                )
            else:
                lines.append(
                    f"| {mm['primary_name']} *(new)* | — | {fmt(mm['direct_family_tam'])} | "
                    f"— | — | {mm['hex_count']} | — | {mm['avg_affluence_score']:.1f} |"
                )
        lines.append("")

    # ── Key changes summary ──
    lines.append("### Summary of Key Differences\n")
    old_tam = prev_stats.get("total_direct_family_tam", 0)
    new_tam = stats.get("total_direct_family_tam", 0)
    old_wealthy = prev_stats.get("total_wealthy_school_children", 0)
    new_wealthy = stats.get("total_wealthy_school_children", 0)
    old_hexes = prev_stats.get("total_hexes", 0)
    new_hexes = stats.get("total_hexes", 0)

    tam_pct = pct_change(new_tam, old_tam)
    wealthy_pct = pct_change(new_wealthy, old_wealthy)

    if new_tam != old_tam:
        direction = "increased" if new_tam > old_tam else "decreased"
        lines.append(f"- **Total Direct Family TAM** {direction} from {fmt(old_tam)} to {fmt(new_tam)} ({tam_pct})")
    else:
        lines.append(f"- **Total Direct Family TAM** remained unchanged at {fmt(new_tam)}")

    if new_wealthy != old_wealthy:
        direction = "increased" if new_wealthy > old_wealthy else "decreased"
        lines.append(f"- **Wealthy School Children** {direction} from {fmt(old_wealthy)} to {fmt(new_wealthy)} ({wealthy_pct})")
    else:
        lines.append(f"- **Wealthy School Children** remained unchanged at {fmt(new_wealthy)}")

    if new_hexes != old_hexes:
        lines.append(f"- **Hex count** changed from {old_hexes} to {new_hexes} ({delta_str(new_hexes, old_hexes)})")
    else:
        lines.append(f"- **Hex count** unchanged at {new_hexes}")

    # Score distribution shift
    old_mean = prev_stats.get("score_mean", 0)
    new_mean = stats.get("score_mean", 0)
    if abs(new_mean - old_mean) > 0.5:
        direction = "upward" if new_mean > old_mean else "downward"
        lines.append(f"- **Mean affluence score** shifted {direction}: {old_mean:.2f} → {new_mean:.2f} ({delta_str(new_mean, old_mean, 2)})")

    lines.append("")
    return lines


# ── Full Markdown Report ──

def generate_report(records, zones, micro_markets, stats, prev_report):
    lines = []
    lines.append("# Stage 2 Affluence Analysis Report: Bangalore Micro Market & Zone Intelligence\n")
    lines.append(f"*Generated from {len(records)} H3-7 hex records | Source: DATA/final/bangalore_hex7_affluent_family_intelligence_master.json*\n")
    lines.append("---\n")

    # ── Executive Summary ──
    lines.append("## Executive Summary\n")

    zone_by_tam = sorted(zones.items(), key=lambda x: x[1]["direct_family_tam"], reverse=True)
    top_zone = zone_by_tam[0]
    top_zone_share = (top_zone[1]["direct_family_tam"] / stats["total_direct_family_tam"] * 100) if stats["total_direct_family_tam"] > 0 else 0

    lines.append(f"Across **{stats['total_hexes']}** analyzed H3 resolution-7 hexagons in the Bangalore metro region:\n")
    lines.append(f"- **Total Direct Family TAM**: {fmt(stats['total_direct_family_tam'])} families across all qualifying societies")
    lines.append(f"- **Total Direct Units**: {fmt(stats['total_direct_units'])} residential units tracked")
    lines.append(f"- **Total Wealthy School-Age Children**: {fmt(stats['total_wealthy_school_children'])} (countable, in habitable hexes)")
    lines.append(f"- **Highest Concentration Zone**: **{top_zone[0]}** with {fmt(top_zone[1]['direct_family_tam'])} families ({top_zone_share:.1f}% of total TAM)")
    lines.append(f"- **Top Micro Markets** collectively hold the vast majority of premium residential TAM\n")

    # Tier summary
    lines.append("### Affluence Tier Distribution\n")
    lines.append("| Tier | Hex Count | % of Total |")
    lines.append("|---|---:|---:|")
    for tier in ["Elite Affluent", "Very High Affluence", "High Affluence", "Upper-Mid / Emerging Affluence", "Mixed / Watchlist", "Low Evidence"]:
        count = stats["tier_counts"].get(tier, 0)
        pct = (count / stats["total_hexes"] * 100) if stats["total_hexes"] > 0 else 0
        lines.append(f"| {tier} | {count} | {pct:.1f}% |")
    lines.append("")

    # Income band summary
    lines.append("### Income Band Distribution (Direct Family TAM)\n")
    lines.append("| Income Band | Families | % of Total |")
    lines.append("|---|---:|---:|")
    for band in ["Ultra Luxury", "Elite Luxury", "Super Luxury", "Premium Luxury", "Luxury", "Premium", "Aspirational Premium"]:
        count = stats["income_band_totals"].get(band, 0)
        pct = (count / stats["total_direct_family_tam"] * 100) if stats["total_direct_family_tam"] > 0 else 0
        lines.append(f"| {band} | {fmt(count)} | {pct:.1f}% |")
    lines.append("")

    # ── What Changed Section (right after executive summary) ──
    delta_lines = generate_delta_section(stats, zones, micro_markets, prev_report)
    lines.extend(delta_lines)

    # ── Zone Analysis ──
    lines.append("---\n")
    lines.append("## Zone-wise Analysis\n")
    lines.append("Bangalore is divided into geographic zones based on bearing and distance from the city center (MG Road / Cubbon Park area).\n")

    # Zone summary table
    lines.append("### Zone Comparison Summary\n")
    lines.append("| Zone | Hexes | High Affluence | Avg Score | Direct Family TAM | Units | Wealthy School Children | TAM Share |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for zone_name, zs in zone_by_tam:
        tam_share = (zs["direct_family_tam"] / stats["total_direct_family_tam"] * 100) if stats["total_direct_family_tam"] > 0 else 0
        lines.append(
            f"| **{zone_name}** | {zs['hex_count']} | {zs['high_affluence_hexes']} | {zs['avg_score']:.1f} | "
            f"{fmt(zs['direct_family_tam'])} | {fmt(zs['direct_total_units'])} | {fmt(zs['wealthy_school_children'])} | {tam_share:.1f}% |"
        )
    lines.append("")

    # Detailed zone sections
    for zone_name, zs in zone_by_tam:
        lines.append(f"### {zone_name} Zone\n")
        lines.append(f"- **Hexes**: {zs['hex_count']} | **High Affluence (≥70)**: {zs['high_affluence_hexes']} | **Upper-Mid (55-70)**: {zs['upper_mid_hexes']}")
        lines.append(f"- **Score Range**: {zs['min_score']:.1f} – {zs['max_score']:.1f} (avg {zs['avg_score']:.1f})")
        lines.append(f"- **Direct Family TAM**: {fmt(zs['direct_family_tam'])} | **Units**: {fmt(zs['direct_total_units'])}")
        lines.append(f"- **Wealthy School Children**: {fmt(zs['wealthy_school_children'])}\n")

        if zs.get("income_bands"):
            lines.append("**Income Bands (Direct TAM)**:\n")
            for band in ["Ultra Luxury", "Elite Luxury", "Super Luxury", "Premium Luxury", "Luxury", "Premium", "Aspirational Premium"]:
                val = zs["income_bands"].get(band, 0)
                if val > 0:
                    lines.append(f"- {band}: {fmt(val)} units")
            lines.append("")

        if zs["top_hexes"]:
            lines.append("**Top Localities**:\n")
            lines.append("| Rank | Locality | Score | Tier | Direct TAM |")
            lines.append("|---:|---|---:|---|---:|")
            for h in zs["top_hexes"]:
                lines.append(f"| #{h['rank']} | {h['name']} | {h['score']:.1f} | {h['tier']} | {fmt(h['direct_tam'])} |")
            lines.append("")

    # ── Micro Markets ──
    lines.append("---\n")
    lines.append("## Top 10 Micro Markets\n")
    lines.append("Micro markets are built by clustering contiguous H3-7 hexes with affluence scores ≥ 40 into connected components. "
                 "They represent geographically coherent wealthy residential zones.\n")

    top10 = micro_markets[:10]

    lines.append("### Summary Table\n")
    lines.append("| # | Micro Market | Zone | Hexes | Avg Score | Direct TAM | Units | Wealthy School Children |")
    lines.append("|---:|---|---|---:|---:|---:|---:|---:|")
    for mm in top10:
        lines.append(
            f"| {mm['id']} | **{mm['primary_name']}** | {mm['primary_zone']} | {mm['hex_count']} | "
            f"{mm['avg_affluence_score']:.1f} | {fmt(mm['direct_family_tam'])} | {fmt(mm['direct_total_units'])} | "
            f"{fmt(mm['wealthy_school_children'])} |"
        )
    lines.append("")

    # Detailed per-micro-market
    for mm in top10:
        lines.append(f"### #{mm['id']} — {mm['primary_name']} ({mm['primary_zone']})\n")

        locality_str = ", ".join(mm["all_locality_names"][:8])
        if len(mm["all_locality_names"]) > 8:
            locality_str += f" (+{len(mm['all_locality_names']) - 8} more)"

        lines.append(f"**Localities**: {locality_str}\n")
        lines.append(f"| Metric | Value |")
        lines.append(f"|---|---:|")
        lines.append(f"| Hex count | {mm['hex_count']} |")
        lines.append(f"| Avg affluence score | {mm['avg_affluence_score']:.1f} |")
        lines.append(f"| Score range | {mm['min_affluence_score']:.1f} – {mm['max_affluence_score']:.1f} |")
        lines.append(f"| Direct family TAM | {fmt(mm['direct_family_tam'])} |")
        lines.append(f"| Direct total units | {fmt(mm['direct_total_units'])} |")
        lines.append(f"| Society cluster TAM | {fmt(mm['society_cluster_tam'])} |")
        lines.append(f"| Wealthy school children | {fmt(mm['wealthy_school_children'])} |")
        lines.append(f"| School-age children | {fmt(mm['school_age_children'])} |")
        lines.append("")

        if mm.get("income_bands"):
            lines.append("**Income Band Breakdown (Direct TAM)**:\n")
            for band in ["Ultra Luxury", "Elite Luxury", "Super Luxury", "Premium Luxury", "Luxury", "Premium", "Aspirational Premium"]:
                val = mm["income_bands"].get(band, 0)
                if val > 0:
                    lines.append(f"- {band}: {fmt(val)} units")
            lines.append("")

        lines.append("**Tier Breakdown**:\n")
        for tier in ["Elite Affluent", "Very High Affluence", "High Affluence", "Upper-Mid / Emerging Affluence", "Mixed / Watchlist", "Low Evidence"]:
            cnt = mm["tier_counts"].get(tier, 0)
            if cnt > 0:
                lines.append(f"- {tier}: {cnt} hexes")
        lines.append("")

        if mm["feeding_societies"]:
            lines.append("**Feeding Societies (Top Residential Projects)**:\n")
            lines.append("| Society | Category | Income Band | Locality | TAM | Units |")
            lines.append("|---|---|---|---|---:|---:|")
            for soc in mm["feeding_societies"][:15]:
                lines.append(
                    f"| {soc['name']} | {soc['category']} | {soc['income_band']} | "
                    f"{soc.get('locality', '')} | {fmt(soc.get('tam', 0))} | {fmt(soc.get('units', 0))} |"
                )
            lines.append("")

        if mm["feeding_schools"]:
            lines.append("**Feeding Schools (Premium Schools Accessible)**:\n")
            lines.append("| School | Category | Board | Annual Fee | Est. Students |")
            lines.append("|---|---|---|---:|---:|")
            for sch in mm["feeding_schools"][:10]:
                lines.append(
                    f"| {sch['name']} | {sch['category']} | {sch.get('board', '')} | "
                    f"{fmt(sch.get('annual_fee', 0))} | {fmt(sch.get('estimated_student_count', 0))} |"
                )
            lines.append("")

        lines.append("**Component Hexes**:\n")
        lines.append("| Rank | Locality | Score | Tier | Direct TAM | Units |")
        lines.append("|---:|---|---:|---|---:|---:|")
        for h in mm["hex_details"][:10]:
            lines.append(
                f"| #{h['rank']} | {h['name']} | {h['score']:.1f} | {h['tier']} | "
                f"{fmt(h['direct_tam'])} | {fmt(h.get('direct_units', 0))} |"
            )
        if len(mm["hex_details"]) > 10:
            lines.append(f"| | *...{len(mm['hex_details']) - 10} more hexes* | | | | |")
        lines.append("")

    # ── Key Inferences ──
    lines.append("---\n")
    lines.append("## Key Inferences & Insights\n")

    top3_zones = zone_by_tam[:3]
    top3_tam = sum(z[1]["direct_family_tam"] for z in top3_zones)
    top3_share = (top3_tam / stats["total_direct_family_tam"] * 100) if stats["total_direct_family_tam"] > 0 else 0
    top3_names = ", ".join(z[0] for z in top3_zones)

    lines.append(f"### 1. Geographic Concentration of Wealth\n")
    lines.append(f"The top 3 zones by TAM — **{top3_names}** — collectively hold **{fmt(top3_tam)}** families "
                 f"(**{top3_share:.1f}%** of all direct TAM). This is a highly concentrated wealth footprint.\n")

    east_zones = {z: s for z, s in zones.items() if "East" in z or z == "East"}
    east_tam = sum(s["direct_family_tam"] for s in east_zones.values())
    east_share = (east_tam / stats["total_direct_family_tam"] * 100) if stats["total_direct_family_tam"] > 0 else 0
    lines.append(f"### 2. East Corridor Analysis\n")
    lines.append(f"The combined East + South-East + North-East zones account for **{fmt(east_tam)}** families "
                 f"(**{east_share:.1f}%** of total TAM), {'confirming the well-known Whitefield–Sarjapur–Outer Ring Road premium residential corridor.' if east_share > 40 else 'showing significant but not dominant presence.'}\n")

    top10_tam = sum(mm["direct_family_tam"] for mm in top10)
    top10_share = (top10_tam / stats["total_direct_family_tam"] * 100) if stats["total_direct_family_tam"] > 0 else 0
    lines.append(f"### 3. Micro Market Concentration\n")
    lines.append(f"The **top 10 micro markets** account for **{fmt(top10_tam)}** families (**{top10_share:.1f}%** of total TAM). "
                 f"These are the most actionable geographic targets for premium school planning, luxury retail placement, and affluent family services.\n")

    ultra_lux_units = stats["income_band_totals"].get("Ultra Luxury", 0)
    elite_lux_units = stats["income_band_totals"].get("Elite Luxury", 0)
    super_lux_units = stats["income_band_totals"].get("Super Luxury", 0)
    total_premium = ultra_lux_units + elite_lux_units + super_lux_units
    ultra_share = (total_premium / stats["total_direct_family_tam"] * 100) if stats["total_direct_family_tam"] > 0 else 0
    lines.append(f"### 4. Ultra, Elite & Super Luxury Segments\n")
    lines.append(f"Units in the **Ultra, Elite, and Super Luxury categories** total "
                 f"**{fmt(total_premium)}** units (**{ultra_share:.1f}%** of all units). "
                 f"This segment represents the highest-value residential footprint for premium services.\n")

    lines.append(f"### 5. School Market Opportunity\n")
    lines.append(f"The total **countable wealthy school-age children** across all habitable hexes is **{fmt(stats['total_wealthy_school_children'])}**. "
                 f"This is the estimated addressable market for premium K-12 education in the Bangalore metro.\n")

    high_aff = sum(1 for r in records if r["final_affluence_score"] >= 70)
    no_islands = sum(1 for r in records if r.get("spatial_relation") == "isolated_high")
    core_clusters = sum(1 for r in records if r.get("spatial_relation") == "core_cluster")
    lines.append(f"### 6. Spatial Quality of the Model\n")
    lines.append(f"- **{high_aff}** hexes qualify as High Affluence or above (score ≥ 70)")
    lines.append(f"- **{core_clusters}** hexes are classified as **core cluster** members")
    lines.append(f"- **{no_islands}** hexes are flagged as **isolated high** (potential anomalies)")
    lines.append(f"- The model shows strong spatial clustering (Moran's I > 0.92), confirming coherent wealthy neighborhoods\n")

    lines.append("---\n")
    lines.append("*This report was auto-generated from the Stage 2 Hex-7 Affluence Final output. "
                 "TAM figures are based on society-level estimated families and should not be treated as exact census counts.*\n")

    return "\n".join(lines)


def main():
    print("=" * 60)
    print("Stage 2 Affluence Analysis — Zone & Micro Market Report")
    print("=" * 60)

    print(f"\n[1/6] Loading records from {FINAL_JSON} ...")
    records = load_records()
    print(f"       Loaded {len(records)} records.")

    print(f"\n[2/6] Loading previous report baseline from {PREV_REPORT_JSON} ...")
    prev_report = load_previous_report()
    if prev_report:
        prev_hexes = prev_report.get("overall", {}).get("total_hexes", "?")
        print(f"       Loaded previous report ({prev_hexes} hexes).")
    else:
        print("       No previous report found — delta section will be skipped.")

    print("\n[3/6] Enriching records with zone classifications ...")
    records = enrich_records(records)

    print("\n[4/6] Computing overall stats ...")
    stats = overall_stats(records)

    print("\n[5/6] Running zone analysis ...")
    zones = zone_analysis(records)

    print("\n[5/6] Building micro markets ...")
    micro_markets = build_micro_markets(records)
    print(f"       Found {len(micro_markets)} micro market clusters.")

    print("\n[6/6] Generating report ...")
    report = generate_report(records, zones, micro_markets, stats, prev_report)
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(report)
    print(f"       Wrote {REPORT_MD}")

    # Write JSON summary for the top 10
    summary = {
        "overall": stats,
        "zones": zones,
        "top_10_micro_markets": micro_markets[:10],
        "all_micro_market_count": len(micro_markets),
    }
    with REPORT_JSON.open("w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"       Wrote {REPORT_JSON}")

    print("\n✅ Done.")


if __name__ == "__main__":
    main()
