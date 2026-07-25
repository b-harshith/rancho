import pandas as pd
from pyiceberg.catalog import load_catalog

# 1. Connect to the Foursquare Iceberg Catalog
catalog = load_catalog(
    "default",
    **{
        "warehouse": "places",
        "uri": "https://catalog.h3-hub.foursquare.com/iceberg",
        "token": "eyJhbGciOiJIUzI1NiJ9.eyJhY3RvclR5cGUiOiJVU0VSIiwiYWN0b3JJZCI6InByb2QtZnNxLXVzZXItMTQxNjQ5MjcyNyIsInR5cGUiOiJQRVJTT05BTCIsInZlcnNpb24iOiIyIiwianRpIjoiZDM4Y2Q1ZjEtODc0Yy00OTk5LTkwNmMtNzcwZDE2MDE3ODBjIiwic3ViIjoicHJvZC1mc3EtdXNlci0xNDE2NDkyNzI3IiwiZXhwIjoxNzg0MzY0MDkyLCJpc3MiOiJkYXRhaHViLW1ldGFkYXRhLXNlcnZpY2UifQ.8o7VzExMxmkw_CBS5Z9bhfIdJ4KgX9ebDmhGXChFbb0", # Keep this safe!
        "header.content-type": "application/vnd.api+json",
        "rest-metrics-reporting-enabled": "false",
    },
)

# 2. Load the Open Source Categories table
print("Loading the categories table...")
table = catalog.load_table('datasets.categories_os')

# 3. Scan the ENTIRE table (no limit) and convert to a Pandas DataFrame
print("Fetching all category data. This might take a moment...")
df = table.scan().to_pandas()

# 4. Check the row count to ensure we have the 1000+ categories
total_rows = len(df)
print(f"Success! Retrieved {total_rows} unique categories.")

# 5. Export the DataFrame to a CSV file in your current directory
csv_filename = "foursquare_os_categories.csv"
df.to_csv(csv_filename, index=False)

print(f"Data successfully saved to {csv_filename}!")