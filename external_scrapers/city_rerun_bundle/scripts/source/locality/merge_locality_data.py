import json
import os

CITY_SLUG = os.environ.get("CITY_SLUG", "bangalore").strip().lower().replace(" ", "-")

def main():
    raw_localities_path = f"data/raw/99acres_{CITY_SLUG}_localities.json"
    mapped_boundaries_path = f"data/processed/{CITY_SLUG}_mapped_data/{CITY_SLUG}_mapped_locality_boundaries.json"
    output_path = f"data/raw/{CITY_SLUG}_localities_enriched.json"

    print("Loading raw localities...")
    with open(raw_localities_path, 'r', encoding='utf-8') as f:
        raw_localities = json.load(f)
    print(f"Loaded {len(raw_localities)} raw localities.")

    print("Loading mapped boundaries...")
    with open(mapped_boundaries_path, 'r', encoding='utf-8') as f:
        mapped_boundaries = json.load(f)
    print(f"Loaded {len(mapped_boundaries)} mapped boundary records.")

    # Create lookup map
    # Key: locality ID, Value: the mapped record
    mapped_dict = {}
    for mb in mapped_boundaries:
        if 'id' in mb:
            mapped_dict[mb['id']] = mb

    # Merge
    merged_count = 0
    for loc in raw_localities:
        loc_id = loc.get('locality_info', {}).get('id')
        if not loc_id:
            continue
            
        mapped_data = mapped_dict.get(loc_id)
        if mapped_data:
            # We want to add the mapping info.
            # If we updated lat/lon during geocoding, maybe we want to keep it or just store the neighborhood
            if 'assigned_neighborhood' in mapped_data and mapped_data['assigned_neighborhood']:
                loc['overture_neighborhood'] = mapped_data['assigned_neighborhood']
                merged_count += 1
            else:
                loc['overture_neighborhood'] = None
                
            # If the script did geocoding, 'found' and 'details' might have been updated
            if 'found' in mapped_data:
                loc['geocoding_details'] = {
                    'found': mapped_data.get('found'),
                    'lat': mapped_data.get('lat'),
                    'lon': mapped_data.get('lon'),
                    'details': mapped_data.get('details')
                }

    print(f"Successfully merged overture neighborhood data into {merged_count} out of {len(raw_localities)} localities.")

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(raw_localities, f, indent=2, ensure_ascii=False)
    
    print(f"Saved enriched data to {output_path}")

if __name__ == '__main__':
    main()
