import sqlite3
import pandas as pd
import json
from pathlib import Path

def main():
    print("Starting K12 School Report Generator...")
    
    # Paths
    project_root = Path(__file__).resolve().parent.parent
    db_path = project_root / "pipeline.db"
    csv_path = project_root / "data" / "cache" / "local_seed_cache.csv"
    extracted_text_dir = project_root / "data" / "extracted_text"
    output_dir = project_root / "data" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_csv_path = output_dir / "unique_schools_details.csv"
    
    # 1. Load schools from local_seed_cache.csv
    csv_schools = {}
    if csv_path.exists():
        try:
            df_csv = pd.read_csv(csv_path)
            print(f"Loaded {len(df_csv)} schools from cache CSV: {csv_path}")
            for _, row in df_csv.iterrows():
                school_id = str(row["School_ID"]).strip()
                csv_schools[school_id] = {
                    "code": school_id,
                    "name": str(row["Name"]).strip(),
                    "board": str(row["Board"]).strip(),
                    "locality": str(row.get("Locality", "")).strip() if pd.notna(row.get("Locality")) else "",
                    "pincode": str(row.get("Pincode", "")).strip() if pd.notna(row.get("Pincode")) else "",
                    "website": str(row.get("Website_URL", "")).strip() if pd.notna(row.get("Website_URL")) else "",
                    "raw_text": ""
                }
        except Exception as e:
            print(f"Error reading CSV cache: {e}")
    else:
        print(f"CSV Cache file not found at {csv_path}")

    # 2. Load schools from SQLite pipeline.db
    db_schools = {}
    if db_path.exists():
        try:
            conn = sqliteConn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM schools")
            rows = cursor.fetchall()
            print(f"Loaded {len(rows)} schools from SQLite database: {db_path}")
            
            for row in rows:
                school_id = str(row["school_id"]).strip()
                # Format postcode nicely
                pincode_val = str(row["pincode"]).strip() if row["pincode"] is not None else ""
                if pincode_val == "nan" or pincode_val == "None":
                    pincode_val = ""
                    
                db_schools[school_id] = {
                    "code": school_id,
                    "name": str(row["name"]).strip(),
                    "board": str(row["board"]).strip(),
                    "locality": str(row["locality"]).strip() if row["locality"] is not None else "",
                    "pincode": pincode_val,
                    "website": str(row["website_url"]).strip() if row["website_url"] is not None else "",
                    "raw_text": str(row["extracted_text_payload"]).strip() if row["extracted_text_payload"] is not None else "",
                    "status": str(row["status"]).strip() if row["status"] is not None else ""
                }
            conn.close()
        except Exception as e:
            print(f"Error reading SQLite database: {e}")
    else:
        print(f"SQLite DB not found at {db_path}")

    # 3. Merge schools by school_id (code) to ensure uniqueness
    all_school_ids = set(csv_schools.keys()).union(set(db_schools.keys()))
    print(f"Total unique school IDs discovered: {len(all_school_ids)}")
    
    unique_schools = []
    
    # 4. Process each school and read raw text files if database raw_text is empty
    text_files_found = 0
    text_db_found = 0
    
    for school_id in sorted(all_school_ids):
        # Prefer DB data for status/raw_text, but fall back to CSV if not in DB
        if school_id in db_schools:
            school_data = db_schools[school_id]
        else:
            school_data = csv_schools[school_id]
            school_data["status"] = "SEED_ONLY"
            
        # Ensure name, board, website, locality, pincode are populated if available in CSV but not DB
        if school_id in csv_schools:
            csv_data = csv_schools[school_id]
            if not school_data["name"] and csv_data["name"]:
                school_data["name"] = csv_data["name"]
            if not school_data["board"] and csv_data["board"]:
                school_data["board"] = csv_data["board"]
            if not school_data["website"] and csv_data["website"]:
                school_data["website"] = csv_data["website"]
            if not school_data["locality"] and csv_data["locality"]:
                school_data["locality"] = csv_data["locality"]
            if not school_data["pincode"] and csv_data["pincode"]:
                school_data["pincode"] = csv_data["pincode"]
                
        # Check raw text
        raw_text = school_data.get("raw_text", "")
        if raw_text:
            text_db_found += 1
        else:
            # Try reading from disk
            txt_path = extracted_text_dir / f"{school_id}.txt"
            if txt_path.exists():
                try:
                    raw_text = txt_path.read_text(encoding="utf-8").strip()
                    text_files_found += 1
                except Exception as e:
                    print(f"Error reading raw text file {txt_path}: {e}")
        
        # Build address
        locality = school_data["locality"]
        pincode = school_data["pincode"]
        
        # Format address nicely
        address_parts = []
        if locality:
            address_parts.append(locality)
        if pincode:
            address_parts.append(pincode)
            
        address = ", ".join(address_parts)
        if not address:
            address = "Address not available"
            
        geocode_query = (
            f"{school_data['name']} "
            f"{locality} "
            f"{pincode} "
            f"Bangalore"
        ).strip()
        # Clean extra spaces
        geocode_query = " ".join(geocode_query.split())

        unique_schools.append({
            "School_Code": school_data["code"],
            "Name": school_data["name"],
            "Board": school_data["board"],
            "Address": address,
            "Pincode": pincode,
            "Geocode_Query": geocode_query,
            "Website": school_data["website"],
            "Raw_Text": raw_text,
            "Pipeline_Status": school_data["status"]
        })
        
    print(f"Raw text found in DB: {text_db_found}")
    print(f"Raw text found on disk: {text_files_found}")
    
    # 5. Save unique schools to CSV
    df_out = pd.DataFrame(unique_schools)
    df_csv = df_out.drop(columns=["Raw_Text"])
    df_csv.to_csv(output_csv_path, index=False)
    print(f"Successfully wrote unified unique schools report to: {output_csv_path}")
    print(f"Report dimensions: {df_csv.shape[0]} rows, {df_csv.shape[1]} columns.")
    
    # 6. Compute statistics
    total_unique = len(df_out)
    
    board_counts = df_out["Board"].value_counts().to_dict()
    
    # How many have raw text
    has_text_mask = df_out["Raw_Text"].str.strip().astype(bool)
    schools_with_text = df_out[has_text_mask]
    total_with_text = len(schools_with_text)
    
    text_board_counts = schools_with_text["Board"].value_counts().to_dict()
    
    # Pipeline status counts
    status_counts = df_out["Pipeline_Status"].value_counts().to_dict()
    
    # Print stats in clean structured JSON to standard output so the outer process can read it
    stats = {
        "total_unique_schools": total_unique,
        "board_breakdown": board_counts,
        "schools_with_raw_text": {
            "total": total_with_text,
            "board_breakdown": text_board_counts,
            "percentage": f"{(total_with_text / total_unique) * 100:.2f}%" if total_unique > 0 else "0%"
        },
        "pipeline_status_breakdown": status_counts
    }
    
    print("\n--- STATISTICS ---")
    print(json.dumps(stats, indent=2))
    
if __name__ == "__main__":
    main()
