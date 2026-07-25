#!/usr/bin/env python3
"""Local sparse TF-IDF vector index for unresolved non-UDISE school candidates."""
import csv, math, re
from collections import Counter, defaultdict
from pathlib import Path

ROOT=Path(__file__).parent.parent
SOURCE=ROOT/'schools'/'final_schools_deduplicated.csv'
OUT=ROOT/'schools'/'remaining_non_udise_vector_candidates.csv'
GENERIC={'school','public','private','international','senior','secondary','higher','high','english','medium','education','educational','academy','convent','campus','branch','cbse','icse','igcse','ib','board','the','of','at','in','and'}
def valid(v):return bool(re.fullmatch(r'\d{11}',(v or '').strip()))
def words(v):return re.sub(r'[^a-z0-9]+',' ',str(v or '').lower()).split()
def features(r):
    n=[x for x in words(r['school_name']) if x not in GENERIC]
    a=[x for x in words(r['address']) if len(x)>2 and x not in GENERIC]
    # Name word/character n-grams receive repeated weight; location tokens retain branch context.
    f=['n:'+x for x in n]*3+['a:'+x for x in a]+(['p:'+r['pincode']]*2 if r['pincode'] else [])+['c:'+r['city'].lower().replace('_',' ')]
    joined=' '.join(n)
    f += ['g:'+joined[i:i+3] for i in range(max(0,len(joined)-2))]
    return Counter(f)
def raw_ratio(a,b):
    from difflib import SequenceMatcher
    return SequenceMatcher(None,' '.join(words(a)),' '.join(words(b))).ratio()*100
def distance(a,b,c,d):return 6371000*math.hypot(math.radians(d-b)*math.cos(math.radians((a+c)/2)),math.radians(c-a))
def city_key(v):return re.sub(r'[_\s]+',' ',str(v or '').strip().lower()).replace('bangalore','bengaluru')
def main():
    with SOURCE.open(encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
    ref=[r for r in rows if valid(r['udise_code'])]; query=[r for r in rows if not valid(r['udise_code'])]
    docs=[features(r) for r in ref]; df=Counter()
    for d in docs:df.update(d.keys())
    n=len(ref); idf={k:math.log((n+1)/(v+1))+1 for k,v in df.items()}
    postings=defaultdict(list); norms=[]
    for j,d in enumerate(docs):
        norm=math.sqrt(sum((tf*idf[x])**2 for x,tf in d.items()));norms.append(norm)
        for x,tf in d.items():postings[x].append((j,tf*idf[x]))
    output=[]
    for q in query:
        qf=features(q);qn=math.sqrt(sum((tf*idf.get(x,0))**2 for x,tf in qf.items()));acc=defaultdict(float)
        for x,tf in qf.items():
            qw=tf*idf.get(x,0)
            for j,dw in postings.get(x,[]):acc[j]+=qw*dw
        scored=[(s/(qn*norms[j]),j) for j,s in acc.items() if qn and norms[j]]
        local=[x for x in scored if city_key(ref[x[1]]['city'])==city_key(q['city'])]
        ranked=[]
        for cos,j in (local or scored):
            r=ref[j]
            try:d=distance(float(q['latitude']),float(q['longitude']),float(r['latitude']),float(r['longitude']))
            except:d=999999
            adjusted=cos+.25*math.exp(-d/1000)+(.10 if q['pincode'] and q['pincode']==r['pincode'] else 0)
            ranked.append((adjusted,cos,j,d))
        ranked=sorted(ranked,reverse=True)[:5]
        for rank,(adjusted,cos,j,d) in enumerate(ranked,1):
            r=ref[j]
            output.append({'non_udise_school_id':q['school_id'],'non_udise_school_name':q['school_name'],'city':q['city'],'pincode':q['pincode'],'latitude':q['latitude'],'longitude':q['longitude'],'candidate_rank':rank,'candidate_udise_code':r['udise_code'],'candidate_school_name':r['school_name'],'candidate_city':r['city'],'candidate_pincode':r['pincode'],'candidate_latitude':r['latitude'],'candidate_longitude':r['longitude'],'vector_cosine_score':round(cos,4),'reranked_score':round(adjusted,4),'raw_name_similarity':round(raw_ratio(q['school_name'],r['school_name']),1),'distance_m':round(d,1),'same_pincode':bool(q['pincode'] and q['pincode']==r['pincode'])})
    with OUT.open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=output[0]);w.writeheader();w.writerows(output)
    top=[x for x in output if x['candidate_rank']==1]
    print('queries',len(query),'candidates',len(output));print('top score >=.80',sum(x['vector_cosine_score']>=.8 for x in top));print(OUT)
if __name__=='__main__':main()
