#!/usr/bin/env python3
import json
import re
from pathlib import Path
import numpy as np
import folium
from folium.plugins import HeatMap
from sklearn.neighbors import KNeighborsRegressor
from sklearn.ensemble import RandomForestRegressor

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = BASE_DIR / "data" / "raw" / "99acres_bangalore_localities.json"
OUTPUT_DIR = BASE_DIR / "data" / "processed"

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

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(INPUT_FILE, encoding="utf-8") as f:
        localities = json.load(f)
        
    print(f"Loaded {len(localities)} localities from {INPUT_FILE.name}")
    
    # 1. Filter and prepare training data
    training_data = []
    min_lat, max_lat = 90.0, -90.0
    min_lon, max_lon = 180.0, -180.0
    
    for loc in localities:
        info = loc.get("locality_info", {})
        coords = info.get("coordinates", {})
        lat = coords.get("latitude")
        lon = coords.get("longitude")
        
        # Keep coordinates inside Bangalore bounding box
        if lat and lon and 12.80 < lat < 13.20 and 77.40 < lon < 77.80:
            min_lat = min(min_lat, lat)
            max_lat = max(max_lat, lat)
            min_lon = min(min_lon, lon)
            max_lon = max(max_lon, lon)
            
            # Extract metrics
            insights = loc.get("market_insights", {})
            inc = loc.get("income_analytics", {})
            inv = loc.get("inventory", {})
            
            # Price
            price = insights.get("market_price_per_sqft") or extract_price(insights.get("price_per_sqft"))
            
            # Income (Affluence Score)
            dist = inc.get("distribution") or {}
            high_pct = dist.get("high") or 0.0
            upper_middle_pct = dist.get("upper_middle") or 0.0
            affluence_score = high_pct + (0.5 * upper_middle_pct)
            
            # Appreciation
            appreciation = extract_appreciation(insights.get("yearly_appreciation"))
            appreciation = max(0.0, appreciation) # Floor appreciation at 0
            
            # Inventory Listings
            sale_count = inv.get("sale", {}).get("total_count") or 0
            rent_count = inv.get("rent", {}).get("total_count") or 0
            total_listings = sale_count + rent_count
            
            training_data.append({
                "lat": lat,
                "lon": lon,
                "price": price,
                "income": affluence_score if affluence_score > 0 else None,
                "trends": appreciation,
                "inventory": total_listings if total_listings > 0 else None,
                # Metadata for markers
                "name": info.get("name", "Unknown"),
                "zone": info.get("zone", {}).get("name") or "Unknown Zone",
                "rating": insights.get("rating") or "N/A",
                "price_display": f"₹{price:,}/sqft" if price else "N/A",
                "appr_display": insights.get("yearly_appreciation") or "N/A",
                "bracket": (inc.get("dominant_income_bracket") or "N/A").replace("_", " ").title()
            })
            
    print(f"Prepared {len(training_data)} training points inside bounding box:")
    print(f"  Latitude bounds:  [{min_lat:.5f}, {max_lat:.5f}]")
    print(f"  Longitude bounds: [{min_lon:.5f}, {max_lon:.5f}]")
    
    # 2. Train Models
    # Model A: Market Price (KNN Regressor)
    X_price = np.array([[pt["lat"], pt["lon"]] for pt in training_data if pt["price"] is not None])
    y_price = np.array([pt["price"] for pt in training_data if pt["price"] is not None])
    print(f"Training Price Model on {len(X_price)} points...")
    model_price = KNeighborsRegressor(n_neighbors=5, weights='distance')
    model_price.fit(X_price, y_price)
    
    # Model B: Income/Affluence (KNN Regressor)
    X_income = np.array([[pt["lat"], pt["lon"]] for pt in training_data if pt["income"] is not None])
    y_income = np.array([pt["income"] for pt in training_data if pt["income"] is not None])
    print(f"Training Income Model on {len(X_income)} points...")
    model_income = KNeighborsRegressor(n_neighbors=5, weights='distance')
    model_income.fit(X_income, y_income)
    
    # Model C: Appreciation Trends (Random Forest Regressor)
    X_trends = np.array([[pt["lat"], pt["lon"]] for pt in training_data])
    y_trends = np.array([pt["trends"] for pt in training_data])
    print(f"Training Trends Model on {len(X_trends)} points...")
    model_trends = RandomForestRegressor(n_estimators=100, max_depth=6, random_state=42)
    model_trends.fit(X_trends, y_trends)
    
    # Model D: Inventory Listings (KNN Regressor)
    X_inventory = np.array([[pt["lat"], pt["lon"]] for pt in training_data if pt["inventory"] is not None])
    y_inventory = np.array([pt["inventory"] for pt in training_data if pt["inventory"] is not None])
    print(f"Training Inventory Model on {len(X_inventory)} points...")
    model_inventory = KNeighborsRegressor(n_neighbors=5, weights='distance')
    model_inventory.fit(X_inventory, y_inventory)
    
    # 3. Create Prediction Grid (60 x 60 points)
    grid_size = 60
    grid_lat = np.linspace(min_lat - 0.01, max_lat + 0.01, grid_size)
    grid_lon = np.linspace(min_lon - 0.01, max_lon + 0.01, grid_size)
    
    grid_points = []
    for lat in grid_lat:
        for lon in grid_lon:
            grid_points.append([lat, lon])
            
    X_grid = np.array(grid_points)
    print(f"Predicting values for dense grid of {len(X_grid)} points...")
    
    pred_price = model_price.predict(X_grid)
    pred_income = model_income.predict(X_grid)
    pred_trends = model_trends.predict(X_grid)
    pred_inventory = model_inventory.predict(X_grid)
    
    # 4. Generate folium map layers
    heat_price = [[X_grid[i][0], X_grid[i][1], float(pred_price[i])] for i in range(len(X_grid))]
    heat_income = [[X_grid[i][0], X_grid[i][1], float(pred_income[i])] for i in range(len(X_grid))]
    heat_trends = [[X_grid[i][0], X_grid[i][1], float(pred_trends[i])] for i in range(len(X_grid))]
    heat_inventory = [[X_grid[i][0], X_grid[i][1], float(pred_inventory[i])] for i in range(len(X_grid))]
    
    # 5. Build Unified Map
    bangalore_center = [12.9716, 77.5946]
    m = folium.Map(location=bangalore_center, zoom_start=11.5, tiles="CartoDB dark_matter")
    
    # Define Feature Groups
    fg_price = folium.FeatureGroup(name="ML-Smoothed Market Insights (Price/sqft)", show=True)
    fg_income = folium.FeatureGroup(name="ML-Smoothed Income (Affluence)", show=False)
    fg_trends = folium.FeatureGroup(name="ML-Smoothed Appreciation Trends", show=False)
    fg_inventory = folium.FeatureGroup(name="ML-Smoothed Inventory Density", show=False)
    fg_markers = folium.FeatureGroup(name="Original Locality Markers", show=False)
    
    # Add HeatMaps to Feature Groups
    HeatMap(heat_price, radius=18, blur=15, min_opacity=0.15).add_to(fg_price)
    HeatMap(heat_income, radius=18, blur=15, min_opacity=0.15, gradient={0.2: '#4b0082', 0.4: '#483d8b', 0.6: '#9370db', 0.8: '#ba55d3', 1.0: '#ff00ff'}).add_to(fg_income)
    HeatMap(heat_trends, radius=18, blur=15, min_opacity=0.15, gradient={0.2: '#330000', 0.4: '#990000', 0.6: '#ff3300', 0.8: '#ff9900', 1.0: '#ffffcc'}).add_to(fg_trends)
    HeatMap(heat_inventory, radius=18, blur=15, min_opacity=0.15, gradient={0.2: '#002200', 0.4: '#006600', 0.6: '#00cc00', 0.8: '#66ff66', 1.0: '#ccffcc'}).add_to(fg_inventory)
    
    # Add Markers
    for pt in training_data:
        popup_html = f"""
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; font-size: 13px; color: #fff; background-color: #222; padding: 12px; border-radius: 8px; width: 260px; border: 1px solid #444; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
            <h4 style="margin: 0 0 4px; color: #58a6ff; font-size: 15px; font-weight: 600; border-bottom: 1px solid #444; padding-bottom: 6px;">{pt['name']}</h4>
            <span style="font-size: 11px; color: #8b949e; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">{pt['zone']}</span>
            <div style="margin-top: 10px; display: grid; grid-template-columns: 1.2fr 1fr; row-gap: 6px; column-gap: 10px;">
                <span style="color: #8b949e;">Market Price:</span>
                <span style="font-weight: 600; text-align: right;">{pt['price_display']}</span>
                
                <span style="color: #8b949e;">Appreciation:</span>
                <span style="font-weight: 600; text-align: right; color: {'#39d353' if pt['trends'] >= 0 else '#f85149'};">{pt['appr_display']}</span>
                
                <span style="color: #8b949e;">Rating:</span>
                <span style="font-weight: 600; text-align: right; color: #ffca28;">★ {pt['rating']}</span>
                
                <span style="color: #8b949e;">Total Listings:</span>
                <span style="font-weight: 600; text-align: right;">{pt['inventory'] or 0}</span>
                
                <span style="color: #8b949e;">Affluence Seg:</span>
                <span style="font-weight: 600; text-align: right; color: #bc8cff;">{pt['bracket']}</span>
            </div>
        </div>
        """
        folium.CircleMarker(
            location=[pt["lat"], pt["lon"]],
            radius=4,
            color="#58a6ff",
            weight=1,
            fill=True,
            fill_color="#1f6feb",
            fill_opacity=0.6,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"{pt['name']} ({pt['zone']})"
        ).add_to(fg_markers)
        
    fg_price.add_to(m)
    fg_income.add_to(m)
    fg_trends.add_to(m)
    fg_inventory.add_to(m)
    fg_markers.add_to(m)
    
    # Layer control collapsed=False
    folium.LayerControl(collapsed=False).add_to(m)
    
    # Save the map
    m.save(OUTPUT_DIR / "heatmap_ml_unified.html")
    print("Successfully generated ML-Normalized Spatial Heatmap at data/processed/heatmap_ml_unified.html")

if __name__ == "__main__":
    main()
