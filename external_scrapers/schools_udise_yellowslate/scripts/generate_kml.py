import json
import simplekml
import html

def create_kml():
    print("Loading data...")
    with open("data/output/schools_analysis_bangalore_cleaned.json", "r") as f:
        data = json.load(f)
        
    kml = simplekml.Kml(name="Schools Analysis Map")
    
    # We will create folders by Fee Group
    folders = {}
    fee_groups = ["Budget", "Affordable", "Premium", "Luxury", "Unknown"]
    
    # Pre-create folders to control order
    for fg in fee_groups:
        folders[fg] = kml.newfolder(name=f"{fg} Schools")
        
    # Styles for different fee groups
    styles = {}
    
    styles["Budget"] = simplekml.Style()
    styles["Budget"].iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/paddle/grn-circle.png'
    
    styles["Affordable"] = simplekml.Style()
    styles["Affordable"].iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/paddle/blu-circle.png'
    
    styles["Premium"] = simplekml.Style()
    styles["Premium"].iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/paddle/ylw-circle.png'
    
    styles["Luxury"] = simplekml.Style()
    styles["Luxury"].iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/paddle/purple-circle.png'
    
    styles["Unknown"] = simplekml.Style()
    styles["Unknown"].iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/paddle/wht-circle.png'

    count = 0
    for s in data["schools"]:
        meta = s.get("metadata", {})
        loc = meta.get("location", {})
        analysis = s.get("analysis_dimensions", {})
        enrollment = s.get("enrollment", {})
        
        lat = loc.get("latitude")
        lon = loc.get("longitude")
        
        if lat is None or lon is None:
            continue
            
        name = meta.get("school_name", "Unknown School")
        udise = s.get("udise_code", "N/A")
        
        # Determine Fee Group
        fee_group = "Unknown"
        confidence_str = "Predicted"
        
        if "fee_information" in s and s["fee_information"] is not None:
            fee = s["fee_information"].get("average_annual_fee")
            if fee is not None:
                if fee <= 45000: fee_group = "Budget"
                elif fee <= 75000: fee_group = "Affordable"
                elif fee <= 150000: fee_group = "Premium"
                else: fee_group = "Luxury"
                
                if s["fee_information"].get("is_fee_estimated"):
                    confidence_str = "Estimated (External Source)"
                else:
                    confidence_str = "Raw / Actual Fee"
        
        if fee_group == "Unknown" and "fee_group" in analysis:
            fee_group = analysis["fee_group"]
            conf = analysis.get("fee_group_confidence", 0.0)
            confidence_str = f"ML Predicted ({conf*100:.1f}%)"
            
        if fee_group not in folders:
            fee_group = "Unknown"
            
        # Create HTML Description
        mgt = meta.get("management", "Unknown")
        board = analysis.get("board_group", "Unknown")
        students = enrollment.get("total_students", "N/A")
        address = meta.get("address", "N/A")
        
        desc = f"""
        <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; font-family: sans-serif;">
            <tr><th align="left" bgcolor="#f2f2f2">UDISE Code</th><td>{html.escape(str(udise))}</td></tr>
            <tr><th align="left" bgcolor="#f2f2f2">Management</th><td>{html.escape(str(mgt))}</td></tr>
            <tr><th align="left" bgcolor="#f2f2f2">Board</th><td>{html.escape(str(board))}</td></tr>
            <tr><th align="left" bgcolor="#f2f2f2">Total Students</th><td>{html.escape(str(students))}</td></tr>
            <tr><th align="left" bgcolor="#f2f2f2">Fee Category</th><td><strong>{fee_group}</strong></td></tr>
            <tr><th align="left" bgcolor="#f2f2f2">Fee Source</th><td>{html.escape(str(confidence_str))}</td></tr>
            <tr><th align="left" bgcolor="#f2f2f2">Address</th><td>{html.escape(str(address))}</td></tr>
        </table>
        """
        
        # Add point to KML
        pnt = folders[fee_group].newpoint(name=name, coords=[(lon, lat)])
        pnt.description = desc
        pnt.style = styles[fee_group]
        
        count += 1
        
    print(f"Added {count} points to KML.")
    output_path = "data/output/schools_map_cleaned.kml"
    kml.save(output_path)
    print(f"Saved KML to {output_path}")

if __name__ == "__main__":
    create_kml()
