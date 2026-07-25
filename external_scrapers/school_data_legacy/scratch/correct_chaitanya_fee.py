import json
import csv

def main():
    json_paths = ["data/school_averages_summary_bangalore.json", "data/school_averages_summary.json"]
    
    for path in json_paths:
        with open(path, "r", encoding="utf-8") as f:
            schools = json.load(f)
            
        updated = False
        for s in schools:
            if s.get("URL") == "https://ezyschooling.com/school/sri-chaitanya-techno-school-hoodi-bangalore-bengaluru":
                print(f"Updating fee for {s['School Name']} from {s['Average Fee (Annual)']} to 84000.0")
                s["Average Fee (Annual)"] = 84000.0
                updated = True
                
        if updated:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(schools, f, indent=2)
                
    # Also regenerate the CSVs
    csv_paths = ["data/school_averages_summary_bangalore.csv", "data/school_averages_summary.csv"]
    fieldnames = [
        'School Name', 'Board', 'URL', 'Student-Teacher Ratio', 
        'Teacher Count', 'Computed Student Count', 'Is Student Count Estimated', 
        'Average Fee (Annual)', 'Is Fee Estimated', 'Starting Class', 'Ending Class', 'Address', 'Pincode', 'Latitude', 'Longitude'
    ]
    
    for csv_path, json_path in zip(csv_paths, json_paths):
        with open(json_path, "r", encoding="utf-8") as jf:
            schools = json.load(jf)
            
        with open(csv_path, "w", newline="", encoding="utf-8") as cf:
            writer = csv.DictWriter(cf, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(schools)
            
    print("CSV files updated successfully.")

if __name__ == "__main__":
    main()
