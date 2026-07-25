import json
import numpy as np

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
    print(f"75th Percentile (Q3 Threshold): INR {q3:,.2f}")
    
    q4_schools = [s for s in valid_schools if float(s["Average Fee (Annual)"]) >= q3]
    # Sort descending by fee
    q4_schools.sort(key=lambda x: float(x["Average Fee (Annual)"]), reverse=True)
    
    print(f"Total Q4 schools found: {len(q4_schools)}")
    
    print("\n| # | School Name | Board | Maximum Annual Fee | Starting Class | Ending Class | Address |")
    print("|---|---|---|---|---|---|---|")
    for idx, s in enumerate(q4_schools):
        fee_val = float(s["Average Fee (Annual)"])
        print(f"| {idx+1} | {s['School Name']} | {s['Board']} | INR {fee_val:,.2f} | {s.get('Starting Class', 'NA')} | {s.get('Ending Class', 'NA')} | {s.get('Address', 'NA')} |")

if __name__ == "__main__":
    main()
