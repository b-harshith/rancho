import json

with open("scratch/redux_state.json") as f:
    state = json.load(f)

# Let's check listing
listing = state.get("listing", {})
print("listing keys:", list(listing.keys()) if isinstance(listing, dict) else type(listing))

# Let's check listingV2
listingV2 = state.get("listingV2", {})
print("listingV2 keys:", list(listingV2.keys()) if isinstance(listingV2, dict) else type(listingV2))

# Let's check establishments
establishments = state.get("establishments", {})
print("establishments keys:", list(establishments.keys()) if isinstance(establishments, dict) else type(establishments))

# Let's print some details about what's inside these
if isinstance(listingV2, dict):
    for k, v in listingV2.items():
        if isinstance(v, dict):
            print(f"listingV2.{k} keys: {list(v.keys())}")
        elif isinstance(v, list):
            print(f"listingV2.{k} len: {len(v)}")
        else:
            print(f"listingV2.{k}: {type(v)}")

if isinstance(listing, dict):
    for k, v in listing.items():
        if isinstance(v, dict):
            print(f"listing.{k} keys: {list(v.keys())}")
        elif isinstance(v, list):
            print(f"listing.{k} len: {len(v)}")
        else:
            print(f"listing.{k}: {type(v)}")

# Save a summary of listings/hospitals found in the current state
with open("scratch/listing_keys.txt", "w") as f:
    json.dump({"listing": listing, "listingV2": listingV2}, f, indent=2)
