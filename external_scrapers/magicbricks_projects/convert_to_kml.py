#!/usr/bin/env python3
import json
import os
import xml.etree.ElementTree as ET
from collections import defaultdict
import html

INPUT_FILE = "data/raw/bangalore_projects_enriched.jsonl"
OUTPUT_FILE = "data/raw/bangalore_projects_enriched.kml"

def format_price(val):
    if not val or val <= 0:
        return 'Contact Developer'
    if val >= 10000000:
        return f"Rs. {val / 10000000:.2f} Cr"
    return f"Rs. {val / 100000:.2f} Lac"

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} does not exist.")
        return
        
    print(f"Reading enriched projects from {INPUT_FILE}...")
    
    # Group projects by locality
    locality_groups = defaultdict(list)
    total_processed = 0
    with_coords = 0
    
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    card = json.loads(line)
                    lat = card.get("latitude")
                    lon = card.get("longitude")
                    if lat is not None and lon is not None:
                        locality = card.get("lmtDName") or "Unknown Locality"
                        locality_groups[locality].append(card)
                        with_coords += 1
                    total_processed += 1
                except Exception:
                    pass
                    
    print(f"Found {with_coords} projects with valid coordinates (out of {total_processed} total).")
    
    # Build KML Structure
    kml_ns = "http://www.opengis.net/kml/2.2"
    kml = ET.Element("kml", xmlns=kml_ns)
    document = ET.SubElement(kml, "Document")
    
    doc_name = ET.SubElement(document, "name")
    doc_name.text = "Bangalore Enriched Projects Map"
    
    doc_desc = ET.SubElement(document, "description")
    doc_desc.text = f"Visual validation layer containing {with_coords} active residential projects in Bangalore."
    
    # Add some basic styling for Placemarks
    style = ET.SubElement(document, "Style", id="projectPin")
    icon_style = ET.SubElement(style, "IconStyle")
    icon = ET.SubElement(icon_style, "Icon")
    href = ET.SubElement(icon, "href")
    href.text = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"
    
    for locality, projects in sorted(locality_groups.items()):
        folder = ET.SubElement(document, "Folder")
        folder_name = ET.SubElement(folder, "name")
        folder_name.text = f"{locality} ({len(projects)})"
        
        for p in projects:
            name = p.get("psmName") or p.get("devName") or "Unnamed Project"
            lat = p["latitude"]
            lon = p["longitude"]
            dev = p.get("devName") or "Unknown Developer"
            units = p.get("totalUnits") or "N/A"
            min_price = format_price(p.get("minPrice"))
            max_price = format_price(p.get("maxPrice"))
            pdp_url = f"https://www.magicbricks.com/{p['pdpUrl']}" if p.get("pdpUrl") else "N/A"
            desc_text = p.get("mhDesc") or ""
            
            # HTML description balloon
            description_html = f"""<![CDATA[
                <div style="font-family: Arial, sans-serif; font-size: 13px; line-height: 1.5; color: #333;">
                    <h3 style="margin-top: 0; color: #1e3a8a;">{html.escape(name)}</h3>
                    <table style="border-collapse: collapse; width: 100%;">
                        <tr>
                            <td style="padding: 4px 0; font-weight: bold; width: 35%;">Developer:</td>
                            <td style="padding: 4px 0;">{html.escape(dev)}</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px 0; font-weight: bold;">Locality:</td>
                            <td style="padding: 4px 0;">{html.escape(locality)}</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px 0; font-weight: bold;">Total Units:</td>
                            <td style="padding: 4px 0;">{units}</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px 0; font-weight: bold;">Price Range:</td>
                            <td style="padding: 4px 0; color: #10b981; font-weight: bold;">{min_price} - {max_price}</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px 0; font-weight: bold;">Source PDP:</td>
                            <td style="padding: 4px 0;"><a href="{pdp_url}" target="_blank">View on MagicBricks</a></td>
                        </tr>
                    </table>
                    <p style="margin-top: 10px; font-style: italic; color: #555;">{html.escape(desc_text)}</p>
                </div>
            ]]>"""
            
            placemark = ET.SubElement(folder, "Placemark")
            p_name = ET.SubElement(placemark, "name")
            p_name.text = name
            
            p_style = ET.SubElement(placemark, "styleUrl")
            p_style.text = "#projectPin"
            
            # KML Description handles CDATA natively if written as text
            p_desc = ET.SubElement(placemark, "description")
            p_desc.text = description_html
            
            point = ET.SubElement(placemark, "Point")
            coords = ET.SubElement(point, "coordinates")
            coords.text = f"{lon},{lat},0"
            
    # Serialize to file
    tree = ET.ElementTree(kml)
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    tree.write(OUTPUT_FILE, encoding="utf-8", xml_declaration=True)
    print(f"Successfully created KML file: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
