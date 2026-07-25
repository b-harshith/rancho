#!/usr/bin/env python3
import json
import re
import os
from pathlib import Path
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = BASE_DIR / "data" / "raw" / "99acres_bangalore_localities.json"
OUTPUT_DIR = BASE_DIR / "data" / "processed"

# Fixed geographical boundaries for Bangalore to ensure identical visual scales
LAT_MIN, LAT_MAX = 12.82, 13.15
LON_MIN, LON_MAX = 77.42, 77.76

# Landmark coordinates to render as anchors for visual models
LANDMARKS = [
    {"name": "Majestic", "lat": 12.9766, "lon": 77.5712},
    {"name": "Indiranagar", "lat": 12.9784, "lon": 77.6408},
    {"name": "Koramangala", "lat": 12.9348, "lon": 77.6189},
    {"name": "Whitefield", "lat": 12.9698, "lon": 77.7510},
    {"name": "Electronic City", "lat": 12.8452, "lon": 77.6636},
    {"name": "Hebbal", "lat": 13.0354, "lon": 77.5978},
    {"name": "Yelahanka", "lat": 13.1007, "lon": 77.5963},
    {"name": "Jayanagar", "lat": 12.9299, "lon": 77.5824},
    {"name": "Rajajinagar", "lat": 12.9889, "lon": 77.5558},
]

def extract_price(price_str):
    if not price_str:
        return None
    nums = re.sub(r"[^\d]", "", price_str)
    return int(nums) if nums else None

def extract_appreciation(appr_str):
    if not appr_str:
        return 0.0
    match = re.search(r"(-?[\d.]+)\s*%", appr_str)
    if match:
        return float(match.group(1))
    return 0.0

def get_color_for_weight(val):
    val = max(0.0, min(1.0, val))
    stops = [
        (0.0, (20, 24, 33)),       # Base Dark color
        (0.1, (0, 0, 255)),        # Blue
        (0.35, (0, 255, 255)),     # Cyan
        (0.6, (0, 255, 0)),        # Green
        (0.85, (255, 165, 0)),     # Orange
        (1.0, (255, 0, 0))         # Red
    ]
    
    for i in range(len(stops) - 1):
        s0, c0 = stops[i]
        s1, c1 = stops[i+1]
        if s0 <= val <= s1:
            ratio = (val - s0) / (s1 - s0)
            r = int(c0[0] + ratio * (c1[0] - c0[0]))
            g = int(c0[1] + ratio * (c1[1] - c0[1]))
            b = int(c0[2] + ratio * (c1[2] - c0[2]))
            return f"rgb({r},{g},{b})"
    return "rgb(255,0,0)"

def render_svg(title, points, val_key, max_val, output_path, label_min, label_max, color_gradient_style="standard"):
    # SVG Dimensions
    width = 900
    height = 950
    padding = 100
    grid_w = width - 2 * padding
    grid_h = height - 2 * padding - 50
    
    # Coordinate conversion
    def to_pixels(lat, lon):
        x = padding + (lon - LON_MIN) / (LON_MAX - LON_MIN) * grid_w
        y = padding + 50 + (1 - (lat - LAT_MIN) / (LAT_MAX - LAT_MIN)) * grid_h
        return x, y

    svg_lines = []
    svg_lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" height="100%" style="background-color: #0d1117;">')
    
    # Gaussian blur for blending overlapping circles into heatmap gradients
    svg_lines.append("""
    <defs>
        <filter id="blurFilter" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="10" />
        </filter>
    </defs>
    """)
    
    # Grid background
    gx, gy = padding, padding + 50
    svg_lines.append(f'  <rect x="{gx}" y="{gy}" width="{grid_w}" height="{grid_h}" fill="#161b22" stroke="#30363d" stroke-width="2"/>')
    
    # Dashed Grid Lines (every 0.05 degrees)
    lat_ticks = np.arange(np.ceil(LAT_MIN / 0.05) * 0.05, LAT_MAX, 0.05)
    lon_ticks = np.arange(np.ceil(LON_MIN / 0.05) * 0.05, LON_MAX, 0.05)
    
    for lat in lat_ticks:
        _, y = to_pixels(lat, LON_MIN)
        svg_lines.append(f'  <line x1="{gx}" y1="{y}" x2="{gx+grid_w}" y2="{y}" stroke="#30363d" stroke-width="1" stroke-dasharray="4,4"/>')
        svg_lines.append(f'  <text x="{gx-15}" y="{y+4}" fill="#8b949e" font-size="11" text-anchor="end" font-weight="600">{lat:.3f}° N</text>')
        
    for lon in lon_ticks:
        x, _ = to_pixels(LAT_MIN, lon)
        svg_lines.append(f'  <line x1="{x}" y1="{gy}" x2="{x}" y2="{gy+grid_h}" stroke="#30363d" stroke-width="1" stroke-dasharray="4,4"/>')
        svg_lines.append(f'  <text x="{x}" y="{gy+grid_h+20}" fill="#8b949e" font-size="11" text-anchor="middle" font-weight="600">{lon:.3f}° E</text>')

    # Grid titles
    svg_lines.append(f'  <text x="{width/2}" y="{gy+grid_h+48}" fill="#8b949e" font-size="13" text-anchor="middle" font-weight="700" letter-spacing="1">LONGITUDE (EAST)</text>')
    svg_lines.append(f'  <text x="{gx-60}" y="{gy+grid_h/2}" fill="#8b949e" font-size="13" text-anchor="middle" font-weight="700" letter-spacing="1" transform="rotate(-90 {gx-60} {gy+grid_h/2})">LATITUDE (NORTH)</text>')

    # Draw Heat Circles (raw observed points)
    svg_lines.append('  <g filter="url(#blurFilter)">')
    for pt in points:
        val = pt.get(val_key)
        if val is None or val <= 0:
            continue
            
        x, y = to_pixels(pt["lat"], pt["lon"])
        norm_val = min(1.0, val / max_val)
        
        # Color mapping
        if color_gradient_style == "purple":
            r = int(75 + norm_val * 180)
            g = int(0)
            b = int(130 + norm_val * 125)
            color = f"rgb({r},{g},{b})"
        elif color_gradient_style == "trends":
            r = int(100 + norm_val * 155)
            g = int(norm_val * 200)
            b = int(norm_val * 100)
            color = f"rgb({r},{g},{b})"
        elif color_gradient_style == "green":
            r = int(norm_val * 150)
            g = int(60 + norm_val * 195)
            b = int(norm_val * 150)
            color = f"rgb({r},{g},{b})"
        else:
            color = get_color_for_weight(norm_val)
            
        svg_lines.append(f'    <circle cx="{x:.1f}" cy="{y:.1f}" r="22" fill="{color}" opacity="0.35" />')
    svg_lines.append('  </g>')
    
    # Landmark Indicators
    for lm in LANDMARKS:
        lx, ly = to_pixels(lm["lat"], lm["lon"])
        if gx <= lx <= gx+grid_w and gy <= ly <= gy+grid_h:
            svg_lines.append(f'  <circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.5" fill="#ffffff" stroke="#000000" stroke-width="0.5"/>')
            svg_lines.append(f'  <text x="{lx:.1f}" y="{ly-8}" fill="#000000" font-size="10.5" font-weight="900" text-anchor="middle" opacity="0.8">{lm["name"]}</text>')
            svg_lines.append(f'  <text x="{lx:.1f}" y="{ly-8}" fill="#f0f6fc" font-size="10.5" font-weight="700" text-anchor="middle">{lm["name"]}</text>')

    # MAP TITLE
    svg_lines.append(f'  <text x="{width/2}" y="45" fill="#f0f6fc" font-size="20" font-weight="700" text-anchor="middle" letter-spacing="0.5">{title}</text>')

    # LEGEND BAR
    leg_x = width - padding - 280
    leg_y = gy + 20
    leg_w = 260
    leg_h = 15
    svg_lines.append(f'  <g>')
    grad_id = f"grad_{output_path.stem}"
    svg_lines.append(f'    <linearGradient id="{grad_id}" x1="0%" y1="0%" x2="100%" y2="0%">')
    if color_gradient_style == "purple":
        svg_lines.append('      <stop offset="0%" stop-color="rgb(75,0,130)" />')
        svg_lines.append('      <stop offset="100%" stop-color="rgb(255,0,255)" />')
    elif color_gradient_style == "trends":
        svg_lines.append('      <stop offset="0%" stop-color="rgb(100,0,0)" />')
        svg_lines.append('      <stop offset="60%" stop-color="rgb(255,80,0)" />')
        svg_lines.append('      <stop offset="100%" stop-color="rgb(255,230,150)" />')
    elif color_gradient_style == "green":
        svg_lines.append('      <stop offset="0%" stop-color="rgb(0,60,0)" />')
        svg_lines.append('      <stop offset="100%" stop-color="rgb(150,255,150)" />')
    else:
        svg_lines.append('      <stop offset="0%" stop-color="rgb(0,0,255)" />')
        svg_lines.append('      <stop offset="50%" stop-color="rgb(0,255,0)" />')
        svg_lines.append('      <stop offset="100%" stop-color="rgb(255,0,0)" />')
    svg_lines.append('    </linearGradient>')
    
    svg_lines.append(f'    <rect x="{leg_x-10}" y="{leg_y-10}" width="{leg_w+20}" height="48" fill="rgba(13,17,23,0.85)" stroke="#30363d" rx="4"/>')
    svg_lines.append(f'    <rect x="{leg_x}" y="{leg_y}" width="{leg_w}" height="{leg_h}" fill="url(#{grad_id})"/>')
    svg_lines.append(f'    <text x="{leg_x}" y="{leg_y+30}" fill="#8b949e" font-size="10" font-weight="600" text-anchor="start">{label_min}</text>')
    svg_lines.append(f'    <text x="{leg_x+leg_w}" y="{leg_y+30}" fill="#8b949e" font-size="10" font-weight="600" text-anchor="end">{label_max}</text>')
    svg_lines.append(f'  </g>')

    svg_lines.append('</svg>')
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(svg_lines))
    print(f"Generated SVG: {output_path.name}")


def convert_svg_to_png(svg_path, png_path):
    import subprocess
    import shutil
    
    # Run macOS qlmanage to convert SVG to PNG
    try:
        subprocess.run(
            ["qlmanage", "-t", "-s", "900", "-o", str(OUTPUT_DIR), str(svg_path)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        # qlmanage creates file named like heatmap_market_insights.svg.png
        gen_png = OUTPUT_DIR / f"{svg_path.name}.png"
        if gen_png.exists():
            shutil.move(str(gen_png), str(png_path))
            print(f"Successfully rendered image: {png_path.name}")
        else:
            print(f"Failed to find generated png for {svg_path.name}")
    except Exception as e:
        print(f"Error converting {svg_path.name} to PNG: {e}")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(INPUT_FILE, encoding="utf-8") as f:
        localities = json.load(f)
        
    training_data = []
    for loc in localities:
        info = loc.get("locality_info", {})
        coords = info.get("coordinates", {})
        lat = coords.get("latitude")
        lon = coords.get("longitude")
        
        if lat and lon and LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
            insights = loc.get("market_insights", {})
            inc = loc.get("income_analytics", {})
            inv = loc.get("inventory", {})
            
            price = insights.get("market_price_per_sqft") or extract_price(insights.get("price_per_sqft"))
            
            dist = inc.get("distribution") or {}
            high_pct = dist.get("high") or 0.0
            upper_middle_pct = dist.get("upper_middle") or 0.0
            affluence_score = high_pct + (0.5 * upper_middle_pct)
            
            appreciation = extract_appreciation(insights.get("yearly_appreciation"))
            appreciation = max(0.0, appreciation)
            
            sale_count = inv.get("sale", {}).get("total_count") or 0
            rent_count = inv.get("rent", {}).get("total_count") or 0
            total_listings = sale_count + rent_count
            
            training_data.append({
                "lat": lat,
                "lon": lon,
                "price": price,
                "income": affluence_score if affluence_score > 0 else None,
                "trends": appreciation,
                "inventory": total_listings if total_listings > 0 else None
            })
            
    print(f"Loaded {len(training_data)} raw observed points within bounding box.")

    # 3. Generate SVGs and convert to PNGs
    # A. Market Price
    svg_path = OUTPUT_DIR / "heatmap_market_insights.svg"
    png_path = OUTPUT_DIR / "heatmap_market_insights.png"
    render_svg(
        "Bangalore Real Estate - Market Price Heatmap (Raw Observed)",
        training_data, "price", 20000, svg_path,
        "Low (₹3,000)", "High (₹20,000+/sqft)"
    )
    convert_svg_to_png(svg_path, png_path)
    
    # B. Income Analytics
    svg_path = OUTPUT_DIR / "heatmap_income_analytics.svg"
    png_path = OUTPUT_DIR / "heatmap_income_analytics.png"
    render_svg(
        "Bangalore Real Estate - Income Affluence Heatmap (Raw Observed)",
        training_data, "income", 85, svg_path,
        "Low Wealth", "High Wealth",
        color_gradient_style="purple"
    )
    convert_svg_to_png(svg_path, png_path)
    
    # C. Appreciation Trends
    svg_path = OUTPUT_DIR / "heatmap_trends.svg"
    png_path = OUTPUT_DIR / "heatmap_trends.png"
    render_svg(
        "Bangalore Real Estate - Capital Growth Heatmap (Raw Observed)",
        training_data, "trends", 25, svg_path,
        "Stable / 0% Growth", "High Growth (25%+/yr)",
        color_gradient_style="trends"
    )
    convert_svg_to_png(svg_path, png_path)
    
    # D. Inventory density
    svg_path = OUTPUT_DIR / "heatmap_inventory.svg"
    png_path = OUTPUT_DIR / "heatmap_inventory.png"
    render_svg(
        "Bangalore Real Estate - Supply Listings Density Heatmap (Raw Observed)",
        training_data, "inventory", 150, svg_path,
        "Low Supply", "High Supply (150+ Listings)",
        color_gradient_style="green"
    )
    convert_svg_to_png(svg_path, png_path)
    
    print("All four raw spatial heatmap SVGs and PNG images successfully generated!")

if __name__ == "__main__":
    main()
