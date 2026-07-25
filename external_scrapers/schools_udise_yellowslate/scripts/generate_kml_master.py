import json
import os
import html
import simplekml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'output')

MASTER_PATH = os.path.join(DATA_DIR, 'yellowslate_schools_master.json')
OUTPUT_KML_PATH = os.path.join(DATA_DIR, 'yellowslate_schools_master.kml')

def generate_master_kml():
    print("Loading master database...")
    if not os.path.exists(MASTER_PATH):
        print(f"Error: Master file not found at {MASTER_PATH}")
        return
        
    with open(MASTER_PATH, 'r', encoding='utf-8') as f:
        schools = json.load(f)
        
    kml = simplekml.Kml(name="Yellowslate Schools Master Map")
    
    # Define fee bracket groups, labels, and styles/colors
    brackets = [
        {"key": "above_2l", "label": "Above 2 Lakhs", "color": "purple-circle.png"},
        {"key": "1l_2l", "label": "1 Lakh - 2 Lakhs", "color": "red-circle.png"},
        {"key": "70k_1l", "label": "70K - 1 Lakh", "color": "orange-circle.png"},
        {"key": "50k_70k", "label": "50K - 70K", "color": "ylw-circle.png"},
        {"key": "30k_50k", "label": "30K - 50K", "color": "blu-circle.png"},
        {"key": "under_30k", "label": "Under 30K", "color": "grn-circle.png"}
    ]
    
    # Create KML folders for each bracket
    folders = {}
    styles = {}
    
    for b in brackets:
        folders[b["key"]] = kml.newfolder(name=b["label"])
        
        # Create Style
        style = simplekml.Style()
        style.iconstyle.icon.href = f"http://maps.google.com/mapfiles/kml/paddle/{b['color']}"
        styles[b["key"]] = style
        
    # Default folder & style for unknown/fallback bracket keys
    folders["unknown"] = kml.newfolder(name="Unknown Bracket")
    style_unknown = simplekml.Style()
    style_unknown.iconstyle.icon.href = "http://maps.google.com/mapfiles/kml/paddle/wht-circle.png"
    styles["unknown"] = style_unknown

    count = 0
    skipped_no_coords = 0
    
    for s in schools:
        lat = s.get("latitude")
        lon = s.get("longitude")
        
        if lat is None or lon is None:
            skipped_no_coords += 1
            continue
            
        name = s.get("school_name", "Unknown School")
        area = s.get("area", "N/A")
        board = s.get("board", "N/A")
        category = s.get("structural_category", "N/A")
        match_status = s.get("match_status", "N/A")
        udise_code = s.get("udise_code") or "N/A"
        udise_name = s.get("udise_school_name") or "N/A"
        enrollment = s.get("student_enrollment") or 0
        enrollment_source = s.get("enrollment_source", "N/A")
        
        fee_bracket = s.get("fee_bracket") or {}
        bracket_key = fee_bracket.get("bracket_key") or "unknown"
        bracket_label = fee_bracket.get("bracket_label") or "Unknown Bracket"
        fee_text = fee_bracket.get("fee_text") or "N/A"
        rank = s.get("rank_in_bracket") or "N/A"
        
        if bracket_key not in folders:
            folder_key = "unknown"
        else:
            folder_key = bracket_key
            
        # Create HTML Description table
        desc = f"""
        <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; font-family: sans-serif; font-size: 13px; max-width: 450px;">
            <tr bgcolor="#f2f2f2"><th colspan="2" align="center" style="font-size: 14px;"><strong>{html.escape(name)}</strong></th></tr>
            <tr><th align="left" bgcolor="#f9f9f9">Area</th><td>{html.escape(str(area))}</td></tr>
            <tr><th align="left" bgcolor="#f9f9f9">Board</th><td>{html.escape(str(board))}</td></tr>
            <tr><th align="left" bgcolor="#f9f9f9">Category</th><td>{html.escape(str(category))}</td></tr>
            <tr><th align="left" bgcolor="#f9f9f9">Fee Bracket</th><td><strong>{html.escape(str(bracket_label))}</strong> ({html.escape(str(fee_text))})</td></tr>
            <tr><th align="left" bgcolor="#f9f9f9">Rank in Bracket</th><td>{html.escape(str(rank))}</td></tr>
            <tr><th align="left" bgcolor="#f9f9f9">Match Status</th><td>{html.escape(str(match_status).replace('_', ' ').title())}</td></tr>
            <tr><th align="left" bgcolor="#f9f9f9">UDISE Code</th><td>{html.escape(str(udise_code))}</td></tr>
            <tr><th align="left" bgcolor="#f9f9f9">UDISE School Name</th><td>{html.escape(str(udise_name))}</td></tr>
            <tr><th align="left" bgcolor="#f9f9f9">Student Enrollment</th><td>{html.escape(f"{enrollment:,}")} ({html.escape(str(enrollment_source))})</td></tr>
            <tr><th align="left" bgcolor="#f9f9f9">Yellowslate Link</th><td><a href="{html.escape(s.get('school_url', ''))}" target="_blank">View School Page</a></td></tr>
        </table>
        """
        
        # Add Placemark point
        pnt = folders[folder_key].newpoint(name=name, coords=[(lon, lat)])
        pnt.description = desc
        pnt.style = styles[folder_key]
        
        count += 1
        
    # Clean up empty folders from KML
    for key, folder in list(folders.items()):
        # If folder contains no features, remove it from KML root
        if not folder.features:
            kml.features.remove(folder)
            
    kml.save(OUTPUT_KML_PATH)
    print(f"\nKML Generation Complete:")
    print(f"- Total schools mapped: {count}")
    print(f"- Schools skipped (no coordinates): {skipped_no_coords}")
    print(f"- Saved KML map to: {OUTPUT_KML_PATH}")

if __name__ == "__main__":
    generate_master_kml()
