#!/usr/bin/env python3
import csv, json, re, ssl, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
UDISE=ROOT/'data/output/schools_analysis_delhi_ncr_compact.json'
AGG=ROOT/'data/client_delivery/schools_geocoded_unified_with_campuses.csv'
OUT=ROOT/'data/output/official_fee_pilot_500.csv'
CITIES={
'Delhi NCR':lambda st,di:st=='DELHI' or any(x in di for x in ('GAUTAM BUDDHA','GURUGRAM','GHAZIABAD','FARIDABAD')),
'Bangalore':lambda st,di:any(x in di for x in ('BENGALURU U NORTH','BENGALURU U SOUTH','BENGALURU RURAL')),
'Hyderabad':lambda st,di:any(x in di for x in ('HYDERABAD','RANGA REDDY','MEDCHAL','SANGAREDDY')),
'Mumbai':lambda st,di:any(x in di for x in ('MUMBAI','SUBURBAN','THANE')),
'Chennai':lambda st,di:any(x in di for x in ('CHENNAI','KANCHIPURAM','KANCHEEPURAM','THIRUVALLUR','TIRUVALLUR')),
'Kolkata':lambda st,di:any(x in di for x in ('KOLKATA','24 PARGANAS','HOWRAH','HOOGHLY')),
'Pune':lambda st,di:'PUNE' in di}
PATHS=('','fees','fee-structure','admissions','admission','mandatory-public-disclosure')
KW=re.compile(r'fee structure|tuition fee|annual fee|school fee|fees for|fee schedule',re.I)
AMOUNT=re.compile(r'(?:₹|rs\.?|inr)\s*([0-9][0-9,]{3,})',re.I)
YEAR=re.compile(r'20(?:2[4-9])\s*[-–/]\s*(?:20)?(?:2[5-9])')
HREF=re.compile(r'href=["\']([^"\']+)["\']',re.I)
TAG=re.compile(r'<[^>]+>'); SPACE=re.compile(r'\s+')

def num(v):
 try:return float(v or 0)
 except:return 0
def normalize_url(w):
 w=w.strip()
 if not re.match(r'^https?://',w,re.I):w='https://'+w
 return w
def fetch(url):
 req=Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; SchoolFeeResearch/1.0)'})
 ctx=ssl.create_default_context()
 with urlopen(req,timeout=10,context=ctx) as r:
  ctype=r.headers.get('Content-Type',''); final=r.geturl(); body=r.read(1500000)
 return final,ctype,body
def inspect(rec):
 base=normalize_url(rec['website']); candidates=[urljoin(base.rstrip('/')+'/',p) for p in PATHS]
 seen=set(); pages=[]; errors=[]
 for url in candidates:
  if url in seen:continue
  seen.add(url)
  try:
   final,ctype,body=fetch(url)
   if 'pdf' in ctype.lower() or final.lower().endswith('.pdf'):
    pages.append((final,'pdf','',[],[]));continue
   text=body.decode('utf-8','ignore')
   plain=SPACE.sub(' ',TAG.sub(' ',text))
   if KW.search(plain):
    amounts=sorted({int(x.replace(',','')) for x in AMOUNT.findall(plain) if 1000<=int(x.replace(',',''))<=2000000})
    pages.append((final,'html',plain[:500],amounts[:20],YEAR.findall(plain)[:5]))
   for h in HREF.findall(text):
    if re.search(r'fee|admission|disclosure',h,re.I):
     link=urljoin(final,h)
     if urlparse(link).netloc==urlparse(final).netloc and link not in seen and len(candidates)<12:candidates.append(link)
  except Exception as e:errors.append(type(e).__name__)
 best=next((p for p in pages if p[3]),pages[0] if pages else None)
 return {**rec,'status':'candidate_found' if best else 'not_found','evidence_url':best[0] if best else '',
  'evidence_type':best[1] if best else '','amount_candidates':'|'.join(map(str,best[3])) if best else '',
  'academic_years':'|'.join(best[4]) if best else '','pages_with_fee_evidence':len(pages),'errors':'|'.join(sorted(set(errors)))}

def main():
 fee_codes=set()
 with open(AGG,encoding='utf-8-sig') as f:
  for r in csv.DictReader(f):
   if max(num(r.get('fee')),num(r.get('fee_min')),num(r.get('fee_max'))) > 0:
    fee_codes.update(x.strip() for x in str(r.get('udise_code') or '').split('|') if x.strip())
 doc=json.loads(UDISE.read_text()); pools=defaultdict(list)
 for s in doc['schools']:
  m=s.get('metadata') or {};code=str(s['udise_code'])
  if code in fee_codes or (m.get('management') or '').strip() not in ('Private Unaided (Recognized)','Madrasa Private Unaided (Recognized)'):continue
  try: high=int(m.get('highest_class'))
  except: high=None
  e=s.get('enrollment') or {}; total=num((e.get('all') or {}).get('total'))
  w=str(((m.get('contact') or {}).get('website') or '')).strip()
  if high==2 or total<=0 or not w or '.' not in w or ' ' in w:continue
  loc=m.get('location') or {};st=(loc.get('state') or '').upper();di=(loc.get('district') or '').upper()
  for city,fn in CITIES.items():
   if fn(st,di):pools[city].append({'city':city,'udise_code':code,'school_name':m.get('school_name'),'address':m.get('address'),'website':w,'total_enrollment':int(total),'grades_2_9':int(num((e.get('grades_2_9') or {}).get('total')))});break
 sample=[];quota=500//len(CITIES)
 for city in CITIES:sample.extend(sorted(pools[city],key=lambda x:x['udise_code'])[:quota])
 remaining=500-len(sample)
 leftovers=[r for c in CITIES for r in sorted(pools[c],key=lambda x:x['udise_code'])[quota:]]
 sample.extend(leftovers[:remaining])
 results=[]
 with ThreadPoolExecutor(max_workers=12) as ex:
  futs=[ex.submit(inspect,r) for r in sample]
  for i,f in enumerate(as_completed(futs),1):
   results.append(f.result())
   if i%50==0:print(f'Completed {i}/500',flush=True)
 fields=['city','udise_code','school_name','address','website','total_enrollment','grades_2_9','status','evidence_url','evidence_type','amount_candidates','academic_years','pages_with_fee_evidence','errors']
 OUT.parent.mkdir(parents=True,exist_ok=True)
 with open(OUT,'w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(sorted(results,key=lambda x:(x['city'],x['school_name'] or '')))
 print('candidate_found',sum(x['status']=='candidate_found' for x in results));print(OUT)
if __name__=='__main__':main()
