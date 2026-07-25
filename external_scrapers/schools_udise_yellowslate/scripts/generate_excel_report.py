import json
import pandas as pd
from pathlib import Path

# Paths
DATA_DIR = Path('/Users/malleswararao/Desktop/school extraction/data/output')
BLR_FILE = Path('/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/src/public/data/school_entities.json')
OUTPUT_EXCEL = Path('/Users/malleswararao/Desktop/school extraction/data/output/Premium_Schools_Report.xlsx')

CITIES = ['delhi_ncr', 'mumbai', 'hyderabad', 'chennai', 'kolkata', 'pune']

def get_bracket(fee):
    if fee > 200000:
        return "> 2 Lakhs"
    elif fee > 160000:
        return "1.6 - 2 Lakhs"
    elif fee >= 100000:
        return "1 - 1.6 Lakhs"
    return "Below 1 Lakh"

def clean_udise(code):
    if not code or str(code).strip() in ('', 'NA', 'N/A', 'None'):
        return "predicted based on fee band and grades offered"
    return str(code).strip()

def main():
    all_schools = []
    
    # Load other cities
    for city in CITIES:
        fpath = DATA_DIR / f'schools_{city}_final.json'
        if fpath.exists():
            with open(fpath) as f:
                schools = json.load(f)
                for s in schools:
                    fee = s.get('fee', 0) or 0
                    if fee >= 100000:
                        g2_9 = int(s.get('student_enrollment_grades_2_9', 0) or 0)
                        if g2_9 == 0:
                            continue
                        all_schools.append({
                            'city': city,
                            'name': s.get('name'),
                            'fee': fee,
                            'bracket': get_bracket(fee),
                            'board': s.get('board', 'CBSE'),
                            'url': s.get('url', 'NA'),
                            'students': int(s.get('students', 0) or 0),
                            'g2_9': g2_9,
                            'udise_code': clean_udise(s.get('udise_code'))
                        })

    # Load Bangalore
    if BLR_FILE.exists():
        with open(BLR_FILE) as f:
            blr_schools = json.load(f)
            for s in blr_schools:
                fee_min = s.get('fee_min')
                fee_max = s.get('fee_max')
                fee = 0
                if fee_min is not None and fee_max is not None:
                    fee = (fee_min + fee_max) / 2
                elif fee_min is not None:
                    fee = fee_min
                elif fee_max is not None:
                    fee = fee_max
                
                if fee >= 100000:
                    g2_9 = int(s.get('students_grades_2_9', 0) or 0)
                    if g2_9 == 0:
                        continue
                    boards_list = s.get('boards')
                    if isinstance(boards_list, list):
                        boards_str = ", ".join(b.upper() for b in boards_list)
                    else:
                        boards_str = str(boards_list or 'CBSE')
                        
                    udise_codes_list = s.get('udise_codes')
                    if isinstance(udise_codes_list, list):
                        udise_str = ", ".join(udise_codes_list) if udise_codes_list else 'NA'
                    else:
                        udise_str = str(udise_codes_list or 'NA')
                        
                    all_schools.append({
                        'city': 'bangalore',
                        'name': s.get('name'),
                        'fee': fee,
                        'bracket': get_bracket(fee),
                        'board': boards_str,
                        'url': s.get('url', 'NA'),
                        'students': int(s.get('students_total', 0) or s.get('students', 0) or 0),
                        'g2_9': g2_9,
                        'udise_code': clean_udise(udise_str)
                    })

    df = pd.DataFrame(all_schools)
    
    # Generate Summary Stats
    summary_list = []
    
    # Combined Stats Helper
    def get_summary_row(data_subset, label):
        return {
            'Fee Bracket': label,
            'Schools': len(data_subset),
            'Total Students': int(data_subset['students'].sum()),
            'Grade 2-9 Students': int(data_subset['g2_9'].sum())
        }
        
    summary_list.append(get_summary_row(df[df['fee'] > 200000], 'Above 2 Lakhs (Combined)'))
    summary_list.append(get_summary_row(df[df['fee'] > 160000], 'Above 1.6 Lakhs (Combined)'))
    summary_list.append(get_summary_row(df[df['fee'] >= 100000], 'Above 1 Lakh (Combined)'))
    
    summary_combined_df = pd.DataFrame(summary_list)
    
    city_summaries = []
    for city in ['bangalore'] + CITIES:
        city_subset = df[df['city'] == city]
        city_label = city.replace('_', ' ').title()
        
        city_summaries.append({
            'City': city_label,
            'Bracket': 'Above 2 Lakhs',
            'Schools': len(city_subset[city_subset['fee'] > 200000]),
            'Total Students': int(city_subset[city_subset['fee'] > 200000]['students'].sum()),
            'Grade 2-9 Students': int(city_subset[city_subset['fee'] > 200000]['g2_9'].sum())
        })
        city_summaries.append({
            'City': city_label,
            'Bracket': 'Above 1.6 Lakhs',
            'Schools': len(city_subset[city_subset['fee'] > 160000]),
            'Total Students': int(city_subset[city_subset['fee'] > 160000]['students'].sum()),
            'Grade 2-9 Students': int(city_subset[city_subset['fee'] > 160000]['g2_9'].sum())
        })
        city_summaries.append({
            'City': city_label,
            'Bracket': 'Above 1 Lakh',
            'Schools': len(city_subset[city_subset['fee'] >= 100000]),
            'Total Students': int(city_subset[city_subset['fee'] >= 100000]['students'].sum()),
            'Grade 2-9 Students': int(city_subset[city_subset['fee'] >= 100000]['g2_9'].sum())
        })
        
    summary_city_df = pd.DataFrame(city_summaries)

    # Start writing Excel
    with pd.ExcelWriter(OUTPUT_EXCEL, engine='openpyxl') as writer:
        # Write Summary tab
        workbook = writer.book
        
        # We write combined stats first
        summary_combined_df.to_excel(writer, sheet_name='Summary Metrics', index=False, startrow=1, startcol=1)
        
        # Write city wise stats
        summary_city_df.to_excel(writer, sheet_name='Summary Metrics', index=False, startrow=7, startcol=1)
        
        # Add labels to the Summary sheet
        worksheet = writer.sheets['Summary Metrics']
        worksheet.cell(row=1, column=2, value="COMBINED METRICS")
        worksheet.cell(row=7, column=2, value="CITY-WISE BREAKDOWN")
        
        # Write each city tab
        for city in ['bangalore'] + CITIES:
            city_subset = df[df['city'] == city]
            if city_subset.empty:
                continue
                
            city_tab_name = city.replace('_', ' ').title()
            
            # Format city columns
            city_export = city_subset[['name', 'udise_code', 'bracket', 'fee', 'board', 'url', 'students']].copy()
            city_export.columns = ['School Name', 'UDISE ID', 'Fee Bracket', 'Annual Fee (INR)', 'Affiliated Board', 'School URL', 'Total Enrollment']
            
            city_export.to_excel(writer, sheet_name=city_tab_name, index=False)
            
            # Auto-fit columns
            ws = writer.sheets[city_tab_name]
            for col in ws.columns:
                max_len = max(len(str(cell.value or '')) for cell in col)
                col_letter = col[0].column_letter
                ws.column_dimensions[col_letter].width = max(max_len + 3, 12)
                
        # Format Summary tab column width
        ws_sum = writer.sheets['Summary Metrics']
        for col in ws_sum.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = col[0].column_letter
            ws_sum.column_dimensions[col_letter].width = max(max_len + 3, 12)
            
    print(f"Excel report successfully generated at {OUTPUT_EXCEL}")

if __name__ == "__main__":
    main()
