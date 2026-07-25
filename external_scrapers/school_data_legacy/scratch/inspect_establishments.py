import json

with open("scratch/redux_state.json") as f:
    state = json.load(f)

est = state.get("establishments", {})
hosp_listing = est.get("hospitalListing", {})
hospitals = hosp_listing.get("hospitals", {})

print("hospitals keys:", list(hospitals.keys()))
if "entities" in hospitals:
    entities = hospitals["entities"]
    print("Number of hospital entities:", len(entities))
    first_key = list(entities.keys())[0] if entities else None
    if first_key:
        print("First hospital entity key:", first_key)
        # Let's save the first hospital to a file
        with open("scratch/first_hospital.json", "w") as f:
            json.dump(entities[first_key], f, indent=2)
        print("Saved first hospital to scratch/first_hospital.json")
        # Let's see some basic keys of the hospital entity
        print("First hospital keys:", list(entities[first_key].keys()))
        print("Name:", entities[first_key].get("name"))
        print("Locality:", entities[first_key].get("locality"))
        print("Address:", entities[first_key].get("address"))
        print("Photos:", len(entities[first_key].get("photos", [])))
        print("Specialties:", entities[first_key].get("specialties"))
