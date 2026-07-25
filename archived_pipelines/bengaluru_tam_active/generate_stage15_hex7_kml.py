import html
import json
from collections import Counter, defaultdict
from pathlib import Path

import h3


DATA_DIR = Path("DATA")
PROCESSED_DATA_DIR = DATA_DIR / "processed"
AUDIT_DIR = DATA_DIR / "audits"
MAPS_DIR = Path("maps") / "h3"

INPUT_JSON = PROCESSED_DATA_DIR / "stage1_5_hex7_spatial_budget_features.json"
OUTPUT_KML = MAPS_DIR / "stage1_5_hex7_spatial_budget_choropleth.kml"
AUDIT_PATH = AUDIT_DIR / "stage1_5_hex7_spatial_budget_kml_audit.json"

BUDGET_COLORS = {
    "Affordable": "#22c55e",
    "Mid-Segment": "#f59e0b",
    "Premium": "#ef4444",
    "Premium Candidate": "#f97316",
    "Ultra Premium": "#7f1d1d",
    "Mixed/Diverse": "#94a3b8",
    "unknown": "#cbd5e1",
}

SEGMENT_LABELS = ("Affordable", "Mid-Segment", "Premium")


def load_records():
    with INPUT_JSON.open("r") as f:
        records = json.load(f)
    if not isinstance(records, list):
        raise ValueError(f"{INPUT_JSON} must contain a top-level array.")
    return records


def esc(value):
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def cdata(value):
    return str(value).replace("]]>", "]]]]><![CDATA[>")


def safe_dict(value):
    return value if isinstance(value, dict) else {}


def fmt_number(value, decimals=0, suffix=""):
    if value is None:
        return "NA"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return esc(value)
    if decimals == 0:
        text = f"{number:,.0f}"
    else:
        text = f"{number:,.{decimals}f}"
    return f"{text}{suffix}"


def fmt_pct(value, decimals=0):
    if value is None:
        return "NA"
    try:
        return f"{float(value) * 100:.{decimals}f}%"
    except (TypeError, ValueError):
        return "NA"


def metric_avg(record, metric):
    return safe_dict(safe_dict(record.get("market_insights")).get("metrics")).get(metric, {}).get(
        "weighted_avg"
    )


def smoothed_metric(record, metric):
    return safe_dict(safe_dict(record.get("smoothed_h3_res_7")).get("metrics")).get(metric)


def child_metric(record, metric):
    rollup = safe_dict(record.get("child_h3_res_8")).get("rolled_up_smoothed_values")
    return safe_dict(safe_dict(rollup).get("metrics")).get(metric)


def base_color(record):
    classification = record.get("refined_budget_segment") or record.get("budget_classification") or "unknown"
    if classification in BUDGET_COLORS:
        return BUDGET_COLORS[classification]
    if classification == "Mixed/Diverse":
        return BUDGET_COLORS["Mixed/Diverse"]
    dominant = record.get("dominant_budget_segment") or "unknown"
    return BUDGET_COLORS.get(dominant, BUDGET_COLORS["unknown"])


def hex_to_kml_color(hex_color, alpha):
    color = hex_color.lstrip("#")
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)
    return f"{alpha:02x}{b:02x}{g:02x}{r:02x}"


def fill_alpha(record, highlight=False):
    share = record.get("spatial_confidence") or record.get("dominant_budget_share") or 0.0
    classification = record.get("refined_budget_segment") or record.get("budget_classification") or ""
    if classification == "Mixed/Diverse":
        alpha = 92
    elif classification == "Premium Candidate":
        alpha = 118 + int(52 * share)
    elif classification == "Ultra Premium":
        alpha = 160 + int(46 * share)
    elif classification.startswith("Mixed"):
        alpha = 96 + int(48 * share)
    else:
        alpha = 118 + int(58 * share)
    if highlight:
        alpha += 52
    return max(72, min(230, alpha))


def style_id(record, mode):
    return f"hex7_{record['hex_id']}_{mode}"


def style_map_id(record):
    return f"hex7_{record['hex_id']}_stylemap"


def kml_style(record, mode):
    color = base_color(record)
    highlight = mode == "highlight"
    fill = hex_to_kml_color(color, fill_alpha(record, highlight=highlight))
    line_color = hex_to_kml_color("#111827" if highlight else "#f8fafc", 235)
    line_width = "2.2" if highlight else "0.8"
    return f"""
    <Style id="{style_id(record, mode)}">
      <LineStyle>
        <color>{line_color}</color>
        <width>{line_width}</width>
      </LineStyle>
      <PolyStyle>
        <color>{fill}</color>
        <fill>1</fill>
        <outline>1</outline>
      </PolyStyle>
    </Style>"""


def kml_style_map(record):
    return f"""
    <StyleMap id="{style_map_id(record)}">
      <Pair>
        <key>normal</key>
        <styleUrl>#{style_id(record, "normal")}</styleUrl>
      </Pair>
      <Pair>
        <key>highlight</key>
        <styleUrl>#{style_id(record, "highlight")}</styleUrl>
      </Pair>
    </StyleMap>"""


def coordinates_for_hex(hex_id):
    boundary = h3.cell_to_boundary(hex_id)
    coords = [(lon, lat) for lat, lon in boundary]
    if coords:
        coords.append(coords[0])
    return " ".join(f"{lon:.8f},{lat:.8f},0" for lon, lat in coords)


def cell_style():
    return (
        "border:1px solid #e5e7eb;"
        "padding:8px 9px;"
        "vertical-align:top;"
        "background:#ffffff;"
    )


def label_style():
    return "font-size:10px;letter-spacing:.04em;text-transform:uppercase;color:#6b7280;"


def value_style():
    return "font-size:13px;color:#111827;font-weight:600;margin-top:2px;"


def stat(label, value):
    return f"""
      <td style="{cell_style()}">
        <div style="{label_style()}">{esc(label)}</div>
        <div style="{value_style()}">{value}</div>
      </td>"""


def section(title, body):
    return f"""
      <div style="margin-top:14px;">
        <div style="font-size:12px;font-weight:700;color:#111827;margin:0 0 6px 0;">{esc(title)}</div>
        {body}
      </div>"""


def mini_table(headers, rows):
    if not rows:
        return '<div style="color:#6b7280;font-size:12px;">No data</div>'
    header_html = "".join(
        f'<th style="border-bottom:1px solid #e5e7eb;padding:6px 7px;text-align:left;font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.04em;background:#f9fafb;">{esc(header)}</th>'
        for header in headers
    )
    rows_html = []
    for row in rows:
        rows_html.append(
            "<tr>"
            + "".join(
                f'<td style="border-bottom:1px solid #f3f4f6;padding:6px 7px;font-size:11px;color:#111827;vertical-align:top;">{cell}</td>'
                for cell in row
            )
            + "</tr>"
        )
    return f"""
      <table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;background:#ffffff;">
        <thead><tr>{header_html}</tr></thead>
        <tbody>{''.join(rows_html)}</tbody>
      </table>"""


def budget_bar(record):
    shares = record.get("spatial_budget_segments") or record.get("budget_segments") or {}
    rows = []
    for segment in SEGMENT_LABELS:
        share = shares.get(segment, 0.0) or 0.0
        width = max(1, int(round(share * 100))) if share > 0 else 0
        color = BUDGET_COLORS[segment]
        rows.append(
            f"""
            <tr>
              <td style="width:88px;padding:5px 0;font-size:11px;color:#374151;">{esc(segment)}</td>
              <td style="padding:5px 8px;">
                <div style="height:8px;background:#f3f4f6;border:1px solid #e5e7eb;">
                  <div style="height:8px;width:{width}%;background:{color};"></div>
                </div>
              </td>
              <td style="width:44px;text-align:right;font-size:11px;color:#111827;font-weight:600;">{fmt_pct(share)}</td>
            </tr>"""
        )
    return f"""
      <table style="width:100%;border-collapse:collapse;">
        <tbody>{''.join(rows)}</tbody>
      </table>"""


def direct_budget_bar(record):
    shares = record.get("budget_segments") or {}
    rows = []
    for segment in SEGMENT_LABELS:
        share = shares.get(segment, 0.0) or 0.0
        width = max(1, int(round(share * 100))) if share > 0 else 0
        color = BUDGET_COLORS[segment]
        rows.append(
            f"""
            <tr>
              <td style="width:88px;padding:5px 0;font-size:11px;color:#374151;">{esc(segment)}</td>
              <td style="padding:5px 8px;">
                <div style="height:8px;background:#f3f4f6;border:1px solid #e5e7eb;">
                  <div style="height:8px;width:{width}%;background:{color};"></div>
                </div>
              </td>
              <td style="width:44px;text-align:right;font-size:11px;color:#111827;font-weight:600;">{fmt_pct(share)}</td>
            </tr>"""
        )
    return f"""
      <table style="width:100%;border-collapse:collapse;">
        <tbody>{''.join(rows)}</tbody>
      </table>"""


def metric_grid(record):
    return f"""
      <table style="width:100%;border-collapse:collapse;">
        <tr>
          {stat("Price / sqft", "Rs " + fmt_number(metric_avg(record, "market_price_per_sqft")))}
          {stat("Rental yield", fmt_number(metric_avg(record, "rental_yield_pct"), 2, "%"))}
        </tr>
        <tr>
          {stat("YoY appreciation", fmt_number(metric_avg(record, "yearly_appreciation_pct"), 1, "%"))}
          {stat("Activity score", fmt_number(metric_avg(record, "activity_score"), 1))}
        </tr>
        <tr>
          {stat("Premium lens", fmt_number(metric_avg(record, "premium_lens_score"), 4))}
          {stat("Entropy", fmt_number(record.get("budget_entropy"), 3))}
        </tr>
      </table>"""


def support_grid(record):
    support = safe_dict(safe_dict(record.get("market_insights")).get("support"))
    inventory = safe_dict(safe_dict(record.get("market_insights")).get("inventory"))
    return f"""
      <table style="width:100%;border-collapse:collapse;">
        <tr>
          {stat("Localities", fmt_number(support.get("locality_count")))}
          {stat("Support weight", fmt_number(support.get("total_support_weight"), 1))}
        </tr>
        <tr>
          {stat("Registry", fmt_number(support.get("registry_count")))}
          {stat("Reviews", fmt_number(support.get("reviews_count")))}
        </tr>
        <tr>
          {stat("Rent listings", fmt_number(inventory.get("rent_total_count")))}
          {stat("Sale listings", fmt_number(inventory.get("sale_total_count")))}
        </tr>
        <tr>
          {stat("Buy excl. land", fmt_number(inventory.get("buy_total_count_excluding_land")))}
          {stat("H3-8 children", fmt_number(safe_dict(record.get("child_h3_res_8")).get("child_count")))}
        </tr>
      </table>"""


def neighbourhood_rows(record):
    rows = []
    for item in record.get("neighbourhoods") or []:
        rows.append(
            [
                esc(item.get("name")),
                fmt_pct(item.get("share")),
                fmt_number(item.get("locality_count")),
                fmt_number(item.get("support_weight"), 1),
                esc(item.get("subtype") or ""),
            ]
        )
    return rows


def locality_rows(record):
    rows = []
    for item in record.get("localities") or []:
        flags = ", ".join(item.get("quality_flags") or [])
        rows.append(
            [
                esc(item.get("name")),
                esc(item.get("neighbourhood_name")),
                esc(item.get("source_budget_segment")),
                fmt_number(item.get("support_weight"), 1),
                esc(item.get("h3_res_8")),
                f"{fmt_number(item.get('lat'), 5)}, {fmt_number(item.get('lon'), 5)}",
                esc(flags),
            ]
        )
    return rows


def tags_html(record):
    tags = record.get("tags") or []
    if not tags:
        return '<div style="color:#6b7280;font-size:12px;">No tags</div>'
    chips = []
    for tag in tags:
        chips.append(
            f"""
            <span style="display:inline-block;border:1px solid #e5e7eb;background:#f9fafb;color:#111827;font-size:11px;padding:4px 6px;margin:0 4px 5px 0;">
              {esc(tag.get("tag"))} <span style="color:#6b7280;">{fmt_pct(tag.get("share"))}</span>
            </span>"""
        )
    return "".join(chips)


def rollup_table(record):
    child = safe_dict(record.get("child_h3_res_8"))
    rolled = safe_dict(child.get("rolled_up_smoothed_values"))
    child_metrics = safe_dict(rolled.get("metrics"))
    smoothed = safe_dict(record.get("smoothed_h3_res_7"))
    smoothed_metrics = safe_dict(smoothed.get("metrics"))
    rows = [
        ["Rolled H3-8 price / sqft", "Rs " + fmt_number(child_metrics.get("price_sqft"))],
        ["Rolled H3-8 high income", fmt_number(child_metrics.get("high_income"), 1, "%")],
        ["Rolled H3-8 activity", fmt_number(child_metrics.get("activity_score"), 1)],
        ["Rolled H3-8 premium lens", fmt_number(child_metrics.get("premium_lens_score"), 4)],
        ["Smoothed H3-7 price / sqft", "Rs " + fmt_number(smoothed_metrics.get("market_price_per_sqft"))],
        ["Smoothed H3-7 activity", fmt_number(smoothed_metrics.get("activity_score"), 1)],
        ["Smoothed H3-7 segment", esc(smoothed.get("dominant_budget_segment"))],
        ["Smoothed H3-7 share", fmt_pct(smoothed.get("dominant_budget_share"))],
    ]
    return mini_table(["Signal", "Value"], rows)


def spatial_scoring_table(record):
    scoring = safe_dict(record.get("spatial_budget_scoring"))
    rows = [
        ["Refined segment", esc(record.get("refined_budget_segment"))],
        ["Original evidence label", esc(record.get("budget_classification"))],
        ["Premium candidate score", fmt_number(record.get("premium_candidate_score"), 3)],
        ["Spatial premium lag", fmt_pct(record.get("spatial_premium_lag"))],
        ["Premium cluster score", fmt_number(record.get("premium_cluster_score"), 3)],
        ["Spatial confidence", fmt_pct(record.get("spatial_confidence"))],
        ["Neighbor hexes", fmt_number(scoring.get("neighbor_hex_count"))],
        ["Spatial blend weight", fmt_pct(scoring.get("spatial_weight"))],
        ["Reasons", esc(", ".join(scoring.get("refinement_reasons") or []))],
    ]
    return mini_table(["Spatial Signal", "Value"], rows)


def quality_html(record):
    quality = safe_dict(record.get("quality"))
    flags = quality.get("flags") or []
    if not flags:
        return '<div style="color:#047857;font-size:12px;">No quality flags</div>'
    return "".join(
        f'<span style="display:inline-block;border:1px solid #fecaca;background:#fff1f2;color:#991b1b;font-size:11px;padding:4px 6px;margin:0 4px 5px 0;">{esc(flag)}</span>'
        for flag in flags
    )


def conflict_html(record):
    flags = record.get("spatial_conflict_flags") or []
    if not flags:
        return '<div style="color:#047857;font-size:12px;">No spatial conflict flags</div>'
    return "".join(
        f'<span style="display:inline-block;border:1px solid #fed7aa;background:#fff7ed;color:#9a3412;font-size:11px;padding:4px 6px;margin:0 4px 5px 0;">{esc(flag)}</span>'
        for flag in flags
    )


def html_card(record):
    dominant_neighbourhood = safe_dict(record.get("dominant_neighbourhood"))
    classification = record.get("refined_budget_segment") or record.get("budget_classification") or "unknown"
    original_classification = record.get("budget_classification") or "unknown"
    dominant_segment = record.get("dominant_budget_segment") or "unknown"
    color = base_color(record)
    subtitle = (
        f"{esc(dominant_neighbourhood.get('name'))} dominant neighbourhood"
        if dominant_neighbourhood
        else "No dominant neighbourhood"
    )
    return f"""
    <div style="font-family:Inter,Arial,sans-serif;width:520px;background:#ffffff;color:#111827;border:1px solid #d1d5db;">
      <div style="padding:14px 16px 12px 16px;border-bottom:1px solid #e5e7eb;background:#ffffff;">
        <div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.08em;">Stage 1.5 H3-7 Spatial Budget Hex</div>
        <div style="font-size:20px;line-height:1.22;font-weight:750;color:#111827;margin-top:4px;">{esc(record.get("name"))}</div>
        <div style="font-size:12px;color:#6b7280;margin-top:3px;">{subtitle}</div>
        <div style="margin-top:9px;">
          <span style="display:inline-block;background:{color};color:#ffffff;font-size:11px;font-weight:700;padding:4px 7px;">{esc(classification)}</span>
          <span style="display:inline-block;border:1px solid #e5e7eb;color:#374151;font-size:11px;padding:3px 7px;margin-left:5px;">Original: {esc(original_classification)}</span>
          <span style="display:inline-block;border:1px solid #e5e7eb;color:#374151;font-size:11px;padding:3px 7px;margin-left:5px;">{esc(record.get("hex_id"))}</span>
        </div>
      </div>
      <div style="padding:14px 16px 16px 16px;">
        {section("Spatial Budget Segment Mix", budget_bar(record))}
        {section("Direct Evidence Budget Mix", direct_budget_bar(record))}
        <table style="width:100%;border-collapse:collapse;margin-top:8px;">
          <tr>
            {stat("Dominant segment", esc(dominant_segment))}
            {stat("Dominant share", fmt_pct(record.get("dominant_budget_share")))}
          </tr>
        </table>
        {section("Spatial Refinement", spatial_scoring_table(record))}
        {section("Market Insights", metric_grid(record))}
        {section("Support And Inventory", support_grid(record))}
        {section("Neighbourhoods In Hex", mini_table(["Neighbourhood", "Share", "Localities", "Weight", "Subtype"], neighbourhood_rows(record)))}
        {section("Localities In Hex", mini_table(["Locality", "Neighbourhood", "Segment", "Weight", "H3-8", "Lat/Lon", "Flags"], locality_rows(record)))}
        {section("Tags", tags_html(record))}
        {section("Rolled-Up And Smoothed Signals", rollup_table(record))}
        {section("Quality", quality_html(record))}
        {section("Spatial Conflicts", conflict_html(record))}
        <div style="border-top:1px solid #e5e7eb;margin-top:14px;padding-top:9px;font-size:10px;line-height:1.45;color:#6b7280;">
          Spatial budget refinement layer. POI weighting and downstream ML classification are still intentionally not applied here.
        </div>
      </div>
    </div>"""


def extended_data(record):
    support = safe_dict(safe_dict(record.get("market_insights")).get("support"))
    inventory = safe_dict(safe_dict(record.get("market_insights")).get("inventory"))
    values = {
        "hex_id": record.get("hex_id"),
        "name": record.get("name"),
        "budget_classification": record.get("budget_classification"),
        "refined_budget_segment": record.get("refined_budget_segment"),
        "spatial_premium_lag": record.get("spatial_premium_lag"),
        "premium_cluster_score": record.get("premium_cluster_score"),
        "spatial_confidence": record.get("spatial_confidence"),
        "premium_candidate_score": record.get("premium_candidate_score"),
        "dominant_budget_segment": record.get("dominant_budget_segment"),
        "dominant_budget_share": record.get("dominant_budget_share"),
        "budget_share_affordable": safe_dict(record.get("budget_segments")).get("Affordable"),
        "budget_share_mid_segment": safe_dict(record.get("budget_segments")).get("Mid-Segment"),
        "budget_share_premium": safe_dict(record.get("budget_segments")).get("Premium"),
        "market_price_per_sqft": metric_avg(record, "market_price_per_sqft"),
        "rental_yield_pct": metric_avg(record, "rental_yield_pct"),
        "yearly_appreciation_pct": metric_avg(record, "yearly_appreciation_pct"),
        "activity_score": metric_avg(record, "activity_score"),
        "premium_lens_score": metric_avg(record, "premium_lens_score"),
        "locality_count": support.get("locality_count"),
        "support_weight": support.get("total_support_weight"),
        "registry_count": support.get("registry_count"),
        "reviews_count": support.get("reviews_count"),
        "rent_total_count": inventory.get("rent_total_count"),
        "sale_total_count": inventory.get("sale_total_count"),
        "buy_total_count_excluding_land": inventory.get("buy_total_count_excluding_land"),
    }
    data = []
    for key, value in values.items():
        data.append(f'<Data name="{esc(key)}"><value>{esc(value)}</value></Data>')
    return f"<ExtendedData>{''.join(data)}</ExtendedData>"


def placemark(record):
    name = f"{record.get('name')} - {record.get('refined_budget_segment') or record.get('budget_classification')}"
    description = html_card(record)
    return f"""
      <Placemark>
        <name>{esc(name)}</name>
        <styleUrl>#{style_map_id(record)}</styleUrl>
        <description><![CDATA[{cdata(description)}]]></description>
        {extended_data(record)}
        <Polygon>
          <extrude>0</extrude>
          <altitudeMode>clampToGround</altitudeMode>
          <outerBoundaryIs>
            <LinearRing>
              <coordinates>{coordinates_for_hex(record["hex_id"])}</coordinates>
            </LinearRing>
          </outerBoundaryIs>
        </Polygon>
      </Placemark>"""


def document_description(records):
    counts = Counter(record.get("refined_budget_segment") or record.get("budget_classification") for record in records)
    rows = []
    for label in sorted(counts):
        color = BUDGET_COLORS.get("Mixed/Diverse" if label == "Mixed/Diverse" else label, "#94a3b8")
        if str(label).startswith("Mixed -"):
            dominant = str(label).replace("Mixed - ", "").replace(" leaning", "")
            color = BUDGET_COLORS.get(dominant, "#94a3b8")
        rows.append(
            f'<tr><td style="padding:4px 8px;"><span style="display:inline-block;width:10px;height:10px;background:{color};border:1px solid #d1d5db;"></span></td><td style="padding:4px 8px;">{esc(label)}</td><td style="padding:4px 8px;text-align:right;">{counts[label]}</td></tr>'
        )
    return f"""
    <div style="font-family:Inter,Arial,sans-serif;background:#ffffff;color:#111827;border:1px solid #d1d5db;width:360px;">
      <div style="padding:12px 14px;border-bottom:1px solid #e5e7eb;">
        <div style="font-size:16px;font-weight:750;">Bangalore Stage 1.5 H3-7 Spatial Budget Choropleth</div>
        <div style="font-size:12px;color:#6b7280;margin-top:4px;">Refined spatial-budget layer with Premium Candidate and Ultra Premium tags.</div>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:12px;">
        {''.join(rows)}
      </table>
    </div>"""


def folder_name(classification, count):
    return f"{classification} ({count})"


def generate_kml(records):
    styles = []
    for record in records:
        styles.append(kml_style(record, "normal"))
        styles.append(kml_style(record, "highlight"))
        styles.append(kml_style_map(record))

    grouped = defaultdict(list)
    for record in records:
        grouped[record.get("refined_budget_segment") or record.get("budget_classification") or "unknown"].append(record)

    folders = []
    for classification in sorted(grouped):
        records_for_class = sorted(grouped[classification], key=lambda item: item.get("name") or "")
        placemarks = "\n".join(placemark(record) for record in records_for_class)
        folders.append(
            f"""
            <Folder>
              <name>{esc(folder_name(classification, len(records_for_class)))}</name>
              {placemarks}
            </Folder>"""
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Bangalore Stage 1.5 H3-7 Spatial Budget Choropleth</name>
    <description><![CDATA[{cdata(document_description(records))}]]></description>
    <open>1</open>
    {''.join(styles)}
    {''.join(folders)}
  </Document>
</kml>
"""


def write_audit(records):
    counts = Counter(record.get("refined_budget_segment") or record.get("budget_classification") for record in records)
    AUDIT_DIR.mkdir(exist_ok=True)
    AUDIT_PATH.write_text(
        json.dumps(
            {
                "input": str(INPUT_JSON),
                "output": str(OUTPUT_KML),
                "record_count": len(records),
                "classification_counts": dict(sorted(counts.items())),
                "style": {
                    "choropleth_basis": "refined_budget_segment",
                    "fill_opacity_basis": "spatial_confidence, falling back to dominant_budget_share",
                    "popup_theme": "light minimalist Notion-style HTML card",
                    "highlight_style": True,
                },
            },
            indent=2,
        )
    )


def main():
    records = load_records()
    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    kml = generate_kml(records)
    OUTPUT_KML.write_text(kml)
    write_audit(records)
    print(f"Wrote {OUTPUT_KML} ({len(records)} placemarks)")
    print(f"Wrote {AUDIT_PATH}")


if __name__ == "__main__":
    main()
