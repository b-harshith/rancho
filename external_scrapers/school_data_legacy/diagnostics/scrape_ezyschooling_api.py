#!/usr/bin/env python3
import os
import json
import csv
import re
import time
import random
import argparse
from statistics import mean
import numpy as np

try:
    from curl_cffi import requests
except ImportError:
    requests = None

def normalize_name(name):
    if not name:
        return ""
    name = name.lower()
    name = re.sub(r'[^a-z0-9\s]', ' ', name)
    stop_words = {'school', 'public', 'private', 'the', 'of', 'and', 'for', 'in', 'high', 'primary', 'secondary', 'composite', 'co', 'education', 'junior', 'college', 'international', 'academy'}
    words = [w for w in name.split() if w not in stop_words]
    return " ".join(words)

def clean_float(val):
    if val is None or val == "NA":
        return None
    try:
        return float(val)
    except ValueError:
        return None

def parse_ezyschooling_fee(school):
    avg_fees_obj = school.get("avg_fees", {})
    if not avg_fees_obj:
        return "NA"
        
    # Try 2026-2027 session first, then fallback to 2025-2026
    session_data = avg_fees_obj.get("2026-2027") or avg_fees_obj.get("2025-2026")
    
    if session_data:
        # 1. Parse class-wise fees
        class_wise = session_data.get("class_wise", {})
        if class_wise:
            class_yearly_fees = []
            for class_id, class_info in class_wise.items():
                fees_numbers = class_info.get("fees_numbers")
                tenure = class_info.get("tenure", "monthly")
                if fees_numbers:
                    try:
                        val = float(fees_numbers)
                        if tenure.lower() == "monthly":
                            val *= 12
                        elif tenure.lower() == "quarterly":
                            val *= 4
                        class_yearly_fees.append(val)
                    except ValueError:
                        pass
            if class_yearly_fees:
                return round(mean(class_yearly_fees), 2)
                
        # 2. Parse range average
        range_info = session_data.get("range", {})
        if range_info:
            lowest = range_info.get("lowest_fee")
            highest = range_info.get("highest_fee")
            tenure = range_info.get("tenure", "monthly")
            if lowest is not None and highest is not None:
                try:
                    avg_val = (float(lowest) + float(highest)) / 2.0
                    if tenure.lower() == "monthly":
                        avg_val *= 12
                    elif tenure.lower() == "quarterly":
                        avg_val *= 4
                    return round(avg_val, 2)
                except ValueError:
                    pass
                    
    # 3. Fallback to top-level avg_fee
    avg_fee = avg_fees_obj.get("avg_fee")
    if avg_fee:
        try:
            val = float(avg_fee)
            tenure = "monthly"
            if session_data and session_data.get("range"):
                tenure = session_data["range"].get("tenure", "monthly")
            if tenure.lower() == "monthly":
                val *= 12
            elif tenure.lower() == "quarterly":
                val *= 4
            return round(val, 2)
        except ValueError:
            pass
            
    return "NA"

def parse_classes(offered_classes):
    if not offered_classes or offered_classes.strip() == "":
        return "NA", "NA"
    parts = offered_classes.split(' - ')
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    elif len(parts) == 1:
        return parts[0].strip(), parts[0].strip()
    return "NA", "NA"

def normalize_board(board_list):
    if not board_list:
        return "Unknown"
    boards = []
    for b in board_list:
        name = b.get("name", "").strip()
        # Clean board names
        if "CBSE" in name.upper():
            boards.append("CBSE")
        elif "ICSE" in name.upper() or "CISCE" in name.upper():
            boards.append("ICSE")
        elif "IB" in name.upper():
            boards.append("IB")
        elif "IGCSE" in name.upper():
            boards.append("IGCSE")
        elif "STATE" in name.upper():
            boards.append("State board")
        elif "NO BOARD" in name.upper():
            boards.append("No Board")
        else:
            boards.append(name)
            
    # Deduplicate and sort
    boards = sorted(list(set(boards)))
    return ", ".join(boards) if boards else "Unknown"

def main():
    parser = argparse.ArgumentParser(description="Scrape Ezyschooling API and merge into dataset.")
    parser.add_argument("--city", type=str, default="bangalore", help="City name (default: bangalore)")
    parser.add_argument("--force-download", action="store_true", help="Force API download even if raw JSON exists")
    args = parser.parse_args()
    
    city_slug = args.city.lower().strip().replace(' ', '-')
    city_clean = args.city.strip().capitalize()
    
    raw_json_path = f"data/ezyschooling_raw_{city_slug}.json"
    summary_json_path = f"school_averages_summary_{city_slug}.json"
    summary_csv_path = f"school_averages_summary_{city_slug}.csv"
    
    # Check if generic filenames should be used as fallback
    if not os.path.exists(summary_json_path):
        summary_json_path = "school_averages_summary.json"
        summary_csv_path = "school_averages_summary.csv"
        
    if not os.path.exists(summary_json_path):
        print(f"Error: Target summary file not found at {summary_json_path}. Run pipeline process first.")
        return
        
    raw_schools = []
    
    # 1. Scraping Phase: Fetch all schools from API or load from cache
    if os.path.exists(raw_json_path) and not args.force_download:
        print(f"Loading cached Ezyschooling raw data from {raw_json_path}...")
        with open(raw_json_path, 'r', encoding='utf-8') as f:
            raw_schools = json.load(f)
        print(f"Loaded {len(raw_schools)} schools from cache.")
    else:
        if requests is None:
            print("Error: curl_cffi module not found. Cannot perform live API scraping. Please install it first.")
            return
            
        print(f"Scraping Ezyschooling API for {city_clean}...")
        url = "https://api.main.ezyschooling.com/api/v1/schools/document/"
        limit = 100
        offset = 0
        total_count = 1  # Will be updated on first request
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://ezyschooling.com",
            "Referer": "https://ezyschooling.com/"
        }
        
        while offset < total_count:
            exclude_cities = "boarding-schools,online-schools"
            if city_slug != "delhi":
                exclude_cities += ",delhi"
            params = {
                "is_active": "true",
                "is_verified": "true",
                "limit": str(limit),
                "offset": str(offset),
                "ordering": "-fees",
                "school_city": city_slug,
                "school_city__exclude": exclude_cities,
                "session": "2026-2027"
            }
            
            print(f"Fetching offset {offset} (Total count resolved: {total_count})...")
            try:
                r = requests.get(url, params=params, headers=headers, impersonate="chrome", timeout=20)
                if r.status_code == 200:
                    data = r.json()
                    total_count = data.get("count", total_count)
                    results = data.get("results", [])
                    raw_schools.extend(results)
                    print(f" -> Fetched {len(results)} schools. Total in list: {len(raw_schools)}.")
                    
                    if not results:
                        break
                else:
                    print(f" [Error] API returned status {r.status_code}. Aborting API loop.")
                    break
            except Exception as e:
                print(f" [Error] Request failed at offset {offset}: {e}")
                break
                
            offset += limit
            time.sleep(random.uniform(1.5, 3.0)) # polite delay
            
        # Save raw scrape data
        if raw_schools:
            os.makedirs("data", exist_ok=True)
            with open(raw_json_path, 'w', encoding='utf-8') as f:
                json.dump(raw_schools, f, indent=2)
            print(f"Saved raw data to {raw_json_path}.")
            
    if not raw_schools:
        print("No school data available from Ezyschooling. Aborting merge.")
        return
        
    # 2. Merge Phase: Merge Ezyschooling data into existing summary
    print(f"\nLoading existing school summary from {summary_json_path}...")
    with open(summary_json_path, 'r', encoding='utf-8') as f:
        summary_data = json.load(f)
        
    print(f"Initial summary has {len(summary_data)} schools.")
    
    # Pre-process existing summary for fast matching
    summary_mapped = []
    for idx, s in enumerate(summary_data):
        lat = clean_float(s.get("Latitude"))
        lon = clean_float(s.get("Longitude"))
        name = s.get("School Name", "")
        summary_mapped.append({
            'idx': idx,
            'name': name,
            'norm_name': normalize_name(name),
            'lat': lat,
            'lon': lon,
            'url': s.get("URL", ""),
            'raw': s
        })
        
    # Stats for city-wide fallbacks (recalculated from current summary)
    ratios = []
    teachers_counts = []
    for s in summary_data:
        # Parse ratio
        rat = s.get("Student-Teacher Ratio")
        if rat and rat != "NA":
            try:
                ratios.append(float(rat.split(':')[0]))
            except Exception:
                pass
        # Parse teachers
        tc = s.get("Teacher Count")
        if tc and tc != "NA":
            try:
                teachers_counts.append(float(tc))
            except Exception:
                pass
                
    fallback_ratio = mean(ratios) if ratios else 22.97
    fallback_teachers = mean(teachers_counts) if teachers_counts else 28.98
    fallback_student_count = round(fallback_ratio * fallback_teachers, 1)
    
    matched_count = 0
    new_schools_added = 0
    
    # Process each Ezyschooling school and match/merge
    for idx, es in enumerate(raw_schools):
        es_name = es.get("name", "")
        es_norm = normalize_name(es_name)
        
        es_coords = es.get("geocoords", {})
        es_lat = clean_float(es_coords.get("lat"))
        es_lon = clean_float(es_coords.get("lon"))
        
        es_zip = es.get("zipcode")
        es_addr = es.get("street_address", "")
        
        # Calculate yearly fee
        es_fee = parse_ezyschooling_fee(es)
        
        # Parse classes
        es_classes_str = es.get("offered_classes", "")
        es_start, es_end = parse_classes(es_classes_str)
        
        # Board
        es_board = normalize_board(es.get("school_boardss", []))
        
        # Student-Teacher Ratio
        es_ratio_str = es.get("student_teacher_ratio", "NA")
        es_ratio = "NA"
        if es_ratio_str and es_ratio_str != "NA" and ":" in es_ratio_str:
            es_ratio = es_ratio_str
            
        # Match search
        match_idx = None
        
        # 1. Match by normalized name
        for sm in summary_mapped:
            if es_norm == sm['norm_name'] and es_norm != "":
                match_idx = sm['idx']
                break
                
        # 2. Match by coordinates and keywords
        if match_idx is None and es_lat is not None and es_lon is not None:
            for sm in summary_mapped:
                if sm['lat'] is not None and sm['lon'] is not None:
                    dist_sq = (es_lat - sm['lat'])**2 + (es_lon - sm['lon'])**2
                    if dist_sq < 0.00000025: # 50 meters
                        # Verify keyword overlap
                        es_words = set(es_norm.split())
                        sm_words = set(sm['norm_name'].split())
                        if es_words.intersection(sm_words) or dist_sq < 1e-10:
                            match_idx = sm['idx']
                            break
                            
        # Merge action
        if match_idx is not None:
            matched_school = summary_data[match_idx]
            
            # Enrich fields if missing
            if (matched_school.get("Average Fee (Annual)") == "NA" or matched_school.get("Average Fee (Annual)") is None) and es_fee != "NA":
                matched_school["Average Fee (Annual)"] = es_fee
                
            if matched_school.get("Address") == "NA" or matched_school.get("Address") == "":
                matched_school["Address"] = es_addr
                
            if matched_school.get("Pincode") == "NA" or matched_school.get("Pincode") == "":
                if es_zip:
                    matched_school["Pincode"] = es_zip
                    
            if matched_school.get("Latitude") == "NA" or matched_school.get("Latitude") is None:
                if es_lat:
                    matched_school["Latitude"] = es_lat
                    
            if matched_school.get("Longitude") == "NA" or matched_school.get("Longitude") is None:
                if es_lon:
                    matched_school["Longitude"] = es_lon
                    
            if matched_school.get("Starting Class") == "NA" or matched_school.get("Starting Class") == "":
                matched_school["Starting Class"] = es_start
                
            if matched_school.get("Ending Class") == "NA" or matched_school.get("Ending Class") == "":
                matched_school["Ending Class"] = es_end
                
            if matched_school.get("Student-Teacher Ratio") == "NA" and es_ratio != "NA":
                matched_school["Student-Teacher Ratio"] = es_ratio
                
            matched_count += 1
        else:
            # Create a brand new school record
            new_school = {
                "School Name": es_name,
                "Board": es_board,
                "URL": f"https://ezyschooling.com/school/{es.get('slug')}",
                "Student-Teacher Ratio": es_ratio,
                "Teacher Count": "NA",
                "Computed Student Count": fallback_student_count,
                "Is Student Count Estimated": "Yes",
                "Average Fee (Annual)": es_fee,
                "Starting Class": es_start,
                "Ending Class": es_end,
                "Address": es_addr if es_addr else "NA",
                "Pincode": es_zip if es_zip else "NA",
                "Latitude": es_lat if es_lat else "NA",
                "Longitude": es_lon if es_lon else "NA"
            }
            summary_data.append(new_school)
            new_schools_added += 1
            
    print(f"\nMerge completed:")
    print(f" - Matched and Enriched existing schools: {matched_count}")
    print(f" - Added brand-new unique schools: {new_schools_added}")
    print(f" - Final dataset size: {len(summary_data)} schools")
    
    # Save back to files
    print(f"\nSaving updated summaries to {summary_json_path}...")
    with open(summary_json_path, 'w', encoding='utf-8') as f:
        json.dump(summary_data, f, indent=2)
    with open("school_averages_summary.json", 'w', encoding='utf-8') as f:
        json.dump(summary_data, f, indent=2)
        
    fieldnames = [
        'School Name', 'Board', 'URL', 'Student-Teacher Ratio', 
        'Teacher Count', 'Computed Student Count', 'Is Student Count Estimated', 
        'Average Fee (Annual)', 'Starting Class', 'Ending Class', 'Address', 'Pincode', 'Latitude', 'Longitude'
    ]
    with open(summary_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_data)
    with open("school_averages_summary.csv", 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_data)
        
    print("CSV summary successfully saved.")

if __name__ == "__main__":
    main()
