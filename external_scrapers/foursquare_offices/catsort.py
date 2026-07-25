import polars as pl
import json
from collections import defaultdict

input_csv = "foursquare_bangalore_places.csv"
output_json = "bangalore_pois_by_category.json"

print(f"Loading '{input_csv}'...")

# 1. Read the data, ensuring specific columns are strings
df = pl.read_csv(
    input_csv,
    schema_overrides={
        "postcode": pl.String,
        "fsq_place_id": pl.String,
        "fsq_category_labels": pl.String # This now contains the comma-separated string
    }
)

# 2. Initialize our nested structure
nested_data = defaultdict(list)

print("Grouping POIs by category... (This may take a moment)")

# 3. Iterate through the DataFrame
# We explode the category labels to ensure a POI appears under every category it belongs to
for row in df.to_dicts():
    categories = row.get("fsq_category_labels", "")
    
    # Split the comma-separated labels back into a list
    category_list = [cat.strip() for cat in categories.split(",") if cat.strip()]
    
    # If a POI has no categories, group it under "Uncategorized"
    if not category_list:
        nested_data["Uncategorized"].append(row)
    else:
        # Place this POI in every category bucket it belongs to
        for cat in category_list:
            nested_data[cat].append(row)

# 4. Save to JSON
print(f"Writing to '{output_json}'...")
with open(output_json, "w") as f:
    json.dump(nested_data, f, indent=4)

print("Success! Nested hierarchy by category created.")