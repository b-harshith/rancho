#!/usr/bin/env python3
import csv, math, re
from collections import defaultdict, Counter
from difflib import SequenceMatcher
from pathlib import Path

ROOT=Path(__file__).parent.parent
SOURCE=ROOT/'schools'/'final_schools_29480_ranked.csv'
OUT=ROOT/'schools'/'non_udise_to_udise_match_audit.csv'
GENERIC={'school','public','private','international','senior','secondary','higher','high','english','medium','education','educational','academy','convent','campus','branch','cbse','icse','igcse','ib','board','the','of','at','in','and'}
def valid(v): return bool(re.fullmatch(r'\d{11}',(v or '').strip()))
def tokens(v):
    s=str(v or '').lower().replace('&',' and ')
    s=re.sub(r'\b(st)\.?\b','saint',s); s=re.sub(r'\b(sree|sri|shree)\b','shri',s)
    return {x for x in re.sub(r'[^a-z0-9]+',' ',s).split() if x not in GENERIC and len(x)>1}
def nscore(a,b):
    ta,tb=tokens(a),tokens(b)
    if not ta or not tb: return 0,0
    common=len(ta&tb); direct=SequenceMatcher(None,' '.join(sorted(ta)),' '.join(sorted(tb))).ratio()*100
    return max(direct,common/min(len(ta),len(tb))*100 if common>=2 else 0),common
def raw_score(a,b):
    def clean(v): return ' '.join(re.sub(r'[^a-z0-9]+',' ',str(v or '').lower()).split())
    return SequenceMatcher(None,clean(a),clean(b)).ratio()*100
def distance(a,b,c,d): return 6371000*math.hypot(math.radians(d-b)*math.cos(math.radians((a+c)/2)),math.radians(c-a))
def grid(r): return (round(float(r['latitude'])/.01),round(float(r['longitude'])/.01))
def main():
    with SOURCE.open(encoding='utf-8',newline='') as f: rows=list(csv.DictReader(f))
    ref=[r for r in rows if valid(r['udise_code'])]; query=[r for r in rows if not valid(r['udise_code'])]
    by_place=defaultdict(set); by_pin=defaultdict(set); by_token=defaultdict(set); by_grid=defaultdict(set)
    for j,r in enumerate(ref):
        if r['google_place_id']: by_place[r['google_place_id']].add(j)
        if r['pincode']: by_pin[r['pincode']].add(j)
        city=r['city'].lower().replace('_',' ')
        for t in tokens(r['school_name']): by_token[(city,t)].add(j)
        by_grid[grid(r)].add(j)
    audit=[]
    for q in query:
        candidates=set(); city=q['city'].lower().replace('_',' ')
        if q['google_place_id']: candidates|=by_place[q['google_place_id']]
        if q['pincode']: candidates|=by_pin[q['pincode']]
        # Avoid broad chain/city tokens (e.g. "delhi" or "dps") that would
        # generate thousands of weak candidates; retain distinctive name terms.
        for t in tokens(q['school_name']):
            bucket=by_token[(city,t)]
            if len(bucket)<=150: candidates|=bucket
        gx,gy=grid(q)
        for x in range(gx-1,gx+2):
            for y in range(gy-1,gy+2): candidates|=by_grid[(x,y)]
        scored=[]
        for j in candidates:
            r=ref[j]; ns,shared=nscore(q['school_name'],r['school_name']); raw=raw_score(q['school_name'],r['school_name']); ad,_=nscore(q['address'],r['address'])
            try: d=distance(float(q['latitude']),float(q['longitude']),float(r['latitude']),float(r['longitude']))
            except: d=999999
            place=bool(q['google_place_id'] and q['google_place_id']==r['google_place_id']); pin=bool(q['pincode'] and q['pincode']==r['pincode'])
            score=(100 if place else 0)+.60*ns+.20*ad+.20*max(0,100-d/30)+(10 if pin else 0)
            eligible=place or (d<=100 and (ns>=70 or ad>=70)) or (ns>=90 and d<=1500) or (ns>=82 and pin and d<=4000)
            if eligible: scored.append((score,ns,raw,ad,d,place,r))
        scored.sort(reverse=True,key=lambda x:x[0]); best=scored[0] if scored else None; gap=(best[0]-scored[1][0]) if len(scored)>1 else 999
        out={'non_udise_school_id':q['school_id'],'non_udise_school_name':q['school_name'],'city':q['city'],'pincode':q['pincode'],'latitude':q['latitude'],'longitude':q['longitude'],'matched_udise_code':'','matched_school_name':'','match_method':'','match_score':'','name_score':'','raw_name_score':'','address_score':'','distance_m':'','confidence':'unmatched'}
        if best:
            score,ns,raw,ad,d,place,r=best; confidence='high' if (place or (raw>=85 and ad>=50 and d<=500 and gap>=4)) else 'medium'
            out.update({'matched_udise_code':r['udise_code'],'matched_school_name':r['school_name'],'match_method':'exact_google_place_id' if place else 'name_address_coordinate','match_score':round(score,1),'name_score':round(ns,1),'raw_name_score':round(raw,1),'address_score':round(ad,1),'distance_m':round(d,1),'confidence':confidence})
        audit.append(out)
    with OUT.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=audit[0]); w.writeheader(); w.writerows(audit)
    print('non_udise',len(query)); print(Counter(x['confidence'] for x in audit)); print(OUT)
if __name__=='__main__': main()
