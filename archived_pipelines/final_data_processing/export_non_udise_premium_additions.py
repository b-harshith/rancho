from pathlib import Path
import pandas as pd

ROOT = Path('/Users/malleswararao/Desktop/final new data/premium_school_review')
MASTER = pd.read_csv(ROOT / 'premium_schools_corrected_layered.csv', dtype=str).fillna('')
EZY = pd.read_csv('/Users/malleswararao/Desktop/school extraction/data/client_export/ezy_yellowslate_unified_all_cities.csv', dtype=str).fillna('')
GEO = pd.read_csv('/Users/malleswararao/Desktop/school extraction/data/client_export/ezy_yellowslate_unified_all_cities_geocoded.csv', dtype=str).fillna('')

out = MASTER[MASTER.udise_code.eq('')].copy()
out['addition_type'] = 'premium_non_udise_fee_source_addition'
out['udise_status'] = 'not_found_in_udise_master'
out['listing_id'] = out.apply(lambda r: f"{r.school_name}|{r.city}|{r.pincode}|{r.google_place_id}", axis=1)

for d in (EZY, GEO):
    for c in ['fee_min','fee_max']:
        if c in d.columns:
            d[c+'_num'] = pd.to_numeric(d[c], errors='coerce')

geo_cols = [c for c in ['google_place_id','google_location_type','google_partial_match','geocode_confidence','google_formatted_address'] if c in GEO.columns]
if geo_cols:
    out = out.merge(GEO[geo_cols].drop_duplicates('google_place_id'), on='google_place_id', how='left', suffixes=('','_geocode'))

cols = [
    'listing_id','school_name','city','state','district','area','address','pincode',
    'latitude','longitude','board','fee_reference','predicted_fee_class','chain_detected',
    'addition_type','udise_status','source_dataset','source_url','google_place_id',
    'fee_min_num','fee_max_num','fee_text','category','primary_url','ezyschooling_url',
    'yellowslate_url','google_location_type','google_partial_match','geocode_confidence',
    'google_formatted_address','audit_note',
]
cols = [c for c in cols if c in out.columns]
out[cols].to_csv(ROOT / 'non_udise_premium_additions.csv', index=False)
print('rows', len(out))
print('cities')
print(out.city.value_counts().to_string())
