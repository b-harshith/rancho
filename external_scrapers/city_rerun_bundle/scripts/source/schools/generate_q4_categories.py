import json
import os
from pathlib import Path

import numpy as np

def get_class_rank(name):
    n = name.lower().strip()
    if "play" in n or "nursery" in n or "pre-nursery" in n or "toddler" in n:
        return 0
    if "lkg" in n or "l.k.g" in n or "lower" in n:
        return 1
    if "ukg" in n or "u.k.g" in n or "upper" in n:
        return 2
    if "kg" in n or "kindergarten" in n:
        return 1.5
    if "1" in n or "first" in n or "one" in n:
        if "10" in n or "ten" in n: return 12
        if "11" in n or "eleven" in n: return 13
        if "12" in n or "twelve" in n: return 14
        return 3
    if "2" in n or "second" in n or "two" in n:
        if "12" in n or "twelve" in n: return 14
        return 4
    if "3" in n or "third" in n or "three" in n:
        return 5
    if "4" in n or "fourth" in n or "four" in n:
        return 6
    if "5" in n or "fifth" in n or "five" in n:
        return 7
    if "6" in n or "sixth" in n or "six" in n:
        return 8
    if "7" in n or "seventh" in n or "seven" in n:
        return 9
    if "8" in n or "eighth" in n or "eight" in n:
        return 10
    if "9" in n or "ninth" in n or "nine" in n:
        return 11
    if "10" in n or "tenth" in n or "ten" in n:
        return 12
    if "11" in n or "eleventh" in n or "eleven" in n:
        return 13
    if "12" in n or "twelfth" in n or "twelve" in n:
        return 14
    return None

def main():
    city_slug = os.environ.get("CITY_SLUG", "bangalore").strip().lower().replace(" ", "-")
    city_name = os.environ.get("CITY_NAME", city_slug.replace("-", " ").title())
    json_path = f"data/school_averages_summary_{city_slug}.json"
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
        
    q3_global = np.percentile(fees, 75)
    
    q4_schools = [s for s in valid_schools if float(s["Average Fee (Annual)"]) >= q3_global]
    q4_schools.sort(key=lambda x: float(x["Average Fee (Annual)"]), reverse=True)
    
    # Categorize:
    categorized = []
    for s in q4_schools:
        fee = float(s["Average Fee (Annual)"])
        if fee >= 165000.0:
            cat = "Ultra Premium"
        elif fee >= 114996.0:
            cat = "Super Premium"
        elif fee > 84996.0:
            cat = "Premium"
        else:
            cat = "Mid-Premium"
            
        s["Q4 Category"] = cat
        categorized.append(s)
        
    artifact_path = Path("reports") / f"{city_slug}_q4_categorized_schools.md"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Calculate counts and students
    counts = {"Ultra Premium": 0, "Super Premium": 0, "Premium": 0, "Mid-Premium": 0}
    students = {"Ultra Premium": 0, "Super Premium": 0, "Premium": 0, "Mid-Premium": 0}
    students_2_9 = {"Ultra Premium": 0, "Super Premium": 0, "Premium": 0, "Mid-Premium": 0}
    
    for s in categorized:
        cat = s["Q4 Category"]
        counts[cat] += 1
        total = float(s.get("Computed Student Count") or 0)
        students[cat] += total
        
        start_name = s.get("Starting Class", "NA")
        end_name = s.get("Ending Class", "NA")
        
        r_start = get_class_rank(start_name)
        r_end = get_class_rank(end_name)
        
        if r_start is not None and r_end is not None:
            r_start_int = int(round(r_start))
            r_end_int = int(round(r_end))
            
            if r_start_int <= r_end_int:
                total_classes = r_end_int - r_start_int + 1
                classes_in_2_9 = 0
                for r in range(r_start_int, r_end_int + 1):
                    if 4 <= r <= 11:
                        classes_in_2_9 += 1
                
                pct = classes_in_2_9 / total_classes
                students_2_9[cat] += total * pct
            else:
                students_2_9[cat] += total * (8/12)
        else:
            students_2_9[cat] += total * (8/12)
        
    with open(artifact_path, "w", encoding="utf-8") as out:
        out.write(f"# Categorized Q4 Schools ({city_name})\n\n")
        out.write(f"This document breaks down the **{len(q4_schools)}** Q4 schools into four sub-quartiles with corresponding premium labels:\n\n")
        out.write(f"1. **Ultra Premium** (>= 75th %ile of Q4: >= INR 165,000.00 annual fee)\n")
        out.write(f"2. **Super Premium** (50th - 75th %ile of Q4: INR 114,996.00 to 165,000.00 annual fee)\n")
        out.write(f"3. **Premium** (25th - 50th %ile of Q4: INR 84,996.01 to 114,995.99 annual fee)\n")
        out.write(f"4. **Mid-Premium** (Bottom tier of Q4: exactly INR 84,996.00 annual fee)\n\n")
        
        out.write("## Distribution Summary\n\n")
        out.write("| Category | Fee Range (Annual) | Count of Schools | Total Count of Students | Count of Students (2nd-9th Std) |\n")
        out.write("|---|---|---|---|---|\n")
        out.write(f"| **Ultra Premium** | >= INR 165,000.00 | {counts['Ultra Premium']} | {int(students['Ultra Premium']):,} | {int(students_2_9['Ultra Premium']):,} |\n")
        out.write(f"| **Super Premium** | INR 114,996.00 - 165,000.00 | {counts['Super Premium']} | {int(students['Super Premium']):,} | {int(students_2_9['Super Premium']):,} |\n")
        out.write(f"| **Premium** | INR 84,996.01 - 114,995.99 | {counts['Premium']} | {int(students['Premium']):,} | {int(students_2_9['Premium']):,} |\n")
        out.write(f"| **Mid-Premium** | INR 84,996.00 | {counts['Mid-Premium']} | {int(students['Mid-Premium']):,} | {int(students_2_9['Mid-Premium']):,} |\n\n")
        
        out.write("## Full Categorized School List\n\n")
        out.write("| # | School Name | Board | Maximum Annual Fee | Category | Total Student Count | Est. 2nd-9th Student Count | Starting Class | Ending Class | Latitude | Longitude | Address |\n")
        out.write("|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        for idx, s in enumerate(categorized):
            fee_val = float(s["Average Fee (Annual)"])
            stud_val = int(float(s.get("Computed Student Count") or 0))
            
            start_name = s.get("Starting Class", "NA")
            end_name = s.get("Ending Class", "NA")
            r_start = get_class_rank(start_name)
            r_end = get_class_rank(end_name)
            if r_start is not None and r_end is not None:
                r_start_int = int(round(r_start))
                r_end_int = int(round(r_end))
                if r_start_int <= r_end_int:
                    total_classes = r_end_int - r_start_int + 1
                    classes_in_2_9 = sum(1 for r in range(r_start_int, r_end_int + 1) if 4 <= r <= 11)
                    stud_val_2_9 = int(stud_val * (classes_in_2_9 / total_classes))
                else:
                    stud_val_2_9 = int(stud_val * (8/12))
            else:
                stud_val_2_9 = int(stud_val * (8/12))
                
            out.write(f"| {idx+1} | {s['School Name']} | {s['Board']} | INR {fee_val:,.2f} | **{s['Q4 Category']}** | {stud_val:,} | {stud_val_2_9:,} | {s.get('Starting Class', 'NA')} | {s.get('Ending Class', 'NA')} | {s.get('Latitude', 'NA')} | {s.get('Longitude', 'NA')} | {s.get('Address', 'NA')} |\n")
            
    # Save as JSON document
    json_output_path = f"data/q4_categorized_schools_{city_slug}.json"
    json_data = []
    for s in categorized:
        fee_val = float(s["Average Fee (Annual)"])
        stud_val = int(float(s.get("Computed Student Count") or 0))
        start_name = s.get("Starting Class", "NA")
        end_name = s.get("Ending Class", "NA")
        
        r_start = get_class_rank(start_name)
        r_end = get_class_rank(end_name)
        if r_start is not None and r_end is not None:
            r_start_int = int(round(r_start))
            r_end_int = int(round(r_end))
            if r_start_int <= r_end_int:
                total_classes = r_end_int - r_start_int + 1
                classes_in_2_9 = sum(1 for r in range(r_start_int, r_end_int + 1) if 4 <= r <= 11)
                stud_val_2_9 = int(stud_val * (classes_in_2_9 / total_classes))
            else:
                stud_val_2_9 = int(stud_val * (8/12))
        else:
            stud_val_2_9 = int(stud_val * (8/12))
            
        json_data.append({
            "School Name": s["School Name"],
            "Board": s["Board"],
            "URL": s["URL"],
            "Student-Teacher Ratio": s.get("Student-Teacher Ratio", "NA"),
            "Teacher Count": s.get("Teacher Count", "NA"),
            "Computed Student Count": stud_val,
            "Est. 2nd-9th Student Count": stud_val_2_9,
            "Average Fee (Annual)": fee_val,
            "Q4 Category": s["Q4 Category"],
            "Starting Class": start_name,
            "Ending Class": end_name,
            "Latitude": s.get("Latitude", "NA"),
            "Longitude": s.get("Longitude", "NA"),
            "Address": s.get("Address", "NA"),
            "Pincode": s.get("Pincode", "NA")
        })
        
    with open(json_output_path, "w", encoding="utf-8") as jf:
        json.dump(json_data, jf, indent=2)
        
    print(f"Artifact updated: {len(categorized)} categorized schools written to markdown and JSON.")

if __name__ == "__main__":
    main()
