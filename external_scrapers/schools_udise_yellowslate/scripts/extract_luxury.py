import json

with open("data/output/schools_analysis_predicted_fees.json") as f:
    data = json.load(f)

luxury_schools = []

for s in data["schools"]:
    fee_group = None
    confidence = "Raw/Actual"
    
    if "fee_information" in s and s["fee_information"] is not None:
        fee = s["fee_information"].get("average_annual_fee")
        if fee is not None and fee > 150000:
            fee_group = "Luxury"
            if s["fee_information"].get("is_fee_estimated"):
                confidence = "Estimated (Source)"
            
    if not fee_group and "analysis_dimensions" in s:
        pred_group = s["analysis_dimensions"].get("fee_group")
        if pred_group == "Luxury":
            fee_group = "Luxury"
            conf_val = s["analysis_dimensions"].get("fee_group_confidence")
            confidence = f"Predicted ({conf_val:.2f})" if conf_val else "Predicted"
            
    if fee_group == "Luxury":
        meta = s.get("metadata", {})
        loc = meta.get("location", {})
        luxury_schools.append({
            "name": meta.get("school_name", "Unknown").replace("|", ""),
            "board": str(s.get("analysis_dimensions", {}).get("board_group", "Unknown")).replace("|", ""),
            "district": str(loc.get("district", "Unknown")).replace("|", ""),
            "block": str(loc.get("block", "Unknown")).replace("|", ""),
            "confidence": confidence
        })

def sort_key(x):
    c = x["confidence"]
    if c == "Raw/Actual": return 0
    if c == "Estimated (Source)": return 1
    if "Predicted (" in c:
        val = float(c.split("(")[1].strip(")"))
        return 2 - val
    return 3

luxury_schools.sort(key=sort_key)

md_lines = ["# Luxury Schools List\n\n"]
md_lines.append(f"Total Luxury Schools identified: {len(luxury_schools)}\n\n")
md_lines.append("| School Name | District | Block | Board | Confidence/Source |")
md_lines.append("|---|---|---|---|---|")

for s in luxury_schools:
    md_lines.append(f"| {s['name']} | {s['district']} | {s['block']} | {s['board']} | {s['confidence']} |")

with open("/Users/malleswararao/.gemini/antigravity-ide/brain/6fd3d189-67fb-4437-bda5-ffdd594340dc/luxury_schools.md", "w") as f:
    f.write("\n".join(md_lines))

print(f"Created artifact with {len(luxury_schools)} schools.")
