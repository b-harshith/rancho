import polars as pl
import json

# 1. Configuration
TARGET_CATEGORY_ID = "4bf58dd8d48988d124941735"
input_csv = "foursquare_bangalore_places.csv"
output_json = "bangalore_office_listings.json"

print(f"Reading '{input_csv}' and filtering for Office category...")

# 2. Read the CSV
df = pl.read_csv(
    input_csv,
    schema_overrides={
        "fsq_category_ids": pl.String,
        "postcode": pl.String
    }
)

# 3. Apply the Filter
filtered_df = df.filter(
    pl.col("fsq_category_ids").str.contains(TARGET_CATEGORY_ID)
)

print(f"Found {len(filtered_df)} listings under the 'Office' category.")

# 4. Save to JSON
# Method: Convert to list of dictionaries and use standard json library 
# to ensure it is wrapped in an array [ ... ]
print(f"Writing results to '{output_json}'...")

data_list = filtered_df.to_dicts()
with open(output_json, "w") as f:
    json.dump(data_list, f, indent=4)

print("Success! JSON file created.")