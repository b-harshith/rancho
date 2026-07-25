#!/usr/bin/env python3
import csv, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
INPUT=ROOT/'data/client_delivery/schools_geocoded_unified_with_campuses.csv'
OUTPUT=ROOT/'data/client_delivery/fee_threshold_expansion_scenarios.png'
CAPACITY=200; OCCUPANCY=.80; EFFECTIVE=160; LEVELS=[.01,.02,.05,.10,.15,.20]
THRESHOLDS=[(100000,'SCENARIO A — FEE ≥ INR 1.0 LAKH'),(160000,'SCENARIO B — FEE ≥ INR 1.6 LAKH'),(200000,'SCENARIO C — FEE ≥ INR 2.0 LAKH')]
NAVY='#102A43'; TEAL='#1B998B'; GOLD='#D9A441'; GRAY='#52606D'; PALE='#EDF5F7'; ROW='#F7FAFC'; LINE='#CFD8E3'
REG='/System/Library/Fonts/Supplemental/Arial.ttf'; BOLD='/System/Library/Fonts/Supplemental/Arial Bold.ttf'
def ft(n,b=False):return ImageFont.truetype(BOLD if b else REG,n)
def n(v):
 try:return float(v or 0)
 except:return 0
def city(c):return {'delhi_ncr':'Delhi NCR','bangalore':'Bangalore'}.get(c,c.title())
def cr(v):return f'INR {v/1e7:,.1f} Cr'
def center(d,b,t,f,color):
 z=d.textbbox((0,0),t,font=f);d.text((b[0]+(b[2]-b[0]-(z[2]-z[0]))/2,b[1]+(b[3]-b[1]-(z[3]-z[1]))/2),t,font=f,fill=color)
def main():
 with open(INPUT,encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
 campuses={}
 for r in rows:campuses.setdefault(r['campus_id'],r)
 city_order=sorted({r['city'] for r in campuses.values()},key=lambda c:int(next(x['city_rank_by_q4_count'] for x in rows if x['city']==c)))
 scenarios=[]
 for threshold,label in THRESHOLDS:
  data=[]
  for c in city_order:
   cohort=[r for r in campuses.values() if r['city']==c and n(r['campus_fee_max'])>=threshold]
   students=sum(n(r['campus_students_grades_2_9']) for r in cohort);market=0
   for r in cohort:
    lo,hi=n(r['campus_fee_min']),n(r['campus_fee_max']);fee=(lo+hi)/2 if lo and hi else hi or lo;market+=n(r['campus_students_grades_2_9'])*fee
   data.append(dict(city=city(c),schools=len(cohort),students=students,market=market,curve=[math.ceil(students*p/EFFECTIVE) for p in LEVELS]))
  scenarios.append((threshold,label,data))
 W,H=3800,3440;im=Image.new('RGB',(W,H),'white');d=ImageDraw.Draw(im)
 d.rectangle((0,0,W,220),fill=NAVY);d.text((90,50),'FEE-THRESHOLD MARKET & CAMPUS EXPANSION SCENARIOS',font=ft(56,True),fill='white');d.text((92,143),'City-wise Grade 2–9 demand and network capacity planning',font=ft(28),fill='#D9EAF0')
 d.rounded_rectangle((70,250,W-70,410),20,fill=PALE)
 assumptions=[('CAMPUS CAPACITY','200 students'),('TARGET OCCUPANCY','80%'),('EFFECTIVE CAPACITY','160 students/campus'),('MAX PENETRATION','20%'),('DELHI TODAY','4 campuses / 800 seats')]
 for i,(a,b) in enumerate(assumptions):x=105+i*725;d.text((x,280),a,font=ft(18,True),fill=GRAY);d.text((x,325),b,font=ft(29,True),fill=NAVY)
 # summary cards
 for i,(threshold,label,data) in enumerate(scenarios):
  schools=sum(x['schools'] for x in data);students=sum(x['students'] for x in data);market=sum(x['market'] for x in data)
  x=70+i*1230;d.rounded_rectangle((x,450,x+1160,630),18,fill='#FBF4E4' if i==1 else ROW,outline='#D6E1E8',width=3)
  d.text((x+35,475),label,font=ft(25,True),fill=NAVY);d.text((x+35,530),f'{schools:,} schools  |  {students:,.0f} students',font=ft(25,True),fill=TEAL);d.text((x+35,580),f'Annual tuition market: {cr(market)}',font=ft(22),fill=GOLD)
 # scenario tables
 headers=['City','Schools','Students','Tuition market','1%','2%','5%','10%','15%','20%'];widths=[450,240,330,420]+[250]*6
 x0=70;xs=[x0]
 for w in widths:xs.append(xs[-1]+w)
 y_starts=[720,1580,2440];rh=82
 for si,((threshold,label,data),y0) in enumerate(zip(scenarios,y_starts)):
  d.text((70,y0-62),label,font=ft(31,True),fill=NAVY);d.text((2300,y0-55),'Campuses required at penetration →',font=ft(20,True),fill=GRAY)
  d.rectangle((x0,y0,xs[-1],y0+rh),fill=NAVY)
  for i,h in enumerate(headers):center(d,(xs[i],y0,xs[i+1],y0+rh),h,ft(19,True),'white')
  total=dict(city='TOTAL',schools=sum(x['schools'] for x in data),students=sum(x['students'] for x in data),market=sum(x['market'] for x in data),curve=[sum(x['curve'][j] for x in data) for j in range(6)])
  for ri,r in enumerate(data+[total]):
   y=y0+(ri+1)*rh;fill='#FBF4E4' if r['city']=='TOTAL' else (ROW if ri%2 else 'white');d.rectangle((x0,y,xs[-1],y+rh),fill=fill,outline=LINE,width=2)
   vals=[r['city'],f"{r['schools']:,}",f"{r['students']:,.0f}",cr(r['market'])]+[f'{z:,}' for z in r['curve']]
   for i,v in enumerate(vals):center(d,(xs[i],y,xs[i+1],y+rh),v,ft(18,True if r['city']=='TOTAL' or i==0 else False),NAVY)
 # footer
 d.line((70,3260,W-70,3260),fill=LINE,width=3)
 d.text((70,3290),'Method: scenario cohort includes campuses whose annual advertised fee_max meets the threshold. Tuition market = fee midpoint × Grade 2–9 enrollment.',font=ft(20),fill=GRAY)
 d.text((70,3335),'Campus requirements are rounded up using 160 occupied students per campus. Delhi’s four existing campuses are not deducted from city totals shown above.',font=ft(20),fill=GRAY)
 d.text((70,3380),'Directional planning model; validate catchments, enrollment estimates and current fee schedules before committing sites.',font=ft(18),fill='#7B8794')
 im.save(OUTPUT,optimize=True);print('Saved',OUTPUT)
 for threshold,label,data in scenarios:print(label,sum(x['schools'] for x in data),sum(x['students'] for x in data),sum(x['market'] for x in data))
if __name__=='__main__':main()
