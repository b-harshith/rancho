#!/usr/bin/env python3
import json
import re
from pathlib import Path
import folium
from folium.plugins import HeatMap

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = BASE_DIR / "data" / "raw" / "99acres_bangalore_localities.json"
OUTPUT_DIR = BASE_DIR / "data" / "processed"

def extract_price(price_str):
    if not price_str:
        return None
    # Extract numeric characters from string like "₹11,850/ sqft"
    nums = re.sub(r"[^\d]", "", price_str)
    return int(nums) if nums else None

def extract_appreciation(appr_str):
    if not appr_str:
        return 0.0
    match = re.search(r"(-?[\d.]+)\s*%", appr_str)
    if match:
        return float(match.group(1))
    return 0.0

def create_map(title, points, heat_data, max_val, color_gradient=None):
    # Centered on Bangalore coordinates
    bangalore_center = [12.9716, 77.5946]
    
    # Use CartoDB Dark Matter for premium high-contrast visual aesthetics
    m = folium.Map(location=bangalore_center, zoom_start=11.5, tiles="CartoDB dark_matter")
    
    # Add Heatmap Layer
    HeatMap(
        heat_data,
        max_val=max_val,
        radius=25,
        blur=15,
        min_opacity=0.2,
        gradient=color_gradient
    ).add_to(m)
    
    # Add styled Markers for each locality
    for p in points:
        lat, lon = p["lat"], p["lon"]
        popup_html = f"""
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; font-size: 13px; color: #fff; background-color: #222; padding: 12px; border-radius: 8px; width: 260px; border: 1px solid #444; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
            <h4 style="margin: 0 0 4px; color: #58a6ff; font-size: 15px; font-weight: 600; border-bottom: 1px solid #444; padding-bottom: 6px;">{p['name']}</h4>
            <span style="font-size: 11px; color: #8b949e; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">{p['zone']}</span>
            <div style="margin-top: 10px; display: grid; grid-template-columns: 1.2fr 1fr; row-gap: 6px; column-gap: 10px;">
                <span style="color: #8b949e;">Market Price:</span>
                <span style="font-weight: 600; text-align: right;">{p['price_display']}</span>
                
                <span style="color: #8b949e;">Appreciation:</span>
                <span style="font-weight: 600; text-align: right; color: {'#39d353' if p['appr_val'] >= 0 else '#f85149'};">{p['appr_display']}</span>
                
                <span style="color: #8b949e;">Rating:</span>
                <span style="font-weight: 600; text-align: right; color: #ffca28;">★ {p['rating']}</span>
                
                <span style="color: #8b949e;">Total Listings:</span>
                <span style="font-weight: 600; text-align: right;">{p['listings']}</span>
                
                <span style="color: #8b949e;">Affluence Seg:</span>
                <span style="font-weight: 600; text-align: right; color: #bc8cff;">{p['bracket']}</span>
            </div>
        </div>
        """
        
        # Adding transparent circle marker to avoid visual clutter unless hovered/clicked
        folium.CircleMarker(
            location=[lat, lon],
            radius=4,
            color="#58a6ff",
            weight=1,
            fill=True,
            fill_color="#1f6feb",
            fill_opacity=0.6,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"{p['name']} ({p['zone']})"
        ).add_to(m)
        
    return m

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(INPUT_FILE, encoding="utf-8") as f:
        localities = json.load(f)
        
    print(f"Loaded {len(localities)} localities from {INPUT_FILE.name}")
    
    # Filter for valid coordinate entries
    valid_entries = []
    for loc in localities:
        info = loc.get("locality_info", {})
        coords = info.get("coordinates", {})
        lat = coords.get("latitude")
        lon = coords.get("longitude")
        
        if lat and lon and lat > 12.0 and lat < 13.5 and lon > 77.0 and lon < 78.5:
            valid_entries.append(loc)
            
    print(f"Found {len(valid_entries)} localities with valid coordinates inside Bangalore bbox.")
    
    # 1. Prepare Base Data lists
    point_metadata_list = []
    
    for loc in valid_entries:
        info = loc.get("locality_info", {})
        insights = loc.get("market_insights", {})
        inc = loc.get("income_analytics", {})
        inv = loc.get("inventory", {})
        
        lat = info["coordinates"]["latitude"]
        lon = info["coordinates"]["longitude"]
        name = info.get("name", "Unknown")
        zone = info.get("zone", {}).get("name") or "Unknown Zone"
        
        rating = insights.get("rating") or "N/A"
        
        # Inventory total
        sale_count = inv.get("sale", {}).get("total_count") or 0
        rent_count = inv.get("rent", {}).get("total_count") or 0
        total_listings = sale_count + rent_count
        
        # Price display
        market_price = insights.get("market_price_per_sqft")
        price_display = f"₹{market_price:,}/sqft" if market_price else (insights.get("price_per_sqft") or "N/A")
        
        # Appreciation display
        appr_val = extract_appreciation(insights.get("yearly_appreciation"))
        appr_display = insights.get("yearly_appreciation") or "N/A"
        
        # Affluence Bracket
        dominant_bracket = inc.get("dominant_income_bracket") or "N/A"
        dominant_bracket_clean = dominant_bracket.replace("_", " ").title()
        
        point_metadata_list.append({
            "lat": lat,
            "lon": lon,
            "name": name,
            "zone": zone,
            "rating": rating,
            "listings": total_listings,
            "price_display": price_display,
            "appr_val": appr_val,
            "appr_display": appr_display,
            "bracket": dominant_bracket_clean
        })
        
    # --- Map 1: Market Insights Heatmap (Price per Sqft) ---
    print("Generating Market Insights Map...")
    price_heat_data = []
    for loc in valid_entries:
        info = loc["locality_info"]
        insights = loc["market_insights"]
        lat = info["coordinates"]["latitude"]
        lon = info["coordinates"]["longitude"]
        
        price = insights.get("market_price_per_sqft") or extract_price(insights.get("price_per_sqft"))
        if price:
            price_heat_data.append([lat, lon, float(price)])
            
    max_price = max([p[2] for p in price_heat_data]) if price_heat_data else 1.0
    # Custom gradient (Blue -> Cyan -> Green -> Yellow -> Red) for standard thermal scale
    price_map = create_map("Market Price Heatmap", point_metadata_list, price_heat_data, max_price)
    price_map.save(OUTPUT_DIR / "heatmap_market_insights.html")
    
    # --- Map 2: Income Analytics Heatmap (High Income Index) ---
    print("Generating Income Analytics Map...")
    income_heat_data = []
    for loc in valid_entries:
        info = loc["locality_info"]
        inc = loc["income_analytics"]
        dist = inc.get("distribution") or {}
        lat = info["coordinates"]["latitude"]
        lon = info["coordinates"]["longitude"]
        
        # Calculate affluence score based on high-income percentage
        high_pct = dist.get("high") or 0.0
        upper_middle_pct = dist.get("upper_middle") or 0.0
        affluence_score = high_pct + (0.5 * upper_middle_pct)
        
        if affluence_score > 0:
            income_heat_data.append([lat, lon, float(affluence_score)])
            
    max_income = max([p[2] for p in income_heat_data]) if income_heat_data else 1.0
    # Purple/Magenta gradient for affluence representation
    income_map = create_map(
        "Income Analytics Heatmap", 
        point_metadata_list, 
        income_heat_data, 
        max_income,
        color_gradient={0.2: '#4b0082', 0.4: '#483d8b', 0.6: '#9370db', 0.8: '#ba55d3', 1.0: '#ff00ff'}
    )
    income_map.save(OUTPUT_DIR / "heatmap_income_analytics.html")
    
    # --- Map 3: Trends Heatmap (Yearly Capital Appreciation) ---
    print("Generating Trends Map...")
    trends_heat_data = []
    for loc in valid_entries:
        info = loc["locality_info"]
        insights = loc["market_insights"]
        lat = info["coordinates"]["latitude"]
        lon = info["coordinates"]["longitude"]
        
        appr_val = extract_appreciation(insights.get("yearly_appreciation"))
        # Floor negative appreciation values to 0 for heat representation
        appr_val = max(0.0, appr_val)
        if appr_val > 0:
            trends_heat_data.append([lat, lon, appr_val])
            
    max_trends = max([p[2] for p in trends_heat_data]) if trends_heat_data else 1.0
    # Energetic orange/red gradient for appreciation
    trends_map = create_map(
        "Trends Heatmap", 
        point_metadata_list, 
        trends_heat_data, 
        max_trends,
        color_gradient={0.2: '#330000', 0.4: '#990000', 0.6: '#ff3300', 0.8: '#ff9900', 1.0: '#ffffcc'}
    )
    trends_map.save(OUTPUT_DIR / "heatmap_trends.html")
    
    # --- Map 4: Inventory Heatmap (Active Real Estate Supply) ---
    print("Generating Inventory Map...")
    inventory_heat_data = []
    for loc in valid_entries:
        info = loc["locality_info"]
        inv = loc["inventory"]
        lat = info["coordinates"]["latitude"]
        lon = info["coordinates"]["longitude"]
        
        sale_count = inv.get("sale", {}).get("total_count") or 0
        rent_count = inv.get("rent", {}).get("total_count") or 0
        total_listings = sale_count + rent_count
        
        if total_listings > 0:
            inventory_heat_data.append([lat, lon, float(total_listings)])
            
    max_inventory = max([p[2] for p in inventory_heat_data]) if inventory_heat_data else 1.0
    # Green gradient for volume/liquidity
    inventory_map = create_map(
        "Inventory Heatmap", 
        point_metadata_list, 
        inventory_heat_data, 
        max_inventory,
        color_gradient={0.2: '#002200', 0.4: '#006600', 0.6: '#00cc00', 0.8: '#66ff66', 1.0: '#ccffcc'}
    )
    inventory_map.save(OUTPUT_DIR / "heatmap_inventory.html")
    
    # --- Map 5: Unified Overlapping Heatmap ---
    print("Generating Unified Overlapping Map...")
    unified_map = create_unified_map(
        point_metadata_list,
        price_heat_data, max_price,
        income_heat_data, max_income,
        trends_heat_data, max_trends,
        inventory_heat_data, max_inventory
    )
    unified_map.save(OUTPUT_DIR / "heatmap_unified.html")
    
    print("All spatial heatmaps successfully generated!")

def create_unified_map(points, price_data, max_price, income_data, max_income, trends_data, max_trends, inv_data, max_inventory):
    bangalore_center = [12.9716, 77.5946]
    m = folium.Map(location=bangalore_center, zoom_start=11.5, tiles="CartoDB dark_matter")
    
    # Define Feature Groups for overlays
    fg_price = folium.FeatureGroup(name="Market Insights (Price/sqft)", show=True)
    fg_income = folium.FeatureGroup(name="Income Analytics (Affluence)", show=False)
    fg_trends = folium.FeatureGroup(name="Appreciation Trends (YoY)", show=False)
    fg_inventory = folium.FeatureGroup(name="Inventory Supply Density", show=False)
    fg_markers = folium.FeatureGroup(name="Locality Popups & Details", show=False)
    
    # 1. Market Insights Heatmap Layer
    HeatMap(
        price_data,
        max_val=max_price,
        radius=25,
        blur=15,
        min_opacity=0.2
    ).add_to(fg_price)
    
    # 2. Income Analytics Heatmap Layer
    HeatMap(
        income_data,
        max_val=max_income,
        radius=25,
        blur=15,
        min_opacity=0.2,
        gradient={0.2: '#4b0082', 0.4: '#483d8b', 0.6: '#9370db', 0.8: '#ba55d3', 1.0: '#ff00ff'}
    ).add_to(fg_income)
    
    # 3. Trends Heatmap Layer
    HeatMap(
        trends_data,
        max_val=max_trends,
        radius=25,
        blur=15,
        min_opacity=0.2,
        gradient={0.2: '#330000', 0.4: '#990000', 0.6: '#ff3300', 0.8: '#ff9900', 1.0: '#ffffcc'}
    ).add_to(fg_trends)
    
    # 4. Inventory Heatmap Layer
    HeatMap(
        inv_data,
        max_val=max_inventory,
        radius=25,
        blur=15,
        min_opacity=0.2,
        gradient={0.2: '#002200', 0.4: '#006600', 0.6: '#00cc00', 0.8: '#66ff66', 1.0: '#ccffcc'}
    ).add_to(fg_inventory)
    
    # 5. Locality Popups & Details CircleMarkers
    for p in points:
        lat, lon = p["lat"], p["lon"]
        popup_html = f"""
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; font-size: 13px; color: #fff; background-color: #222; padding: 12px; border-radius: 8px; width: 260px; border: 1px solid #444; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
            <h4 style="margin: 0 0 4px; color: #58a6ff; font-size: 15px; font-weight: 600; border-bottom: 1px solid #444; padding-bottom: 6px;">{p['name']}</h4>
            <span style="font-size: 11px; color: #8b949e; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">{p['zone']}</span>
            <div style="margin-top: 10px; display: grid; grid-template-columns: 1.2fr 1fr; row-gap: 6px; column-gap: 10px;">
                <span style="color: #8b949e;">Market Price:</span>
                <span style="font-weight: 600; text-align: right;">{p['price_display']}</span>
                
                <span style="color: #8b949e;">Appreciation:</span>
                <span style="font-weight: 600; text-align: right; color: {'#39d353' if p['appr_val'] >= 0 else '#f85149'};">{p['appr_display']}</span>
                
                <span style="color: #8b949e;">Rating:</span>
                <span style="font-weight: 600; text-align: right; color: #ffca28;">★ {p['rating']}</span>
                
                <span style="color: #8b949e;">Total Listings:</span>
                <span style="font-weight: 600; text-align: right;">{p['listings']}</span>
                
                <span style="color: #8b949e;">Affluence Seg:</span>
                <span style="font-weight: 600; text-align: right; color: #bc8cff;">{p['bracket']}</span>
            </div>
        </div>
        """
        
        folium.CircleMarker(
            location=[lat, lon],
            radius=4,
            color="#58a6ff",
            weight=1,
            fill=True,
            fill_color="#1f6feb",
            fill_opacity=0.6,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"{p['name']} ({p['zone']})"
        ).add_to(fg_markers)
        
    # Add FeatureGroups to map
    fg_price.add_to(m)
    fg_income.add_to(m)
    fg_trends.add_to(m)
    fg_inventory.add_to(m)
    fg_markers.add_to(m)
    
    # Add Interactive Layer Control UI (collapsed=False to keep it open & readable)
    folium.LayerControl(collapsed=False).add_to(m)
    
    return m

if __name__ == "__main__":
    main()
