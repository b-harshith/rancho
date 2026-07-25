import json
import pandas as pd
import numpy as np

with open("data/output/schools_analysis_classified.json") as f:
    data = json.load(f)

schools = data["schools"]
print("Total schools:", len(schools))

records = []
for s in schools:
    total_students = (s.get("enrollment") or {}).get("total_students")
    fee_info = s.get("fee_information") or {}
    avg_fee = fee_info.get("average_annual_fee")
    records.append({
        "udise_code": s.get("udise_code"),
        "total_students": total_students,
        "average_annual_fee": avg_fee
    })

df = pd.DataFrame(records)
print(df.describe())
print("Schools with non-null students:", df["total_students"].notnull().sum())
print("Schools with non-null fees:", df["average_annual_fee"].notnull().sum())
