import csv
import html
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path

import h3


CITY_SLUG = os.environ.get("CITY_SLUG", "bangalore").strip().lower().replace(" ", "-")
CITY_NAME = os.environ.get("CITY_NAME", CITY_SLUG.replace("-", " ").title())
DATA_DIR = Path("DATA")
STAGE2_DIR = DATA_DIR / "Stage2 processing"
PROCESSED_DIR = DATA_DIR / "processed"
FINAL_DIR = DATA_DIR / "final"
AUDIT_DIR = DATA_DIR / "audits"
FINAL_MAP_DIR = Path("maps") / "final"

STAGE2_MASTER = PROCESSED_DIR / f"{CITY_SLUG}_stage2_hex7_affluence_master.json"
SOCIETIES_PATH = DATA_DIR / f"q4_categorized_societies_{CITY_SLUG}.json"
SCHOOLS_PATH = DATA_DIR / f"q4_categorized_schools_{CITY_SLUG}.json"
HOSPITALS_PATH = DATA_DIR / f"q4_categorized_hospitals_{CITY_SLUG}.json"

OUTPUT_JSON = FINAL_DIR / f"{CITY_SLUG}_hex7_affluent_family_intelligence_master.json"
OUTPUT_CSV = FINAL_DIR / f"{CITY_SLUG}_hex7_affluent_family_intelligence_flat.csv"
OUTPUT_GEOJSON = FINAL_DIR / f"{CITY_SLUG}_hex7_affluent_family_intelligence.geojson"
OUTPUT_KML = FINAL_MAP_DIR / f"{CITY_SLUG}_hex7_affluent_family_intelligence.kml"
OUTPUT_README = FINAL_DIR / f"README_{CITY_SLUG}_hex7_affluent_family_intelligence.md"
AUDIT_JSON = AUDIT_DIR / f"{CITY_SLUG}_final_hex_intelligence_audit.json"
METHODOLOGY_MD = AUDIT_DIR / f"{CITY_SLUG}_final_hex_intelligence_methodology.md"

SCHOOL_AGE_FAMILY_RATE = 0.38
CHILDREN_PER_SCHOOL_AGE_FAMILY = 1.25

COUNTABLE_50L_PLUS_BANDS = {"50L-1Cr", "1Cr-2Cr", "2Cr-5Cr", "5Cr+"}


def load_json(path):
    with path.open("r") as f:
        return json.load(f)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def safe_dict(value):
    return value if isinstance(value, dict) else {}


def safe_list(value):
    return value if isinstance(value, list) else []


def num(value, default=0.0):
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        if math.isnan(float(value)):
            return default
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if text.upper() in {"", "NA", "N/A", "NONE", "NULL"}:
            return default
        try:
            return float(text)
        except ValueError:
            return default
    return default


def clean_text(value, default="NA"):
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def round_num(value, decimals=2):
    return round(num(value), decimals)


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


def fmt_bool(value):
    return "Yes" if value else "No"


def coordinates_for_kml(hex_id):
    boundary = h3.cell_to_boundary(hex_id)
    coords = [f"{lon:.8f},{lat:.8f},0" for lat, lon in boundary]
    first_lat, first_lon = boundary[0]
    coords.append(f"{first_lon:.8f},{first_lat:.8f},0")
    return " ".join(coords)


def geojson_geometry(hex_id):
    boundary = h3.cell_to_boundary(hex_id)
    coords = [[lon, lat] for lat, lon in boundary]
    coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}


def hex_to_kml_color(hex_color, alpha):
    color = hex_color.lstrip("#")
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)
    return f"{alpha:02x}{b:02x}{g:02x}{r:02x}"


def score_color(score):
    score = num(score)
    if score >= 90:
        return "#064e3b"
    if score >= 80:
        return "#15803d"
    if score >= 70:
        return "#84cc16"
    if score >= 55:
        return "#f59e0b"
    if score >= 40:
        return "#f97316"
    return "#94a3b8"


def estimate_conservative_50l_plus_tam(income_band_family_tam):
    total = 0.0
    for band, values in safe_dict(income_band_family_tam).items():
        if band in COUNTABLE_50L_PLUS_BANDS:
            total += num(safe_dict(values).get("direct"))
    return total


def estimate_40l_plus_linear_tam(income_band_family_tam):
    conservative_50l_plus = estimate_conservative_50l_plus_tam(income_band_family_tam)
    aspirational_band = num(safe_dict(income_band_family_tam).get("25L-50L", {}).get("direct"))
    # The source band is 25L-50L. A linear split counts only the 40L-50L slice.
    return conservative_50l_plus + (10.0 / 25.0) * aspirational_band


def summarize_societies(record):
    evidence = safe_list(safe_dict(record.get("top_evidence")).get("societies"))
    categories = Counter(clean_text(item.get("category")) for item in evidence)
    direct = [item for item in evidence if item.get("direct_in_hex")]
    nearby = [item for item in evidence if not item.get("direct_in_hex")]
    return {
        "direct_societies_in_top_evidence": len(direct),
        "nearby_societies_in_top_evidence": len(nearby),
        "top_evidence_category_mix": dict(categories),
        "top_evidence_only_note": (
            "Category mix is based on retained top evidence, while TAM fields use "
            "the full Stage 2 aggregation."
        ),
        "top_societies": evidence[:10],
    }


def summarize_schools(record):
    scores = safe_dict(record.get("component_scores"))
    summary = safe_dict(record.get("poi_summary"))
    schools = safe_list(safe_dict(record.get("top_evidence")).get("schools"))
    category_mix = Counter(clean_text(item.get("category")) for item in schools)
    return {
        "school_score_used_in_ranking": round_num(scores.get("school_score"), 6),
        "school_access_score": round_num(scores.get("school_access_score"), 6),
        "residential_school_fit_score": round_num(scores.get("residential_school_fit_score"), 6),
        "eligible_school_routes_count": int(num(summary.get("eligible_school_routes_count"))),
        "effective_school_score_count": int(num(summary.get("effective_school_score_count"))),
        "top_evidence_category_mix": dict(category_mix),
        "bus_aware_note": (
            "School access uses OSRM route distance, 35 km/h conversion, and bus-aware "
            "travel decay. It is an access signal, not a student allocation model."
        ),
        "top_schools": schools[:25],
    }


def summarize_hospitals(record):
    summary = safe_dict(record.get("poi_summary"))
    hospitals = safe_list(safe_dict(record.get("top_evidence")).get("hospitals"))
    category_mix = Counter(clean_text(item.get("category")) for item in hospitals)
    return {
        "hospitals_nearby_count": int(num(summary.get("hospitals_nearby_count"))),
        "top_evidence_category_mix": dict(category_mix),
        "top_hospitals": hospitals[:10],
    }


def final_record(stage2_record):
    tam = safe_dict(stage2_record.get("tam"))
    market = safe_dict(stage2_record.get("stage1_5_market"))
    scores = safe_dict(stage2_record.get("component_scores"))
    habitability = safe_dict(stage2_record.get("habitability"))
    poi_summary = safe_dict(stage2_record.get("poi_summary"))
    income_band_family_tam = safe_dict(tam.get("income_band_family_tam"))
    conservative_50l_plus = estimate_conservative_50l_plus_tam(income_band_family_tam)
    estimated_40l_plus_linear = estimate_40l_plus_linear_tam(income_band_family_tam)
    direct_family_tam = num(tam.get("direct_family_tam"))
    conservative_50l_plus_share = (
        conservative_50l_plus / direct_family_tam if direct_family_tam > 0 else 0.0
    )
    estimated_40l_plus_linear_share = (
        estimated_40l_plus_linear / direct_family_tam if direct_family_tam > 0 else 0.0
    )
    countable_family_tam = num(tam.get("countable_direct_family_tam"))
    countable_school_age_families = countable_family_tam * SCHOOL_AGE_FAMILY_RATE
    countable_school_age_children = countable_school_age_families * CHILDREN_PER_SCHOOL_AGE_FAMILY

    return {
        "hex_id": stage2_record["hex_id"],
        "rank": int(stage2_record["rank"]),
        "name": clean_text(stage2_record.get("name")),
        "final_affluence_score": round_num(stage2_record.get("final_affluence_score"), 4),
        "base_affluence_score": round_num(stage2_record.get("base_affluence_score"), 4),
        "affluence_tier": clean_text(stage2_record.get("affluence_tier")),
        "spatial_relation": clean_text(stage2_record.get("spatial_relation")),
        "confidence_score": round_num(stage2_record.get("confidence_score"), 4),
        "component_scores": {
            "society_score": round_num(scores.get("society_score"), 6),
            "society_cluster_score": round_num(scores.get("society_cluster_score"), 6),
            "school_score": round_num(scores.get("school_score"), 6),
            "school_access_score": round_num(scores.get("school_access_score"), 6),
            "residential_school_fit_score": round_num(
                scores.get("residential_school_fit_score"), 6
            ),
            "hospital_score": round_num(scores.get("hospital_score"), 6),
            "market_score": round_num(scores.get("market_score"), 6),
            "sez_workplace_score": round_num(scores.get("sez_workplace_score"), 6),
            "habitability_score": round_num(scores.get("habitability_score"), 6),
        },
        "tam": {
            "countable_family_tam": round_num(countable_family_tam, 2),
            "direct_family_tam": round_num(direct_family_tam, 2),
            "direct_total_units": round_num(tam.get("direct_total_units"), 2),
            "direct_luxury_society_tam": round_num(tam.get("direct_luxury_society_tam"), 2),
            "nearby_family_tam_weighted_context": round_num(
                tam.get("nearby_family_tam_weighted"), 2
            ),
            "society_cluster_tam_weighted_context_not_counted": round_num(
                tam.get("society_cluster_tam_weighted"), 2
            ),
            "surrounding_affluent_cluster_tam_weighted_context_not_counted": round_num(
                tam.get("surrounding_affluent_cluster_tam_weighted"), 2
            ),
            "income_band_family_tam": income_band_family_tam,
            "conservative_50l_plus_family_tam": round_num(conservative_50l_plus, 2),
            "conservative_50l_plus_share_of_direct_tam": round_num(
                conservative_50l_plus_share, 4
            ),
            "estimated_40l_plus_family_tam_linear_25_50_split": round_num(
                estimated_40l_plus_linear, 2
            ),
            "estimated_40l_plus_share_linear_25_50_split": round_num(
                estimated_40l_plus_linear_share, 4
            ),
            "countable_school_age_families": round(countable_school_age_families, 2),
            "countable_school_age_children": round(countable_school_age_children, 2),
            "countable_wealthy_school_children": round_num(
                tam.get("countable_wealthy_school_children"), 2
            ),
            "derivation": {
                "school_age_family_rate": SCHOOL_AGE_FAMILY_RATE,
                "children_per_school_age_family": CHILDREN_PER_SCHOOL_AGE_FAMILY,
                "wealthy_school_children_source": (
                    "Stage 2 countable school-age children multiplied by local school access score."
                ),
            },
        },
        "market": {
            "market_price_per_sqft": market.get("market_price_per_sqft"),
            "rental_yield_pct": market.get("rental_yield_pct"),
            "yearly_appreciation_pct": market.get("yearly_appreciation_pct"),
            "activity_score": market.get("activity_score"),
            "premium_lens_score": market.get("premium_lens_score"),
            "dominant_budget_segment": market.get("dominant_budget_segment"),
            "dominant_budget_share": market.get("dominant_budget_share"),
            "budget_entropy": market.get("budget_entropy"),
            "refined_budget_segment": market.get("refined_budget_segment"),
            "premium_candidate_score": market.get("premium_candidate_score"),
            "spatial_confidence": market.get("spatial_confidence"),
            "locality_count": market.get("locality_count"),
            "support_weight": market.get("support_weight"),
            "sale_total_count": market.get("sale_total_count"),
        },
        "habitability": habitability,
        "poi_summary": {
            "societies_direct_count": int(num(poi_summary.get("societies_direct_count"))),
            "societies_nearby_count": int(num(poi_summary.get("societies_nearby_count"))),
            "society_cluster_project_count": int(
                num(poi_summary.get("society_cluster_project_count"))
            ),
            "schools_nearby_count": int(num(poi_summary.get("schools_nearby_count"))),
            "eligible_school_routes_count": int(
                num(poi_summary.get("eligible_school_routes_count"))
            ),
            "effective_school_score_count": int(
                num(poi_summary.get("effective_school_score_count"))
            ),
            "hospitals_nearby_count": int(num(poi_summary.get("hospitals_nearby_count"))),
            "sez_nearby_count": int(num(poi_summary.get("sez_nearby_count"))),
        },
        "society_summary": summarize_societies(stage2_record),
        "school_summary": summarize_schools(stage2_record),
        "hospital_summary": summarize_hospitals(stage2_record),
        "top_evidence": {
            "societies": safe_list(safe_dict(stage2_record.get("top_evidence")).get("societies")),
            "schools": safe_list(safe_dict(stage2_record.get("top_evidence")).get("schools")),
            "hospitals": safe_list(safe_dict(stage2_record.get("top_evidence")).get("hospitals")),
            "sez_workplaces": safe_list(
                safe_dict(stage2_record.get("top_evidence")).get("sez_workplaces")
            ),
        },
        "routing": safe_dict(stage2_record.get("routing")),
        "quality_flags": safe_list(stage2_record.get("quality_flags")),
        "decision_notes": [
            "Use countable_family_tam as the family TAM estimate for this hex.",
            "Use nearby and cluster TAM only as spatial context, not as additional countable families.",
            "Use top schools as plausible premium-school access evidence, not as assigned enrollment.",
            "Inspect top_evidence before making high-value market decisions.",
        ],
    }


def flat_record(record):
    tam = record["tam"]
    market = record["market"]
    scores = record["component_scores"]
    habitability = safe_dict(record["habitability"])
    poi_summary = record["poi_summary"]
    top_societies = record["top_evidence"]["societies"][:5]
    top_schools = record["top_evidence"]["schools"][:5]
    top_hospitals = record["top_evidence"]["hospitals"][:5]
    return {
        "rank": record["rank"],
        "hex_id": record["hex_id"],
        "name": record["name"],
        "final_affluence_score": record["final_affluence_score"],
        "affluence_tier": record["affluence_tier"],
        "spatial_relation": record["spatial_relation"],
        "confidence_score": record["confidence_score"],
        "countable_family_tam": tam["countable_family_tam"],
        "direct_family_tam": tam["direct_family_tam"],
        "direct_total_units": tam["direct_total_units"],
        "direct_luxury_society_tam": tam["direct_luxury_society_tam"],
        "conservative_50l_plus_family_tam": tam["conservative_50l_plus_family_tam"],
        "conservative_50l_plus_share_of_direct_tam": tam[
            "conservative_50l_plus_share_of_direct_tam"
        ],
        "estimated_40l_plus_family_tam_linear_25_50_split": tam[
            "estimated_40l_plus_family_tam_linear_25_50_split"
        ],
        "estimated_40l_plus_share_linear_25_50_split": tam[
            "estimated_40l_plus_share_linear_25_50_split"
        ],
        "countable_school_age_families": tam["countable_school_age_families"],
        "countable_school_age_children": tam["countable_school_age_children"],
        "countable_wealthy_school_children": tam["countable_wealthy_school_children"],
        "nearby_family_tam_weighted_context": tam["nearby_family_tam_weighted_context"],
        "society_cluster_tam_weighted_context_not_counted": tam[
            "society_cluster_tam_weighted_context_not_counted"
        ],
        "market_price_per_sqft": market.get("market_price_per_sqft"),
        "refined_budget_segment": market.get("refined_budget_segment"),
        "premium_candidate_score": market.get("premium_candidate_score"),
        "rental_yield_pct": market.get("rental_yield_pct"),
        "yearly_appreciation_pct": market.get("yearly_appreciation_pct"),
        "society_score": scores["society_score"],
        "society_cluster_score": scores["society_cluster_score"],
        "school_score": scores["school_score"],
        "school_access_score": scores["school_access_score"],
        "residential_school_fit_score": scores["residential_school_fit_score"],
        "hospital_score": scores["hospital_score"],
        "market_score": scores["market_score"],
        "sez_workplace_score": scores["sez_workplace_score"],
        "habitability_score": scores["habitability_score"],
        "habitability_class": habitability.get("habitability_class"),
        "habitable_for_residential_tam": habitability.get("habitable_for_residential_tam"),
        "societies_direct_count": poi_summary["societies_direct_count"],
        "societies_nearby_count": poi_summary["societies_nearby_count"],
        "society_cluster_project_count": poi_summary["society_cluster_project_count"],
        "eligible_school_routes_count": poi_summary["eligible_school_routes_count"],
        "hospitals_nearby_count": poi_summary["hospitals_nearby_count"],
        "top_societies": " | ".join(
            f"{item.get('name')} ({item.get('category')}, TAM {fmt_number(item.get('estimated_families_tam'))})"
            for item in top_societies
        ),
        "top_schools": " | ".join(
            f"{item.get('name')} ({item.get('category')}, {fmt_number(item.get('travel_time_min_at_35_kmph'), 1)} min)"
            for item in top_schools
        ),
        "top_hospitals": " | ".join(
            f"{item.get('name')} ({item.get('category')}, {fmt_number(item.get('travel_time_min_at_35_kmph'), 1)} min)"
            for item in top_hospitals
        ),
        "quality_flags": " | ".join(record["quality_flags"]),
    }


def write_csv(records):
    rows = [flat_record(record) for record in records]
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_geojson(records):
    features = []
    for record in records:
        features.append(
            {
                "type": "Feature",
                "geometry": geojson_geometry(record["hex_id"]),
                "properties": flat_record(record),
            }
        )
    write_json(OUTPUT_GEOJSON, {"type": "FeatureCollection", "features": features})


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


def kml_description(record):
    tam = record["tam"]
    market = record["market"]
    scores = record["component_scores"]
    habitability = safe_dict(record["habitability"])
    society_rows = [
        [
            esc(item.get("name")),
            esc(item.get("category")),
            fmt_number(item.get("estimated_families_tam")),
            fmt_number(item.get("total_units")),
            fmt_number(item.get("avg_price_per_sqft")),
            fmt_number(item.get("distance_km"), 2),
        ]
        for item in record["top_evidence"]["societies"][:8]
    ]
    school_rows = [
        [
            esc(item.get("name")),
            esc(item.get("category")),
            esc(item.get("board")),
            fmt_number(item.get("annual_fee")),
            fmt_number(item.get("estimated_student_count")),
            fmt_number(item.get("travel_time_min_at_35_kmph"), 1),
        ]
        for item in record["top_evidence"]["schools"][:10]
    ]
    hospital_rows = [
        [
            esc(item.get("name")),
            esc(item.get("category")),
            fmt_number(item.get("doctors_count")),
            fmt_number(item.get("reviews_count")),
            fmt_number(item.get("travel_time_min_at_35_kmph"), 1),
        ]
        for item in record["top_evidence"]["hospitals"][:6]
    ]
    sez_rows = [
        [
            esc(item.get("name")),
            fmt_number(item.get("office_spaces")),
            fmt_number(item.get("distance_km"), 2),
            fmt_number(item.get("overlap_ratio"), 3),
        ]
        for item in record["top_evidence"]["sez_workplaces"][:5]
    ]
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:800px;color:#111827;">
      <h2 style="margin:0 0 4px 0;font-size:18px;">#{record['rank']} {esc(record['name'])}</h2>
      <div style="font-size:11px;color:#6b7280;">{esc(record['hex_id'])}</div>
      <table style="border-collapse:collapse;width:100%;margin-top:10px;"><tr>
        {stat_cell("Final score", fmt_number(record["final_affluence_score"], 1))}
        {stat_cell("Tier", esc(record["affluence_tier"]))}
        {stat_cell("Confidence", fmt_number(record["confidence_score"], 2))}
        {stat_cell("Spatial relation", esc(record["spatial_relation"]))}
      </tr><tr>
        {stat_cell("Countable family TAM", fmt_number(tam["countable_family_tam"]))}
        {stat_cell("Direct units", fmt_number(tam["direct_total_units"]))}
        {stat_cell("School-age children", fmt_number(tam["countable_school_age_children"]))}
        {stat_cell("Wealthy-school children", fmt_number(tam["countable_wealthy_school_children"]))}
      </tr><tr>
        {stat_cell("Society", fmt_number(scores["society_score"], 2))}
        {stat_cell("School access", fmt_number(scores["school_access_score"], 2))}
        {stat_cell("School fit", fmt_number(scores["residential_school_fit_score"], 2))}
        {stat_cell("Habitable", esc(habitability.get("habitability_class")))}
      </tr></table>
      {section("Market", mini_table(["Metric", "Value"], [
        ["Price/sqft", fmt_number(market.get("market_price_per_sqft"))],
        ["Refined budget segment", esc(market.get("refined_budget_segment"))],
        ["Premium candidate score", fmt_number(market.get("premium_candidate_score"), 2)],
        ["Rental yield", fmt_number(market.get("rental_yield_pct"), 2)],
        ["Yearly appreciation", fmt_number(market.get("yearly_appreciation_pct"), 2)]
      ]))}
      {section("TAM Derivation", mini_table(["Metric", "Value"], [
        ["Countable direct family TAM", fmt_number(tam["countable_family_tam"])],
        ["School-age families = family TAM x 0.38", fmt_number(tam["countable_school_age_families"])],
        ["School-age children = school-age families x 1.25", fmt_number(tam["countable_school_age_children"])],
        ["Wealthy-school children = children x school access", fmt_number(tam["countable_wealthy_school_children"])],
        ["50L+ conservative family TAM", fmt_number(tam["conservative_50l_plus_family_tam"])],
        ["50L+ share of direct TAM", fmt_number(100 * tam["conservative_50l_plus_share_of_direct_tam"], 1) + "%"],
        ["Estimated 40L+ TAM (linear 25L-50L split)", fmt_number(tam["estimated_40l_plus_family_tam_linear_25_50_split"])],
        ["Estimated 40L+ share", fmt_number(100 * tam["estimated_40l_plus_share_linear_25_50_split"], 1) + "%"],
        ["Nearby weighted TAM", fmt_number(tam["nearby_family_tam_weighted_context"]) + " context only"],
        ["Society cluster TAM", fmt_number(tam["society_cluster_tam_weighted_context_not_counted"]) + " context only"]
      ]))}
      {section("Habitability", mini_table(["Metric", "Value"], [
        ["Class", esc(habitability.get("habitability_class"))],
        ["Habitable for TAM", fmt_bool(habitability.get("habitable_for_residential_tam"))],
        ["Buildings", fmt_number(habitability.get("building_count"))],
        ["Building coverage", fmt_number(habitability.get("building_coverage_ratio"), 4)]
      ]))}
      {section("Top societies", mini_table(["Society", "Category", "TAM", "Units", "Price/sqft", "Km"], society_rows))}
      {section("Top schools", mini_table(["School", "Category", "Board", "Fee", "Students", "Min"], school_rows))}
      {section("Top hospitals", mini_table(["Hospital", "Category", "Doctors", "Reviews", "Min"], hospital_rows))}
      {section("SEZ context", mini_table(["Zone", "Offices", "Km", "Overlap"], sez_rows))}
      {section("Quality flags", "<div style='font-size:12px;color:#374151;'>" + esc(", ".join(record["quality_flags"]) or "None") + "</div>")}
    </div>
    """


def kml_style(record, mode):
    highlight = mode == "highlight"
    alpha = 220 if highlight else 175
    line = "#111827" if highlight else "#f8fafc"
    width = "2.2" if highlight else "0.8"
    return f"""
    <Style id="final_hex_{record['hex_id']}_{mode}">
      <LineStyle><color>{hex_to_kml_color(line, 235)}</color><width>{width}</width></LineStyle>
      <PolyStyle><color>{hex_to_kml_color(score_color(record['final_affluence_score']), alpha)}</color><fill>1</fill><outline>1</outline></PolyStyle>
    </Style>"""


def kml_style_map(record):
    return f"""
    <StyleMap id="final_hex_{record['hex_id']}_stylemap">
      <Pair><key>normal</key><styleUrl>#final_hex_{record['hex_id']}_normal</styleUrl></Pair>
      <Pair><key>highlight</key><styleUrl>#final_hex_{record['hex_id']}_highlight</styleUrl></Pair>
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


def poi_description(title, rows):
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;color:#111827;">
      <h2 style="margin:0 0 8px 0;font-size:16px;">{esc(title)}</h2>
      {mini_table(["Metric", "Value"], rows)}
    </div>
    """


def valid_lat_lon(lat, lon):
    return 12.45 <= num(lat, -999) <= 13.50 and 77.10 <= num(lon, -999) <= 78.10


def source_url(value):
    text = clean_text(value, "")
    if not text:
        return "NA"
    return f'<a href="{esc(text)}">source</a>'


def load_society_pins():
    pins = []
    for item in load_json(SOCIETIES_PATH):
        lat = num(item.get("Latitude"), None)
        lon = num(item.get("Longitude"), None)
        if lat is None or lon is None or not valid_lat_lon(lat, lon):
            continue
        pins.append(
            {
                "name": clean_text(item.get("Society Name")),
                "lat": lat,
                "lon": lon,
                "description": poi_description(
                    clean_text(item.get("Society Name")),
                    [
                        ["Category", esc(item.get("Q4 Category"))],
                        ["Locality", esc(item.get("Locality"))],
                        ["Estimated families TAM", fmt_number(item.get("Estimated Families (TAM)"))],
                        ["Total units", fmt_number(item.get("Total Units"))],
                        ["Avg price/sqft", fmt_number(item.get("Avg Price per SqFt"))],
                        ["Construction", esc(item.get("Construction Status"))],
                        ["RERA", esc(item.get("RERA ID"))],
                        ["URL", source_url(item.get("URL"))],
                    ],
                ),
            }
        )
    return pins


def load_school_pins():
    pins = []
    for item in load_json(SCHOOLS_PATH):
        lat = num(item.get("Latitude"), None)
        lon = num(item.get("Longitude"), None)
        if lat is None or lon is None or not valid_lat_lon(lat, lon):
            continue
        pins.append(
            {
                "name": clean_text(item.get("School Name")),
                "lat": lat,
                "lon": lon,
                "description": poi_description(
                    clean_text(item.get("School Name")),
                    [
                        ["Category", esc(item.get("Q4 Category"))],
                        ["Board", esc(item.get("Board"))],
                        ["Annual fee", fmt_number(item.get("Average Fee (Annual)"))],
                        ["Computed students", fmt_number(item.get("Computed Student Count"))],
                        ["Est. 2nd-9th students", fmt_number(item.get("Est. 2nd-9th Student Count"))],
                        ["Classes", f"{esc(item.get('Starting Class'))} to {esc(item.get('Ending Class'))}"],
                        ["URL", source_url(item.get("URL"))],
                    ],
                ),
            }
        )
    return pins


def load_hospital_pins():
    pins = []
    for item in load_json(HOSPITALS_PATH):
        lat = num(item.get("Latitude"), None)
        lon = num(item.get("Longitude"), None)
        if lat is None or lon is None or not valid_lat_lon(lat, lon):
            continue
        pins.append(
            {
                "name": clean_text(item.get("Hospital Name")),
                "lat": lat,
                "lon": lon,
                "description": poi_description(
                    clean_text(item.get("Hospital Name")),
                    [
                        ["Category", esc(item.get("Q4 Category"))],
                        ["Locality", esc(item.get("Locality"))],
                        ["Doctors", fmt_number(item.get("Doctors Count"))],
                        ["Beds", fmt_number(item.get("Extracted Beds"))],
                        ["Rating", fmt_number(item.get("Rating"), 1)],
                        ["Reviews", fmt_number(item.get("Reviews Count"))],
                        ["URL", source_url(item.get("URL"))],
                    ],
                ),
            }
        )
    return pins


def write_kml(records):
    FINAL_MAP_DIR.mkdir(parents=True, exist_ok=True)
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
        <styleUrl>#final_hex_{record['hex_id']}_stylemap</styleUrl>
        <description><![CDATA[{cdata(kml_description(record))}]]></description>
        <Polygon>
          <outerBoundaryIs><LinearRing><coordinates>{coordinates_for_kml(record['hex_id'])}</coordinates></LinearRing></outerBoundaryIs>
        </Polygon>
      </Placemark>"""
        )

    society_pins = load_society_pins()
    school_pins = load_school_pins()
    hospital_pins = load_hospital_pins()

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{CITY_NAME} Hex-7 Affluent Family Intelligence</name>
    {''.join(styles)}
    {poi_pin_style("poi_society", "#16a34a", 0.9)}
    {poi_pin_style("poi_school", "#2563eb", 0.85)}
    {poi_pin_style("poi_hospital", "#dc2626", 0.85)}
    <Folder>
      <name>Final Hex Intelligence ({len(records)})</name>
      {''.join(placemarks)}
    </Folder>
    <Folder>
      <name>Source POI Pins</name>
      <Folder>
        <name>Societies ({len(society_pins)})</name>
        {''.join(point_placemark(pin["name"], pin["lat"], pin["lon"], "poi_society", pin["description"]) for pin in society_pins)}
      </Folder>
      <Folder>
        <name>Schools ({len(school_pins)})</name>
        {''.join(point_placemark(pin["name"], pin["lat"], pin["lon"], "poi_school", pin["description"]) for pin in school_pins)}
      </Folder>
      <Folder>
        <name>Hospitals ({len(hospital_pins)})</name>
        {''.join(point_placemark(pin["name"], pin["lat"], pin["lon"], "poi_hospital", pin["description"]) for pin in hospital_pins)}
      </Folder>
    </Folder>
  </Document>
</kml>
"""
    OUTPUT_KML.write_text(kml)
    return {
        "society_pins": len(society_pins),
        "school_pins": len(school_pins),
        "hospital_pins": len(hospital_pins),
    }


def write_methodology(records, audit):
    text = f"""# {CITY_NAME} Hex-7 Affluent Family Intelligence Methodology

This is the final company-facing layer built from the validated Stage 2 hex output.
It intentionally keeps the unit of decision-making at H3 resolution 7.

## Why Stage 3 Huff allocation is not used as the final deliverable

The society-to-school Huff model conserves children mathematically, but it answers a
different question: which school each society might choose. The company need is more
direct: for any clicked hex, show affluent family TAM, market evidence, nearby affluent
societies, school access, hospital access, habitability, and raw evidence.

The per-hex output is therefore more useful and less fragile because it avoids:

- merging many hexes into oversized connected areas,
- pretending to know school choice at child-level precision,
- over-weighting schools as destinations rather than access amenities,
- adding model complexity where direct derived counts are enough.

## Countable TAM

Use `tam.countable_family_tam` as the primary family TAM. It is the direct society
family estimate inside the hex and is not inflated with neighboring hexes.

Nearby and cluster fields are retained only as context:

- `nearby_family_tam_weighted_context`
- `society_cluster_tam_weighted_context_not_counted`
- `surrounding_affluent_cluster_tam_weighted_context_not_counted`

These fields help identify wealthy clusters around a small H3-7 hex, but they should
not be added to countable family TAM.

## Derived child estimates

The final file keeps the simple Stage 2 derivation:

```text
countable_school_age_families = countable_family_tam * {SCHOOL_AGE_FAMILY_RATE}
countable_school_age_children = countable_school_age_families * {CHILDREN_PER_SCHOOL_AGE_FAMILY}
countable_wealthy_school_children = countable_school_age_children * local_school_access_score
```

`countable_wealthy_school_children` is a modeled estimate, not ground-truth enrollment.
It is meant to answer: "How much affluent school-going child TAM is plausibly present
in this hex, given residential evidence and access to premium schools?"

## School evidence

Top schools are listed as local access evidence using OSRM route distance and
35 km/h travel-time conversion from Stage 2. Families in the city often use buses,
so the Stage 2 school logic uses bus-aware travel windows and does not penalize the
first 15 minutes heavily.

Schools are not assigned to individual children in this final output.

## Income-band interpretation

`conservative_50l_plus_family_tam` counts only direct TAM in these bands:

- 50L-1Cr
- 1Cr-2Cr
- 2Cr-5Cr
- 5Cr+

The `25L-50L` band is not counted in this conservative measure because it crosses
the 40 LPA threshold. Some families in that band may earn over 40 LPA, but the source
band is too wide to claim that precisely.

Across the current final output, the conservative 50L+ direct TAM share is
{audit['income']['conservative_50l_plus_share_pct']}%. If the 25L-50L band is split
linearly and only the 40L-50L slice is counted, the estimated 40L+ direct TAM share is
{audit['income']['estimated_40l_plus_share_linear_25_50_split_pct']}%.

## Output files

- `{OUTPUT_JSON}`
- `{OUTPUT_CSV}`
- `{OUTPUT_GEOJSON}`
- `{OUTPUT_KML}`

## Audit summary

- Hexes: {audit['hex_count']}
- Countable family TAM: {audit['tam_totals']['countable_family_tam']}
- Countable school-age children: {audit['tam_totals']['countable_school_age_children']}
- Countable wealthy-school children: {audit['tam_totals']['countable_wealthy_school_children']}
- Estimated 40L+ direct family TAM: {audit['tam_totals']['estimated_40l_plus_family_tam_linear_25_50_split']}
- Source society pins in KML: {audit['kml_pins']['society_pins']}
- Source school pins in KML: {audit['kml_pins']['school_pins']}
- Source hospital pins in KML: {audit['kml_pins']['hospital_pins']}
"""
    METHODOLOGY_MD.parent.mkdir(parents=True, exist_ok=True)
    METHODOLOGY_MD.write_text(text)


def write_readme(audit):
    text = f"""# {CITY_NAME} Hex-7 Affluent Family Intelligence

This folder contains the final per-hex deliverable for the affluent-family TAM analysis.

## Recommended files

- `{OUTPUT_JSON.name}` - full nested evidence file.
- `{OUTPUT_CSV.name}` - spreadsheet-friendly summary.
- `{OUTPUT_GEOJSON.name}` - GIS polygon layer.
- `../../maps/final/{OUTPUT_KML.name}` - click-ready Google Earth map.

## What to use for decisions

- Use `tam.countable_family_tam` for countable affluent family TAM.
- Use `tam.countable_school_age_children` for school-age child TAM.
- Use `tam.countable_wealthy_school_children` as a premium-school-access-adjusted child estimate.
- Use nearby and cluster TAM fields only as context, not as extra families.
- Use `top_evidence` to inspect the societies, schools, hospitals, and SEZ/workplace context behind each score.

## Current totals

- Hexes: {audit['hex_count']}
- Countable family TAM: {audit['tam_totals']['countable_family_tam']}
- Countable school-age children: {audit['tam_totals']['countable_school_age_children']}
- Countable wealthy-school children: {audit['tam_totals']['countable_wealthy_school_children']}
- Conservative 50L+ direct TAM share: {audit['income']['conservative_50l_plus_share_pct']}%
- Estimated 40L+ direct TAM share using a linear split of the 25L-50L band: {audit['income']['estimated_40l_plus_share_linear_25_50_split_pct']}%

## Important caveat

This is a decision-support layer, not ground truth. The strongest fields are direct society
TAM, total units, market pricing, and raw POI evidence. Derived child estimates are useful
for prioritization, but should be validated with field research before commercial decisions.
"""
    OUTPUT_README.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_README.write_text(text)


def make_audit(records, kml_pins):
    tier_counts = Counter(record["affluence_tier"] for record in records)
    spatial_counts = Counter(record["spatial_relation"] for record in records)
    habitability_counts = Counter(
        clean_text(safe_dict(record["habitability"]).get("habitability_class")) for record in records
    )
    flag_counts = Counter(flag for record in records for flag in record["quality_flags"])
    tam_totals = {
        "countable_family_tam": round_num(
            sum(record["tam"]["countable_family_tam"] for record in records), 2
        ),
        "direct_family_tam": round_num(
            sum(record["tam"]["direct_family_tam"] for record in records), 2
        ),
        "direct_total_units": round_num(
            sum(record["tam"]["direct_total_units"] for record in records), 2
        ),
        "countable_school_age_families": round_num(
            sum(record["tam"]["countable_school_age_families"] for record in records), 2
        ),
        "countable_school_age_children": round_num(
            sum(record["tam"]["countable_school_age_children"] for record in records), 2
        ),
        "countable_wealthy_school_children": round_num(
            sum(record["tam"]["countable_wealthy_school_children"] for record in records), 2
        ),
        "conservative_50l_plus_family_tam": round_num(
            sum(record["tam"]["conservative_50l_plus_family_tam"] for record in records), 2
        ),
        "estimated_40l_plus_family_tam_linear_25_50_split": round_num(
            sum(
                record["tam"]["estimated_40l_plus_family_tam_linear_25_50_split"]
                for record in records
            ),
            2,
        ),
    }
    share = (
        100.0 * tam_totals["conservative_50l_plus_family_tam"] / tam_totals["direct_family_tam"]
        if tam_totals["direct_family_tam"] > 0
        else 0.0
    )
    linear_40l_share = (
        100.0
        * tam_totals["estimated_40l_plus_family_tam_linear_25_50_split"]
        / tam_totals["direct_family_tam"]
        if tam_totals["direct_family_tam"] > 0
        else 0.0
    )
    audit = {
        "hex_count": len(records),
        "source": str(STAGE2_MASTER),
        "outputs": {
            "json": str(OUTPUT_JSON),
            "csv": str(OUTPUT_CSV),
            "geojson": str(OUTPUT_GEOJSON),
            "kml": str(OUTPUT_KML),
            "readme": str(OUTPUT_README),
            "methodology": str(METHODOLOGY_MD),
        },
        "tier_counts": dict(tier_counts),
        "spatial_relation_counts": dict(spatial_counts),
        "habitability_counts": dict(habitability_counts),
        "quality_flag_counts": dict(flag_counts),
        "tam_totals": tam_totals,
        "income": {
            "conservative_50l_plus_bands": sorted(COUNTABLE_50L_PLUS_BANDS),
            "conservative_50l_plus_share_pct": round(share, 2),
            "estimated_40l_plus_share_linear_25_50_split_pct": round(linear_40l_share, 2),
            "note": (
                "25L-50L is excluded from conservative 50L+ because it crosses the 40 LPA "
                "threshold. The separate estimated 40L+ metric assumes a linear split "
                "inside the 25L-50L band."
            ),
        },
        "kml_pins": kml_pins,
        "top_25_hexes": [
            {
                "rank": record["rank"],
                "hex_id": record["hex_id"],
                "name": record["name"],
                "final_affluence_score": record["final_affluence_score"],
                "tier": record["affluence_tier"],
                "countable_family_tam": record["tam"]["countable_family_tam"],
                "countable_wealthy_school_children": record["tam"][
                    "countable_wealthy_school_children"
                ],
            }
            for record in records[:25]
        ],
        "guardrails": [
            "No Huff school allocation is used in final outputs.",
            "Nearby and cluster TAM fields are context only and are not counted as families.",
            "KML includes raw POI pins so decisions can be checked against source evidence.",
        ],
    }
    return audit


def main():
    stage2_records = load_json(STAGE2_MASTER)
    records = [final_record(record) for record in stage2_records]
    records.sort(key=lambda item: item["rank"])

    payload = {
        "metadata": {
            "title": f"{CITY_NAME} Hex-7 Affluent Family Intelligence",
            "source_stage": "Stage 2 hex-7 affluence master",
            "source_file": str(STAGE2_MASTER),
            "hex_count": len(records),
            "model_position": (
                "Final per-hex decision-support layer. The experimental Huff school "
                "allocation model is intentionally excluded."
            ),
        },
        "schema_notes": {
            "countable_family_tam": "Primary family TAM. Direct society TAM only.",
            "context_tam": "Nearby and cluster TAM fields are not countable families.",
            "top_evidence": "Raw evidence retained for explainability and manual inspection.",
        },
        "hexes": records,
    }
    write_json(OUTPUT_JSON, payload)
    write_csv(records)
    write_geojson(records)
    kml_pins = write_kml(records)
    audit = make_audit(records, kml_pins)
    write_json(AUDIT_JSON, audit)
    write_methodology(records, audit)
    write_readme(audit)

    print(f"Wrote {OUTPUT_JSON}")
    print(f"Wrote {OUTPUT_CSV}")
    print(f"Wrote {OUTPUT_GEOJSON}")
    print(f"Wrote {OUTPUT_KML}")
    print(f"Wrote {AUDIT_JSON}")
    print(f"Wrote {METHODOLOGY_MD}")


if __name__ == "__main__":
    main()
