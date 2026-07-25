from pathlib import Path
import pandas as pd

root = Path('/Users/malleswararao/Desktop/final new data/premium_school_review')
val_dir = root / 'validation_results'
master = pd.read_csv(root / 'premium_schools_corrected_layered.csv', dtype=str).fillna('')
vals = pd.concat([pd.read_csv(p, dtype=str).fillna('') for p in val_dir.glob('UDISE_INFERRED_BATCH_*.csv')], ignore_index=True)
j = vals.merge(master[['udise_code','classFrm','classTo','grade_2_9_enrollment_est','school_level','fee_evidence_max_observed']], on='udise_code', how='left')
j['grade_2_9_enrollment_est_num'] = pd.to_numeric(j['grade_2_9_enrollment_est'], errors='coerce')
# The customer's target is schools serving children in Grades 2-9, not schools
# that must offer every grade from 2 through 9. The master already computes an
# estimated enrollment measure for that target segment; positive enrollment is
# the authoritative eligibility signal.
j['target_grade_2_9_scope'] = (j['grade_2_9_enrollment_est_num'] > 0).map({True:'yes', False:'no'})
queue = j[(j['validation_decision'] == 'not_premium') & (j['target_grade_2_9_scope'] == 'yes')].copy()
queue = queue.sort_values(['city','school_name']).reset_index(drop=True)
queue['recheck_batch_id'] = 'GRADE_2_9_RECHECK_' + (queue.index // 50 + 1).astype(str).str.zfill(3)
queue['recheck_order'] = queue.index % 50 + 1
queue.to_csv(root / 'grade_2_9_recheck_queue.csv', index=False)
batch_dir = root / 'grade_2_9_recheck_batches'
batch_dir.mkdir(exist_ok=True)
for batch, group in queue.groupby('recheck_batch_id', sort=True):
    group.to_csv(batch_dir / f'{batch}.csv', index=False)
print('recheck_rows', len(queue))
print('recheck_batches', queue['recheck_batch_id'].nunique())
print('by_city')
print(queue['city'].value_counts().to_string())
