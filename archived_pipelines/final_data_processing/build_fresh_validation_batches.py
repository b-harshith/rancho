from pathlib import Path
import json
import pandas as pd

ROOT = Path('/Users/malleswararao/Desktop/final new data/premium_school_review')
MASTER = pd.read_csv(ROOT / 'premium_schools_corrected_layered_restored.csv', dtype=str).fillna('')
FULL = pd.read_csv('/Users/malleswararao/Desktop/school extraction/data/client_export/udise_schools_client.csv', dtype=str).fillna('')

summary = []
for raw in FULL.summary_json:
    try:
        summary.append(json.loads(raw))
    except Exception:
        summary.append({})
ud = pd.DataFrame(summary)
scope = pd.DataFrame({
    'udise_code': FULL.udise_code,
    'full_class_from': pd.to_numeric(ud.get('classFrm'), errors='coerce'),
    'full_class_to': pd.to_numeric(ud.get('classTo'), errors='coerce'),
    'full_udise_name': FULL.school_name,
    'full_udise_address': ud.get('address', ''),
    'full_pincode': FULL.pincode,
}).drop_duplicates('udise_code')

df = MASTER.merge(scope, on='udise_code', how='left')
g29 = pd.to_numeric(df.get('estimated_grade_2_9_student_count', ''), errors='coerce')
df['target_grade_2_9_signal'] = ((g29 > 0) | ((df.full_class_from <= 2) & (df.full_class_to >= 9))).map({True:'yes',False:'no'})
df['known_chain_protected'] = (df.chain_detected.ne('') & df.chain_detected.ne('independent')).map({True:'yes',False:'no'})
df['fresh_validation_id'] = df.apply(lambda r: r.udise_code if r.udise_code else f"{r.school_name}|{r.city}|{r.address}", axis=1)
df['review_search_query'] = (df.school_name + ' ' + df.city + ' school fees official').str.strip()
df['fresh_guardrail_instructions'] = df.apply(lambda r: (
    'Known premium chain: do not label not_premium solely because fee evidence is missing or grade span stops before XII; verify exact branch and use protected_known_premium_pending_branch_evidence if branch evidence remains incomplete.'
    if r.known_chain_protected == 'yes' else
    'Use target_grade_2_9_signal and exact branch identity; do not require Class XII.'
), axis=1)

outdir = ROOT / 'fresh_validation_batches'
outdir.mkdir(exist_ok=True)
for old in outdir.glob('FRESH_PREMIUM_BATCH_*.csv'):
    old.unlink()
df = df.sort_values(['city','school_name','fresh_validation_id']).reset_index(drop=True)
df['fresh_batch_id'] = 'FRESH_PREMIUM_BATCH_' + (df.index // 50 + 1).astype(str).str.zfill(3)
df['fresh_order_in_batch'] = df.index % 50 + 1
for batch, group in df.groupby('fresh_batch_id', sort=True):
    group.to_csv(outdir / f'{batch}.csv', index=False)
df.to_csv(ROOT / 'fresh_validation_master_index.csv', index=False)
print('rows', len(df))
print('batches', df.fresh_batch_id.nunique())
print('known_chain_rows', int((df.known_chain_protected == 'yes').sum()))
print('grade_2_9_signal_yes', int((df.target_grade_2_9_signal == 'yes').sum()))
