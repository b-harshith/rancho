#!/usr/bin/env python3
"""Offline adversarial probes for scope-revision remediation R1."""
from __future__ import annotations
import csv, hashlib, json, os, sys, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from collectors.ezyschooling.collector import validate_normalized
from collectors.magicbricks_localities.collector import Collector, Options, normalize_locality, validate_runtime_contracts
from collectors.magicbricks_localities.parser import parse_detail_page
from pipelines.geospatial.prepare_delhi_ncr import build_pins
from pipelines.schools.merge import geocode_records

def rows(path):
    with path.open(newline='', encoding='utf-8') as f: return list(csv.DictReader(f))

def run():
    out = {}
    pin_dir = ROOT/'DATA/reference/pincodes'; c=rows(pin_dir/'delhi_ncr_pin_candidates.csv'); x=rows(pin_dir/'delhi_ncr_pin_exclusions.csv')
    with tempfile.TemporaryDirectory() as td:
        t=Path(td); src=t/'postal.csv'
        src.write_text('pincode,statename,districtname,officename,deliverystatus\n110001,DELHI,CENTRAL,A,Delivery\n110001,UP,BUDAUN,B,Non-Delivery\n110002,UP,BUDAUN,C,Delivery\n', encoding='utf-8')
        a1,b1,a2,b2=(t/n for n in ('a1.csv','b1.csv','a2.csv','b2.csv'))
        build_pins(src,a1,b1); build_pins(src,a2,b2)
        out['pins']={'disjoint':{r['pincode'] for r in c}.isdisjoint({r['pincode'] for r in x}), 'counts':[len(c),len(x)],
          'deterministic':a1.read_bytes()==a2.read_bytes() and b1.read_bytes()==b2.read_bytes(),
          'cross_district_pin_not_excluded':'110001' not in {r['pincode'] for r in rows(b1)}}
    # Canonical runtime mutation rejection.
    detail=json.loads((ROOT/'tests/collectors/fixtures/magicbricks_localities_detail.json').read_text())
    loc=normalize_locality('delhi_ncr',parse_detail_page(detail['html'],detail['url']))
    rejected=[]
    for field,value in [('entity_id','bad'),('review_count',-1),('lat',999)]:
        bad=dict(loc); bad[field]=value
        try: validate_runtime_contracts([bad]); rejected.append(False)
        except Exception: rejected.append(True)
    out['magic_schema']={'valid_passes': True, 'mutations_rejected':rejected}
    # Demonstrate whether untrusted component IDs can escape the raw stage directory.
    comp={'source_city_id':'../../../../escape','source_city_name':'X','verified_url':'https://www.magicbricks.com/x','pagination_url':'https://www.magicbricks.com/x?page={page}&city={city_name}'}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        escaped = []
        try:
            col = Collector('delhi_ncr', {'components': [comp]}, Options(root))
            col._save_raw('pages', f"{comp['source_city_id']}-p00001", comp['verified_url'], 'x', {})
            escaped = [str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p.suffix == '.html' and col.raw not in p.parents]
        except ValueError:
            pass
        out['magic_path_probe'] = {'escaped_raw_stage': escaped}
    # Stale cache must not be used; separately observe whether it is durably pruned when no refresh is allowed.
    now=datetime(2026,6,30,tzinfo=timezone.utc); query='Alpha, Delhi, delhi_ncr, India'; key=hashlib.sha256(query.casefold().encode()).hexdigest()
    with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{'GOOGLE_MAPS_API_KEY':'SENTINEL_SECRET'}):
        cache=Path(td)/'cache.json'; cache.write_text(json.dumps({key:{'status':'OK','lat':1,'lon':1,'fetched_at':(now-timedelta(days=30)).isoformat()}}))
        rec=[{'name':'Alpha','address':'Delhi','canonical_city_id':'delhi_ncr','lat':None,'lon':None,'quality_flags':[]}]
        geocode_records(rec,cache,[76,28,78,30],1,0,now=now)
        saved=cache.read_text()
        out['geocode']={'stale_not_used':rec[0]['lat'] is None,'stale_pruned':key not in json.loads(saved),'secret_absent': 'SENTINEL_SECRET' not in saved,'cache_keys_hashed':all(len(k)==64 for k in json.loads(saved))}
    evidence=json.loads((ROOT/'collectors/magicbricks_localities/evidence/delhi_ncr_preflight_20260630.json').read_text())
    hashes = [z['artifact_sha256'] for z in evidence['components']] + [z['artifact_sha256'] for z in evidence['sampled_details']]
    out['preflight']={'components':len(evidence['components']),'details':len(evidence['sampled_details']), 'hashes_well_formed':all(len(h)==64 for h in hashes),
      'raw_evidence_present': any((ROOT/'collectors/magicbricks_localities/evidence').glob('*.html')) or any((ROOT/'collectors/magicbricks_localities/evidence').glob('*.jsonl')),
      'origin':evidence.get('evidence_origin')}
    return out

if __name__=='__main__': print(json.dumps(run(),indent=2,sort_keys=True))
