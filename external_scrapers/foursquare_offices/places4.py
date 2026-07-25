import polars as pl
from pyiceberg.catalog import load_catalog

# 1. Connect to Foursquare Catalog
print("Connecting to Foursquare Catalog...")
catalog = load_catalog(
    "default",
    **{
        "warehouse": "places",
        "uri": "https://catalog.h3-hub.foursquare.com/iceberg",
        "token": "eyJhbGciOiJIUzI1NiJ9.eyJhY3RvclR5cGUiOiJVU0VSIiwiYWN0b3JJZCI6InByb2QtZnNxLXVzZXItMTQxNjQ5MjcyNyIsInR5cGUiOiJQRVJTT05BTCIsInZlcnNpb24iOiIyIiwianRpIjoiZDM4Y2Q1ZjEtODc0Yy00OTk5LTkwNmMtNzcwZDE2MDE3ODBjIiwic3ViIjoicHJvZC1mc3EtdXNlci0xNDE2NDkyNzI3IiwiZXhwIjoxNzg0MzY0MDkyLCJpc3MiOiJkYXRhaHViLW1ldGFkYXRhLXNlcnZpY2UifQ.8o7VzExMxmkw_CBS5Z9bhfIdJ4KgX9ebDmhGXChFbb0", # ⚠️ Paste your real token back here!
        "header.content-type": "application/vnd.api+json",
        "rest-metrics-reporting-enabled": "false",
        "s3.region": "us-east-1",
        "s3.connect-timeout": "60",
        "s3.request-timeout": "60",
    },
)

print("Loading the OS Places table metadata...")
table = catalog.load_table('datasets.places_os')

# 2. Define the Schema fields
target_schema = [
    "fsq_place_id", "name", "latitude", "longitude", "address", "locality", 
    "region", "postcode", "admin_region", "post_town", "po_box", "country", 
    "date_created", "date_refreshed", "date_closed", "tel", "website", 
    "email", "facebook_id", "instagram", "twitter", "fsq_category_ids", 
    "fsq_category_labels", "placemaker_url", "unresolved_flags", "geom", "bbox"
]

print("Executing PyIceberg spatial scan for Bangalore...")
arrow_table = table.scan(
    row_filter="country == 'IN' and latitude >= 12.85 and latitude <= 13.10 and longitude >= 77.45 and longitude <= 77.75",
    selected_fields=target_schema
).to_arrow()

# 3. Convert to Polars
bangalore_pois = pl.from_arrow(arrow_table)
print(f"Successfully pulled {len(bangalore_pois)} POIs in Bangalore.")

# --- NEW STEP: Flatten the nested data types so they can fit into a CSV ---
print("Formatting nested data for CSV export...")
processed_pois = bangalore_pois.with_columns([
    # Convert lists/arrays into clean, comma-separated strings
    pl.col("fsq_category_ids").list.join(", ").fill_null(""),
    pl.col("fsq_category_labels").list.join(", ").fill_null(""),
    pl.col("unresolved_flags").list.join(", ").fill_null(""),
    
    # Cast the complex bounding box struct directly to a text string
    pl.col("bbox").cast(pl.String),
    
    # FIX: Safely encode raw geometry bytes into a Hex text string instead of direct casting
    pl.col("geom").bin.encode("hex").fill_null("")
])

# 4. Export to CSV safely
output_csv = "foursquare_bangalore_places.csv"
processed_pois.write_csv(output_csv)

print(f"\nSuccess! Dataset successfully saved locally to '{output_csv}'")