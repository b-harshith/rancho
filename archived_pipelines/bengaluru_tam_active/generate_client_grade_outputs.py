#!/usr/bin/env python3
"""Generate client-grade recommendation, validation, and commute artifacts.

This is a packaging layer over the existing final H3 intelligence output. It
does not rebuild the core model; it makes the deliverable easier to audit,
explain, and use in the web platform.
"""

from __future__ import annotations

import csv
import json
import math
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

import h3


ROOT = Path(__file__).resolve().parents[2]
FINAL_DIR = ROOT / "DATA" / "final"
AUDIT_DIR = ROOT / "DATA" / "audits"
CLIENT_DIR = ROOT / "DATA" / "client_handoff"
PUBLIC_DATA_DIR = ROOT / "web_platform" / "public" / "data"
PUBLIC_REPORTS_DIR = ROOT / "web_platform" / "public" / "reports"

MASTER_PATH = FINAL_DIR / "bangalore_hex7_affluent_family_intelligence_master.json"
FINAL_CSV_PATH = FINAL_DIR / "bangalore_hex7_affluent_family_intelligence_flat.csv"
GEOJSON_PATH = FINAL_DIR / "bangalore_hex7_affluent_family_intelligence.geojson"
PUBLIC_GEOJSON_PATH = PUBLIC_DATA_DIR / "hexes.geojson"
PUBLIC_REPORT_PATH = PUBLIC_DATA_DIR / "report.json"
PUBLIC_MASTER_PATH = PUBLIC_DATA_DIR / "hexes_master.json"
METRO_PATH = PUBLIC_DATA_DIR / "bangalore_metro_stations.json"


def load_json(path: Path):
    return json.loads(path.read_text())


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def write_md(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n")


def unique_preserving_order(values):
    seen = set()
    result = []
    for value in values or []:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def num(value, default=0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, low=0.0, high=100.0) -> float:
    return max(low, min(high, value))


def score_from_distance(distance_km: float, good: float, poor: float) -> float:
    if distance_km <= good:
        return 100.0
    if distance_km >= poor:
        return 20.0
    return 100.0 - ((distance_km - good) / (poor - good)) * 80.0


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def pct(value, total) -> float:
    return round((value / total) * 100, 1) if total else 0.0


def confidence_band(record) -> str:
    score = num(record.get("confidence_score"))
    flags = record.get("quality_flags") or []
    tam = num(record.get("tam", {}).get("countable_family_tam"))
    if score >= 0.75 and tam > 0 and not flags:
        return "High confidence"
    if score >= 0.45 and tam > 0:
        return "Medium confidence"
    return "Low confidence"


def recommendation_status(tam_share, score, confidence, commute_score=60.0) -> str:
    if tam_share >= 12 and score >= 40 and confidence != "Low confidence" and commute_score >= 55:
        return "Launch now"
    if tam_share >= 5 and score >= 32 and commute_score >= 45:
        return "Shortlist"
    if tam_share >= 1 or confidence == "Low confidence":
        return "Validate on ground"
    return "Avoid for now"


def route_ratio(items) -> float:
    ratios = []
    for item in items:
        straight = num(item.get("straight_line_distance_km"))
        route = num(item.get("route_distance_km"))
        if straight > 0 and route > 0:
            ratios.append(route / straight)
    if not ratios:
        return 2.2
    return median(sorted(ratios)[:10])


def nearest_route_time(items) -> float:
    times = [num(item.get("travel_time_min_at_35_kmph"), 999) for item in items]
    times = [t for t in times if t > 0 and t < 999]
    return min(times) if times else 30.0


def nearest_metro(lat, lon, metro_stations):
    best = None
    for station in metro_stations:
        d = haversine_km(lat, lon, num(station.get("latitude")), num(station.get("longitude")))
        if best is None or d < best["distance_km"]:
            best = {
                "name": station.get("name") or station.get("original_name") or "Metro station",
                "line": station.get("line") or "Unknown",
                "distance_km": round(d, 2),
            }
    return best or {"name": "NA", "line": "Unknown", "distance_km": 99.0}


def commute_score_for_hex(record, metro_stations):
    lat, lon = h3.cell_to_latlng(record["hex_id"])
    scores = record.get("component_scores", {})
    poi = record.get("poi_summary", {})
    top = record.get("top_evidence", {})
    schools = top.get("schools") or []
    hospitals = top.get("hospitals") or []
    sez = top.get("sez_workplaces") or []
    route_items = schools[:8] + hospitals[:8]
    ratio = route_ratio(route_items)
    route_time = nearest_route_time(route_items)
    metro = nearest_metro(lat, lon, metro_stations)

    route_count = num(poi.get("eligible_school_routes_count")) + num(poi.get("hospitals_nearby_count"))
    society_density = num(poi.get("societies_nearby_count")) + num(poi.get("society_cluster_project_count"))
    habitability = num(scores.get("habitability_score")) * 100
    market = num(scores.get("market_score")) * 100
    school_access = num(scores.get("school_access_score")) * 100
    hospital_access = num(scores.get("hospital_score")) * 100
    sez_pull = num(scores.get("sez_workplace_score")) * 100

    arterial_time_score = score_from_distance(route_time, good=6, poor=25)
    route_density_score = clamp((route_count / 110) * 100)
    arterial_access = 0.58 * arterial_time_score + 0.42 * route_density_score

    road_quality = clamp(0.45 * habitability + 0.25 * market + 0.15 * school_access + 0.15 * hospital_access)
    redundancy = clamp((route_count / 120) * 55 + (society_density / 70) * 25 + (len(sez) / 5) * 20)
    directness = clamp(110 - (ratio - 1.0) * 52, 15, 100)
    chokepoint_risk = clamp(100 - max(0, ratio - 1.25) * 38 - max(0, 35 - route_count) * 0.9)
    traffic_pattern = clamp(100 - (sez_pull * 0.18) - (school_access * 0.08) - max(0, ratio - 1.6) * 22)
    transit_relief = score_from_distance(metro["distance_km"], good=0.75, poor=6.0)

    final = clamp(
        0.22 * arterial_access
        + 0.16 * road_quality
        + 0.16 * redundancy
        + 0.18 * directness
        + 0.14 * chokepoint_risk
        + 0.08 * traffic_pattern
        + 0.06 * transit_relief
    )

    if final >= 80:
        band = "Excellent commute convenience"
    elif final >= 65:
        band = "Strong commute convenience"
    elif final >= 50:
        band = "Moderate commute convenience"
    else:
        band = "Commute friction risk"

    best_corridors = []
    for item in sorted(route_items, key=lambda x: num(x.get("travel_time_min_at_35_kmph"), 999))[:4]:
        best_corridors.append(
            {
                "name": item.get("name", "POI"),
                "type": item.get("poi_type", "route"),
                "travel_time_min_at_35_kmph": round(num(item.get("travel_time_min_at_35_kmph")), 1),
                "route_distance_km": round(num(item.get("route_distance_km")), 2),
                "directness_ratio": round(num(item.get("route_distance_km")) / max(num(item.get("straight_line_distance_km")), 0.1), 2),
            }
        )

    return {
        "hex_id": record["hex_id"],
        "name": record.get("name", "Unnamed hex"),
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "score": round(final, 1),
        "band": band,
        "components": {
            "arterial_access": round(arterial_access, 1),
            "road_quality_proxy": round(road_quality, 1),
            "network_redundancy": round(redundancy, 1),
            "route_directness": round(directness, 1),
            "chokepoint_risk_proxy": round(chokepoint_risk, 1),
            "traffic_pattern_proxy": round(traffic_pattern, 1),
            "transit_relief": round(transit_relief, 1),
        },
        "evidence": {
            "median_route_directness_ratio": round(ratio, 2),
            "nearest_routed_poi_minutes_at_35_kmph": round(route_time, 1),
            "eligible_route_count": int(route_count),
            "entry_exit_proxy_count": int(clamp(round(redundancy / 12), 1, 8)),
            "nearest_metro": metro,
            "best_corridors": best_corridors,
            "traffic_caveat": "Free proxy from OSM/OSRM-derived routing evidence; not live traffic.",
        },
    }


def weighted_average(rows, key, weight_key=None):
    total_weight = 0.0
    acc = 0.0
    for row in rows:
        weight = num(row.get(weight_key), 1.0) if weight_key else 1.0
        acc += num(row.get(key)) * weight
        total_weight += weight
    return round(acc / total_weight, 1) if total_weight else 0.0


def aggregate_commute_by_zone(commute_by_hex, hex_zone, hex_tam):
    grouped = defaultdict(list)
    for hex_id, commute in commute_by_hex.items():
        zone = hex_zone.get(hex_id)
        if zone:
            row = {**commute, "tam": hex_tam.get(hex_id, 0)}
            grouped[zone].append(row)
    output = {}
    for zone, rows in grouped.items():
        ranked = sorted(rows, key=lambda r: r["score"], reverse=True)
        output[zone] = {
            "score_tam_weighted": weighted_average(rows, "score", "tam"),
            "score_area_weighted": weighted_average(rows, "score"),
            "best_hexes": [{"hex_id": r["hex_id"], "name": r["name"], "score": r["score"]} for r in ranked[:3]],
            "worst_hexes": [{"hex_id": r["hex_id"], "name": r["name"], "score": r["score"]} for r in ranked[-3:]],
        }
    return output


def status_copy(status: str) -> str:
    return {
        "Launch now": "High TAM and enough supporting confidence for immediate site shortlisting.",
        "Shortlist": "Strong potential, but validate commercial availability and local access before committing.",
        "Validate on ground": "Promising signal exists, but evidence or access needs field confirmation.",
        "Avoid for now": "Low current TAM or weak evidence relative to stronger alternatives.",
    }.get(status, "Needs review.")


def build_recommendations(report, commute_by_zone, commute_by_hex):
    overall_tam = num(report["overall"]["total_direct_family_tam"])
    zones = []
    for name, stats in report["zones"].items():
        tam = num(stats.get("direct_family_tam"))
        commute = commute_by_zone.get(name, {}).get("score_tam_weighted", 55.0)
        conf = "High confidence" if tam > 15000 and num(stats.get("high_affluence_hexes")) > 0 else "Medium confidence" if tam > 0 else "Low confidence"
        status = recommendation_status(pct(tam, overall_tam), num(stats.get("avg_score")), conf, commute)
        zones.append(
            {
                "name": name,
                "status": status,
                "rationale": status_copy(status),
                "tam": round(tam),
                "tam_share_pct": pct(tam, overall_tam),
                "avg_score": num(stats.get("avg_score")),
                "commute_score": commute,
                "confidence_band": conf,
                "next_step": "Shortlist 2-3 sites and verify frontage, access, and rents." if status in {"Launch now", "Shortlist"} else "Keep as benchmark or revisit after field validation.",
            }
        )
    zones.sort(key=lambda z: (["Avoid for now", "Validate on ground", "Shortlist", "Launch now"].index(z["status"]), z["tam"], z["commute_score"]), reverse=True)

    markets = []
    for market in report.get("top_10_micro_markets", []):
        hex_rows = [commute_by_hex.get(h.get("hex_id")) for h in market.get("hex_details", [])]
        hex_rows = [row for row in hex_rows if row]
        commute = weighted_average([{**row, "tam": 1} for row in hex_rows], "score") if hex_rows else 55.0
        tam = num(market.get("direct_family_tam"))
        status = recommendation_status(pct(tam, overall_tam), num(market.get("avg_affluence_score")), "High confidence", commute)
        markets.append(
            {
                "name": market.get("primary_name"),
                "zone": market.get("primary_zone"),
                "status": status,
                "rationale": f"{round(tam):,} family TAM, {num(market.get('avg_affluence_score')):.1f} avg score, commute proxy {commute:.1f}.",
                "tam": round(tam),
                "tam_share_pct": pct(tam, overall_tam),
                "avg_score": num(market.get("avg_affluence_score")),
                "commute_score": commute,
                "next_step": "Prioritize commercial inventory search inside the highest-scoring connected pockets.",
            }
        )
    markets.sort(key=lambda m: (m["status"] == "Launch now", m["tam"], m["commute_score"]), reverse=True)

    avoid_zones = [z for z in zones if z["status"] == "Avoid for now"][:3]
    return {"zones": zones, "micro_markets": markets, "avoid_or_deprioritize": avoid_zones}


def build_sensitivity(total_family_tam):
    school_age_rates = [0.30, 0.38, 0.45]
    children_per_family = [1.10, 1.25, 1.40]
    rows = []
    for rate in school_age_rates:
        for cpf in children_per_family:
            children = total_family_tam * rate * cpf
            rows.append(
                {
                    "school_age_family_rate": rate,
                    "children_per_school_age_family": cpf,
                    "school_age_children": round(children),
                }
            )
    penetration = [0.01, 0.02, 0.03, 0.05]
    capacity = [120, 180, 240]
    center_rows = []
    baseline_children = total_family_tam * 0.38 * 1.25
    for p in penetration:
        for c in capacity:
            center_rows.append(
                {
                    "penetration": p,
                    "center_capacity": c,
                    "estimated_centers": round((baseline_children * p) / c, 1),
                }
            )
    radius_rows = [
        {"radius_km": 3, "interpretation": "Immediate neighborhood validation"},
        {"radius_km": 5, "interpretation": "Local launch catchment"},
        {"radius_km": 7, "interpretation": "Current default expansion lens"},
        {"radius_km": 10, "interpretation": "Broad city-submarket scan"},
    ]
    return {
        "school_age_children": rows,
        "center_capacity": center_rows,
        "catchment_radius": radius_rows,
    }


def build_validation(master, geojson, public_geojson, report, rows):
    final_hex_count = len(master["hexes"])
    active_hex_count = len(public_geojson["features"])
    final_tam = sum(num(r.get("tam", {}).get("countable_family_tam")) for r in master["hexes"])
    csv_tam = sum(num(r.get("countable_family_tam")) for r in rows)
    public_tam = sum(num(f["properties"].get("countable_family_tam")) for f in public_geojson["features"])
    zone_tam = sum(num(v.get("direct_family_tam")) for v in report["zones"].values())
    missing_coords = 0
    for dataset_path in ["societies.json", "schools.json", "hospitals.json"]:
        for item in load_json(PUBLIC_DATA_DIR / dataset_path):
            if not num(item.get("lat")) or not num(item.get("lon")):
                missing_coords += 1
    society_names = [s.get("name") for s in load_json(PUBLIC_DATA_DIR / "societies.json")]
    duplicate_societies = sum(count - 1 for count in Counter(society_names).values() if count > 1)
    checks = [
        {
            "name": "Final master hex count",
            "status": "pass" if final_hex_count == 310 else "warn",
            "value": final_hex_count,
            "expected": 310,
        },
        {
            "name": "Active analysis hex count",
            "status": "pass" if active_hex_count == 264 else "warn",
            "value": active_hex_count,
            "expected": 264,
        },
        {
            "name": "Final JSON vs CSV TAM",
            "status": "pass" if abs(final_tam - csv_tam) < 0.01 else "fail",
            "value": round(final_tam, 2),
            "expected": round(csv_tam, 2),
        },
        {
            "name": "Active GeoJSON vs zone report TAM",
            "status": "pass" if abs(public_tam - zone_tam) < 0.01 else "fail",
            "value": round(public_tam, 2),
            "expected": round(zone_tam, 2),
        },
        {
            "name": "Missing POI coordinates",
            "status": "pass" if missing_coords == 0 else "warn",
            "value": missing_coords,
            "expected": 0,
        },
        {
            "name": "Duplicate society names",
            "status": "warn" if duplicate_societies else "pass",
            "value": duplicate_societies,
            "expected": 0,
        },
    ]
    return {
        "coverage": {
            "final_h3_hexes": final_hex_count,
            "active_analysis_hexes": active_hex_count,
            "coverage_note": "Final package contains all 310 H3 cells. The app/report active layer contains the 264 analysis cells used for zone and micro-market summaries.",
        },
        "totals": {
            "final_countable_family_tam": round(final_tam, 2),
            "csv_countable_family_tam": round(csv_tam, 2),
            "active_geojson_family_tam": round(public_tam, 2),
            "zone_report_family_tam": round(zone_tam, 2),
        },
        "checks": checks,
    }


def markdown_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def main():
    CLIENT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    master = load_json(MASTER_PATH)
    public_master = load_json(PUBLIC_MASTER_PATH)
    report = load_json(FINAL_DIR / "stage2_affluence_zone_micromarket_report.json")
    geojson = load_json(GEOJSON_PATH)
    public_geojson = load_json(GEOJSON_PATH)
    metro = load_json(METRO_PATH)

    with FINAL_CSV_PATH.open(newline="") as f:
        csv_rows = list(csv.DictReader(f))

    commute_by_hex = {record["hex_id"]: commute_score_for_hex(record, metro) for record in master["hexes"]}
    hex_zone = {f["properties"]["hex_id"]: f["properties"].get("zone") for f in public_geojson["features"]}
    hex_tam = {r["hex_id"]: num(r.get("tam", {}).get("countable_family_tam")) for r in master["hexes"]}
    commute_by_zone = aggregate_commute_by_zone(commute_by_hex, hex_zone, hex_tam)

    for feature in public_geojson["features"]:
        props = feature["properties"]
        commute = commute_by_hex.get(props["hex_id"])
        if commute:
            props["commute_score"] = commute["score"]
            props["commute_band"] = commute["band"]
            props["commute_components"] = commute["components"]
            props["commute_evidence"] = commute["evidence"]

    # Keep final GeoJSON aligned for GIS handoff too.
    for feature in geojson["features"]:
        props = feature["properties"]
        commute = commute_by_hex.get(props["hex_id"])
        if commute:
            props["commute_score"] = commute["score"]
            props["commute_band"] = commute["band"]

    for record in public_master.get("hexes", []):
        commute = commute_by_hex.get(record["hex_id"])
        if commute:
            record["commute"] = commute

    for record in master.get("hexes", []):
        commute = commute_by_hex.get(record["hex_id"])
        if commute:
            record["commute"] = commute
            decision_notes = unique_preserving_order(record.get("decision_notes", []))
            commute_note = "Commute score is a free OSM/OSRM-derived proxy, not live traffic."
            if commute_note not in decision_notes:
                decision_notes.append(commute_note)
            record["decision_notes"] = decision_notes

    validation = build_validation(master, geojson, public_geojson, report, csv_rows)
    recommendations = build_recommendations(report, commute_by_zone, commute_by_hex)
    total_tam = num(report["overall"]["total_countable_family_tam"])
    sensitivity = build_sensitivity(total_tam)
    commute_summary = {
        "method": "Free OSM/OSRM-derived commute-friction proxy",
        "not_live_traffic": True,
        "components": [
            "Arterial access",
            "Road quality proxy",
            "Network redundancy",
            "Route directness",
            "Chokepoint risk proxy",
            "Traffic pattern proxy",
            "Transit relief",
        ],
        "zone_summary": commute_by_zone,
        "top_commute_hexes": sorted(commute_by_hex.values(), key=lambda x: x["score"], reverse=True)[:10],
        "weak_commute_hexes": sorted(commute_by_hex.values(), key=lambda x: x["score"])[:10],
    }

    client_summary = {
        "generated_from": {
            "master": str(MASTER_PATH.relative_to(ROOT)),
            "report": str(PUBLIC_REPORT_PATH.relative_to(ROOT)),
        },
        "coverage": validation["coverage"],
        "executive_metrics": {
            "family_tam": round(total_tam),
            "school_age_children_base": round(total_tam * 0.38 * 1.25),
            "wealthy_school_children": round(num(report["overall"]["total_wealthy_school_children"])),
            "zones": len(report["zones"]),
            "micro_markets": report.get("all_micro_market_count", len(report.get("top_10_micro_markets", []))),
        },
        "recommendations": recommendations,
        "sensitivity": sensitivity,
        "validation": validation,
        "commute": commute_summary,
        "handoff_links": [
            {"label": "Executive report", "href": "reports/EXECUTIVE_REPORT.md"},
            {"label": "Data dictionary", "href": "reports/DATA_DICTIONARY.md"},
            {"label": "Commute methodology", "href": "reports/COMMUTE_METHODOLOGY.md"},
            {"label": "Validation summary", "href": "reports/VALIDATION_SUMMARY.md"},
            {"label": "Source lineage", "href": "reports/SOURCE_LINEAGE.md"},
        ],
    }

    write_json(PUBLIC_DATA_DIR / "commute_scores.json", {"by_hex": commute_by_hex, "by_zone": commute_by_zone})
    write_json(PUBLIC_DATA_DIR / "client_summary.json", client_summary)
    write_json(CLIENT_DIR / "validation_summary.json", validation)
    write_json(PUBLIC_GEOJSON_PATH, public_geojson)
    write_json(GEOJSON_PATH, geojson)
    write_json(PUBLIC_MASTER_PATH, public_master)
    write_json(MASTER_PATH, master)

    report["coverage"] = validation["coverage"]
    report["commute_summary"] = {
        "method": commute_summary["method"],
        "zone_summary": commute_by_zone,
        "note": "Commute scores are free OSM/OSRM-derived proxies and do not use live traffic.",
    }
    write_json(PUBLIC_REPORT_PATH, report)

    top_zone_rows = [
        [z["status"], z["name"], f"{z['tam']:,}", f"{z['tam_share_pct']}%", z["avg_score"], z["commute_score"]]
        for z in recommendations["zones"][:6]
    ]
    top_market_rows = [
        [m["status"], m["name"], m["zone"], f"{m['tam']:,}", f"{m['tam_share_pct']}%", m["commute_score"]]
        for m in recommendations["micro_markets"][:6]
    ]
    check_rows = [[c["status"], c["name"], c["value"], c["expected"]] for c in validation["checks"]]

    readme = f"""
# Bangalore Market Intelligence Client Handoff

Open the web platform first, then use these reports for board/client review.

## What to Open First

- Web platform: https://ranchoblr.vercel.app
- Executive report: `EXECUTIVE_REPORT.md`
- Validation summary: `VALIDATION_SUMMARY.md`
- Data dictionary: `DATA_DICTIONARY.md`
- Commute methodology: `COMMUTE_METHODOLOGY.md`

## Coverage Convention

- Final H3 coverage: **{validation['coverage']['final_h3_hexes']} hexes**
- Active analysis coverage: **{validation['coverage']['active_analysis_hexes']} hexes**
- Countable family TAM: **{round(total_tam):,} families**

The final package keeps all H3 cells. The active analysis layer is the filtered set used for zone and micro-market summaries.
"""
    write_md(CLIENT_DIR / "README_CLIENT.md", readme)

    executive = f"""
# Executive Market Recommendation

## Current Decision

The strongest launch focus remains the eastern and south-eastern premium residential belt, with South-East and East zones carrying the largest TAM share and strongest micro-market depth.

## Recommended Zones

{markdown_table(['Status', 'Zone', 'Family TAM', 'Share', 'Avg Score', 'Commute'], top_zone_rows)}

## Recommended Micro-Markets

{markdown_table(['Status', 'Micro-market', 'Zone', 'Family TAM', 'Share', 'Commute'], top_market_rows)}

## Avoid or Deprioritize

Zones with low TAM or weak evidence should not be first-wave launch candidates unless field validation reveals a specific commercial advantage.

## Next Validation Steps

- Verify top society clusters inside the recommended micro-markets.
- Confirm commercial frontage, parking, entry/exit, and rents around shortlisted sites.
- Validate traffic-risk proxy with field observation during school pickup and evening commute windows.
- Use sensitivity tables before committing center capacity assumptions.
"""
    write_md(CLIENT_DIR / "EXECUTIVE_REPORT.md", executive)

    dictionary = """
# Data Dictionary

| Metric | Meaning | Client Use |
| --- | --- | --- |
| `countable_family_tam` | Primary affluent-family estimate from direct society aggregation. | Main TAM number. |
| `direct_family_tam` | Non-duplicated family TAM inside the hex or grouped region. | Cross-check against countable TAM. |
| `countable_school_age_children` | `countable_family_tam × 0.38 × 1.25`. | School-age child opportunity estimate. |
| `countable_wealthy_school_children` | School-age children adjusted by local school access score. | Premium education opportunity proxy. |
| `nearby_family_tam_weighted_context` | Nearby weighted family TAM context. | Context only; do not add to countable TAM. |
| `society_cluster_tam_weighted_context_not_counted` | Cluster influence around the hex. | Cluster signal only; not unique families. |
| `confidence_score` | Evidence strength from model inputs and quality flags. | Use to decide field-validation priority. |
| `habitability_score` | Overture building evidence and residential plausibility. | Helps avoid non-residential false positives. |
| `commute_score` | Free OSM/OSRM-derived commute-friction proxy. | Access quality screen, not live traffic. |
| `quality_flags` | Known caveats such as missing evidence or low building evidence. | Must be reviewed before final decisions. |
"""
    write_md(CLIENT_DIR / "DATA_DICTIONARY.md", dictionary)

    validation_md = f"""
# Validation Summary

## Coverage

- Final H3 coverage: **{validation['coverage']['final_h3_hexes']}**
- Active analysis coverage: **{validation['coverage']['active_analysis_hexes']}**
- Coverage note: {validation['coverage']['coverage_note']}

## Checks

{markdown_table(['Status', 'Check', 'Value', 'Expected'], check_rows)}
"""
    write_md(CLIENT_DIR / "VALIDATION_SUMMARY.md", validation_md)

    source_lineage = """
# Source Lineage

## Inputs

- Stage 2 curated societies, schools, hospitals, localities, SEZ zones, Overture building evidence, metro stations, and OSRM routing graph.

## Production Scripts

- `scripts/active/generate_stage2_hex7_affluence.py`
- `scripts/active/evaluate_stage2_hex7_spatial_diagnostics.py`
- `scripts/active/generate_final_hex_intelligence.py`
- `scripts/active/generate_client_grade_outputs.py`

## Outputs

- Final nested JSON, flat CSV, GeoJSON, KML, client reports, validation summary, commute scores, and web-platform data files.

## Caveat

This is a decision-support layer. Field validation is still required before lease or launch commitments.
"""
    write_md(CLIENT_DIR / "SOURCE_LINEAGE.md", source_lineage)

    commute_method = """
# Commute Convenience Methodology

The commute score is a free proxy model, not live traffic.

## Components

- Arterial access: nearest routed POI travel time and routed evidence density.
- Road quality proxy: habitability, market support, school access, and hospital access.
- Network redundancy: routed school/hospital evidence plus nearby society/cluster density.
- Route directness: OSRM route distance divided by straight-line distance for nearby schools/hospitals.
- Chokepoint risk proxy: penalties for poor route directness and low route redundancy.
- Traffic pattern proxy: penalties for heavy workplace/school pull and route friction.
- Transit relief: distance to nearest metro station.

## Interpretation

Use this as a first-pass access screen. Confirm road width, frontage, turns, parking, pickup/dropoff behavior, and peak-hour congestion on ground.
"""
    write_md(CLIENT_DIR / "COMMUTE_METHODOLOGY.md", commute_method)

    income_band_totals = report.get("overall", {}).get("income_band_totals", {})
    conservative_tam_60l = num(income_band_totals.get("1.5Cr+", 0)) + num(income_band_totals.get("60L-1.5Cr", 0))
    estimated_tam_40l = conservative_tam_60l + (20.0 / 30.0) * num(income_band_totals.get("30L-60L", 0))
    total_direct_tam = num(report.get("overall", {}).get("total_direct_family_tam", 1.0))
    conservative_share_pct = (conservative_tam_60l / total_direct_tam) * 100 if total_direct_tam > 0 else 0.0
    estimated_share_pct = (estimated_tam_40l / total_direct_tam) * 100 if total_direct_tam > 0 else 0.0

    final_readme = f"""
# Bangalore Hex-7 Affluent Family Intelligence

This folder contains the final per-hex deliverable for the affluent-family TAM analysis.

## Recommended files

- `bangalore_hex7_affluent_family_intelligence_master.json` - full nested evidence file.
- `bangalore_hex7_affluent_family_intelligence_flat.csv` - spreadsheet-friendly summary.
- `bangalore_hex7_affluent_family_intelligence.geojson` - GIS polygon layer.
- `../../maps/final/bangalore_hex7_affluent_family_intelligence.kml` - click-ready Google Earth map.
- `../client_handoff/README_CLIENT.md` - client-facing handoff guide.

## Coverage convention

- Final H3 coverage: **{validation['coverage']['final_h3_hexes']} hexes**
- Active analysis coverage: **{validation['coverage']['active_analysis_hexes']} hexes**

The final package keeps all modeled H3 cells. The active analysis layer is the filtered set used in the web platform for zone and micro-market summaries.

## What to use for decisions

- Use `tam.countable_family_tam` for countable affluent family TAM.
- Use `tam.countable_school_age_children` for school-age child TAM.
- Use `tam.countable_wealthy_school_children` as a premium-school-access-adjusted child estimate.
- Use nearby and cluster TAM fields only as context, not as extra families.
- Use `commute.score` as a free commute-friction proxy, not live traffic.
- Use `top_evidence` to inspect the societies, schools, hospitals, and SEZ/workplace context behind each score.

## Current totals

- Countable family TAM: {total_tam:.0f}
- Countable school-age children: {total_tam * 0.38 * 1.25:.0f}
- Wealthy-school children: {num(report['overall']['total_wealthy_school_children']):.0f}
- Conservative 60L+ direct TAM share: {conservative_share_pct:.2f}%
- Estimated 40L+ direct AHI TAM share: {estimated_share_pct:.2f}%

## Important caveat

This is a decision-support layer, not ground truth. Derived child estimates and commute scores are useful for prioritization, but should be validated with field research before commercial decisions.
"""
    write_md(FINAL_DIR / "README_bangalore_hex7_affluent_family_intelligence.md", final_readme)

    for md in CLIENT_DIR.glob("*.md"):
        shutil.copy2(md, PUBLIC_REPORTS_DIR / md.name)
    write_json(PUBLIC_REPORTS_DIR / "validation_summary.json", validation)

    print("Generated client-grade outputs:")
    print(f"- {PUBLIC_DATA_DIR / 'client_summary.json'}")
    print(f"- {PUBLIC_DATA_DIR / 'commute_scores.json'}")
    print(f"- {CLIENT_DIR}")


if __name__ == "__main__":
    main()
