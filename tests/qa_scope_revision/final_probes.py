#!/usr/bin/env python3
"""Independent offline final probes for DNC scope revision R2."""
from __future__ import annotations
import csv, hashlib, json, os, sys, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from collectors.magicbricks_localities.collector import Collector, Options, normalize_locality, validate_runtime_contracts
from collectors.magicbricks_localities.parser import parse_detail_page
from pipelines.schools.merge import geocode_records

def run():
    out={}
    p=ROOT/'DATA/reference/pincodes'
    with (p/'delhi_ncr_pin_candidates.csv').open() as f: c=list(csv.DictReader(f))
    with (p/'delhi_ncr_pin_exclusions.csv').open() as f: x=list(csv.DictReader(f))
    out['geo']={'candidates':len(c),'unique':len({r['pincode'] for r in c}),'exclusions':len(x),'intersection':sorted({r['pincode'] for r in c}&{r['pincode'] for r in x})}

    now=datetime(2026,6,30,tzinfo=timezone.utc); valid='a'*64; fresh='b'*64
    loaded={valid:{'status':'OK','lat':1,'lon':1,'fetched_at':(now-timedelta(days=30)).isoformat(),'url':'secret'},
            fresh:{'status':'ZERO_RESULTS','lat':None,'lon':None,'fetched_at':now.isoformat()},
            'not-a-hash':{'key':'SENTINEL'}, 'c'*64:{'status':'OK','fetched_at':'malformed'}}
    with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{'GOOGLE_MAPS_API_KEY':'SENTINEL_SECRET'}):
        cache=Path(td)/'cache.json'; cache.write_text(json.dumps(loaded))
        rows=[{'name':'No call','canonical_city_id':'delhi_ncr','lat':None,'lon':None,'quality_flags':[]}]
        geocode_records(rows,cache,[76,28,78,30],1,0,now=now)
        saved=json.loads(cache.read_text()); text=cache.read_text()
        out['cache']={'keys':sorted(saved),'only_fresh_survives':set(saved)=={fresh},'rewritten':saved!=loaded,'secret_absent':'SENTINEL' not in text and 'secret' not in text}

    base={'source_city_id':'2624','source_city_name':'New delhi','verified_url':'https://www.magicbricks.com/x','pagination_url':'https://www.magicbricks.com/x?page={page}&city={city_name}'}
    variants=['../x','..','.', '/abs','\\escape','%2e%2e','a/b','a\\b','\x00bad']
    rejected=[]
    with tempfile.TemporaryDirectory() as td:
        for value in variants:
            bad=dict(base,source_city_id=value)
            try: Collector('delhi_ncr',{'components':[bad]},Options(Path(td))); rejected.append(False)
            except (ValueError,OSError): rejected.append(True)
        col=Collector('delhi_ncr',{'components':[base]},Options(Path(td),resume=True))
        try: col.stage2([{'source_url':'https://evil.example/stolen','link_key':'foreign'}])
        except RuntimeError: pass
        manifest=json.loads((col.root/'manifest.json').read_text())
        out['containment']={'variants':variants,'all_rejected':all(rejected),'results':rejected,
          'foreign_quarantined':'REDACTED_FOREIGN_URL' in col.quarantine.read_text(),
          'failed_manifest':manifest.get('status')=='failed' and manifest.get('failed_stage')=='detail' and manifest.get('production_complete') is False}

    evroot=ROOT/'collectors/magicbricks_localities/evidence'; ev=json.loads((evroot/'delhi_ncr_preflight_20260630.json').read_text())
    observations=[*ev['components'],*ev['sampled_details']]; consistency=[]
    for ob in observations:
        art=(evroot/ob['artifact_path']).resolve(); payload=json.loads(art.read_text())
        hash_ok=hashlib.sha256(art.read_bytes()).hexdigest()==ob['artifact_sha256']
        if 'configured_source_city_id' in ob:
            content_ok=str(payload.get('source_city_id'))==str(ob['source_returned_city_id']) and payload.get('record_count')==ob['sample_size'] and len(payload.get('locality_names',[]))==ob['city_matches']
        else:
            content_ok=str(payload.get('source_entity_id'))==str(ob['source_entity_id']) and str(payload.get('source_city_id'))==str(ob['source_city_id']) and payload.get('latitude') is not None and payload.get('longitude') is not None
        consistency.append(hash_ok and content_ok and evroot.resolve() in art.parents)
    out['evidence']={'observations':len(observations),'all_hash_and_content_consistent':all(consistency),'results':consistency}

    d=json.loads((ROOT/'tests/collectors/fixtures/magicbricks_localities_detail.json').read_text()); loc=normalize_locality('delhi_ncr',parse_detail_page(d['html'],d['url']))
    validate_runtime_contracts([loc]); rejected_types=[]
    for k,v in [('entity_id','bad'),('lat',91),('review_count',2.5),('price_per_sqft',-1)]:
        z=dict(loc); z[k]=v
        try: validate_runtime_contracts([z]); rejected_types.append(False)
        except Exception: rejected_types.append(True)
    out['contract']={'valid_passes':True,'all_mutations_rejected':all(rejected_types),'results':rejected_types}
    return out

if __name__=='__main__': print(json.dumps(run(),indent=2,sort_keys=True))
