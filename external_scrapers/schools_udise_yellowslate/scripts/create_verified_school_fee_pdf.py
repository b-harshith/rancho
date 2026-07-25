#!/usr/bin/env python3
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pdf/verified_school_enrollment_and_fees.pdf"

rows = [
('Delhi International School Edge','07080313651','Sector 18, Dwarka, New Delhi 110075','1,037','730','₹1,12,080-₹1,44,300','Ezyschooling','https://ezyschooling.com/school/delhi-international-school-edge-dis-edge-sector-18-dwarka-delhi'),
('Delhi Public School, Dwarka Expressway','06180101705','Sector 102A, Dwarka Expressway, Gurugram','1,278','919','₹1,57,616-₹1,92,016','Ezyschooling','https://ezyschooling.com/school/delhi-public-school-dwarka-expressway-sector-103-gurgaon'),
('St. Thomas School, Indirapuram','09090907605','Gyan Khand II, Indirapuram, Ghaziabad','2,124','1,434','₹62,340-₹95,820','Ezyschooling','https://ezyschooling.com/school/st-thomas-school-indirapuram-ghaziabad'),
('Panchsheel Public School','07090320101','H-Block, Jaitpur, Badarpur, New Delhi','2,480','1,766','₹36,485-₹68,490','Ezyschooling','https://ezyschooling.com/school/panchsheel-public-school-jaitpur-south-east-delhi'),
('Ralli International School','09090907903','Niti Khand III, Indirapuram, Ghaziabad 201014','1,887','1,348','₹62,280-₹86,340','Ezyschooling','https://ezyschooling.com/school/ralli-international-school-indirapuram-ghaziabad'),
('Clarence High School','29280601008','Richards Town, Bengaluru','1,483','1,187','₹1,00,000','Yellow Slate','https://yellowslate.com/school/bengaluru/clarence-high-school-sagayapura-richards-town'),
("St. Peter's Convent School",'06191604322','Sector 88, Greater Faridabad, Haryana 121002','1,549','1,302','₹1,31,600-₹1,74,600','Ezyschooling','https://ezyschooling.com/school/st-peters-convent-school-greater-faridabad-faridabad'),
('Suncity School, Sector 37D','06184100213','Sector 37D, Basai, Gurugram','981','799','₹1,80,720-₹2,34,280','Ezyschooling','https://ezyschooling.com/school/suncity-school-sector-37-d-gurgaon'),
('Salwan Public School','07060314902','Rajinder Nagar, New Delhi','2,998','1,943','₹1,29,300-₹1,68,660','Ezyschooling','https://ezyschooling.com/school/salwan-public-school-rajender-nagar-central-delhi'),
('Gyan Bharati School','07090316902','Saket, near PVR, New Delhi','2,186','1,575','₹96,600-₹1,23,000','Ezyschooling','https://ezyschooling.com/school/gyan-bharati-school-saket-south-delhi'),
('Seth Anandram Jaipuria School','09090905017','Sector 14C, Vasundhara, Ghaziabad 201012','4,431','3,027','₹1,42,788-₹1,65,576','Ezyschooling','https://ezyschooling.com/school/seth-anandram-jaipuria-school-vasundhara-ghaziabad'),
]

def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Use INR text instead of a currency glyph so the PDF renders consistently
    # across phones and WhatsApp preview engines.
    global rows
    rows = [tuple(value.replace('₹', 'INR ') if i == 5 else value for i, value in enumerate(row)) for row in rows]
    font_path = '/System/Library/Fonts/Supplemental/Arial Unicode.ttf'
    if Path(font_path).exists():
        pdfmetrics.registerFont(TTFont('Unicode', font_path)); font='Unicode'
    else: font='Helvetica'
    doc=SimpleDocTemplate(str(OUT),pagesize=landscape(A4),rightMargin=10*mm,leftMargin=10*mm,topMargin=10*mm,bottomMargin=10*mm,
        title='Verified School Enrollment and Fee Records')
    styles=getSampleStyleSheet()
    title=ParagraphStyle('title',parent=styles['Title'],fontName=font,fontSize=17,leading=21,textColor=colors.HexColor('#16324F'),spaceAfter=3*mm)
    sub=ParagraphStyle('sub',parent=styles['Normal'],fontName=font,fontSize=8.5,leading=11,textColor=colors.HexColor('#52606D'),alignment=TA_CENTER,spaceAfter=5*mm)
    cell=ParagraphStyle('cell',fontName=font,fontSize=7.2,leading=9.2,textColor=colors.HexColor('#263238'),alignment=TA_LEFT)
    num=ParagraphStyle('num',parent=cell,alignment=TA_CENTER)
    head=ParagraphStyle('head',parent=cell,fontSize=7.3,leading=9,textColor=colors.white,alignment=TA_CENTER)
    link=ParagraphStyle('link',parent=num,textColor=colors.HexColor('#0B67B2'))
    story=[]
    data=[[Paragraph(x,head) for x in ['School','UDISE code','Address','Total enrollment','Grades 2-9 enrollment','Valid annual fee','Fee source']]]
    for school,code,address,total,g29,fee,source,url in rows:
        data.append([Paragraph(school,cell),Paragraph(code,num),Paragraph(address,cell),Paragraph(total,num),Paragraph(g29,num),Paragraph(fee,num),Paragraph(f'<link href="{url}"><u>{source}</u></link>',link)])
    table=Table(data,colWidths=[47*mm,26*mm,61*mm,24*mm,23*mm,36*mm,25*mm],repeatRows=1)
    table.setStyle(TableStyle([
      ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#16324F')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
      ('GRID',(0,0),(-1,-1),0.35,colors.HexColor('#CBD5E1')),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
      ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
      ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F4F7FA')]),
    ]))
    story.append(table)
    doc.build(story)
    print(OUT)
if __name__=='__main__': main()
