from pathlib import Path
import re
import pandas as pd

ROOT = Path('/Users/malleswararao/Desktop/final new data/premium_school_review')
MASTER = pd.read_csv(ROOT / 'premium_schools_corrected_layered.csv', dtype=str).fillna('')
VAL_DIR = ROOT / 'validation_results'
VAL = pd.concat([pd.read_csv(p, dtype=str).fillna('') for p in VAL_DIR.glob('UDISE_INFERRED_BATCH_*.csv')], ignore_index=True)

GENERIC = {
    'school','public','international','academy','high','higher','secondary','senior','sr','sec','primary','nursery',
    'convent','vidyalaya','vidya','mandir','matriculation','matric','global','world','the','and','of','english',
    'medium','residential','campus','boys','girls','coed','co','ed','learning','college','junior','day','boarding',
    'model','sch','group','school',
}

def norm(text):
    text = re.sub(r'[^a-z0-9]+', ' ', str(text or '').lower())
    return ' '.join(text.split())

def signature(text):
    toks = [t for t in norm(text).split() if len(t) > 2 and t not in GENERIC]
    return ' '.join(toks[:2]) if len(toks) >= 2 else (toks[0] if toks else '')

MASTER['name_signature'] = MASTER['school_name'].map(signature)
sig_counts = MASTER['name_signature'].value_counts()
MASTER['individual_chain_candidate'] = MASTER['name_signature'].where(MASTER['name_signature'].map(sig_counts).ge(3), '')
MASTER['known_premium_chain'] = MASTER['chain_detected'].where(
    MASTER['chain_detected'].ne('') & MASTER['chain_detected'].ne('independent'), ''
)
MASTER['chain_protection_status'] = 'none'
MASTER.loc[MASTER['known_premium_chain'].ne(''), 'chain_protection_status'] = 'known_premium_chain'
MASTER.loc[(MASTER['known_premium_chain'].eq('')) & MASTER['individual_chain_candidate'].ne(''), 'chain_protection_status'] = 'individual_chain_candidate'

guardrail_cols = [
    'udise_code','school_name','city','evidence_tier','premium_basis','model_score','grade_2_9_enrollment_est',
    'school_level','chain_detected','known_premium_chain','name_signature','individual_chain_candidate',
    'chain_protection_status','final_latitude','final_longitude','source_url',
]
MASTER[[c for c in guardrail_cols if c in MASTER.columns]].to_csv(ROOT / 'premium_chain_guardrail_audit.csv', index=False)
MASTER.to_csv(ROOT / 'premium_schools_corrected_layered_guardrailed.csv', index=False)

chain_rows = MASTER[MASTER['chain_protection_status'].ne('none')].copy()
chain_rows.groupby(['chain_protection_status','known_premium_chain','individual_chain_candidate'], dropna=False).size().reset_index(name='rows').to_csv(ROOT / 'premium_chain_candidate_summary.csv', index=False)

joined = VAL.merge(MASTER[['udise_code','chain_detected','known_premium_chain','individual_chain_candidate','grade_2_9_enrollment_est','school_level']], on='udise_code', how='left')
joined['original_validation_decision'] = joined['validation_decision']
joined['chain_guardrail_applied'] = (joined['known_premium_chain'].fillna('') != '')
joined['chain_guardrail_reason'] = joined['known_premium_chain'].map(lambda x: f'Known premium chain from model regex: {x}' if x else '')
joined['validation_decision_guardrailed'] = joined['validation_decision']
mask = joined['chain_guardrail_applied'] & joined['validation_decision'].eq('not_premium')
joined.loc[mask, 'validation_decision_guardrailed'] = 'protected_known_premium_chain'
joined.loc[mask, 'notes'] = joined.loc[mask, 'notes'].astype(str).str.strip() + ' | Protected from not_premium downgrade because the model known-premium-chain detector matched.'
joined.to_csv(ROOT / 'validation_results_guardrailed.csv', index=False)

print('master rows', len(MASTER))
print('known premium chain rows', int(MASTER.known_premium_chain.ne('').sum()))
print('individual chain candidate rows', int((MASTER.individual_chain_candidate.ne('') & MASTER.known_premium_chain.eq('')).sum()))
print('validated rows', len(joined))
print('known-chain not-premium overrides', int(mask.sum()))
print('guardrailed decisions')
print(joined.validation_decision_guardrailed.value_counts().to_string())
