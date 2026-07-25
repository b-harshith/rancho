import json
import os

input_file = "data/output/schools_analysis_delhi_ncr.json"
output_file = "data/output/schools_analysis_delhi_ncr_compact.json"

if not os.path.exists(input_file):
    print(f"Error: {input_file} does not exist.")
    exit(1)

with open(input_file, "r", encoding="utf-8") as f:
    data = json.load(f)

print(f"Compacting {len(data.get('schools', []))} schools...")

for school in data.get("schools", []):
    # 1. Remove data_quality
    if "data_quality" in school:
        del school["data_quality"]
    
    # 2. Flatten academic_year
    ay = school.get("academic_year")
    if isinstance(ay, dict):
        school["academic_year"] = ay.get("description", "2024-25")
        
    meta = school.get("metadata", {})
    if not meta:
        continue
        
    # 3. Remove status and searched_pincode
    if "status" in meta:
        del meta["status"]
    if "searched_pincode" in meta:
        del meta["searched_pincode"]
        
    # Move reported_pincode to pincode
    if "reported_pincode" in meta:
        meta["pincode"] = meta.pop("reported_pincode")
        
    # 4. Clean contact
    if "contact" in meta:
        contact = meta["contact"]
        keys_to_remove = [k for k, v in contact.items() if v is None or str(v).strip().upper() == "NA"]
        for k in keys_to_remove:
            del contact[k]
        if not contact:
            del meta["contact"]
            
    # 5. Clean address and location
    if "location" in meta:
        loc = meta["location"]
        if "coordinate_source" in loc:
            del loc["coordinate_source"]
        
        # Round coordinates and rename to lat/lng
        if "latitude" in loc and loc["latitude"] is not None:
            loc["lat"] = round(float(loc["latitude"]), 5)
            del loc["latitude"]
        if "longitude" in loc and loc["longitude"] is not None:
            loc["lng"] = round(float(loc["longitude"]), 5)
            del loc["longitude"]
            
        # Rename village_or_ward to village
        if "village_or_ward" in loc:
            loc["village"] = loc.pop("village_or_ward")
            
        if "distance_from_center_km" in loc:
            del loc["distance_from_center_km"]
            
    # 6. Clean Enrollment
    enroll = school.get("enrollment", {})
    if enroll:
        total = enroll.get("total_students", 0)
        boys = enroll.get("boys", 0)
        girls = enroll.get("girls", 0)
        
        g2_9_total = 0
        g2_9_boys = 0
        g2_9_girls = 0
        
        for c in enroll.get("by_class", []):
            try:
                # Class levels in Delhi can be integers or strings like '1', '2'
                lvl = c.get("class_level")
                if lvl:
                    level = int(lvl)
                    if 2 <= level <= 9:
                        g2_9_total += c.get("total", 0)
                        g2_9_boys += c.get("boys", 0)
                        g2_9_girls += c.get("girls", 0)
            except ValueError:
                pass
                
        school["enrollment"] = {
            "all": {
                "total": total,
                "boys": boys,
                "girls": girls
            },
            "grades_2_9": {
                "total": g2_9_total,
                "boys": g2_9_boys,
                "girls": g2_9_girls
            }
        }

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"Saved compacted schools to {output_file}.")
