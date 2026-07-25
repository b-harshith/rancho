#!/usr/bin/env python3
import json
import re
from pathlib import Path
import numpy as np
from sklearn.neighbors import KNeighborsRegressor
from sklearn.ensemble import RandomForestRegressor

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = BASE_DIR / "data" / "raw" / "99acres_bangalore_localities.json"
OUTPUT_FILE = BASE_DIR / "data" / "processed" / "heatmap_comparison.html"

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
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    with open(INPUT_FILE, encoding="utf-8") as f:
        localities = json.load(f)
        
    training_data = []
    min_lat, max_lat = 90.0, -90.0
    min_lon, max_lon = 180.0, -180.0
    
    for loc in localities:
        info = loc.get("locality_info", {})
        coords = info.get("coordinates", {})
        lat = coords.get("latitude")
        lon = coords.get("longitude")
        
        if lat and lon and 12.80 < lat < 13.20 and 77.40 < lon < 77.80:
            min_lat = min(min_lat, lat)
            max_lat = max(max_lat, lat)
            min_lon = min(min_lon, lon)
            max_lon = max(max_lon, lon)
            
            insights = loc.get("market_insights", {})
            inc = loc.get("income_analytics", {})
            inv = loc.get("inventory", {})
            
            # Price
            price = insights.get("market_price_per_sqft") or extract_price(insights.get("price_per_sqft"))
            
            # Income
            dist = inc.get("distribution") or {}
            high_pct = dist.get("high") or 0.0
            upper_middle_pct = dist.get("upper_middle") or 0.0
            affluence_score = high_pct + (0.5 * upper_middle_pct)
            
            # Appreciation
            appreciation = extract_appreciation(insights.get("yearly_appreciation"))
            appreciation = max(0.0, appreciation)
            
            # Inventory
            sale_count = inv.get("sale", {}).get("total_count") or 0
            rent_count = inv.get("rent", {}).get("total_count") or 0
            total_listings = sale_count + rent_count
            
            training_data.append({
                "lat": round(lat, 5),
                "lon": round(lon, 5),
                "price": price,
                "income": affluence_score if affluence_score > 0 else None,
                "trends": appreciation,
                "inventory": total_listings if total_listings > 0 else None,
                "name": info.get("name", "Unknown"),
                "zone": info.get("zone", {}).get("name") or "Unknown Zone",
                "rating": insights.get("rating") or "N/A",
                "price_display": f"₹{price:,}/sqft" if price else "N/A",
                "appr_display": insights.get("yearly_appreciation") or "N/A",
                "bracket": (inc.get("dominant_income_bracket") or "N/A").replace("_", " ").title()
            })
            
    # Train models
    # Price Model
    X_price = np.array([[pt["lat"], pt["lon"]] for pt in training_data if pt["price"] is not None])
    y_price = np.array([pt["price"] for pt in training_data if pt["price"] is not None])
    model_price = KNeighborsRegressor(n_neighbors=5, weights='distance')
    model_price.fit(X_price, y_price)
    
    # Income Model
    X_income = np.array([[pt["lat"], pt["lon"]] for pt in training_data if pt["income"] is not None])
    y_income = np.array([pt["income"] for pt in training_data if pt["income"] is not None])
    model_income = KNeighborsRegressor(n_neighbors=5, weights='distance')
    model_income.fit(X_income, y_income)
    
    # Trends Model
    X_trends = np.array([[pt["lat"], pt["lon"]] for pt in training_data])
    y_trends = np.array([pt["trends"] for pt in training_data])
    model_trends = RandomForestRegressor(n_estimators=100, max_depth=6, random_state=42)
    model_trends.fit(X_trends, y_trends)
    
    # Inventory Model
    X_inventory = np.array([[pt["lat"], pt["lon"]] for pt in training_data if pt["inventory"] is not None])
    y_inventory = np.array([pt["inventory"] for pt in training_data if pt["inventory"] is not None])
    model_inventory = KNeighborsRegressor(n_neighbors=5, weights='distance')
    model_inventory.fit(X_inventory, y_inventory)
    
    # Generate grid
    grid_size = 60
    grid_lat = np.linspace(min_lat - 0.01, max_lat + 0.01, grid_size)
    grid_lon = np.linspace(min_lon - 0.01, max_lon + 0.01, grid_size)
    
    grid_points = []
    for lat in grid_lat:
        for lon in grid_lon:
            grid_points.append([round(lat, 5), round(lon, 5)])
            
    X_grid = np.array(grid_points)
    pred_price = model_price.predict(X_grid)
    pred_income = model_income.predict(X_grid)
    pred_trends = model_trends.predict(X_grid)
    pred_inventory = model_inventory.predict(X_grid)
    
    # Prepare serializable list of predicted points
    grid_data_list = []
    for i in range(len(grid_points)):
        grid_data_list.append({
            "lat": grid_points[i][0],
            "lon": grid_points[i][1],
            "price": float(pred_price[i]),
            "income": float(pred_income[i]),
            "trends": float(pred_trends[i]),
            "inventory": float(pred_inventory[i])
        })
        
    # Serialize data to JSON strings for HTML embedding
    raw_points_json = json.dumps(training_data)
    grid_points_json = json.dumps(grid_data_list)
    
    # HTML template with Leaflet, Leaflet.heat, and leaflet-side-by-side slider plugin
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Real Estate Heatmap Comparison: Raw vs ML-Normalized</title>
    
    <!-- Leaflet CSS & JS -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"></script>
    
    <!-- Leaflet.heat Plugin -->
    <script src="https://cdn.jsdelivr.net/npm/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
    
    <!-- Leaflet Side-by-Side Plugin -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet-side-by-side@2.2.0/layout.min.css" />
    <script src="https://cdn.jsdelivr.net/gh/digidem/leaflet-side-by-side@2.0.0/leaflet-side-by-side.min.js"></script>
    
    <!-- Google Fonts -->
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    
    <style>
        * {{
            box-sizing: border-box;
            font-family: 'Outfit', sans-serif;
        }}
        html, body {{
            height: 100%;
            margin: 0;
            padding: 0;
            background-color: #0d1117;
            color: #c9d1d9;
            overflow: hidden;
        }}
        #app-container {{
            display: flex;
            flex-direction: column;
            height: 100%;
        }}
        header {{
            background: rgba(13, 17, 23, 0.85);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid #30363d;
            padding: 12px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            z-index: 1000;
        }}
        .logo-container h1 {{
            margin: 0;
            font-size: 20px;
            font-weight: 700;
            background: linear-gradient(90deg, #58a6ff, #bc8cff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .logo-container p {{
            margin: 2px 0 0;
            font-size: 11px;
            color: #8b949e;
        }}
        .controls {{
            display: flex;
            gap: 10px;
        }}
        .btn {{
            background: #21262d;
            border: 1px solid #30363d;
            color: #c9d1d9;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
        }}
        .btn:hover {{
            background: #30363d;
            border-color: #8b949e;
        }}
        .btn.active {{
            background: #1f6feb;
            border-color: #58a6ff;
            color: #ffffff;
            box-shadow: 0 0 8px rgba(31, 111, 235, 0.4);
        }}
        #map-wrapper {{
            flex: 1;
            position: relative;
        }}
        #map {{
            width: 100%;
            height: 100%;
        }}
        /* Glowing neon divider line for the side-by-side slider */
        .leaflet-sbs-divider {{
            background: linear-gradient(180deg, #58a6ff, #bc8cff) !important;
            width: 4px !important;
            box-shadow: 0 0 15px rgba(88, 166, 255, 0.8) !important;
        }}
        /* Overlay Labels for Left and Right Sides */
        .map-label {{
            position: absolute;
            top: 20px;
            padding: 8px 16px;
            background: rgba(13, 17, 23, 0.85);
            backdrop-filter: blur(8px);
            border: 1px solid #30363d;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 700;
            z-index: 999;
            pointer-events: none;
            box-shadow: 0 4px 12px rgba(0,0,0,0.5);
        }}
        .map-label.left {{
            left: 20px;
            color: #ff7b72;
            border-left: 3px solid #ff7b72;
        }}
        .map-label.right {{
            right: 20px;
            color: #58a6ff;
            border-right: 3px solid #58a6ff;
        }}
        /* Tooltip and Popups Styling */
        .leaflet-popup-content-wrapper, .leaflet-popup-tip {{
            background: #21262d !important;
            color: #c9d1d9 !important;
            border: 1px solid #30363d;
            border-radius: 8px;
        }}
        .leaflet-popup-close-button {{
            color: #8b949e !important;
        }}
        /* Legend Container */
        .legend-card {{
            position: absolute;
            bottom: 24px;
            left: 24px;
            background: rgba(22, 27, 34, 0.9);
            backdrop-filter: blur(10px);
            border: 1px solid #30363d;
            padding: 16px;
            border-radius: 8px;
            z-index: 999;
            width: 250px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.6);
        }}
        .legend-title {{
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 8px;
            color: #f0f6fc;
        }}
        .legend-bar {{
            height: 12px;
            border-radius: 3px;
            margin-bottom: 6px;
        }}
        .legend-labels {{
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            color: #8b949e;
        }}
        .info-toggle {{
            position: absolute;
            bottom: 24px;
            right: 24px;
            background: rgba(22, 27, 34, 0.9);
            border: 1px solid #30363d;
            padding: 10px;
            border-radius: 8px;
            z-index: 999;
            font-size: 11px;
            color: #8b949e;
        }}
    </style>
</head>
<body>

<div id="app-container">
    <header>
        <div class="logo-container">
            <h1>Spatial Model Swipe Comparison</h1>
            <p>Compare observed raw real estate data vs continuous Machine Learning normalized surfaces</p>
        </div>
        <div class="controls">
            <button class="btn active" onclick="switchMetric('price')">Market Price</button>
            <button class="btn" onclick="switchMetric('income')">Income Affluence</button>
            <button class="btn" onclick="switchMetric('trends')">Growth/Appreciation</button>
            <button class="btn" onclick="switchMetric('inventory')">Supply/Inventory</button>
        </div>
    </header>

    <div id="map-wrapper">
        <div class="map-label left">BEFORE ML: Raw Observed Points</div>
        <div class="map-label right">AFTER ML: Interpolated Continuous Surface</div>
        
        <div id="map"></div>
        
        <!-- Legend Overlay -->
        <div class="legend-card" id="legend">
            <div class="legend-title" id="legend-title">Market Price (per sqft)</div>
            <div class="legend-bar" id="legend-color-bar" style="background: linear-gradient(90deg, blue, cyan, lime, yellow, red);"></div>
            <div class="legend-labels">
                <span id="legend-min">Low</span>
                <span id="legend-max">High</span>
            </div>
        </div>
        
        <!-- Quick Info Overlay -->
        <div class="info-toggle">
            * Drag slider in center to swipe | Click locality markers for details.
        </div>
    </div>
</div>

<script>
    // Embed python serialized data
    const rawData = {raw_points_json};
    const gridData = {grid_points_json};
    
    // Initialize Map
    const map = L.map('map', {{
        center: [12.9716, 77.5946],
        zoom: 11.5,
        zoomControl: true
    }});
    
    // Dark base tiles
    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
        attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
    }}).addTo(map);

    // Track active layers
    let activeLeftHeat = null;
    let activeRightHeat = null;
    
    // Track active metric
    let currentMetric = 'price';
    
    const markersGroup = L.layerGroup().addTo(map);
    
    // Side by side swipe controller (initialize empty, we set layers dynamically)
    let swipeControl = L.control.sideBySide([], []).addTo(map);
    
    // Configs for each metric
    const configs = {{
        price: {{
            name: "Market Price per SqFt",
            gradient: {{0.4: 'blue', 0.6: 'cyan', 0.7: 'lime', 0.8: 'yellow', 1.0: 'red'}},
            colorBar: "linear-gradient(90deg, blue, cyan, lime, yellow, red)",
            minLabel: "₹3,000",
            maxLabel: "₹25,000+",
            maxVal: 20000,
            getWeight: (pt) => pt.price || 0
        }},
        income: {{
            name: "Income Affluence Score",
            gradient: {{0.2: '#4b0082', 0.4: '#483d8b', 0.6: '#9370db', 0.8: '#ba55d3', 1.0: '#ff00ff'}},
            colorBar: "linear-gradient(90deg, #4b0082, #483d8b, #9370db, #ba55d3, #ff00ff)",
            minLabel: "Low Affluence",
            maxLabel: "High Affluence",
            maxVal: 85,
            getWeight: (pt) => pt.income || 0
        }},
        trends: {{
            name: "Yearly Capital Appreciation",
            gradient: {{0.2: '#330000', 0.4: '#990000', 0.6: '#ff3300', 0.8: '#ff9900', 1.0: '#ffffcc'}},
            colorBar: "linear-gradient(90deg, #330000, #990000, #ff3300, #ff9900, #ffffcc)",
            minLabel: "0% / Stable",
            maxLabel: "35%+",
            maxVal: 25,
            getWeight: (pt) => pt.trends || 0
        }},
        inventory: {{
            name: "Inventory Supply Density",
            gradient: {{0.2: '#002200', 0.4: '#006600', 0.6: '#00cc00', 0.8: '#66ff66', 1.0: '#ccffcc'}},
            colorBar: "linear-gradient(90deg, #002200, #006600, #00cc00, #66ff66, #ccffcc)",
            minLabel: "Low Supply",
            maxLabel: "High Supply (Guts)",
            maxVal: 80,
            getWeight: (pt) => pt.inventory || 0
        }}
    }};

    // Function to render heatmaps based on chosen metric
    function renderHeatmaps() {{
        // Remove previous heat layers from map
        if (activeLeftHeat) map.removeLayer(activeLeftHeat);
        if (activeRightHeat) map.removeLayer(activeRightHeat);
        
        // Clear previous markers
        markersGroup.clearLayers();
        
        const cfg = configs[currentMetric];
        
        // 1. Prepare Left Side data (Raw points)
        const leftPoints = [];
        rawData.forEach(pt => {{
            const w = cfg.getWeight(pt);
            if (w > 0) {{
                leftPoints.push([pt.lat, pt.lon, w]);
            }}
        }});
        
        // 2. Prepare Right Side data (ML grid prediction)
        const rightPoints = [];
        gridData.forEach(pt => {{
            const w = cfg.getWeight(pt);
            if (w > 0) {{
                rightPoints.push([pt.lat, pt.lon, w]);
            }}
        }});
        
        // Find max value in grid to scale properly
        const maxVal = cfg.maxVal;
        
        // 3. Render Leaflet Heat Layers directly on map
        activeLeftHeat = L.heatLayer(leftPoints, {{
            radius: 24,
            blur: 15,
            max: maxVal,
            gradient: cfg.gradient
        }}).addTo(map);
        
        activeRightHeat = L.heatLayer(rightPoints, {{
            radius: 18,
            blur: 15,
            max: maxVal,
            gradient: cfg.gradient
        }}).addTo(map);
        
        // Monkey-patch getContainer so leaflet-side-by-side can find the canvas element to clip
        activeLeftHeat.getContainer = function() {{ return this._canvas; }};
        activeRightHeat.getContainer = function() {{ return this._canvas; }};
        
        // 4. Update the side-by-side controller
        swipeControl.setLeftLayers(activeLeftHeat);
        swipeControl.setRightLayers(activeRightHeat);
        
        // 4. Render Markers on both sides (global marker layer overlay)
        rawData.forEach(pt => {{
            const popupHtml = `
            <div style="font-family: 'Outfit', sans-serif; font-size: 13px; color: #fff; background-color: #21262d; padding: 4px; width: 250px;">
                <h4 style="margin: 0 0 6px; color: #58a6ff; font-size: 15px; font-weight: 600; border-bottom: 1px solid #30363d; padding-bottom: 6px;">${{pt.name}}</h4>
                <span style="font-size: 11px; color: #8b949e; font-weight: bold; text-transform: uppercase;">${{pt.zone}}</span>
                <div style="margin-top: 10px; display: grid; grid-template-columns: 1.2fr 1fr; row-gap: 6px; column-gap: 10px;">
                    <span style="color: #8b949e;">Market Price:</span>
                    <span style="font-weight: 600; text-align: right;">${{pt.price_display}}</span>
                    
                    <span style="color: #8b949e;">Appreciation:</span>
                    <span style="font-weight: 600; text-align: right; color: ${{pt.trends >= 0 ? '#39d353' : '#f85149'}};">${{pt.appr_display}}</span>
                    
                    <span style="color: #8b949e;">Rating:</span>
                    <span style="font-weight: 600; text-align: right; color: #ffca28;">★ ${{pt.rating}}</span>
                    
                    <span style="color: #8b949e;">Total Listings:</span>
                    <span style="font-weight: 600; text-align: right;">${{pt.inventory || 0}}</span>
                    
                    <span style="color: #8b949e;">Affluence Seg:</span>
                    <span style="font-weight: 600; text-align: right; color: #bc8cff;">${{pt.bracket}}</span>
                </div>
            </div>
            `;
            
            L.circleMarker([pt.lat, pt.lon], {{
                radius: 4,
                color: "#58a6ff",
                weight: 1,
                fill: true,
                fillColor: "#1f6feb",
                fillOpacity: 0.6
            }}).bindPopup(popupHtml)
              .bindTooltip(`${{pt.name}} (${{pt.zone}})`)
              .addTo(markersGroup); // Add to markersGroup to clear old markers on metric switch
        }});
        
        // 5. Update legend details
        document.getElementById("legend-title").innerText = cfg.name;
        document.getElementById("legend-color-bar").style.background = cfg.colorBar;
        document.getElementById("legend-min").innerText = cfg.minLabel;
        document.getElementById("legend-max").innerText = cfg.maxLabel;
    }}
    
    // Switch metric handler
    window.switchMetric = function(metric) {{
        currentMetric = metric;
        
        // Update active class on buttons
        const buttons = document.querySelectorAll('.controls .btn');
        buttons.forEach(btn => btn.classList.remove('active'));
        
        // Find clicked button
        event.target.classList.add('active');
        
        renderHeatmaps();
    }};
    
    // Initial Render
    renderHeatmaps();
</script>

</body>
</html>
"""
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"Comparison Dashboard HTML successfully compiled at {OUTPUT_FILE.name}")

if __name__ == "__main__":
    main()
