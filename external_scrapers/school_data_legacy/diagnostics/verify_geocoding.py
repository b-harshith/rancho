#!/usr/bin/env python3
import json
import csv
import os
import re
import argparse

def main():
    parser = argparse.ArgumentParser(description="Verify school averages summary geocoding and data integrity.")
    parser.add_argument("--city", type=str, default="bangalore", help="Name of the city (e.g. bangalore, delhi)")
    args = parser.parse_args()
    
    city_slug = args.city.lower().strip().replace(' ', '-')
    
    json_path = f"data/school_averages_summary_{city_slug}.json"
    csv_path = f"data/school_averages_summary_{city_slug}.csv"
    
    if not os.path.exists(json_path):
        # Fallback to generic names if city specific don't exist
        json_path = "data/school_averages_summary.json"
        csv_path = "data/school_averages_summary.csv"
        
    if not os.path.exists(json_path):
        print(f"Error: JSON summary not found at {json_path}")
        return
        
    if not os.path.exists(csv_path):
        print(f"Error: CSV summary not found at {csv_path}")
        return
        
    print(f"Verifying files for city '{args.city}'...")
    print(f" - JSON Path: {json_path}")
    print(f" - CSV Path: {csv_path}")
    
    print("Loading JSON summary data...")
    with open(json_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
        
    print("Loading CSV summary data...")
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        csv_data = list(reader)
        
    print(f"JSON rows: {len(json_data)}")
    print(f"CSV rows: {len(csv_data)}")
    
    # 1. Assert row counts match
    assert len(json_data) == len(csv_data), f"Row count mismatch! JSON: {len(json_data)}, CSV: {len(csv_data)}"
    print("✓ Row counts match.")
    
    # 2. Assert all fields are present
    required_fields = [
        'School Name', 'Board', 'URL', 'Student-Teacher Ratio', 
        'Teacher Count', 'Computed Student Count', 'Is Student Count Estimated', 
        'Average Fee (Annual)', 'Is Fee Estimated', 'Starting Class', 'Ending Class', 'Address', 'Pincode', 'Latitude', 'Longitude'
    ]
    
    missing_fields_json = 0
    missing_fields_csv = 0
    missing_address = 0
    missing_pincode = 0
    missing_coords = 0
    
    for idx, row in enumerate(json_data):
        # Check keys
        for field in required_fields:
            if field not in row:
                missing_fields_json += 1
                
        # Count NA or empty fields
        addr = row.get("Address")
        pin = row.get("Pincode")
        lat = row.get("Latitude")
        lon = row.get("Longitude")
        
        if not addr or addr == "NA" or addr == "None":
            missing_address += 1
        if not pin or pin == "NA" or pin == "None":
            missing_pincode += 1
        if lat == "NA" or lon == "NA" or lat is None or lon is None:
            missing_coords += 1
            
    for row in csv_data:
        for field in required_fields:
            if field not in row:
                missing_fields_csv += 1
                
    assert missing_fields_json == 0, f"JSON rows have missing fields: {missing_fields_json}"
    assert missing_fields_csv == 0, f"CSV rows have missing fields: {missing_fields_csv}"
    print("✓ All required fields are present in both JSON and CSV files.")
    
    # 3. Print geocoding stats
    print(f"\nStats:")
    print(f" - Schools with missing Address: {missing_address} / {len(json_data)}")
    print(f" - Schools with missing Pincode: {missing_pincode} / {len(json_data)}")
    print(f" - Schools with missing Lat/Lon: {missing_coords} / {len(json_data)}")
    
    # 4. Verify manual fee overrides are intact (only for Bangalore)
    if city_slug == "bangalore":
        test_fees = {
            "BNM Primary And High School": 140000.0,
            "Arrow Kids Public School": 35000.0,
            "Orchids The International School Mahalakshmi Layout, Bangalore": 134583.33
        }
        
        print("\nVerifying manual fee overrides:")
        overrides_ok = True
        for school_name, expected_fee in test_fees.items():
            found = False
            for row in json_data:
                if row.get("School Name") == school_name:
                    found = True
                    fee = row.get("Average Fee (Annual)")
                    try:
                        fee_val = float(fee) if fee != "NA" else None
                    except Exception:
                        fee_val = None
                    
                    if fee_val == expected_fee:
                        print(f" - {school_name}: Fee is {fee_val} (Matches expected {expected_fee}) ✓")
                    else:
                        print(f" - {school_name}: Fee is {fee_val} (MISMATCH! Expected {expected_fee}) ✗")
                        overrides_ok = False
            if not found:
                print(f" - {school_name}: Not found in dataset! ✗")
                overrides_ok = False
                
        if overrides_ok:
            print("✓ All manual fee overrides verified successfully.")
        else:
            print("✗ Verification failed for manual fee overrides.")
            
    print("\nVerification process complete!")

if __name__ == "__main__":
    main()
