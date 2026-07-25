import os
from datetime import datetime
import geopandas as gpd
import pandas as pd

def generate_pdf_report(grid_gdf: gpd.GeoDataFrame, ward_scores: list,
                         city_config: dict, tier_config: dict, bundle_dir: str):
    """
    Generate a one-page executive PDF summary report.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    except ImportError:
        print("[PDF] reportlab not installed, skipping PDF report generation.")
        return None
    
    city_name = city_config["city"]["name"]
    tier_label = tier_config.get("label", "Premium")
    top_n = city_config["output"]["top_n_zones"]
    alpha = city_config["gravity_model"]["alpha"]
    beta = city_config["gravity_model"]["beta"]
    today = datetime.now().strftime("%d %B %Y")
    
    pdf_path = f"{bundle_dir}/summary_report.pdf"
    
    doc = SimpleDocTemplate(
        pdf_path, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        "title", parent=styles["Title"],
        fontSize=20, textColor=colors.HexColor("#6366f1"),
        spaceAfter=6
    )
    subtitle_style = ParagraphStyle(
        "subtitle", parent=styles["Normal"],
        fontSize=12, textColor=colors.HexColor("#94a3b8"),
        spaceAfter=12
    )
    section_style = ParagraphStyle(
        "section", parent=styles["Heading2"],
        fontSize=13, textColor=colors.HexColor("#1e293b"),
        borderPad=4, spaceBefore=12, spaceAfter=6
    )
    body_style = ParagraphStyle(
        "body", parent=styles["Normal"],
        fontSize=10, textColor=colors.HexColor("#334155"),
        leading=14
    )
    
    story = []
    
    # ---- Title ----
    story.append(Paragraph("CatchmentIQ Intelligence Report", title_style))
    story.append(Paragraph(f"{city_name} · {tier_label} Tier · {today}", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#6366f1"), spaceAfter=12))
    
    # ---- Summary Stats ----
    habitable = grid_gdf[grid_gdf["is_habitable"] == True]
    total_tam = int(habitable["apportioned_students"].sum()) if "apportioned_students" in habitable.columns else 0
    top_zones = habitable.nlargest(top_n, "percentile_score") if "percentile_score" in habitable.columns else habitable.head(top_n)
    stable_count = len(top_zones[top_zones.get("stability_flag", pd.Series()) == "Stable"]) if "stability_flag" in top_zones.columns else 0
    poi_validated_count = len(top_zones[top_zones.get("poi_validated", pd.Series()) == True]) if "poi_validated" in top_zones.columns else 0
    
    story.append(Paragraph("Executive Summary", section_style))
    story.append(Paragraph(
        f"This report summarises the CatchmentIQ spatial demand analysis for <b>{city_name}</b> "
        f"targeting the <b>{tier_label}</b> household income segment. The pipeline uses school catchment "
        f"data combined with real estate listings to probabilistically map family concentrations, "
        f"validated against on-ground POI signals.",
        body_style
    ))
    story.append(Spacer(1, 8))
    
    summary_data = [
        ["Metric", "Value"],
        ["Estimated TAM (Total)", f"{total_tam:,} students"],
        [f"Top {top_n} Demand Zones", f"{len(top_zones)} hexes identified"],
        ["Stable Zones (3-run check)", f"{stable_count}/{top_n}"],
        ["POI-Validated Zones", f"{poi_validated_count}/{top_n}"],
        ["Model Parameters", f"α={alpha}, β={beta}"],
        ["Run Date", today],
    ]
    
    summary_table = Table(summary_data, colWidths=[8*cm, 8*cm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#6366f1")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 11),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#1e293b")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWHEIGHT", (0, 0), (-1, -1), 22),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 12))
    
    # ---- Top 10 Zones ----
    story.append(Paragraph(f"Top {min(10, top_n)} Demand Zones", section_style))
    
    cols = ["hex_id", "percentile_score", "absolute_tam", "ward_name", "stability_flag", "poi_validated"]
    available = [c for c in cols if c in top_zones.columns]
    top_10 = top_zones[available].head(10).copy()
    
    table_data = [["Rank", "Score (%)", "TAM", "Ward", "Stable?", "Validated?"]]
    for i, (_, row) in enumerate(top_10.iterrows(), 1):
        stable_val = "✓" if row.get("stability_flag") == "Stable" else "~"
        validated_val = "✓" if row.get("poi_validated") else "✗"
        table_data.append([
            str(i),
            f"{row.get('percentile_score', 0):.1f}",
            f"{int(row.get('absolute_tam', 0)):,}",
            str(row.get("ward_name", "N/A"))[:25],
            stable_val,
            validated_val
        ])
    
    zone_table = Table(table_data, colWidths=[1.2*cm, 2*cm, 2*cm, 6*cm, 2*cm, 2.8*cm])
    zone_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f1f5f9"), colors.white]),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#1e293b")),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWHEIGHT", (0, 0), (-1, -1), 20),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(zone_table)
    story.append(Spacer(1, 12))
    
    # ---- Methodology & Definitions ----
    story.append(Paragraph("Methodology & Definitions", section_style))
    methodology = [
        "<b>Demand Score (Percentile Rank):</b> A relative ranking (0-100) indicating a zone's Total Addressable Market (TAM) compared to all other habitable zones in the city.",
        "<b>Spatial Interaction Model:</b> Allocates students using $P(j|i) = (W_{j,b} \\cdot e^{-\\beta_i \\cdot d_{ij}}) / \\sum_k (W_{k,b} \\cdot e^{-\\beta_i \\cdot d_{ik}})$, where $d_{ij}$ is Manhattan distance and $\\beta_i$ is bracket decay friction.",
        "<b>3D Capacity Mass ($W_{j,b}$):</b> Realigned volume $W_{j,b} = B_j \\cdot R_{j,b}$ where $B_j$ is 3D residential volume (footprint × levels) and $R_{j,b}$ is socio-economic bracket ratio.",
        "<b>Effective Student Pull:</b> Enrollment ($n_i$) scaled by board confidence ($c_i$): $T_{ij} = (n_i \\cdot c_i) \\cdot P(j|i)$."
    ]
    for item in methodology:
        story.append(Paragraph(f"• {item}", body_style))
        story.append(Spacer(1, 4))
    
    story.append(Spacer(1, 8))

    # ---- Key Assumptions ----
    story.append(Paragraph("Model Assumptions", section_style))
    h3_res = city_config["grid"].get("h3_resolution", 7)
    assumptions = [
        f"Income proxy: School fee ≥ ₹{tier_config.get('school_fee_min', 0):,}/year",
        f"Property proxy: Sale ≥ ₹{tier_config.get('realestate', {}).get('sale', {}).get('price_min', 0):,} OR Rent ≥ ₹{tier_config.get('realestate', {}).get('rent', {}).get('price_min', 0):,}/mo",
        f"School boards targeted: {', '.join(tier_config.get('school_boards', []))}",
        f"Distance Metric: Manhattan distance in kilometers",
        f"H3 resolution: {h3_res} (~1.22km hex edge)",
        f"Friction (β): Premium=0.15, Mid-Market=0.30, Economy=0.50",
        f"POI validation: Overture Maps + OSM fallback",
    ]
    for assumption in assumptions:
        story.append(Paragraph(f"• {assumption}", body_style))
    
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=6))
    story.append(Paragraph(
        f"Generated by CatchmentIQ v1.0 · {today} · For internal use only",
        ParagraphStyle("footer", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#94a3b8"), alignment=TA_CENTER)
    ))
    
    doc.build(story)
    print(f"[OUTPUT] ✅ PDF report saved: {pdf_path}")
    return pdf_path
