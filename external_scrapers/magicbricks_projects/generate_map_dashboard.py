import json
import os

CLASSIFIED_FILE = "data/processed/bangalore_projects_classified.json"
GEOJSON_FILE = "data/processed/bangalore_projects.geojson"
MAP_HTML_FILE = "interactive_map.html"

def classify_project_type(name, locality):
    name = (name or "").lower()
    locality = (locality or "").lower()
    if any(k in name or k in locality for k in ["plot", "plots", "land", "layout", "site", "sites"]):
        return "Plot / Land"
    if any(k in name or k in locality for k in ["villa", "villas", "bungalow", "bungalows", "row house", "rowhouse"]):
        return "Villa / Bungalow"
    if "builder floor" in name:
        return "Builder Floor"
    if any(k in name for k in ["flat", "flats", "apartment", "apartments", "studio", "condo", "penthouse"]):
        return "Apartment / Flat"
    if "house" in name:
        return "Independent House"
    return "Apartment / Flat"

def main():
    if not os.path.exists(CLASSIFIED_FILE):
        print(f"Error: {CLASSIFIED_FILE} does not exist.")
        return

    with open(CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        projects = json.load(f)

    # 1. Generate GeoJSON
    geojson_features = []
    for p in projects:
        lat = p.get("lat")
        lon = p.get("lon")
        if lat is None or lon is None:
            continue
            
        name = p.get("name")
        locality = p.get("locality")
        project_type = classify_project_type(name, locality)
        
        # Calculate a mid-point price for general filtering
        min_p = p.get("min_price") or 0.0
        max_p = p.get("max_price") or 0.0
        mid_price = (min_p + max_p) / 2 if (min_p and max_p) else (min_p or max_p or 0.0)
        
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(lon), float(lat)]
            },
            "properties": {
                "name": name,
                "locality": locality,
                "category": p.get("category"),
                "quartile_1": p.get("quartile analysis 1"),
                "quartile_2": p.get("quartile analysis 2"),
                "price_SQFT": p.get("price_SQFT"),
                "units": p.get("units"),
                "url": p.get("url"),
                "construction_status": p.get("construction_status"),
                "min_price": min_p,
                "max_price": max_p,
                "mid_price": mid_price,
                "project_type": project_type
            }
        }
        geojson_features.append(feature)

    geojson_data = {
        "type": "FeatureCollection",
        "features": geojson_features
    }

    os.makedirs(os.path.dirname(GEOJSON_FILE), exist_ok=True)
    with open(GEOJSON_FILE, "w", encoding="utf-8") as f:
        json.dump(geojson_data, f, indent=2, ensure_ascii=False)
    print(f"Successfully generated GeoJSON with {len(geojson_features)} features at {GEOJSON_FILE}.")

    # 2. Generate Standalone HTML Map Viewer
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bangalore Residential Projects Map Dashboard</title>
    
    <!-- Leaflet & MarkerCluster CSS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
    <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" />
    
    <!-- Google Fonts & Tailwind-like CSS variables -->
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    
    <style>
        :root {{
            --bg-dark: #0f172a;
            --panel-dark: rgba(30, 41, 59, 0.75);
            --border-light: rgba(255, 255, 255, 0.08);
            --accent-blue: #3b82f6;
            --accent-green: #10b981;
            --accent-purple: #8b5cf6;
            --accent-gold: #f59e0b;
            --text-main: #f8fafc;
            --text-secondary: #94a3b8;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Outfit', sans-serif;
        }}

        body {{
            background: var(--bg-dark);
            color: var(--text-main);
            height: 100vh;
            display: flex;
            overflow: hidden;
        }}

        #map {{
            flex: 1;
            height: 100%;
            z-index: 1;
        }}

        /* Control Panel Styles */
        .sidebar {{
            width: 420px;
            background: var(--panel-dark);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border-right: 1px solid var(--border-light);
            z-index: 10;
            display: flex;
            flex-direction: column;
            box-shadow: 10px 0 30px rgba(0,0,0,0.5);
        }}

        .sidebar-header {{
            padding: 24px;
            border-bottom: 1px solid var(--border-light);
            background: rgba(15, 23, 42, 0.4);
        }}

        .sidebar-header h1 {{
            font-size: 20px;
            font-weight: 700;
            letter-spacing: -0.5px;
            background: linear-gradient(135deg, #60a5fa, #c084fc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 6px;
        }}

        .sidebar-header p {{
            font-size: 13px;
            color: var(--text-secondary);
        }}

        .sidebar-content {{
            flex: 1;
            overflow-y: auto;
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 24px;
        }}

        /* Filters Section */
        .filter-group {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}

        .filter-label {{
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-secondary);
        }}

        select, input[type="range"] {{
            width: 100%;
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid var(--border-light);
            border-radius: 8px;
            color: var(--text-main);
            padding: 10px 12px;
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s;
        }}

        select:focus {{
            border-color: var(--accent-blue);
        }}

        /* Price Slider */
        .range-container {{
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid var(--border-light);
            padding: 14px;
            border-radius: 8px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }}

        .range-labels {{
            display: flex;
            justify-content: space-between;
            font-size: 13px;
            color: var(--text-secondary);
        }}

        .range-val {{
            font-weight: 600;
            color: var(--accent-blue);
        }}

        /* Metrics Grid */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
        }}

        .metric-card {{
            background: rgba(30, 41, 59, 0.4);
            border: 1px solid var(--border-light);
            border-radius: 12px;
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 4px;
            transition: transform 0.2s, background-color 0.2s;
        }}

        .metric-card:hover {{
            background: rgba(30, 41, 59, 0.6);
            transform: translateY(-2px);
        }}

        .metric-title {{
            font-size: 12px;
            color: var(--text-secondary);
            font-weight: 500;
        }}

        .metric-value {{
            font-size: 20px;
            font-weight: 700;
            color: var(--text-main);
        }}

        .metric-value.highlight {{
            color: var(--accent-green);
        }}

        /* Custom Popup Styles */
        .leaflet-popup-content-wrapper {{
            background: rgba(15, 23, 42, 0.95);
            backdrop-filter: blur(8px);
            border: 1px solid var(--border-light);
            color: var(--text-main);
            border-radius: 12px;
            padding: 6px;
        }}

        .leaflet-popup-tip {{
            background: rgba(15, 23, 42, 0.95);
        }}

        .popup-title {{
            font-size: 15px;
            font-weight: 700;
            margin-bottom: 6px;
            color: #60a5fa;
        }}

        .popup-detail {{
            font-size: 12px;
            margin-bottom: 4px;
            color: var(--text-secondary);
        }}

        .popup-detail span {{
            color: var(--text-main);
            font-weight: 600;
        }}

        .popup-tag {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            margin-top: 6px;
            margin-right: 4px;
        }}

        .tag-status {{
            background: rgba(16, 185, 129, 0.15);
            color: #34d399;
        }}

        .tag-category {{
            background: rgba(139, 92, 246, 0.15);
            color: #a78bfa;
        }}

        .popup-link {{
            display: block;
            margin-top: 10px;
            font-size: 12px;
            color: var(--accent-blue);
            text-decoration: none;
            font-weight: 600;
        }}

        .popup-link:hover {{
            text-decoration: underline;
        }}

        /* Scrollbar styles */
        ::-webkit-scrollbar {{
            width: 6px;
        }}
        ::-webkit-scrollbar-track {{
            background: transparent;
        }}
        ::-webkit-scrollbar-thumb {{
            background: rgba(255,255,255,0.1);
            border-radius: 3px;
        }}
        ::-webkit-scrollbar-thumb:hover {{
            background: rgba(255,255,255,0.2);
        }}
    </style>
</head>
<body>

    <div class="sidebar">
        <div class="sidebar-header">
            <h1>Bangalore Projects</h1>
            <p>Interactive Market Intelligence Dashboard</p>
        </div>
        
        <div class="sidebar-content">
            <!-- Metrics Grid -->
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-title">Total Projects</div>
                    <div id="stat-projects" class="metric-value">0</div>
                </div>
                <div class="metric-card">
                    <div class="metric-title">Total Units</div>
                    <div id="stat-units" class="metric-value highlight">0</div>
                </div>
                <div class="metric-card">
                    <div class="metric-title">Avg Price (Cr)</div>
                    <div id="stat-avg-price" class="metric-value">₹0.00</div>
                </div>
                <div class="metric-card">
                    <div class="metric-title">Avg Price / SqFt</div>
                    <div id="stat-avg-sqft" class="metric-value">₹0</div>
                </div>
            </div>

            <!-- Filters Section -->
            <div class="filter-group">
                <div class="filter-label">Project Type</div>
                <select id="filter-type">
                    <option value="all">All Types</option>
                    <option value="Apartment / Flat">Apartment / Flat</option>
                    <option value="Villa / Bungalow">Villa / Bungalow</option>
                    <option value="Plot / Land">Plot / Land</option>
                    <option value="Builder Floor">Builder Floor</option>
                    <option value="Independent House">Independent House</option>
                </select>
            </div>

            <div class="filter-group">
                <div class="filter-label">Construction Status</div>
                <select id="filter-status">
                    <option value="all">All Statuses</option>
                    <option value="Ready To Move">Ready To Move</option>
                    <option value="Under Construction">Under Construction</option>
                </select>
            </div>

            <div class="filter-group">
                <div class="filter-label">Luxury Segment</div>
                <select id="filter-category">
                    <option value="all">All Segments</option>
                    <option value="Affordable">Affordable</option>
                    <option value="Mid-Range">Mid-Range</option>
                    <option value="Aspire / Upper-Mid">Aspire / Upper-Mid</option>
                    <option value="Premium Luxury">Premium Luxury (Q4-Sub-Q1)</option>
                    <option value="Super Luxury">Super Luxury (Q4-Sub-Q2)</option>
                    <option value="Ultra Luxury">Ultra Luxury (Q4-Sub-Q3)</option>
                    <option value="Elite Luxury">Elite Luxury (Q4-Sub-Q4)</option>
                </select>
            </div>

            <div class="filter-group">
                <div class="filter-label">Max Price Limit (Cr)</div>
                <div class="range-container">
                    <input type="range" id="filter-price" min="0" max="30" step="0.5" value="30">
                    <div class="range-labels">
                        <span>₹0 Cr</span>
                        <span class="range-val" id="price-slider-val">₹30+ Cr</span>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div id="map"></div>

    <!-- Leaflet & Plugins Script -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
    <script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>

    <!-- Embedded GeoJSON Data -->
    <script>
        const geojsonData = {json.dumps(geojson_data)};
    </script>

    <script>
        // Initialize Map
        const map = L.map('map', {{
            center: [12.9716, 77.5946],
            zoom: 11,
            zoomControl: false
        }});

        L.control.zoom({{ position: 'topright' }}).addTo(map);

        // Dark Map Tiles
        L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
        }}).addTo(map);

        // Marker cluster group
        let markerCluster = L.markerClusterGroup({{
            maxClusterRadius: 50,
            showCoverageOnHover: false
        }}).addTo(map);

        // Color mapping for marker dots
        function getSegmentColor(category) {{
            switch(category) {{
                case 'Elite Luxury': return '#ef4444'; // Red
                case 'Ultra Luxury': return '#ec4899'; // Pink
                case 'Super Luxury': return '#a855f7'; // Purple
                case 'Premium Luxury': return '#3b82f6'; // Blue
                case 'Aspire / Upper-Mid': return '#f59e0b'; // Amber
                case 'Mid-Range': return '#10b981'; // Green
                case 'Affordable': return '#6b7280'; // Gray
                default: return '#3b82f6';
            }}
        }}

        // Format Currency
        const defFormatCr = (val) => {{
            if (!val) return 'N/A';
            return '₹' + (val / 1e7).toFixed(2) + ' Cr';
        }};

        // Update Filters & Metrics
        function updateMap() {{
            const selectedType = document.getElementById('filter-type').value;
            const selectedStatus = document.getElementById('filter-status').value;
            const selectedCategory = document.getElementById('filter-category').value;
            const maxPriceVal = parseFloat(document.getElementById('filter-price').value);

            // Update range slider text label
            if (maxPriceVal >= 30) {{
                document.getElementById('price-slider-val').innerText = 'All Prices';
            }} else {{
                document.getElementById('price-slider-val').innerText = 'Up to ₹' + maxPriceVal.toFixed(1) + ' Cr';
            }}

            // Clear existing markers
            markerCluster.clearLayers();

            let matchedProjects = 0;
            let totalUnits = 0;
            let totalPriceSum = 0;
            let totalSqftSum = 0;
            let priceCount = 0;
            let sqftCount = 0;

            geojsonData.features.forEach(feature => {{
                const prop = feature.properties;
                
                // Filtering checks
                if (selectedType !== 'all' && prop.project_type !== selectedType) return;
                if (selectedStatus !== 'all' && prop.construction_status !== selectedStatus) return;
                if (selectedCategory !== 'all' && prop.category !== selectedCategory) return;
                
                const midPriceCr = prop.mid_price / 1e7;
                if (maxPriceVal < 30 && midPriceCr > maxPriceVal) return;

                // Accumulate Stats
                matchedProjects++;
                if (prop.units) totalUnits += parseInt(prop.units);
                if (prop.mid_price) {{
                    totalPriceSum += prop.mid_price;
                    priceCount++;
                }}
                if (prop.price_SQFT) {{
                    totalSqftSum += prop.price_SQFT;
                    sqftCount++;
                }}

                // Create Marker
                const color = getSegmentColor(prop.category);
                const marker = L.circleMarker([feature.geometry.coordinates[1], feature.geometry.coordinates[0]], {{
                    radius: 8,
                    fillColor: color,
                    color: '#ffffff',
                    weight: 1,
                    opacity: 0.8,
                    fillOpacity: 0.8
                }});

                // Popup construction
                const priceFormatted = prop.min_price === prop.max_price ? 
                    defFormatCr(prop.min_price) : 
                    `${{defFormatCr(prop.min_price)}} - ${{defFormatCr(prop.max_price)}}`;

                const popupHtml = `
                    <div class="popup-title">${{prop.name}}</div>
                    <div class="popup-detail">Locality: <span>${{prop.locality}}</span></div>
                    <div class="popup-detail">Price: <span>${{priceFormatted}}</span></div>
                    <div class="popup-detail">Avg/SqFt: <span>${{prop.price_SQFT ? '₹' + prop.price_SQFT.toLocaleString() : 'N/A'}}</span></div>
                    <div class="popup-detail">Total Units: <span>${{prop.units || 'N/A'}}</span></div>
                    <div>
                        <span class="popup-tag tag-status">${{prop.construction_status}}</span>
                        <span class="popup-tag tag-category">${{prop.category}}</span>
                    </div>
                    ${{prop.url ? `<a href="${{prop.url}}" target="_blank" class="popup-link">View on MagicBricks →</a>` : ''}}
                `;

                marker.bindPopup(popupHtml);
                markerCluster.addLayer(marker);
            }});

            // Update stats labels in dashboard
            document.getElementById('stat-projects').innerText = matchedProjects.toLocaleString();
            document.getElementById('stat-units').innerText = totalUnits.toLocaleString();
            document.getElementById('stat-avg-price').innerText = priceCount > 0 ? 
                '₹' + (totalPriceSum / priceCount / 1e7).toFixed(2) + ' Cr' : 'N/A';
            document.getElementById('stat-avg-sqft').innerText = sqftCount > 0 ? 
                '₹' + Math.round(totalSqftSum / sqftCount).toLocaleString() : 'N/A';
        }}

        // Bind filter event listeners
        document.getElementById('filter-type').addEventListener('change', updateMap);
        document.getElementById('filter-status').addEventListener('change', updateMap);
        document.getElementById('filter-category').addEventListener('change', updateMap);
        document.getElementById('filter-price').addEventListener('input', updateMap);

        // Initial Map Run
        updateMap();
    </script>
</body>
</html>
"""

    with open(MAP_HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"Successfully generated interactive HTML dashboard map at {MAP_HTML_FILE}.")

if __name__ == "__main__":
    main()
