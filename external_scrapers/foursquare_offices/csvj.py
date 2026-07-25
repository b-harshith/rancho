import polars as pl
import json # Only needed if you use the alternative array method below

input_csv = "foursquare_bangalore_places.csv"
output_json = "foursquare_bangalore_places.json"

print(f"Reading data from '{input_csv}'...")

try:
    df = pl.read_csv(
        input_csv,
        schema_overrides={
            "postcode": pl.String,
            "tel": pl.String,
            "facebook_id": pl.String,
            "twitter": pl.String,
            "fsq_place_id": pl.String
        }
    )
    
    print(f"Successfully loaded {len(df)} POIs.")
    
    # ---------------------------------------------------------
    # OPTION 1: The Modern Polars Way (Highly Recommended)
    # ---------------------------------------------------------
    print(f"Writing to Newline-Delimited JSON (NDJSON)...")
    # This writes each POI as its own JSON object on a new line
    df.write_ndjson(output_json)
    
    print("Success! Data successfully exported.")

    # ---------------------------------------------------------
    # OPTION 2: The Standard Array Way (If your app demands it)
    # ---------------------------------------------------------
    # If your downstream application absolutely REQUIRES a standard 
    # JSON array starting with '[' and ending with ']', uncomment 
    # the 3 lines below (Note: this uses more of your computer's RAM).
    
    # print("Converting to standard JSON array...")
    # with open("foursquare_standard_array.json", "w") as f:
    #     json.dump(df.to_dicts(), f, indent=4) 

except FileNotFoundError:
    print(f"Error: Could not find '{input_csv}'.")
except Exception as e:
    print(f"An error occurred: {e}")