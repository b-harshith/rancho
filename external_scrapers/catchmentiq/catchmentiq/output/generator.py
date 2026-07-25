import os
import json
import csv
import geopandas as gpd
import pandas as pd
import folium
from datetime import datetime
from folium.plugins import HeatMap
import xml.etree.ElementTree as ET

def export_to_kml(
    output_path: str,
    grid_res8: gpd.GeoDataFrame,
    grid_res7: gpd.GeoDataFrame,
    schools_gdf: gpd.GeoDataFrame,
    isochrones_gdf: gpd.GeoDataFrame,
    pois_gdf: gpd.GeoDataFrame,
    ranked_schools_df: pd.DataFrame,
    city_name: str,
    tier_label: str
):
    """
    Export all layers to a highly structured, categorized, and styled KML file for Google Earth.
    """
    from shapely.geometry import Polygon, MultiPolygon
    import xml.etree.ElementTree as ET
    
    kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    doc = ET.SubElement(kml, "Document")
    
    name_el = ET.SubElement(doc, "name")
    name_el.text = f"CatchmentIQ Analysis - {city_name} ({tier_label})"
    
    desc_el = ET.SubElement(doc, "description")
    desc_el.text = "CatchmentIQ Probabilistic Spatial Decision Support System Output Bundle"
    
    # Pre-calculate value-based percentages for Resolution 8 and 7 grids to ensure linear value scaling
    grid_res8 = grid_res8.copy()
    grid_res7 = grid_res7.copy()
    
    for df in [grid_res8, grid_res7]:
        if "apportioned_students" in df.columns:
            max_val = df["apportioned_students"].max()
            if max_val > 0:
                df["demand_pct"] = (df["apportioned_students"] / max_val) * 100.0
            else:
                df["demand_pct"] = 0.0
        else:
            df["demand_pct"] = 0.0
            
        for col_name, pct_name in [("rental_index", "rent_percentile"), 
                                   ("rental_ppsqft", "ppsqft_percentile"), 
                                   ("school_density", "sd_percentile")]:
            if col_name in df.columns:
                max_val = df[col_name].max()
                if max_val > 0:
                    df[pct_name] = (df[col_name] / max_val) * 100.0
                else:
                    df[pct_name] = 0.0
                df[pct_name] = df[pct_name].fillna(0.0)
            else:
                df[pct_name] = 0.0
                
    # 1. Styles Definition
    def add_style(doc_el, style_id, line_color, line_width, poly_color):
        style = ET.SubElement(doc_el, "Style", id=style_id)
        if line_color or line_width:
            l_style = ET.SubElement(style, "LineStyle")
            if line_color:
                ET.SubElement(l_style, "color").text = line_color
            if line_width:
                ET.SubElement(l_style, "width").text = str(line_width)
        if poly_color:
            p_style = ET.SubElement(style, "PolyStyle")
            ET.SubElement(p_style, "color").text = poly_color
            ET.SubElement(p_style, "fill").text = "1"
            ET.SubElement(p_style, "outline").text = "1"

    # Isochrone bands colors
    add_style(doc, "iso_0_10", "ff27ae60", 1, "3327ae60")  # 20% opacity green
    add_style(doc, "iso_10_20", "fff39c12", 1, "20f39c12") # 12% opacity orange
    add_style(doc, "iso_20_30", "ffe74c3c", 1, "10e74c3c")  # 6% opacity red
    
    # Standard school pin style
    school_icon_style = ET.SubElement(doc, "Style", id="school_pin")
    icon_style = ET.SubElement(school_icon_style, "IconStyle")
    ET.SubElement(icon_style, "color").text = "ff356bff"  # Orange-red
    icon = ET.SubElement(icon_style, "Icon")
    ET.SubElement(icon, "href").text = "http://maps.google.com/mapfiles/kml/shapes/schools.png"
    
    # POI pin style
    poi_icon_style = ET.SubElement(doc, "Style", id="poi_pin")
    p_icon_style = ET.SubElement(poi_icon_style, "IconStyle")
    ET.SubElement(p_icon_style, "color").text = "ff0fc4f1"  # Gold
    p_icon = ET.SubElement(p_icon_style, "Icon")
    ET.SubElement(p_icon, "href").text = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"
    
    # Ranked School style
    ranked_icon_style = ET.SubElement(doc, "Style", id="ranked_pin")
    r_icon_style = ET.SubElement(ranked_icon_style, "IconStyle")
    ET.SubElement(r_icon_style, "color").text = "ffad448e"  # Purple
    ET.SubElement(r_icon_style, "scale").text = "1.3"
    r_icon = ET.SubElement(r_icon_style, "Icon")
    ET.SubElement(r_icon, "href").text = "http://maps.google.com/mapfiles/kml/shapes/star.png"
    
    def dict_to_html_table(title, data_dict):
        html = f"<h3>{title}</h3><table border='1' cellpadding='4' style='border-collapse: collapse; font-family: sans-serif; font-size: 12px;'>"
        for k, v in data_dict.items():
            html += f"<tr><td><b>{k}</b></td><td>{v}</td></tr>"
        html += "</table>"
        return html
        
    def get_coords_str(geom):
        if isinstance(geom, Polygon):
            coords = list(geom.exterior.coords)
            return " ".join([f"{lon},{lat},0" for lon, lat in coords])
        elif isinstance(geom, MultiPolygon):
            if not geom.geoms:
                return ""
            coords = list(geom.geoms[0].exterior.coords)
            return " ".join([f"{lon},{lat},0" for lon, lat in coords])
        return ""

    # Helper for vibrant multi-stop color ramps in KML format (aabbggrr)
    def get_vibrant_kml_color(pct, alpha="99", colormap_type="default"):
        factor = min(1.0, max(0.0, pct / 100.0))
        if colormap_type == "rental":
            # Purple theme (Light Purple to Vibrant Dark Purple)
            stops = [
                (0.0, (242, 240, 247)),
                (0.3, (188, 189, 220)),
                (0.6, (117, 107, 177)),
                (0.85, (84, 39, 143)),
                (1.0, (63, 0, 125))
            ]
        elif colormap_type == "ppsqft":
            # Warm Oranges/Reds (Yellow-Orange to Vibrant Deep Red)
            stops = [
                (0.0, (254, 240, 217)),
                (0.3, (253, 204, 138)),
                (0.6, (252, 141, 89)),
                (0.85, (227, 74, 51)),
                (1.0, (179, 0, 0))
            ]
        elif colormap_type == "school_density":
            # Teal to Deep Indigo theme
            stops = [
                (0.0, (247, 252, 240)),
                (0.3, (204, 235, 197)),
                (0.6, (123, 204, 196)),
                (0.85, (43, 140, 190)),
                (1.0, (8, 64, 129))
            ]
        else:
            # Default (Demand Score): Yellow to Orange to Red
            stops = [
                (0.0, (255, 255, 178)),
                (0.3, (254, 204, 92)),
                (0.6, (253, 141, 60)),
                (0.85, (240, 59, 32)),
                (1.0, (189, 0, 38))
            ]
            
        for i in range(len(stops) - 1):
            s1, rgb1 = stops[i]
            s2, rgb2 = stops[i+1]
            if s1 <= factor <= s2:
                t = (factor - s1) / (s2 - s1)
                r = int(rgb1[0] + (rgb2[0] - rgb1[0]) * t)
                g = int(rgb1[1] + (rgb2[1] - rgb1[1]) * t)
                b = int(rgb1[2] + (rgb2[2] - rgb1[2]) * t)
                return f"{alpha}{b:02x}{g:02x}{r:02x}"
                
        r, g, b = stops[-1][1]
        return f"{alpha}{b:02x}{g:02x}{r:02x}"

    def get_kml_color(score, alpha="99"):
        return get_vibrant_kml_color(score, alpha, "default")

    def get_rent_kml_color(pct, alpha="99"):
        return get_vibrant_kml_color(pct, alpha, "rental")

    def get_school_dens_kml_color(pct, alpha="99"):
        return get_vibrant_kml_color(pct, alpha, "school_density")
        
    def get_ppsqft_kml_color(pct, alpha="99"):
        return get_vibrant_kml_color(pct, alpha, "ppsqft")

    # Helper to append geometry to placemark
    def append_geom_to_pm(pm_el, geom):
        if isinstance(geom, Polygon):
            poly_el = ET.SubElement(pm_el, "Polygon")
            out_ring = ET.SubElement(poly_el, "outerBoundaryIs")
            ring = ET.SubElement(out_ring, "LinearRing")
            ET.SubElement(ring, "coordinates").text = get_coords_str(geom)
        elif isinstance(geom, MultiPolygon):
            multi_el = ET.SubElement(pm_el, "MultiGeometry")
            for sub_geom in geom.geoms:
                poly_el = ET.SubElement(multi_el, "Polygon")
                out_ring = ET.SubElement(poly_el, "outerBoundaryIs")
                ring = ET.SubElement(out_ring, "LinearRing")
                ET.SubElement(ring, "coordinates").text = get_coords_str(sub_geom)

    # 2. Folder for Ranked Schools (Partnerships)
    if ranked_schools_df is not None and not ranked_schools_df.empty:
        f_ranked = ET.SubElement(doc, "Folder")
        ET.SubElement(f_ranked, "name").text = "🤝 School Partnerships (Ranked)"
        for _, row in ranked_schools_df.iterrows():
            pm = ET.SubElement(f_ranked, "Placemark")
            ET.SubElement(pm, "name").text = f"Rank #{int(row['rank'])}: {row['school_name']}"
            ET.SubElement(pm, "styleUrl").text = "#ranked_pin"
            
            desc_dict = {
                "Partnership Score": f"{row['partnership_score']:.1f} / 100",
                "Board": row['board'],
                "Annual Fee": f"₹{row['avg_fee_annual']:,}",
                "Student Count": row['student_count'],
                "TAM Density Score": f"{row['tam_density_score']*100:.1f}%",
                "Fee Alignment Score": f"{row['fee_alignment_score']*100:.1f}%",
                "Hex Percentile": f"{row['hex_percentile']:.1f}%ile"
            }
            desc = ET.SubElement(pm, "description")
            desc.text = dict_to_html_table("Partnership Details", desc_dict)
            
            point = ET.SubElement(pm, "Point")
            ET.SubElement(point, "coordinates").text = f"{row['lon']},{row['lat']},0"
            
    # 3. Folder for All Schools
    if schools_gdf is not None and not schools_gdf.empty:
        f_schools = ET.SubElement(doc, "Folder")
        ET.SubElement(f_schools, "name").text = "🏫 All Schools"
        for _, row in schools_gdf.iterrows():
            pm = ET.SubElement(f_schools, "Placemark")
            ET.SubElement(pm, "name").text = str(row.get("name", "School"))
            ET.SubElement(pm, "styleUrl").text = "#school_pin"
            
            desc_dict = {
                "Board": ", ".join(row.get("board", [])),
                "Annual Fee": f"₹{row.get('avg_fee', 0):,.0f}",
                "Student Count": row.get("student_count", 0),
                "Fee Estimated?": "Yes" if row.get("fee_is_estimated") else "No"
            }
            desc = ET.SubElement(pm, "description")
            desc.text = dict_to_html_table("School Info", desc_dict)
            
            point = ET.SubElement(pm, "Point")
            ET.SubElement(point, "coordinates").text = f"{row.geometry.x},{row.geometry.y},0"
            
    # 4. Folder for POIs
    if pois_gdf is not None and not pois_gdf.empty:
        f_pois = ET.SubElement(doc, "Folder")
        ET.SubElement(f_pois, "name").text = "📍 Points of Interest (POIs)"
        for _, row in pois_gdf.iterrows():
            pm = ET.SubElement(f_pois, "Placemark")
            ET.SubElement(pm, "name").text = str(row.get("name", "POI"))
            ET.SubElement(pm, "styleUrl").text = "#poi_pin"
            
            desc_dict = {
                "Category": row.get("category", "N/A"),
                "Weight": row.get("weight", 1.0)
            }
            desc = ET.SubElement(pm, "description")
            desc.text = dict_to_html_table("POI Details", desc_dict)
            
            point = ET.SubElement(pm, "Point")
            ET.SubElement(point, "coordinates").text = f"{row.geometry.x},{row.geometry.y},0"
            
    # 5. Folder for Isochrones (Reverse Catchments)
    if isochrones_gdf is not None and not isochrones_gdf.empty:
        f_isos = ET.SubElement(doc, "Folder")
        ET.SubElement(f_isos, "name").text = "🎓 Catchment Zones (Reverse Isochrones)"
        for _, row in isochrones_gdf.iterrows():
            if row.geometry is None or row.geometry.is_empty:
                continue
            
            pm = ET.SubElement(f_isos, "Placemark")
            ET.SubElement(pm, "name").text = f"{row['school_name']} ({row['band']} mins)"
            
            band = row.get("band", "0-10")
            if band == "0-10" or "0-10" in band:
                style_url = "#iso_0_10"
            elif band == "10-20" or "10-20" in band:
                style_url = "#iso_10_20"
            else:
                style_url = "#iso_20_30"
            ET.SubElement(pm, "styleUrl").text = style_url
            
            desc_dict = {
                "School": row['school_name'],
                "Travel Band": f"{band} minutes",
                "Midpoint Minutes": row.get("band_midpoint_minutes", 0.0)
            }
            desc = ET.SubElement(pm, "description")
            desc.text = dict_to_html_table("Isochrone Band", desc_dict)
            append_geom_to_pm(pm, row.geometry)

    # 6. Folder for H3 Res 8 Grid (Categorized Choropleths)
    if grid_res8 is not None and not grid_res8.empty:
        f_res8 = ET.SubElement(doc, "Folder")
        ET.SubElement(f_res8, "name").text = "📊 Demand Choropleth (Resolution 8 - Detailed)"
        
        # Subfolders for H3 Res 8
        f_res8_top10 = ET.SubElement(f_res8, "Folder")
        ET.SubElement(f_res8_top10, "name").text = "🏆 Top 10% Hotspots (Score >= 90)"
        
        f_res8_high = ET.SubElement(f_res8, "Folder")
        ET.SubElement(f_res8_high, "name").text = "🔥 High Demand (Score 70 - 90)"
        
        f_res8_mid = ET.SubElement(f_res8, "Folder")
        ET.SubElement(f_res8_mid, "name").text = "📈 Moderate Demand (Score 40 - 70)"
        
        f_res8_low = ET.SubElement(f_res8, "Folder")
        ET.SubElement(f_res8_low, "name").text = "📉 Low Demand (Score < 40)"
        
        sorted_res8 = grid_res8.sort_values("percentile_score", ascending=True)
        for idx, row in sorted_res8.iterrows():
            if row.geometry is None or row.geometry.is_empty:
                continue
            
            score = row.get("percentile_score", 0.0) or 0.0
            color_score = row.get("demand_pct", 0.0) or 0.0
            tam = int(row.get("absolute_tam", 0))
            validated_icon = "✅" if row.get("poi_validated") else "⚠️"
            
            # Select folder category based on value percentage (ratio-based)
            if color_score >= 90:
                parent_folder = f_res8_top10
            elif color_score >= 70:
                parent_folder = f_res8_high
            elif color_score >= 40:
                parent_folder = f_res8_mid
            else:
                parent_folder = f_res8_low
                
            pm = ET.SubElement(parent_folder, "Placemark")
            ET.SubElement(pm, "name").text = f"Res 8: {score:.1f}% (TAM: {tam})"
            
            style = ET.SubElement(pm, "Style")
            l_style = ET.SubElement(style, "LineStyle")
            ET.SubElement(l_style, "color").text = "ff1e293b"
            ET.SubElement(l_style, "width").text = "0.5"
            p_style = ET.SubElement(style, "PolyStyle")
            ET.SubElement(p_style, "color").text = get_kml_color(color_score, "66")
            ET.SubElement(p_style, "fill").text = "1"
            ET.SubElement(p_style, "outline").text = "1"
            
            desc_dict = {
                "H3 Index": row["hex_id"],
                "Demand Percentile": f"{score:.1f}%",
                "TAM Estimate": f"{tam} students",
                "Wealth Index": f"{row.get('capacity_mass', 0):.2f}",
                "Ward": row.get("ward_name", "N/A"),
                "POI Density": f"{row.get('poi_density', 0):.2f}",
                "POI Validated": validated_icon,
                "Stability": row.get("stability_flag", "N/A"),
                "Rental Index": f"₹{int(row.get('rental_index', 0)):,}/mo" if row.get("rental_index", 0) > 0 else "N/A",
                "School Density": f"{int(row.get('school_density', 0)):,} students" if row.get("school_density", 0) > 0 else "N/A"
            }
            desc = ET.SubElement(pm, "description")
            desc.text = dict_to_html_table("Hexagon (Res 8)", desc_dict)
            append_geom_to_pm(pm, row.geometry)

    # 7. Folder for H3 Res 7 Grid (Categorized Choropleths)
    if grid_res7 is not None and not grid_res7.empty:
        f_res7 = ET.SubElement(doc, "Folder")
        ET.SubElement(f_res7, "name").text = "📊 Demand Choropleth (Resolution 7 - Aggregated)"
        
        # Subfolders for H3 Res 7
        f_res7_top10 = ET.SubElement(f_res7, "Folder")
        ET.SubElement(f_res7_top10, "name").text = "🏆 Top 10% Hotspots (Score >= 90)"
        
        f_res7_high = ET.SubElement(f_res7, "Folder")
        ET.SubElement(f_res7_high, "name").text = "🔥 High Demand (Score 70 - 90)"
        
        f_res7_mid = ET.SubElement(f_res7, "Folder")
        ET.SubElement(f_res7_mid, "name").text = "📈 Moderate Demand (Score 40 - 70)"
        
        f_res7_low = ET.SubElement(f_res7, "Folder")
        ET.SubElement(f_res7_low, "name").text = "📉 Low Demand (Score < 40)"
        
        sorted_res7 = grid_res7.sort_values("percentile_score", ascending=True)
        for idx, row in sorted_res7.iterrows():
            if row.geometry is None or row.geometry.is_empty:
                continue
            
            score = row.get("percentile_score", 0.0) or 0.0
            color_score = row.get("demand_pct", 0.0) or 0.0
            tam = int(row.get("absolute_tam", 0))
            validated_icon = "✅" if row.get("poi_validated") else "⚠️"
            
            # Select folder category based on value percentage (ratio-based)
            if color_score >= 90:
                parent_folder = f_res7_top10
            elif color_score >= 70:
                parent_folder = f_res7_high
            elif color_score >= 40:
                parent_folder = f_res7_mid
            else:
                parent_folder = f_res7_low
                
            pm = ET.SubElement(parent_folder, "Placemark")
            ET.SubElement(pm, "name").text = f"Res 7: {score:.1f}% (TAM: {tam})"
            
            style = ET.SubElement(pm, "Style")
            l_style = ET.SubElement(style, "LineStyle")
            ET.SubElement(l_style, "color").text = "ff064e3b"
            ET.SubElement(l_style, "width").text = "0.8"
            p_style = ET.SubElement(style, "PolyStyle")
            ET.SubElement(p_style, "color").text = get_kml_color(color_score, "80")
            ET.SubElement(p_style, "fill").text = "1"
            ET.SubElement(p_style, "outline").text = "1"
            
            desc_dict = {
                "H3 Index": row["hex_id"],
                "Demand Percentile": f"{score:.1f}%",
                "TAM Estimate": f"{tam} students",
                "Wealth Index": f"{row.get('capacity_mass', 0):.2f}",
                "Ward": row.get("ward_name", "N/A"),
                "POI Density": f"{row.get('poi_density', 0):.2f}",
                "POI Validated": validated_icon,
                "Stability": row.get("stability_flag", "N/A"),
                "Rental Index": f"₹{int(row.get('rental_index', 0)):,}/mo" if row.get("rental_index", 0) > 0 else "N/A",
                "School Density": f"{int(row.get('school_density', 0)):,} students" if row.get("school_density", 0) > 0 else "N/A"
            }
            desc = ET.SubElement(pm, "description")
            desc.text = dict_to_html_table("Hexagon (Res 7)", desc_dict)
            append_geom_to_pm(pm, row.geometry)

    # 8. Folder for Rental Index Heatmap (Res 8)
    if grid_res8 is not None and not grid_res8.empty and "rental_index" in grid_res8.columns:
        f_rent = ET.SubElement(doc, "Folder")
        ET.SubElement(f_rent, "name").text = "🔥 Rental Index Heatmap (Resolution 8)"
        
        f_rent_ultra = ET.SubElement(f_rent, "Folder")
        ET.SubElement(f_rent_ultra, "name").text = "🏆 Top 10% Luxury (Rent %ile >= 90)"
        
        f_rent_luxury = ET.SubElement(f_rent, "Folder")
        ET.SubElement(f_rent_luxury, "name").text = "🥇 High Rent (Rent %ile 70 - 90)"
        
        f_rent_premium = ET.SubElement(f_rent, "Folder")
        ET.SubElement(f_rent_premium, "name").text = "🥈 Moderate Rent (Rent %ile 40 - 70)"
        
        f_rent_budget = ET.SubElement(f_rent, "Folder")
        ET.SubElement(f_rent_budget, "name").text = "🥉 Low Rent (Rent %ile < 40)"
        
        sorted_rent = grid_res8[grid_res8["rental_index"] > 0].sort_values("rental_index", ascending=True)
        for idx, row in sorted_rent.iterrows():
            if row.geometry is None or row.geometry.is_empty:
                continue
            
            rent_val = row["rental_index"]
            ppsqft_val = row.get("rental_ppsqft", 0.0)
            pct = row.get("rent_percentile", 0.0)
            
            if pct >= 90:
                parent_folder = f_rent_ultra
            elif pct >= 70:
                parent_folder = f_rent_luxury
            elif pct >= 40:
                parent_folder = f_rent_premium
            else:
                parent_folder = f_rent_budget
                
            pm = ET.SubElement(parent_folder, "Placemark")
            ET.SubElement(pm, "name").text = f"Rent: ₹{int(rent_val):,}/mo (%ile: {pct:.1f})"
            
            style = ET.SubElement(pm, "Style")
            l_style = ET.SubElement(style, "LineStyle")
            ET.SubElement(l_style, "color").text = "ff4a1254"
            ET.SubElement(l_style, "width").text = "0.5"
            p_style = ET.SubElement(style, "PolyStyle")
            ET.SubElement(p_style, "color").text = get_rent_kml_color(pct, "80")
            ET.SubElement(p_style, "fill").text = "1"
            ET.SubElement(p_style, "outline").text = "1"
            
            desc_dict = {
                "H3 Index": row["hex_id"],
                "Average Rent": f"₹{int(rent_val):,}/month",
                "Rent Percentile": f"{pct:.1f}%",
                "Price-per-sqft": f"₹{ppsqft_val:.2f}/sqft/month",
                "Ward": row.get("ward_name", "N/A"),
                "Stability": row.get("stability_flag", "N/A")
            }
            desc = ET.SubElement(pm, "description")
            desc.text = dict_to_html_table("Rental Index Details", desc_dict)
            append_geom_to_pm(pm, row.geometry)

    # 9. Folder for Rent Per-Sqft Heatmap (Res 8)
    if grid_res8 is not None and not grid_res8.empty and "rental_ppsqft" in grid_res8.columns:
        f_ppsqft = ET.SubElement(doc, "Folder")
        ET.SubElement(f_ppsqft, "name").text = "💰 Rent Per-Sqft Heatmap (Resolution 8)"
        
        f_pq_ultra = ET.SubElement(f_ppsqft, "Folder")
        ET.SubElement(f_pq_ultra, "name").text = "💎 Top 10% High Rate (Rate %ile >= 90)"
        
        f_pq_high = ET.SubElement(f_ppsqft, "Folder")
        ET.SubElement(f_pq_high, "name").text = "🥇 High Rate (Rate %ile 70 - 90)"
        
        f_pq_medium = ET.SubElement(f_ppsqft, "Folder")
        ET.SubElement(f_pq_medium, "name").text = "🥈 Moderate Rate (Rate %ile 40 - 70)"
        
        f_pq_low = ET.SubElement(f_ppsqft, "Folder")
        ET.SubElement(f_pq_low, "name").text = "🥉 Low Rate (Rate %ile < 40)"
        
        sorted_ppsqft = grid_res8[grid_res8["rental_ppsqft"] > 0].sort_values("rental_ppsqft", ascending=True)
        for idx, row in sorted_ppsqft.iterrows():
            if row.geometry is None or row.geometry.is_empty:
                continue
            
            rent_val = row.get("rental_index", 0.0)
            ppsqft_val = row["rental_ppsqft"]
            pct = row.get("ppsqft_percentile", 0.0)
            
            if pct >= 90:
                parent_folder = f_pq_ultra
            elif pct >= 70:
                parent_folder = f_pq_high
            elif pct >= 40:
                parent_folder = f_pq_medium
            else:
                parent_folder = f_pq_low
                
            pm = ET.SubElement(parent_folder, "Placemark")
            ET.SubElement(pm, "name").text = f"Rate: ₹{ppsqft_val:.2f}/sqft (%ile: {pct:.1f})"
            
            style = ET.SubElement(pm, "Style")
            l_style = ET.SubElement(style, "LineStyle")
            ET.SubElement(l_style, "color").text = "ff633b11"
            ET.SubElement(l_style, "width").text = "0.5"
            p_style = ET.SubElement(style, "PolyStyle")
            ET.SubElement(p_style, "color").text = get_ppsqft_kml_color(pct, "80")
            ET.SubElement(p_style, "fill").text = "1"
            ET.SubElement(p_style, "outline").text = "1"
            
            desc_dict = {
                "H3 Index": row["hex_id"],
                "Average Rent": f"₹{int(rent_val):,}/month",
                "Price-per-sqft": f"₹{ppsqft_val:.2f}/sqft/month",
                "Rate Percentile": f"{pct:.1f}%",
                "Ward": row.get("ward_name", "N/A"),
                "Stability": row.get("stability_flag", "N/A")
            }
            desc = ET.SubElement(pm, "description")
            desc.text = dict_to_html_table("Rent Per-Sqft Details", desc_dict)
            append_geom_to_pm(pm, row.geometry)

    # 10. Folder for School Density Heatmap (Res 8)
    if grid_res8 is not None and not grid_res8.empty and "school_density" in grid_res8.columns:
        f_school_dens = ET.SubElement(doc, "Folder")
        ET.SubElement(f_school_dens, "name").text = "🏫 School Density Heatmap (Resolution 8)"
        
        f_sd_very_high = ET.SubElement(f_school_dens, "Folder")
        ET.SubElement(f_sd_very_high, "name").text = "🏫 Very High Density (%ile >= 90)"
        
        f_sd_high = ET.SubElement(f_school_dens, "Folder")
        ET.SubElement(f_sd_high, "name").text = "🏫 High Density (%ile 70 - 90)"
        
        f_sd_medium = ET.SubElement(f_school_dens, "Folder")
        ET.SubElement(f_sd_medium, "name").text = "🏫 Medium Density (%ile 40 - 70)"
        
        f_sd_low = ET.SubElement(f_school_dens, "Folder")
        ET.SubElement(f_sd_low, "name").text = "🏫 Low Density (%ile < 40)"
        
        sorted_sd = grid_res8[grid_res8["school_density"] > 0].sort_values("school_density", ascending=True)
        for idx, row in sorted_sd.iterrows():
            if row.geometry is None or row.geometry.is_empty:
                continue
            
            sd_val = row["school_density"]
            pct = row.get("sd_percentile", 0.0)
            
            if pct >= 90:
                parent_folder = f_sd_very_high
            elif pct >= 70:
                parent_folder = f_sd_high
            elif pct >= 40:
                parent_folder = f_sd_medium
            else:
                parent_folder = f_sd_low
                
            pm = ET.SubElement(parent_folder, "Placemark")
            ET.SubElement(pm, "name").text = f"Density: {int(sd_val):,} (%ile: {pct:.1f})"
            
            style = ET.SubElement(pm, "Style")
            l_style = ET.SubElement(style, "LineStyle")
            ET.SubElement(l_style, "color").text = "ff082b54"
            ET.SubElement(l_style, "width").text = "0.5"
            p_style = ET.SubElement(style, "PolyStyle")
            ET.SubElement(p_style, "color").text = get_school_dens_kml_color(pct, "80")
            ET.SubElement(p_style, "fill").text = "1"
            ET.SubElement(p_style, "outline").text = "1"
            
            desc_dict = {
                "H3 Index": row["hex_id"],
                "School Density Index": f"{int(sd_val):,} weighted students",
                "Density Percentile": f"{pct:.1f}%",
                "Ward": row.get("ward_name", "N/A"),
                "Stability": row.get("stability_flag", "N/A")
            }
            desc = ET.SubElement(pm, "description")
            desc.text = dict_to_html_table("School Density Details", desc_dict)
            append_geom_to_pm(pm, row.geometry)
            
    tree = ET.ElementTree(kml)
    tree.write(output_path, encoding="UTF-8", xml_declaration=True)

def create_output_bundle(
    grid_res8_gdf: gpd.GeoDataFrame, 
    grid_res7_gdf: gpd.GeoDataFrame,
    schools_gdf: gpd.GeoDataFrame,
    pois_gdf: gpd.GeoDataFrame, 
    ward_scores: list,
    city_config: dict, 
    tier_config: dict, 
    re_gdf: gpd.GeoDataFrame = None,
    isochrones_gdf: gpd.GeoDataFrame = None,
    ranked_schools_df: pd.DataFrame = None
):
    """
    Create the full output bundle (interactive Folium map, KML, CSVs, GeoJSONs).
    """
    city_name = city_config["city"]["name"]
    tier_label = tier_config["label"].replace("₹", "INR_").replace("+", "plus").replace("-", "_to_").replace(" ", "_").strip("_")
    tier_slug = tier_label.replace("₹", "").replace(" ", "_").replace("/", "_")
    
    today = datetime.now().strftime("%Y-%m-%d")
    bundle_dir = f"output/{city_name.lower()}_{today}_{tier_slug}"
    os.makedirs(bundle_dir, exist_ok=True)
    
    print(f"[OUTPUT] Generating output bundle at {bundle_dir}/")
    
    city_center = city_config["city"]["center"]
    zoom_level = city_config["city"]["zoom"]
    top_n = city_config["output"]["top_n_zones"]
    
    habitable_grid_res8 = grid_res8_gdf[grid_res8_gdf["is_habitable"] == True].copy()
    habitable_grid_res7 = grid_res7_gdf[grid_res7_gdf["is_habitable"] == True].copy()
    
    # Fill missing columns with defaults for safety
    for col in ["percentile_score", "absolute_tam", "capacity_mass", "poi_density", "poi_validated", "ward_name", "ward_poi_score", "stability_flag", "apportioned_students", "rental_index", "rental_ppsqft", "school_density", "family_ratio", "premium_area_score"]:
        if col not in grid_res8_gdf.columns:
            grid_res8_gdf[col] = 0.0 if col in ["rental_index", "rental_ppsqft", "school_density", "family_ratio", "premium_area_score"] else None
        if col not in grid_res7_gdf.columns:
            grid_res7_gdf[col] = 0.0 if col in ["rental_index", "rental_ppsqft", "school_density", "family_ratio", "premium_area_score"] else None
            
        if col not in habitable_grid_res8.columns:
            habitable_grid_res8[col] = 0.0 if col in ["rental_index", "rental_ppsqft", "school_density"] else None
        if col not in habitable_grid_res7.columns:
            habitable_grid_res7[col] = 0.0 if col in ["rental_index", "rental_ppsqft", "school_density"] else None
            
    top_zones = habitable_grid_res8.nlargest(top_n, "percentile_score")
    
    # Pre-calculate value-based percentages for habitable grids to ensure linear value scaling (giving hot zones proportional contrast)
    for df in [habitable_grid_res8, habitable_grid_res7]:
        if "apportioned_students" in df.columns:
            max_val = df["apportioned_students"].max()
            if max_val > 0:
                df["demand_pct"] = (df["apportioned_students"] / max_val) * 100.0
            else:
                df["demand_pct"] = 0.0
        else:
            df["demand_pct"] = 0.0
            
        for col_name, pct_name in [("rental_index", "rent_percentile"), 
                                   ("rental_ppsqft", "ppsqft_percentile"), 
                                   ("school_density", "sd_percentile")]:
            if col_name in df.columns:
                max_val = df[col_name].max()
                if max_val > 0:
                    df[pct_name] = (df[col_name] / max_val) * 100.0
                else:
                    df[pct_name] = 0.0
                df[pct_name] = df[pct_name].fillna(0.0)
            else:
                df[pct_name] = 0.0
            
    # ---- Folium Map Setup ----
    print("[OUTPUT] Building interactive Folium HTML map...")
    fmap = folium.Map(location=city_center, zoom_start=zoom_level, tiles=None)
    
    folium.TileLayer(
        tiles="CartoDB positron",
        attr="© OpenStreetMap contributors © CARTO",
        name="Light Map",
        control=False
    ).add_to(fmap)
    
    import branca.colormap as cm
    colormap = cm.LinearColormap(
        colors=["#ffffcc", "#fecc5c", "#fd8d3c", "#e31a1c"],
        vmin=0,
        vmax=100,
        caption="Demand Intensity (% of Max TAM)"
    )
    
    # ---- Choropleth (Res 8) ----
    if not habitable_grid_res8.empty:
        hex8_geojson = json.loads(habitable_grid_res8.to_json())
        demand8_layer = folium.FeatureGroup(name="Demand Score (H3 Res 8)", show=False)
        for feature in hex8_geojson["features"]:
            props = feature["properties"]
            score = props.get("percentile_score") or 0.0
            color_score = props.get("demand_pct") or 0.0
            color = colormap(color_score)
            
            validated_icon = "✅" if props.get("poi_validated") else "⚠️"
            stable_icon = "🔒" if props.get("stability_flag") == "Stable" else "🔄"
            
            popup_html = f"""
            <div style="font-family: 'Segoe UI', sans-serif; min-width: 220px;">
                <h4 style="color: #6366f1; margin: 0 0 8px 0;">Res 8 Hex Zone</h4>
                <table style="font-size: 13px; width: 100%; border-collapse: collapse;">
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Demand Intensity</td>
                        <td><strong>{color_score:.1f}% of Max</strong></td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Percentile Rank</td>
                        <td>{score:.1f}%ile</td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">TAM Estimate</td>
                        <td><strong>{props.get('absolute_tam', 0):,} students</strong></td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Wealth Mass</td>
                        <td>{props.get('capacity_mass', 0):.2f}</td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Ward</td>
                        <td>{props.get('ward_name', 'N/A')}</td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">POI Density</td>
                        <td>{props.get('poi_density', 0):.2f}</td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">POI Validated</td>
                        <td>{validated_icon}</td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Stability</td>
                        <td>{stable_icon} {props.get('stability_flag', 'N/A')}</td></tr>
                </table>
            </div>"""
            
            folium.GeoJson(
                feature,
                style_function=lambda feat, c=color, s=color_score: {
                    "fillColor": c,
                    "fillOpacity": min(0.8, max(0.05, s / 100)),
                    "color": "#1e293b",
                    "weight": 0.5
                },
                tooltip=folium.Tooltip(f"Res 8 | Intensity: {color_score:.1f}% | TAM: {props.get('absolute_tam', 0):,}"),
                popup=folium.Popup(popup_html, max_width=280)
            ).add_to(demand8_layer)
        demand8_layer.add_to(fmap)
        
    # ---- Choropleth (Res 7) ----
    if not habitable_grid_res7.empty:
        hex7_geojson = json.loads(habitable_grid_res7.to_json())
        demand7_layer = folium.FeatureGroup(name="Demand Score (H3 Res 7)", show=True)
        for feature in hex7_geojson["features"]:
            props = feature["properties"]
            score = props.get("percentile_score") or 0.0
            color_score = props.get("demand_pct") or 0.0
            color = colormap(color_score)
            
            validated_icon = "✅" if props.get("poi_validated") else "⚠️"
            stable_icon = "🔒" if props.get("stability_flag") == "Stable" else "🔄"
            
            popup_html = f"""
            <div style="font-family: 'Segoe UI', sans-serif; min-width: 220px;">
                <h4 style="color: #10b981; margin: 0 0 8px 0;">Res 7 Aggregated Zone</h4>
                <table style="font-size: 13px; width: 100%; border-collapse: collapse;">
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Demand Intensity</td>
                        <td><strong>{color_score:.1f}% of Max</strong></td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Percentile Rank</td>
                        <td>{score:.1f}%ile</td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Aggregated TAM</td>
                        <td><strong>{props.get('absolute_tam', 0):,} students</strong></td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Aggregated Wealth</td>
                        <td>{props.get('capacity_mass', 0):.2f}</td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Ward</td>
                        <td>{props.get('ward_name', 'N/A')}</td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Aggregated POI Density</td>
                        <td>{props.get('poi_density', 0):.2f}</td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">POI Validated</td>
                        <td>{validated_icon}</td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Stability</td>
                        <td>{stable_icon} {props.get('stability_flag', 'N/A')}</td></tr>
                </table>
            </div>"""
            
            folium.GeoJson(
                feature,
                style_function=lambda feat, c=color, s=color_score: {
                    "fillColor": c,
                    "fillOpacity": min(0.8, max(0.05, s / 100)),
                    "color": "#064e3b",
                    "weight": 0.8
                },
                tooltip=folium.Tooltip(f"Res 7 | Intensity: {color_score:.1f}% | TAM: {props.get('absolute_tam', 0):,}"),
                popup=folium.Popup(popup_html, max_width=280)
            ).add_to(demand7_layer)
        demand7_layer.add_to(fmap)
        colormap.add_to(fmap)
        
    # ---- Rental Index Layer ----
    if "rental_index" in habitable_grid_res8.columns:
        rent_grid = habitable_grid_res8[habitable_grid_res8["rental_index"] > 0]
        if not rent_grid.empty:
            rent_colormap = cm.LinearColormap(
                colors=["#f2f0f7", "#dadaeb", "#bcbddc", "#9e9ac8", "#756bb1", "#54278f", "#3f007d"],
                vmin=0,
                vmax=100,
                caption="Rental Index (Percentile)"
            )
            rent_geojson = json.loads(rent_grid.to_json())
            rent_layer = folium.FeatureGroup(name="Rental Index Heatmap (Res 8)", show=False)
            for feature in rent_geojson["features"]:
                props = feature["properties"]
                rent_val = props.get("rental_index") or 0.0
                rent_pct = props.get("rent_percentile") or 0.0
                color = rent_colormap(rent_pct)
                
                popup_html = f"""
                <div style="font-family: 'Segoe UI', sans-serif; min-width: 200px;">
                    <h4 style="color: #54278f; margin: 0 0 8px 0;">Rental Index (Res 8)</h4>
                    <table style="font-size: 13px; width: 100%; border-collapse: collapse;">
                        <tr><td style="color: #888; padding: 2px 8px 2px 0">Average Rent</td>
                            <td><strong>₹{int(rent_val):,}/mo</strong></td></tr>
                        <tr><td style="color: #888; padding: 2px 8px 2px 0">Rent Percentile</td>
                            <td><strong>{rent_pct:.1f}%</strong></td></tr>
                        <tr><td style="color: #888; padding: 2px 8px 2px 0">Price-per-sqft</td>
                            <td>₹{props.get('rental_ppsqft', 0.0):.2f}/sqft/mo</td></tr>
                        <tr><td style="color: #888; padding: 2px 8px 2px 0">Ward</td>
                            <td>{props.get('ward_name', 'N/A')}</td></tr>
                    </table>
                </div>"""
                
                folium.GeoJson(
                    feature,
                    style_function=lambda feat, c=color: {
                        "fillColor": c,
                        "fillOpacity": 0.6,
                        "color": "#4a1254",
                        "weight": 0.5
                    },
                    tooltip=folium.Tooltip(f"Rent: ₹{int(rent_val):,}/mo (%ile: {rent_pct:.1f}%) | Sqft: ₹{props.get('rental_ppsqft', 0.0):.2f}"),
                    popup=folium.Popup(popup_html, max_width=250)
                ).add_to(rent_layer)
            rent_layer.add_to(fmap)
            rent_colormap.add_to(fmap)

    # ---- Rent Price-per-sqft Layer ----
    if "rental_ppsqft" in habitable_grid_res8.columns:
        pq_grid = habitable_grid_res8[habitable_grid_res8["rental_ppsqft"] > 0]
        if not pq_grid.empty:
            pq_colormap = cm.LinearColormap(
                colors=["#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"],
                vmin=0,
                vmax=100,
                caption="Rent Per-Sqft Rate (Percentile)"
            )
            pq_geojson = json.loads(pq_grid.to_json())
            pq_layer = folium.FeatureGroup(name="Rent Per-Sqft Heatmap (Res 8)", show=False)
            for feature in pq_geojson["features"]:
                props = feature["properties"]
                ppsqft_val = props.get("rental_ppsqft") or 0.0
                ppsqft_pct = props.get("ppsqft_percentile") or 0.0
                color = pq_colormap(ppsqft_pct)
                
                popup_html = f"""
                <div style="font-family: 'Segoe UI', sans-serif; min-width: 200px;">
                    <h4 style="color: #bd0026; margin: 0 0 8px 0;">Rent Per-Sqft (Res 8)</h4>
                    <table style="font-size: 13px; width: 100%; border-collapse: collapse;">
                        <tr><td style="color: #888; padding: 2px 8px 2px 0">Price-per-sqft</td>
                            <td><strong>₹{ppsqft_val:.2f}/sqft/mo</strong></td></tr>
                        <tr><td style="color: #888; padding: 2px 8px 2px 0">Rate Percentile</td>
                            <td><strong>{ppsqft_pct:.1f}%</strong></td></tr>
                        <tr><td style="color: #888; padding: 2px 8px 2px 0">Average Rent</td>
                            <td>₹{int(props.get('rental_index', 0)):,}/mo</td></tr>
                        <tr><td style="color: #888; padding: 2px 8px 2px 0">Ward</td>
                            <td>{props.get('ward_name', 'N/A')}</td></tr>
                    </table>
                </div>"""
                
                folium.GeoJson(
                    feature,
                    style_function=lambda feat, c=color: {
                        "fillColor": c,
                        "fillOpacity": 0.6,
                        "color": "#633b11",
                        "weight": 0.5
                    },
                    tooltip=folium.Tooltip(f"Sqft Rate: ₹{ppsqft_val:.2f} (%ile: {ppsqft_pct:.1f}%) | Rent: ₹{int(props.get('rental_index', 0)):,}/mo"),
                    popup=folium.Popup(popup_html, max_width=250)
                ).add_to(pq_layer)
            pq_layer.add_to(fmap)
            pq_colormap.add_to(fmap)

    # ---- School Density Layer ----
    if "school_density" in habitable_grid_res8.columns:
        sd_grid = habitable_grid_res8[habitable_grid_res8["school_density"] > 0]
        if not sd_grid.empty:
            sd_colormap = cm.LinearColormap(
                colors=["#f7fbff", "#c6dbef", "#9ecae1", "#6baed6", "#3182bd", "#08519c", "#08306b"],
                vmin=0,
                vmax=100,
                caption="School Density (Percentile)"
            )
            sd_geojson = json.loads(sd_grid.to_json())
            sd_layer = folium.FeatureGroup(name="School Density Heatmap (Res 8)", show=False)
            for feature in sd_geojson["features"]:
                props = feature["properties"]
                sd_val = props.get("school_density") or 0.0
                sd_pct = props.get("sd_percentile") or 0.0
                color = sd_colormap(sd_pct)
                
                popup_html = f"""
                <div style="font-family: 'Segoe UI', sans-serif; min-width: 200px;">
                    <h4 style="color: #084594; margin: 0 0 8px 0;">School Density (Res 8)</h4>
                    <table style="font-size: 13px; width: 100%; border-collapse: collapse;">
                        <tr><td style="color: #888; padding: 2px 8px 2px 0">Density Index</td>
                            <td><strong>{int(sd_val):,} students</strong></td></tr>
                        <tr><td style="color: #888; padding: 2px 8px 2px 0">Density Percentile</td>
                            <td><strong>{sd_pct:.1f}%</strong></td></tr>
                        <tr><td style="color: #888; padding: 2px 8px 2px 0">Ward</td>
                            <td>{props.get('ward_name', 'N/A')}</td></tr>
                    </table>
                </div>"""
                
                folium.GeoJson(
                    feature,
                    style_function=lambda feat, c=color: {
                        "fillColor": c,
                        "fillOpacity": 0.6,
                        "color": "#082b54",
                        "weight": 0.5
                    },
                    tooltip=folium.Tooltip(f"Density: {int(sd_val):,} (%ile: {sd_pct:.1f}%)"),
                    popup=folium.Popup(popup_html, max_width=250)
                ).add_to(sd_layer)
            sd_layer.add_to(fmap)
            sd_colormap.add_to(fmap)
            
    # ---- Top N Zones Layer ----
    if not top_zones.empty:
        top_layer = folium.FeatureGroup(name=f"Top {top_n} Zones (Res 8)", show=True)
        top_geojson = json.loads(top_zones.to_json())
        for i, feature in enumerate(top_geojson["features"]):
            props = feature["properties"]
            score = props.get("percentile_score") or 0.0
            folium.GeoJson(
                feature,
                style_function=lambda feat: {
                    "fillColor": "#ef4444",
                    "fillOpacity": 0.4,
                    "color": "#b91c1c",
                    "weight": 2.5
                },
                tooltip=folium.Tooltip(f"🏆 Top Zone #{i+1} | Score: {score:.1f}%")
            ).add_to(top_layer)
        top_layer.add_to(fmap)
        
    # ---- School Partnership Rankings Layer ----
    if ranked_schools_df is not None and not ranked_schools_df.empty:
        partnership_layer = folium.FeatureGroup(name="🤝 School Partnerships (Ranked)", show=True)
        for _, school in ranked_schools_df.iterrows():
            rank = int(school.get("rank", 0))
            score = school.get("partnership_score", 0.0)
            name = school.get("school_name", "School")
            
            color = "#8E44AD" if rank <= 5 else "#3498DB"
            radius = 8 if rank <= 5 else 6
            
            popup_html = f"""
            <div style="font-family: 'Segoe UI', sans-serif; min-width: 250px;">
                <h4 style="color: #8e44ad; margin: 0 0 4px 0;">Rank #{rank}: {name}</h4>
                <div style="font-size: 14px; margin-bottom: 8px;"><strong>Partnership Score: {score:.1f} / 100</strong></div>
                <table style="font-size: 12px; width: 100%; border-collapse: collapse;">
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Board</td><td><strong>{school.get('board', 'N/A')}</strong></td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Annual Fee</td><td><strong>₹{school.get('avg_fee_annual', 0):,.0f}</strong></td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Students</td><td>{school.get('student_count', 0)}</td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">TAM Density</td><td>{school.get('tam_density_score', 0)*100:.1f}%</td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Fee Match</td><td>{school.get('fee_alignment_score', 0)*100:.1f}%</td></tr>
                    <tr><td style="color: #888; padding: 2px 8px 2px 0">Hex Percentile</td><td>{school.get('hex_percentile', 0):.1f}%ile</td></tr>
                </table>
            </div>"""
            
            folium.CircleMarker(
                location=[school.get("lat"), school.get("lon")],
                radius=radius,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.9,
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=folium.Tooltip(f"🏆 Rank #{rank} | {name} (Score: {score:.1f})")
            ).add_to(partnership_layer)
        partnership_layer.add_to(fmap)

    # ---- Schools Layer ----
    if schools_gdf is not None and not schools_gdf.empty:
        schools_layer = folium.FeatureGroup(name="🏫 Schools", show=False)
        for _, school in schools_gdf.iterrows():
            folium.CircleMarker(
                location=[school.geometry.y, school.geometry.x],
                radius=5,
                color="#FF6B35",
                fill=True,
                fill_color="#FF6B35",
                fill_opacity=0.8,
                popup=folium.Popup(f"""
                    <b>{school.get('name', 'School')}</b><br>
                    Board: {', '.join(school.get('board', []))}<br>
                    Fee: ₹{school.get('avg_fee', 0):,.0f}<br>
                    Students: {school.get('student_count', 0)}
                """, max_width=250),
                tooltip=school.get("name", "School")
            ).add_to(schools_layer)
        schools_layer.add_to(fmap)
        
    # ---- POI Layer ----
    if pois_gdf is not None and not pois_gdf.empty:
        poi_layer = folium.FeatureGroup(name="📍 POIs", show=False)
        for _, poi in pois_gdf.iterrows():
            folium.CircleMarker(
                location=[poi.geometry.y, poi.geometry.x],
                radius=6,
                color="#F1C40F",
                fill=True,
                fill_color="#F1C40F",
                fill_opacity=0.85,
                popup=folium.Popup(f"""
                    <b>{poi.get('name', 'POI')}</b><br>
                    Category: {poi.get('category', 'N/A')}
                """, max_width=200),
                tooltip=poi.get("name", "POI")
            ).add_to(poi_layer)
        poi_layer.add_to(fmap)

    # ---- Point-Based Heatmaps ----
    print("[OUTPUT] Adding point-based continuous heatmap overlays...")
    
    # 1. Schools Location Heatmap
    if schools_gdf is not None and not schools_gdf.empty:
        school_points = [[row.geometry.y, row.geometry.x] for _, row in schools_gdf.iterrows() if row.geometry]
        if school_points:
            HeatMap(
                data=school_points,
                name="🔥 School Concentration Heatmap (Points)",
                show=False,
                radius=25,
                blur=20,
                min_opacity=0.3
            ).add_to(fmap)
            
    # 2. Real Estate Rent Heatmaps
    if re_gdf is not None and not re_gdf.empty:
        rent_listings = re_gdf[re_gdf["transaction_type"] == "Rent"].copy()
        
        # Rent Price point heatmap (weighted by price)
        rent_points = [[row.geometry.y, row.geometry.x, row["price_inr"]] for _, row in rent_listings.iterrows() if row.geometry and row["price_inr"] > 0]
        if rent_points:
            max_rent = max(w[2] for w in rent_points)
            scaled_rent_points = [[w[0], w[1], w[2] / max_rent] for w in rent_points]
            HeatMap(
                data=scaled_rent_points,
                name="🔥 Rent Price Heatmap (Points)",
                show=False,
                radius=30,
                blur=25,
                min_opacity=0.2
            ).add_to(fmap)
            
        # Rent Per-sqft point heatmap (weighted by ppsqft)
        ppsqft_points = [[row.geometry.y, row.geometry.x, row["price_per_sqft"]] for _, row in rent_listings.iterrows() if row.geometry and row["price_per_sqft"] > 0]
        if ppsqft_points:
            max_pp = max(w[2] for w in ppsqft_points)
            scaled_ppsqft_points = [[w[0], w[1], w[2] / max_pp] for w in ppsqft_points]
            HeatMap(
                data=scaled_ppsqft_points,
                name="🔥 Rent Per-Sqft Heatmap (Points)",
                show=False,
                radius=30,
                blur=25,
                min_opacity=0.2
            ).add_to(fmap)
        
    # ---- Isochrones Layer (Reverse Catchments) ----
    if isochrones_gdf is not None and not isochrones_gdf.empty:
        schools_with_iso = sorted(isochrones_gdf["school_name"].unique())
        BAND_COLORS = {
            "0-10": "#27AE60",
            "10-20": "#F39C12",
            "20-30": "#E74C3C"
        }
        BAND_OPACITIES = {
            "0-10": 0.15,
            "10-20": 0.08,
            "20-30": 0.04
        }
        for s_name in schools_with_iso:
            school_iso = isochrones_gdf[isochrones_gdf["school_name"] == s_name]
            iso_fg = folium.FeatureGroup(name=f"🎓 Catchment: {s_name}", show=False)
            for _, row in school_iso.iterrows():
                band = row.get("band", "0-10")
                color = BAND_COLORS.get(band, "#95A5A6")
                opacity = BAND_OPACITIES.get(band, 0.05)
                
                if row.geometry is not None and not row.geometry.is_empty:
                    geom_simple = row.geometry.simplify(0.0001, preserve_topology=True)
                    folium.GeoJson(
                        geom_simple,
                        style_function=lambda feat, c=color, o=opacity: {
                            "fillColor": c,
                            "fillOpacity": o,
                            "color": c,
                            "weight": 1.0,
                            "dashArray": "5, 5"
                        },
                        tooltip=folium.Tooltip(f"{s_name} | Band: {band} mins")
                    ).add_to(iso_fg)
            iso_fg.add_to(fmap)

    folium.LayerControl(collapsed=False).add_to(fmap)
    
    html_path = f"{bundle_dir}/interactive_map.html"
    fmap.save(html_path)
    print(f"[OUTPUT] ✅ Interactive map saved: {html_path}")
    
    # ---- CSV Exports ----
    print("[OUTPUT] Exporting hex_scores_res8.csv and hex_scores_res7.csv...")
    csv8_path = f"{bundle_dir}/hex_scores_res8.csv"
    csv7_path = f"{bundle_dir}/hex_scores_res7.csv"
    csv_compat_path = f"{bundle_dir}/hex_scores.csv"
    
    output_cols = [
        "hex_id", "percentile_score", "absolute_tam", "apportioned_students",
        "students_premium", "students_midmarket", "students_economy",
        "pct_premium", "pct_midmarket", "pct_economy",
        "kde_premium", "kde_midmarket", "kde_economy",
        "idw_rent_normalized", "idw_ppsqft_normalized",
        "rental_index", "rental_ppsqft", "school_density",
        "capacity_mass", "poi_density", "poi_validated",
        "ward_name", "ward_poi_score", "stability_flag"
    ]
                   
    # Res 8
    res8_copy = habitable_grid_res8.copy()
    res8_copy["center_lat"] = res8_copy.geometry.centroid.y
    res8_copy["center_lon"] = res8_copy.geometry.centroid.x
    available8 = ["hex_id", "center_lat", "center_lon"] + [c for c in output_cols[1:] if c in res8_copy.columns]
    res8_copy[available8].to_csv(csv8_path, index=False)
    res8_copy[available8].to_csv(csv_compat_path, index=False) # Backwards compatible copy
    
    # Res 7
    res7_copy = habitable_grid_res7.copy()
    res7_copy["center_lat"] = res7_copy.geometry.centroid.y
    res7_copy["center_lon"] = res7_copy.geometry.centroid.x
    available7 = ["hex_id", "center_lat", "center_lon"] + [c for c in output_cols[1:] if c in res7_copy.columns]
    res7_copy[available7].to_csv(csv7_path, index=False)
    
    # ---- GeoJSON Exports ----
    print("[OUTPUT] Exporting hex GeoJSONs...")
    geojson8_path = f"{bundle_dir}/hex_scores_res8.geojson"
    geojson7_path = f"{bundle_dir}/hex_scores_res7.geojson"
    geojson_compat_path = f"{bundle_dir}/hex_scores.geojson"
    
    habitable_grid_res8.to_file(geojson8_path, driver="GeoJSON")
    habitable_grid_res8.to_file(geojson_compat_path, driver="GeoJSON") # Backwards compatible copy
    habitable_grid_res7.to_file(geojson7_path, driver="GeoJSON")
    
    # Top Zones GeoJSON
    top_path = f"{bundle_dir}/top_zones.geojson"
    top_zones.to_file(top_path, driver="GeoJSON")
    
    # Isochrones GeoJSON
    if isochrones_gdf is not None and not isochrones_gdf.empty:
        isochrones_path = f"{bundle_dir}/isochrones.geojson"
        isochrones_gdf.to_file(isochrones_path, driver="GeoJSON")
        
    # Ward JSON/CSVs
    ward_json_path = f"{bundle_dir}/ward_poi_proximity.json"
    with open(ward_json_path, "w") as f:
        json.dump(ward_scores, f, indent=2, default=str)
        
    ward_csv_path = f"{bundle_dir}/ward_poi_proximity.csv"
    if ward_scores:
        ward_rows = []
        for ws in ward_scores:
            row = {"ward_name": ws["ward_name"], "total_proximity_score": ws["total_proximity_score"]}
            for cat, cat_data in ws.get("category_scores", {}).items():
                row[f"{cat}_nearest_m"] = cat_data.get("nearest_meters")
                row[f"{cat}_count_2km"] = cat_data.get("count_within_2km")
            ward_rows.append(row)
        pd.DataFrame(ward_rows).to_csv(ward_csv_path, index=False)
        
    # Config snapshot
    snapshot_path = f"{bundle_dir}/config_snapshot.json"
    config_snapshot = {
        "city": city_config["city"]["name"],
        "tier": tier_config.get("label"),
        "gravity_alpha": city_config["gravity_model"]["alpha"],
        "gravity_beta": city_config["gravity_model"]["beta"],
        "run_date": today,
        "top_n_zones": top_n
    }
    with open(snapshot_path, "w") as f:
        json.dump(config_snapshot, f, indent=2)
        
    # ---- 8. Styled KML Export ----
    kml_path = f"{bundle_dir}/catchmentiq_output.kml"
    print(f"[OUTPUT] Generating rich styled KML at {kml_path}...")
    export_to_kml(
        output_path=kml_path,
        grid_res8=habitable_grid_res8,
        grid_res7=habitable_grid_res7,
        schools_gdf=schools_gdf,
        isochrones_gdf=isochrones_gdf,
        pois_gdf=pois_gdf,
        ranked_schools_df=ranked_schools_df,
        city_name=city_name,
        tier_label=tier_config.get("label", "Premium")
    )
    print(f"[OUTPUT] ✅ Styled KML saved: {kml_path}")
    
    # ---- 9. Interactive Catchment Analyzer Module ----
    tier_label_str = tier_config.get("label", "").lower()
    run_bracket = "premium"
    if "midmarket" in tier_label_str or "mid-market" in tier_label_str or "12lpa" in tier_label_str:
        run_bracket = "midmarket"
    elif "economy" in tier_label_str or "budget" in tier_label_str:
        run_bracket = "economy"
        
    _generate_catchment_analyzer(bundle_dir, habitable_grid_res7, schools_gdf, re_gdf, run_bracket)
    
    return bundle_dir


def _generate_catchment_analyzer(bundle_dir, habitable_grid_res7, schools_gdf, re_gdf, run_bracket="premium"):
    """Generate a self-contained HTML Catchment Analyzer module using React, Tailwind, and Leaflet."""
    print("[OUTPUT] Generating interactive Catchment Analyzer HTML module...")
    
    # Clean and simplify the grid GeoJSON for browser efficiency
    keep_cols = ["hex_id", "ward_name", "apportioned_students", "students_premium", "students_midmarket", "students_economy", 
                 "rental_index", "rental_ppsqft", "school_density", "kde_premium", "kde_midmarket", "kde_economy",
                 "idw_rent_normalized", "idw_ppsqft_normalized", "stability_flag", "poi_validated", "is_habitable", "geometry",
                 "structural_volume", "listings_premium", "listings_midmarket", "listings_economy",
                 "ratio_premium", "ratio_midmarket", "ratio_economy",
                 "feeder_premium", "feeder_midmarket", "feeder_economy"]
    grid_simplified = habitable_grid_res7[[c for c in keep_cols if c in habitable_grid_res7.columns]].copy()
    
    # Store centroid coordinates for Manhattan calculations in UI
    grid_simplified["centroid_lat"] = grid_simplified.geometry.centroid.y
    grid_simplified["centroid_lon"] = grid_simplified.geometry.centroid.x
    
    # Simplify geometries to keep the GeoJSON payload lightweight
    grid_simplified["geometry"] = grid_simplified.geometry.simplify(0.0001, preserve_topology=True)
    grid_geojson_str = grid_simplified.to_json()
    
    # Serialize schools
    schools_list = []
    for idx, s in schools_gdf.iterrows():
        fb = s.get("fee_bracket")
        if fb is None or (isinstance(fb, float) and np.isnan(fb)):
            avg_fee = s.get("avg_fee", 0.0)
            if avg_fee >= 150000:
                fb = "premium"
            elif avg_fee >= 60000:
                fb = "midmarket"
            else:
                fb = "economy"
        schools_list.append({
            "name": str(s["name"]),
            "lat": float(s.geometry.y),
            "lon": float(s.geometry.x),
            "student_count": int(s["student_count"]),
            "board": ", ".join(s["board"]) if isinstance(s["board"], list) else str(s["board"]),
            "fee_bracket": str(fb),
            "board_confidence": float(s.get("board_confidence", 1.0)),
            "avg_fee": float(s.get("avg_fee", 0.0))
        })
    schools_json_str = json.dumps(schools_list)
    
    # Serialize real estate listings for IDW heatmap (sample to 5000 max to prevent browser lag)
    listings_list = []
    if re_gdf is not None and not re_gdf.empty:
        listings_df = re_gdf.copy()
        if len(listings_df) > 5000:
            listings_df = listings_df.sample(n=5000, random_state=42)
        for idx, row in listings_df.iterrows():
            try:
                listings_list.append({
                    "lat": float(row.geometry.y),
                    "lon": float(row.geometry.x),
                    "price": float(row.get("price_inr", 0.0)),
                    "ppsqft": float(row.get("price_per_sqft", 0.0)),
                    "type": str(row.get("transaction_type", "Rent")),
                    "bracket": str(row.get("bracket", row.get("listing_bracket", "economy")))
                })
            except Exception:
                continue
    listings_json_str = json.dumps(listings_list)
    
    # Pre-compute top 10 hotspots
    from catchmentiq.output.catchment_analyzer_precompute import get_top_hotspots
    hotspots_list = get_top_hotspots(habitable_grid_res7)
    hotspots_json_str = json.dumps(hotspots_list)

    # Locate templates directory
    templates_dir = os.path.join(os.path.dirname(__file__), "templates")
    
    # Read modular template files
    with open(os.path.join(templates_dir, "index.html"), "r") as f:
        index_html = f.read()
    with open(os.path.join(templates_dir, "swiss.css"), "r") as f:
        swiss_css = f.read()
    with open(os.path.join(templates_dir, "App.js"), "r") as f:
        app_js = f.read()
    with open(os.path.join(templates_dir, "Sidebar.js"), "r") as f:
        sidebar_js = f.read()
    with open(os.path.join(templates_dir, "MapComponent.js"), "r") as f:
        map_component_js = f.read()
    with open(os.path.join(templates_dir, "AuditPanel.js"), "r") as f:
        audit_panel_js = f.read()

    # 1. Output Modular Bundle inside bundle_dir
    os.makedirs(os.path.join(bundle_dir, "css"), exist_ok=True)
    os.makedirs(os.path.join(bundle_dir, "js"), exist_ok=True)
    os.makedirs(os.path.join(bundle_dir, "js", "components"), exist_ok=True)

    # Write CSS and component files
    with open(os.path.join(bundle_dir, "css", "swiss.css"), "w") as f:
        f.write(swiss_css)
    with open(os.path.join(bundle_dir, "js", "App.js"), "w") as f:
        f.write(app_js)
    with open(os.path.join(bundle_dir, "js", "components", "Sidebar.js"), "w") as f:
        f.write(sidebar_js)
    with open(os.path.join(bundle_dir, "js", "components", "MapComponent.js"), "w") as f:
        f.write(map_component_js)
    with open(os.path.join(bundle_dir, "js", "components", "AuditPanel.js"), "w") as f:
        f.write(audit_panel_js)
    
    # Write data.js containing coordinates and geometries
    data_js_content = f"""// Dynamic Data Variables generated by CatchmentIQ pipeline
window.gridData = {grid_geojson_str};
window.schoolsData = {schools_json_str};
window.listingsData = {listings_json_str};
window.hotspotsData = {hotspots_json_str};
window.runTargetBracket = "{run_bracket}";
"""
    with open(os.path.join(bundle_dir, "js", "data.js"), "w") as f:
        f.write(data_js_content)

    # Write modular index.html
    with open(os.path.join(bundle_dir, "index.html"), "w") as f:
        f.write(index_html)

    # 2. Output Standalone Single-File Bundle (catchment_analyzer.html)
    # Replace stylesheets and scripts with inlined contents for direct file:// browsing without CORS issues
    standalone_html = index_html
    
    # Inline CSS
    standalone_html = standalone_html.replace(
        '<link rel="stylesheet" href="css/swiss.css" />',
        f"<style>\n{swiss_css}\n</style>"
    )
    
    # Inline Data JS
    standalone_html = standalone_html.replace(
        '<script src="js/data.js"></script>',
        f"<script>\n{data_js_content}\n</script>"
    )
    
    # Inline JS components
    standalone_html = standalone_html.replace(
        '<script type="text/babel" src="js/components/Sidebar.js"></script>',
        f'<script type="text/babel">\n{sidebar_js}\n</script>'
    )
    standalone_html = standalone_html.replace(
        '<script type="text/babel" src="js/components/MapComponent.js"></script>',
        f'<script type="text/babel">\n{map_component_js}\n</script>'
    )
    standalone_html = standalone_html.replace(
        '<script type="text/babel" src="js/components/AuditPanel.js"></script>',
        f'<script type="text/babel">\n{audit_panel_js}\n</script>'
    )
    standalone_html = standalone_html.replace(
        '<script type="text/babel" src="js/App.js"></script>',
        f'<script type="text/babel">\n{app_js}\n</script>'
    )

    standalone_path = os.path.join(bundle_dir, "catchment_analyzer.html")
    with open(standalone_path, "w") as f:
        f.write(standalone_html)
        
    print(f"[OUTPUT] ✅ Modular Catchment Analyzer saved in: {bundle_dir}/")
    print(f"[OUTPUT] ✅ Standalone Catchment Analyzer saved: {standalone_path}")
