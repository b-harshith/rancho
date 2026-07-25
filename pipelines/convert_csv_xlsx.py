#!/usr/bin/env python3
import os
import pandas as pd
import xlsxwriter
from pathlib import Path

# Define paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = str(PROJECT_ROOT / "final_data" / "multicity_source")
OUTPUT_PATH = str(PROJECT_ROOT / "final_data" / "final_data_consolidated.xlsx")

# Mapping of sheets to their respective CSV files
FILES_MAP = {
    "Projects": os.path.join(DATA_DIR, "Projects/magicbricks_projects_final_master.csv"),
    "Hospitals": os.path.join(DATA_DIR, "hospitals/hospitals_all_cities.csv"),
    "Localities": os.path.join(DATA_DIR, "localities/real_estate_localities_and_societies.csv"),
    "Offices": os.path.join(DATA_DIR, "offices/offices_unified_all_cities.csv"),
    "Schools": os.path.join(DATA_DIR, "schools/final_schools.csv")
}

def style_excel():
    print("Starting conversion to Excel using xlsxwriter...")
    
    # Create workbook
    workbook = xlsxwriter.Workbook(OUTPUT_PATH, {'strings_to_urls': False})
    
    # Formats definition
    font_name = 'Segoe UI'
    
    header_format = workbook.add_format({
        'bold': True,
        'font_name': font_name,
        'font_size': 11,
        'font_color': '#FFFFFF',
        'bg_color': '#1F4E79',
        'align': 'center',
        'valign': 'vcenter',
        'text_wrap': True,
        'border': 1,
        'border_color': '#E0E0E0'
    })
    
    # Text formats
    left_odd = workbook.add_format({
        'font_name': font_name,
        'font_size': 10,
        'bg_color': '#FFFFFF',
        'valign': 'vcenter',
        'border': 1,
        'border_color': '#E0E0E0'
    })
    left_even = workbook.add_format({
        'font_name': font_name,
        'font_size': 10,
        'bg_color': '#F8F9FA',
        'valign': 'vcenter',
        'border': 1,
        'border_color': '#E0E0E0'
    })

    # Integer formats
    int_odd = workbook.add_format({
        'font_name': font_name,
        'font_size': 10,
        'bg_color': '#FFFFFF',
        'align': 'right',
        'valign': 'vcenter',
        'num_format': '#,##0',
        'border': 1,
        'border_color': '#E0E0E0'
    })
    int_even = workbook.add_format({
        'font_name': font_name,
        'font_size': 10,
        'bg_color': '#F8F9FA',
        'align': 'right',
        'valign': 'vcenter',
        'num_format': '#,##0',
        'border': 1,
        'border_color': '#E0E0E0'
    })

    # Float formats
    float_odd = workbook.add_format({
        'font_name': font_name,
        'font_size': 10,
        'bg_color': '#FFFFFF',
        'align': 'right',
        'valign': 'vcenter',
        'num_format': '#,##0.00',
        'border': 1,
        'border_color': '#E0E0E0'
    })
    float_even = workbook.add_format({
        'font_name': font_name,
        'font_size': 10,
        'bg_color': '#F8F9FA',
        'align': 'right',
        'valign': 'vcenter',
        'num_format': '#,##0.00',
        'border': 1,
        'border_color': '#E0E0E0'
    })

    # Coordinate formats
    coord_odd = workbook.add_format({
        'font_name': font_name,
        'font_size': 10,
        'bg_color': '#FFFFFF',
        'align': 'center',
        'valign': 'vcenter',
        'num_format': '0.000000',
        'border': 1,
        'border_color': '#E0E0E0'
    })
    coord_even = workbook.add_format({
        'font_name': font_name,
        'font_size': 10,
        'bg_color': '#F8F9FA',
        'align': 'center',
        'valign': 'vcenter',
        'num_format': '0.000000',
        'border': 1,
        'border_color': '#E0E0E0'
    })

    # Center-aligned formats
    center_odd = workbook.add_format({
        'font_name': font_name,
        'font_size': 10,
        'bg_color': '#FFFFFF',
        'align': 'center',
        'valign': 'vcenter',
        'border': 1,
        'border_color': '#E0E0E0'
    })
    center_even = workbook.add_format({
        'font_name': font_name,
        'font_size': 10,
        'bg_color': '#F8F9FA',
        'align': 'center',
        'valign': 'vcenter',
        'border': 1,
        'border_color': '#E0E0E0'
    })

    for sheet_name, csv_path in FILES_MAP.items():
        if not os.path.exists(csv_path):
            print(f"Warning: File not found: {csv_path}. Skipping.")
            continue
            
        print(f"Loading {csv_path}...")
        df = pd.read_csv(csv_path)
        print(f"Writing sheet '{sheet_name}' ({len(df)} rows)...")
        
        # Create worksheet
        worksheet = workbook.add_worksheet(sheet_name)
        
        # Explicitly show grid lines
        worksheet.hide_gridlines(2)
        
        # Freeze top row
        worksheet.freeze_panes(1, 0)
        
        # Write headers
        headers = list(df.columns)
        worksheet.write_row(0, 0, headers, header_format)
        worksheet.set_row(0, 26)
        
        # Keep track of column widths
        max_col_widths = [len(str(h)) for h in headers]
        
        # Write rows
        for r_idx, row in enumerate(df.itertuples(index=False), start=1):
            worksheet.set_row(r_idx, 20)
            is_even = (r_idx % 2 == 0)
            
            for c_idx, val in enumerate(row):
                val_str = "" if pd.isna(val) else str(val)
                if len(val_str) > max_col_widths[c_idx]:
                    max_col_widths[c_idx] = len(val_str)
                
                # Check for NaN / Empty
                if pd.isna(val):
                    worksheet.write_blank(r_idx, c_idx, "", left_even if is_even else left_odd)
                    continue
                
                col_name = headers[c_idx].lower()
                
                # Coordinates
                if ('lat' in col_name or 'lon' in col_name or 'coordinate' in col_name) and isinstance(val, (int, float)):
                    worksheet.write_number(r_idx, c_idx, float(val), coord_even if is_even else coord_odd)
                # IDs, Pincodes, Codes, ZIPs
                elif 'id' in col_name or 'code' in col_name or 'pin' in col_name or 'zip' in col_name:
                    worksheet.write(r_idx, c_idx, str(val), center_even if is_even else center_odd)
                # Numeric fields
                elif isinstance(val, (int, float)):
                    # Handle floats that are actually integers (e.g. 1.0)
                    if isinstance(val, int) or (isinstance(val, float) and val.is_integer()):
                        worksheet.write_number(r_idx, c_idx, int(val), int_even if is_even else int_odd)
                    else:
                        worksheet.write_number(r_idx, c_idx, float(val), float_even if is_even else float_odd)
                # Booleans
                elif isinstance(val, bool):
                    worksheet.write_boolean(r_idx, c_idx, val, center_even if is_even else center_odd)
                # Standard text
                else:
                    worksheet.write(r_idx, c_idx, str(val), left_even if is_even else left_odd)
                    
        # Apply column widths
        for c_idx, max_len in enumerate(max_col_widths):
            width = min(max(max_len + 4, 12), 50)
            worksheet.set_column(c_idx, c_idx, width)
            
        # Set autofilter
        worksheet.autofilter(0, 0, len(df), len(headers) - 1)
        print(f"Sheet '{sheet_name}' write complete.")
        
    print(f"Closing and saving workbook to {OUTPUT_PATH}...")
    workbook.close()
    print("Excel creation completed successfully!")

if __name__ == "__main__":
    style_excel()
