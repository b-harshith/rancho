import json
import numpy as np
import os

def main():
    json_path = "data/school_averages_summary_bangalore.json"
    with open(json_path, "r", encoding="utf-8") as f:
        schools = json.load(f)
        
    valid_schools = []
    fees = []
    for s in schools:
        fee = s.get("Average Fee (Annual)")
        if fee != "NA" and fee is not None:
            try:
                val = float(fee)
                valid_schools.append(s)
                fees.append(val)
            except ValueError:
                pass
                
    if not fees:
        print("No valid fees found.")
        return
        
    q3 = np.percentile(fees, 75)
    
    q4_schools = [s for s in valid_schools if float(s["Average Fee (Annual)"]) >= q3]
    q4_schools.sort(key=lambda x: float(x["Average Fee (Annual)"]), reverse=True)
    
    artifact_path = "/Users/malleswararao/.gemini/antigravity-ide/brain/5ad9d68c-7c50-4a98-8496-16e26f027f49/q4_schools_list.md"
    
    with open(artifact_path, "w", encoding="utf-8") as out:
        out.write(f"# Q4 Schools List (Bangalore)\n\n")
        out.write(f"This document lists all **{len(q4_schools)}** schools in the 4th quartile (top 25% by fee, threshold: **INR {q3:,.2f}** annual fee).\n\n")
        out.write("| # | School Name | Board | Maximum Annual Fee | Starting Class | Ending Class | Latitude | Longitude | Address | \n")
        out.write("|---|---|---|---|---|---|---|---|---| \n")
        for idx, s in enumerate(q4_schools):
            fee_val = float(s["Average Fee (Annual)"])
            out.write(f"| {idx+1} | {s['School Name']} | {s['Board']} | INR {fee_val:,.2f} | {s.get('Starting Class', 'NA')} | {s.get('Ending Class', 'NA')} | {s.get('Latitude', 'NA')} | {s.get('Longitude', 'NA')} | {s.get('Address', 'NA')} | \n")
            
    print(f"Artifact created successfully: {len(q4_schools)} schools written.")

if __name__ == "__main__":
    main()
