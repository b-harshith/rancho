import json

def analyze_fees():
    with open("data/output/schools_analysis_with_fees.json") as f:
        data = json.load(f)
        
    print("Keys in first school:", list(data["schools"][0].keys()))
    
    fee_groups = {}
    fee_counts = 0
    numeric_fees = []
    
    for s in data["schools"]:
        if "fees" in s and s["fees"] is not None:
            fee_counts += 1
            fee_info = s["fees"]
            # let's see what is inside fees
            if fee_counts == 1:
                print("Sample fee info:", json.dumps(fee_info, indent=2))
                
            if "annual_fee" in fee_info and fee_info["annual_fee"] is not None:
                numeric_fees.append(fee_info["annual_fee"])
                
    print(f"\nTotal schools: {len(data['schools'])}")
    print(f"Schools with fee data: {fee_counts}")
    print(f"Schools with numeric annual fee: {len(numeric_fees)}")
    
    # Calculate brackets
    brackets = {
        "Budget (<= 45k)": 0,
        "Affordable (45k - 75k)": 0,
        "Premium (75k - 150k)": 0,
        "Luxury (> 150k)": 0
    }
    
    for fee in numeric_fees:
        if fee <= 45000:
            brackets["Budget (<= 45k)"] += 1
        elif fee <= 75000:
            brackets["Affordable (45k - 75k)"] += 1
        elif fee <= 150000:
            brackets["Premium (75k - 150k)"] += 1
        else:
            brackets["Luxury (> 150k)"] += 1
            
    print("\nProportions:")
    for b, count in brackets.items():
        prop = (count / len(numeric_fees)) * 100 if numeric_fees else 0
        print(f"{b}: {count} ({prop:.1f}%)")

if __name__ == "__main__":
    analyze_fees()
