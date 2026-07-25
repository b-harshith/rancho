import json
import simplekml

# 1. Load your filtered office data
input_json = "bangalore_office_listings.json"
output_kml = "bangalore_offices.kml"

print(f"Loading {input_json}...")
with open(input_json, "r") as f:
    data = json.load(f)

# 2. Initialize the KML object
kml = simplekml.Kml()

# 3. Add points to the KML
print("Generating placemarks...")
for poi in data:
    name = poi.get("name", "Unknown Office")
    lat = poi.get("latitude")
    lon = poi.get("longitude")
    address = poi.get("address", "No address provided")

    if lat and lon:
        # Create a point and add it to the KML
        pnt = kml.newpoint(name=name, coords=[(lon, lat)])
        pnt.description = f"Address: {address}\nPlace ID: {poi.get('fsq_place_id')}"

# 4. Save the KML file
kml.save(output_kml)
print(f"Success! '{output_kml}' has been created.")