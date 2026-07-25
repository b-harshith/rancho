from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path('/Users/malleswararao/Desktop/school extraction')
WORK = Path('/Users/malleswararao/Desktop/final new data/premium_school_review')
CURRENT = pd.read_csv(ROOT / 'output/final_master_premium_schools_after_all_city_rematch_city_baseline_fix.csv', dtype=str).fillna('')
PRIOR = pd.read_csv(ROOT / 'output/final_master_premium_schools_after_delhi_rematch_bengaluru_fix.csv', dtype=str).fillna('')
PLUS = pd.read_csv(ROOT / 'output/master_premium_schools_udise_0p4_plus_non_udise.csv', dtype=str).fillna('')
PRED = pd.read_csv(ROOT / 'output/fee_classification_predictions_all_udise.csv', dtype=str).fillna('')
BASE = pd.read_csv('/Users/malleswararao/Desktop/final new data/schools/processed/master_schools_all_28947.csv', dtype=str).fillna('')
FULL_UDISE = pd.read_csv(ROOT / 'data/client_export/udise_schools_client.csv', dtype=str).fillna('')
EZY = pd.read_csv(ROOT / 'data/client_export/ezy_yellowslate_unified_all_cities.csv', dtype=str).fillna('')

TARGET_CITIES = {'delhi_ncr','hyderabad','mumbai','bengaluru','chennai','pune','kolkata'}
current_codes = set(CURRENT.loc[CURRENT.udise_code.ne(''), 'udise_code'])

base = BASE[['udise_code','school_name','city','district','state','board','k12_enrollment','grade_2_9_enrollment_est','latitude','longitude','geocode_status','geocode_location_type','geocode_formatted_address','geocode_place_id','school_level']].copy()
base['g29_num'] = pd.to_numeric(base['grade_2_9_enrollment_est'], errors='coerce')

# The processed 28,947-row subset is not the complete UDISE universe. Use the
# full client export as the grade-scope backstop for schools such as Silver
# Oaks that are present in UDISE but absent from the narrower processed subset.
full_rows = []
for raw in FULL_UDISE.summary_json:
    try:
        full_rows.append(__import__('json').loads(raw))
    except Exception:
        full_rows.append({})
full_summary = pd.DataFrame(full_rows)
full = pd.DataFrame({
    'udise_code': FULL_UDISE.udise_code,
    'full_school_name': FULL_UDISE.school_name,
    'full_pincode': FULL_UDISE.pincode,
    'full_class_from': pd.to_numeric(full_summary.get('classFrm'), errors='coerce'),
    'full_class_to': pd.to_numeric(full_summary.get('classTo'), errors='coerce'),
    'full_state': full_summary.get('stateName', ''),
    'full_district': full_summary.get('districtName', ''),
    'full_address': full_summary.get('address', ''),
}).drop_duplicates('udise_code')

pred = PRED.merge(base[['udise_code','g29_num','school_level']], on='udise_code', how='left').merge(full[['udise_code','full_class_from','full_class_to','full_pincode','full_address']], on='udise_code', how='left')
pred['target_grade_2_9'] = pred['g29_num'].gt(0) | ((pred['full_class_from'] <= 2) & (pred['full_class_to'] >= 9))
chain_candidates = pred.loc[
    pred.predicted_fee_class.eq('>1L')
    & pred.chain_detected.ne('')
    & pred.chain_detected.ne('independent')
    & pred.target_grade_2_9
    & pred.inferred_city.isin(TARGET_CITIES)
    & ~pred.udise_code.isin(current_codes)
].copy()
chain_candidates['omission_reason'] = 'known_premium_chain_model_prediction_missing_from_latest_master'

EZY['fee_max_num'] = pd.to_numeric(EZY.fee_max, errors='coerce')
fee = EZY[EZY.udise_code.ne('')].groupby('udise_code', as_index=False).agg(
    fee_max_observed=('fee_max_num','max'),
    fee_min_observed=('fee_min_num','max') if 'fee_min_num' in EZY.columns else ('fee_max_num','min'),
    fee_school_name=('school_name','first'),
    fee_city=('city','first'),
    fee_category=('category', lambda s: '|'.join(sorted(set(x for x in s if x)))),
    fee_url=('primary_url','first'),
)
direct = pred.merge(fee, on='udise_code', how='inner')
direct = direct.loc[
    direct.fee_max_observed.ge(100000)
    & direct.target_grade_2_9
    & direct.inferred_city.isin(TARGET_CITIES)
    & ~direct.udise_code.isin(current_codes)
].copy()
direct['omission_reason'] = 'exact_udise_fee_source_at_or_above_1L_missing_from_latest_master'

candidate_codes = set(chain_candidates.udise_code) | set(direct.udise_code)
report = pred[pred.udise_code.isin(candidate_codes)].merge(fee, on='udise_code', how='left')
report['direct_fee_evidence'] = report.fee_max_observed.ge(100000).map({True:'yes',False:'no'})
report['known_premium_chain_evidence'] = (report.chain_detected.ne('') & report.chain_detected.ne('independent')).map({True:'yes',False:'no'})
report['restoration_reason'] = report.udise_code.map({r.udise_code: ('direct_fee_and_known_chain' if r.udise_code in set(direct.udise_code)&set(chain_candidates.udise_code) else 'direct_fee_evidence' if r.udise_code in set(direct.udise_code) else 'known_premium_chain_model') for r in report.itertuples()})
report.to_csv(WORK / 'premium_omission_audit.csv', index=False)

source_by_code = {}
for frame, source in [(PLUS,'previous_premium_master'), (PRIOR,'previous_rematch_master')]:
    for _, row in frame[frame.udise_code.ne('')].iterrows():
        source_by_code.setdefault(row.udise_code, (row.to_dict(), source))

rows = []
current_cols = list(CURRENT.columns)
for code in sorted(candidate_codes):
    if code in source_by_code:
        row, source = source_by_code[code]
        row = {c: row.get(c,'') for c in current_cols}
    else:
        p = pred[pred.udise_code.eq(code)].iloc[0].to_dict()
        b_matches = base[base.udise_code.eq(code)]
        b = b_matches.iloc[0].to_dict() if len(b_matches) else {
            'udise_code': code,
            'school_name': p.get('school_name',''),
            'city': p.get('inferred_city',''),
            'district': p.get('district',''),
            'state': p.get('state',''),
            'board': p.get('inferred_board',''),
            'k12_enrollment': p.get('enrollment_total',''),
            'grade_2_9_enrollment_est': '',
            'latitude': '', 'longitude': '', 'pincode': p.get('full_pincode',''),
        }
        ef = fee[fee.udise_code.eq(code)].iloc[0].to_dict() if code in set(fee.udise_code) else {}
        row = {c:'' for c in current_cols}
        row.update({
            'record_type':'UDISE_RESTORED_PREMIUM_GUARDRAIL',
            'premium_basis':'', 'udise_code':code,
            'school_name':b.get('school_name') or p.get('school_name',''),
            'city':b.get('city') or p.get('inferred_city',''),
            'state':b.get('state',''), 'district':b.get('district',''),
            'pincode':b.get('pincode',''),
            'latitude':b.get('latitude',''), 'longitude':b.get('longitude',''),
            'board':p.get('inferred_board',''),
            'fee_reference':ef.get('fee_url',''), 'predicted_fee_class':'>1L',
            'confidence':'0.99' if code in set(direct.udise_code) else p.get('confidence',''),
            'threshold_used':p.get('market_threshold','0.4'),
            'chain_detected':p.get('chain_detected',''),
            'enrollment_total':b.get('k12_enrollment',''),
            'estimated_grade_2_9_student_count':b.get('grade_2_9_enrollment_est',''),
            'enrollment_source':'UDISE',
            'source_dataset':'ezy_yellowslate_exact_udise' if code in set(direct.udise_code) else 'fee_classification_predictions_all_udise',
            'source_url':ef.get('fee_url',''),
        })
        source = 'constructed_from_udise_prediction_and_fee_sources'
    is_direct = code in set(direct.udise_code)
    is_chain = code in set(chain_candidates.udise_code)
    if is_direct:
        fee_match = fee[fee.udise_code.eq(code)]
        fee_url = fee_match.iloc[0].get('fee_url','') if len(fee_match) else ''
        row['fee_reference'] = fee_url or row.get('fee_reference','')
        row['source_url'] = fee_url or row.get('source_url','')
        row['source_dataset'] = 'ezy_yellowslate_exact_udise'
        row['confidence'] = '0.99'
    row['record_type'] = 'UDISE_RESTORED_PREMIUM_GUARDRAIL'
    row['premium_basis'] = 'restored_direct_fee_evidence_ge2_9' if is_direct else 'restored_known_premium_chain_ge2_9'
    row['audit_note'] = f'Restored after omission audit: {"direct fee evidence >=1L" if is_direct else "known premium chain model match"}; Grade 2-9 enrollment estimate positive; source={source}.'
    rows.append(row)

restored = pd.DataFrame(rows, columns=current_cols)
out = pd.concat([CURRENT, restored], ignore_index=True)
# Candidate codes are explicitly excluded from CURRENT, and blank UDISE codes
# represent separately added non-UDISE listings. Preserve those rows rather
# than collapsing branches that happen to share a school name.
out.to_csv(WORK / 'premium_schools_corrected_layered_restored.csv', index=False)
print('current_rows',len(CURRENT))
print('direct_candidates',len(direct))
print('chain_candidates',len(chain_candidates))
print('union_candidates',len(candidate_codes))
print('restored_rows',len(restored))
print('new_rows',len(out))
print('output',WORK / 'premium_schools_corrected_layered_restored.csv')
