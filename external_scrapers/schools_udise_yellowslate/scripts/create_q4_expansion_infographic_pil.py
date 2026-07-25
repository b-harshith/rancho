#!/usr/bin/env python3
import csv, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
INPUT=ROOT/'data/client_delivery/schools_geocoded_unified_with_campuses.csv'
OUTPUT=ROOT/'data/client_delivery/q4_market_expansion_matrix.png'
CAPACITY,OCCUPANCY=200,.80; EFFECTIVE=160
LEVELS=[.01,.02,.05,.10,.15,.20,.25]
NAVY='#102A43'; BLUE='#176B87'; TEAL='#1B998B'; GOLD='#D9A441'; GRAY='#52606D'; PALE='#EDF5F7'
REG='/System/Library/Fonts/Supplemental/Arial.ttf'; BOLD='/System/Library/Fonts/Supplemental/Arial Bold.ttf'
def font(n,b=False): return ImageFont.truetype(BOLD if b else REG,n)
def num(v):
 try:return float(v or 0)
 except:return 0
def city_name(c): return {'delhi_ncr':'Delhi NCR','bangalore':'Bangalore'}.get(c,c.title())
def cr(v):return f'INR {v/1e7:,.1f} Cr'
def lakh(v):return f'INR {v/1e5:.2f}L'
def centered(d,box,text,f,fill):
 b=d.textbbox((0,0),text,font=f); d.text((box[0]+(box[2]-box[0]-(b[2]-b[0]))/2,box[1]+(box[3]-box[1]-(b[3]-b[1]))/2),text,font=f,fill=fill)
def main():
 with open(INPUT,encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
 camps={}
 for r in rows:camps.setdefault(r['campus_id'],r)
 cities=[]
 order=sorted({r['city'] for r in camps.values()},key=lambda c:int(next(x['city_rank_by_q4_count'] for x in rows if x['city']==c)))
 for c in order:
  q=[r for r in camps.values() if r['city']==c and r['fee_quartile']=='Q4']; students=sum(num(r['campus_students_grades_2_9']) for r in q)
  fees=[num(r['campus_fee_max']) for r in q if num(r['campus_fee_max'])>0]; market=0
  for r in q:
   lo,hi=num(r['campus_fee_min']),num(r['campus_fee_max']); fee=(lo+hi)/2 if lo and hi else hi or lo; market+=num(r['campus_students_grades_2_9'])*fee
  cities.append(dict(key=c,name=city_name(c),q4=len(q),students=students,start=min(fees),end=max(fees),market=market,curve=[math.ceil(students*p/EFFECTIVE) for p in LEVELS]))
 tq=sum(x['q4'] for x in cities); ts=sum(x['students'] for x in cities); tm=sum(x['market'] for x in cities); tc=[sum(x['curve'][i] for x in cities) for i in range(7)]
 W,H=3600,2600; im=Image.new('RGB',(W,H),'white');d=ImageDraw.Draw(im)
 # Header
 d.rectangle((0,0,W,220),fill=NAVY);d.text((90,55),'Q4 SCHOOL MARKET & CAMPUS EXPANSION MATRIX',font=font(58,True),fill='white');d.text((92,145),'City-specific premium school demand • Grade 2–9 market • Annual fee economics',font=font(28),fill='#D9EAF0')
 # assumptions
 d.rounded_rectangle((70,250,W-70,410),20,fill=PALE)
 assumptions=[('CAMPUS CAPACITY','200 students'),('TARGET OCCUPANCY','80%'),('EFFECTIVE CAPACITY','160 students/campus'),('DELHI FOOTPRINT','4 campuses / 800 seats')]
 for i,(a,b) in enumerate(assumptions):x=110+i*850;d.text((x,280),a,font=font(20,True),fill=GRAY);d.text((x,325),b,font=font(34,True),fill=NAVY)
 # kpis
 kpis=[(f'{tq:,}','Q4 CAMPUSES'),(f'{ts:,.0f}','TARGET STUDENTS'),(cr(tm),'ANNUAL TUITION MARKET'),('7','CITIES')]
 for i,(v,l) in enumerate(kpis):x=70+i*875;d.rounded_rectangle((x,450,x+820,620),16,fill='#F7FAFC',outline='#D6E1E8',width=3);centered(d,(x,465,x+820,550),v,font(44,True),GOLD if i==2 else NAVY);centered(d,(x,545,x+820,605),l,font(19,True),GRAY)
 d.text((70,665),'CITY-WISE Q4 MARKET AND CAMPUSES REQUIRED AT TARGET PENETRATION',font=font(32,True),fill=NAVY)
 # table
 headers=['City','Q4','Students','Q4 fee bracket','Tuition market','1%','2%','5%','10%','15%','20%','25%']; widths=[390,170,260,430,360]+[190]*7
 x0,y0=70,725; rh=105; xs=[x0]
 for w in widths:xs.append(xs[-1]+w)
 d.rectangle((x0,y0,xs[-1],y0+rh),fill=NAVY)
 for i,h in enumerate(headers):centered(d,(xs[i],y0,xs[i+1],y0+rh),h,font(19,True),'white')
 table=cities+[dict(name='TOTAL',q4=tq,students=ts,start=0,end=0,market=tm,curve=tc)]
 for ri,r in enumerate(table):
  y=y0+(ri+1)*rh; fill='#FBF4E4' if ri==len(table)-1 else ('#F7FAFC' if ri%2 else 'white');d.rectangle((x0,y,xs[-1],y+rh),fill=fill,outline='#CFD8E3',width=2)
  vals=[r['name'],f"{r['q4']:,}",f"{r['students']:,.0f}",'—' if r['name']=='TOTAL' else f"{lakh(r['start'])}–{lakh(r['end'])}",cr(r['market'])]+[f'{z:,}' for z in r['curve']]
  for i,v in enumerate(vals):centered(d,(xs[i],y,xs[i+1],y+rh),v,font(18,True if ri==len(table)-1 or i==0 else False),NAVY)
 # bar chart
 cy=1740;d.text((70,cy),'Q4 ADDRESSABLE STUDENTS',font=font(30,True),fill=NAVY);maxs=max(x['students'] for x in cities)
 for i,r in enumerate(cities):y=1800+i*75;d.text((70,y+10),r['name'],font=font(20,True),fill=NAVY);bw=int(1100*r['students']/maxs);d.rounded_rectangle((330,y,330+bw,y+44),8,fill=TEAL);d.text((350+bw,y+8),f"{r['students']:,.0f}",font=font(18),fill=GRAY)
 # Delhi callout
 delhi=next(x for x in cities if x['key']=='delhi_ncr'); new=[max(0,n-4) for n in delhi['curve']]; pen=800/delhi['students']*100
 d.rounded_rectangle((1850,1740,3530,2285),18,fill='#FFF7E6',outline='#E8C36A',width=3);d.text((1900,1785),'DELHI BASELINE & EXPANSION',font=font(30,True),fill=NAVY);d.text((1900,1845),f'Current implied Q4 penetration: {pen:.2f}%',font=font(25,True),fill=GOLD)
 d.text((1900,1905),'Additional campuses required after existing 4:',font=font(22),fill=GRAY)
 for i,(p,n) in enumerate(zip(LEVELS,new)):x=1900+(i%4)*390;y=1970+(i//4)*105;d.rounded_rectangle((x,y,x+350,y+75),10,fill='white',outline='#E8C36A');centered(d,(x,y,x+350,y+75),f'{int(p*100)}% → {n}',font(21,True),NAVY)
 # footer
 d.line((70,2380,W-70,2380),fill='#CBD5E0',width=3);d.text((70,2410),'Expansion priority by Q4 students: Bangalore → Delhi NCR → Hyderabad → Mumbai → Chennai → Pune / Kolkata',font=font(23,True),fill=NAVY)
 note='Fee bracket = lowest to highest annual fee_max within each city Q4. Tuition market = annual fee midpoint × Grade 2–9 enrollment. Campus requirements are rounded up at 160 occupied seats.'
 d.text((70,2470),note,font=font(18),fill=GRAY);d.text((70,2520),'Directional planning model; validate local catchments, enrollment estimates and advertised fees before committing sites.',font=font(17),fill='#7B8794')
 im.save(OUTPUT,optimize=True);print('Saved',OUTPUT);print('Fee ranges:',[(x['name'],lakh(x['start']),lakh(x['end'])) for x in cities])
if __name__=='__main__':main()
