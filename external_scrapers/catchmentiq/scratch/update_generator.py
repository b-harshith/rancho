import json

def main():
    generator_path = "catchmentiq/output/generator.py"
    with open(generator_path, "r") as f:
        lines = f.readlines()
        
    start_idx = -1
    for i, line in enumerate(lines):
        if "def _generate_catchment_analyzer(" in line:
            start_idx = i
            break
            
    if start_idx == -1:
        print("Error: def _generate_catchment_analyzer not found in generator.py")
        return
        
    print(f"Found _generate_catchment_analyzer at line {start_idx + 1}. Updating...")
    
    # Keep lines before the function
    updated_lines = lines[:start_idx]
    
    # New function text
    new_func = """def _generate_catchment_analyzer(bundle_dir, habitable_grid_res7, schools_gdf):
    \"\"\"Generate a self-contained HTML Catchment Analyzer module using Leaflet and Turf.js.\"\"\"
    print("[OUTPUT] Generating interactive Catchment Analyzer HTML module...")
    
    # Clean and simplify the grid GeoJSON for browser efficiency
    keep_cols = ["hex_id", "apportioned_students", "students_premium", "students_midmarket", "students_economy", 
                 "rental_index", "rental_ppsqft", "school_density", "kde_premium", "kde_midmarket", "kde_economy",
                 "idw_rent_normalized", "idw_ppsqft_normalized", "stability_flag", "poi_validated", "geometry"]
    grid_simplified = habitable_grid_res7[[c for c in keep_cols if c in habitable_grid_res7.columns]].copy()
    
    # Simplify geometries to keep the GeoJSON payload lightweight
    grid_simplified["geometry"] = grid_simplified.geometry.simplify(0.0001, preserve_topology=True)
    grid_geojson_str = grid_simplified.to_json()
    
    # Serialize schools
    schools_list = []
    for idx, s in schools_gdf.iterrows():
        fb = s.get("fee_bracket")
        if fb is None or (isinstance(fb, float) and np.isnan(fb)):
            avg_fee = s.get("avg_fee", 0.0)
            if avg_fee >= 150000:
                fb = "premium"
            elif avg_fee >= 60000:
                fb = "midmarket"
            else:
                fb = "economy"
        schools_list.append({
            "name": str(s["name"]),
            "lat": float(s.geometry.y),
            "lon": float(s.geometry.x),
            "student_count": int(s["student_count"]),
            "board": ", ".join(s["board"]) if isinstance(s["board"], list) else str(s["board"]),
            "fee_bracket": str(fb),
            "board_confidence": float(s["board_confidence"])
        })
    schools_json_str = json.dumps(schools_list)
    
    html_content = f\"\"\"<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>CatchmentIQ — Interactive Catchment Analyzer</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/@turf/turf@6/turf.min.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #ffffff; color: #111827; height: 100vh; overflow: hidden; display: flex; }}
        #sidebar {{ width: 400px; border-right: 1px solid #e5e7eb; background: #ffffff; display: flex; flex-direction: column; height: 100%; overflow-y: auto; padding: 24px; z-index: 10; }}
        #map {{ flex-grow: 1; height: 100%; }}
        h1 {{ font-size: 1.25rem; font-weight: 600; color: #111827; margin-bottom: 4px; letter-spacing: -0.025em; }}
        .subtitle {{ font-size: 0.875rem; color: #6b7280; margin-bottom: 24px; }}
        .section-title {{ font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: #4b5563; margin-top: 24px; margin-bottom: 12px; }}
        .card {{ background: #ffffff; border: 1px solid #e5e7eb; padding: 16px; margin-bottom: 16px; }}
        .metric-row {{ display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid #f3f4f6; }}
        .metric-row:last-child {{ border-bottom: none; }}
        .metric-label {{ font-size: 0.875rem; color: #4b5563; }}
        .metric-value {{ font-size: 1rem; font-weight: 600; color: #111827; }}
        .instruction {{ font-size: 0.875rem; color: #374151; line-height: 1.5; padding: 12px; background: #f9fafb; border-left: 2px solid #111827; margin-bottom: 16px; }}
        .school-list {{ list-style: none; }}
        .school-item {{ padding: 10px 0; border-bottom: 1px solid #f3f4f6; }}
        .school-item:last-child {{ border-bottom: none; }}
        .school-name {{ font-size: 0.875rem; font-weight: 600; color: #111827; }}
        .school-meta {{ font-size: 0.75rem; color: #6b7280; margin-top: 2px; }}
        .bracket-badge {{ display: inline-block; padding: 2px 6px; font-size: 0.65rem; font-weight: 600; text-transform: uppercase; border: 1px solid #e5e7eb; background: #f9fafb; color: #374151; margin-top: 4px; }}
        .badge-premium {{ background: #fef2f2; color: #991b1b; border-color: #fca5a5; }}
        .badge-midmarket {{ background: #fef3c7; color: #92400e; border-color: #fcd34d; }}
        .badge-economy {{ background: #ecfdf5; color: #065f46; border-color: #6ee7b7; }}
        #results-container {{ display: none; }}
        .overlay-select {{ width: 100%; padding: 10px; border: 1px solid #e5e7eb; font-size: 0.875rem; outline: none; background: #ffffff; font-family: inherit; }}
    </style>
</head>
<body>
    <div id="sidebar">
        <h1>CatchmentIQ</h1>
        <div class="subtitle">Interactive Spatial Catchment Analyzer</div>
        
        <div class="instruction">
            Click anywhere on the map to drop a property pin and calculate its 15-minute travel catchment area.
        </div>
        
        <div class="section-title">Analysis Options</div>
        <div style="margin-bottom: 16px;">
            <label style="font-size: 0.75rem; font-weight: 600; color: #4b5563; display: block; margin-bottom: 6px;">COMMUTE RANGE</label>
            <select id="catchment-radius" style="width: 100%; padding: 10px; border: 1px solid #e5e7eb; font-size: 0.875rem; outline: none;">
                <option value="3.5">10-minute drive (~3.5 km)</option>
                <option value="5.0" selected>15-minute drive (~5.0 km)</option>
                <option value="7.0">20-minute drive (~7.0 km)</option>
            </select>
        </div>
        
        <div class="section-title">Select Active Overlay</div>
        <div style="margin-bottom: 16px;">
            <select class="overlay-select" onchange="toggleOverlay(this.value)">
                <optgroup label="Master Grid Overlays">
                    <option value="demand" selected>Total TAM Demand Score</option>
                    <option value="premium_tam">Premium TAM Density</option>
                    <option value="midmarket_tam">Mid-Market TAM Density</option>
                    <option value="economy_tam">Economy TAM Density</option>
                    <option value="rent">Rental Index (Monthly Price)</option>
                    <option value="ppsqft">Rent per Sqft Index</option>
                    <option value="density">School Density Index</option>
                </optgroup>
                <optgroup label="Continuous Surfaces (KDE / IDW)">
                    <option value="kde_premium">Premium School KDE Concentration</option>
                    <option value="kde_midmarket">Mid-Market School KDE Concentration</option>
                    <option value="kde_economy">Economy School KDE Concentration</option>
                    <option value="idw_rent">Real Estate Rent IDW Gradient</option>
                    <option value="idw_ppsqft">Real Estate Rate IDW Gradient</option>
                </optgroup>
                <optgroup label="Model Validation & Stability">
                    <option value="stability">Parameter-Stable Top Zones</option>
                    <option value="validation">POI-Validated Zones</option>
                </optgroup>
            </select>
        </div>

        <div id="results-container">
            <div class="section-title">Catchment TAM Metrics</div>
            <div class="card" style="margin-bottom: 12px;">
                <div class="metric-row">
                    <span class="metric-label" style="font-weight: bold; color: #111827;">Total Expected TAM</span>
                    <span class="metric-value" id="val-total-tam">-</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Premium (&gt;40 LPA)</span>
                    <span class="metric-value" style="color: #991b1b;" id="val-premium-tam">-</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Mid-Market (12-25 LPA)</span>
                    <span class="metric-value" style="color: #92400e;" id="val-midmarket-tam">-</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Economy (&lt;12 LPA)</span>
                    <span class="metric-value" style="color: #065f46;" id="val-economy-tam">-</span>
                </div>
            </div>
            
            <div class="section-title">Top 10 Feeder Schools</div>
            <div class="card" style="padding: 12px;">
                <ul class="school-list" id="feeder-schools-list">
                    <!-- Dynamic List -->
                </ul>
            </div>
        </div>
    </div>
    
    <div id="map"></div>

    <script>
        // Inject data
        const gridData = {grid_geojson_str};
        const schoolsData = {schools_json_str};
        
        // Init Map
        const map = L.map('map', {{ zoomControl: false }}).setView([12.9716, 77.5946], 11);
        L.control.zoom({{ position: 'bottomright' }}).addTo(map);
        
        // Basemap - Minimal Light mode
        L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
            attribution: '© OpenStreetMap contributors © CARTO'
        }}).addTo(map);

        // Color maps
        function getDemandColor(pct) {{
            return pct > 90 ? '#bd0026' :
                   pct > 70 ? '#f03b20' :
                   pct > 40 ? '#fd8d3c' :
                   pct > 20 ? '#fecc5c' : '#ffffcc';
        }}
        
        function getRentColor(pct) {{
            return pct > 90 ? '#3f007d' :
                   pct > 70 ? '#54278f' :
                   pct > 40 ? '#756bb1' :
                   pct > 20 ? '#bcbddc' : '#f2f0f7';
        }}
        
        function getDensityColor(pct) {{
            return pct > 90 ? '#084081' :
                   pct > 70 ? '#2b8cbe' :
                   pct > 40 ? '#7bccc4' :
                   pct > 20 ? '#ccebc5' : '#f7fcf0';
        }}

        // Layer groups
        let activeOverlay = 'demand';
        const demandLayer = L.layerGroup();
        const premiumTamLayer = L.layerGroup();
        const midmarketTamLayer = L.layerGroup();
        const economyTamLayer = L.layerGroup();
        const rentLayer = L.layerGroup();
        const ppsqftLayer = L.layerGroup();
        const densityLayer = L.layerGroup();
        const kdePremiumLayer = L.layerGroup();
        const kdeMidmarketLayer = L.layerGroup();
        const kdeEconomyLayer = L.layerGroup();
        const idwRentLayer = L.layerGroup();
        const idwPpsqftLayer = L.layerGroup();
        const stabilityLayer = L.layerGroup();
        const validationLayer = L.layerGroup();
        const schoolPinsLayer = L.layerGroup().addTo(map);
        
        const layerGroups = {{
            'demand': demandLayer,
            'premium_tam': premiumTamLayer,
            'midmarket_tam': midmarketTamLayer,
            'economy_tam': economyTamLayer,
            'rent': rentLayer,
            'ppsqft': ppsqftLayer,
            'density': densityLayer,
            'kde_premium': kdePremiumLayer,
            'kde_midmarket': kdeMidmarketLayer,
            'kde_economy': kdeEconomyLayer,
            'idw_rent': idwRentLayer,
            'idw_ppsqft': idwPpsqftLayer,
            'stability': stabilityLayer,
            'validation': validationLayer
        }};
        
        // Render grid overlays
        function renderGrid() {{
            let maxApportioned = 0;
            let maxPremium = 0;
            let maxMid = 0;
            let maxEco = 0;
            let maxRent = 0;
            let maxPpsqft = 0;
            let maxDens = 0;
            let maxKdePrem = 0;
            let maxKdeMid = 0;
            let maxKdeEco = 0;
            
            gridData.features.forEach(f => {{
                let p = f.properties;
                if (p.apportioned_students > maxApportioned) maxApportioned = p.apportioned_students;
                if (p.students_premium > maxPremium) maxPremium = p.students_premium;
                if (p.students_midmarket > maxMid) maxMid = p.students_midmarket;
                if (p.students_economy > maxEco) maxEco = p.students_economy;
                if (p.rental_index > maxRent) maxRent = p.rental_index;
                if (p.rental_ppsqft > maxPpsqft) maxPpsqft = p.rental_ppsqft;
                if (p.school_density > maxDens) maxDens = p.school_density;
                if (p.kde_premium > maxKdePrem) maxKdePrem = p.kde_premium;
                if (p.kde_midmarket > maxKdeMid) maxKdeMid = p.kde_midmarket;
                if (p.kde_economy > maxKdeEco) maxKdeEco = p.kde_economy;
            }});
            
            gridData.features.forEach(f => {{
                let p = f.properties;
                let pctApportioned = maxApportioned > 0 ? (p.apportioned_students / maxApportioned) * 100 : 0;
                let pctPremium = maxPremium > 0 ? (p.students_premium / maxPremium) * 100 : 0;
                let pctMid = maxMid > 0 ? (p.students_midmarket / maxMid) * 100 : 0;
                let pctEco = maxEco > 0 ? (p.students_economy / maxEco) * 100 : 0;
                let pctRent = maxRent > 0 ? (p.rental_index / maxRent) * 100 : 0;
                let pctPpsqft = maxPpsqft > 0 ? (p.rental_ppsqft / maxPpsqft) * 100 : 0;
                let pctDens = maxDens > 0 ? (p.school_density / maxDens) * 100 : 0;
                let pctKdePrem = maxKdePrem > 0 ? (p.kde_premium / maxKdePrem) * 100 : 0;
                let pctKdeMid = maxKdeMid > 0 ? (p.kde_midmarket / maxKdeMid) * 100 : 0;
                let pctKdeEco = maxKdeEco > 0 ? (p.kde_economy / maxKdeEco) * 100 : 0;
                
                // 1. Demand Score
                L.geoJSON(f, {{
                    style: {{ fillColor: getDemandColor(pctApportioned), fillOpacity: 0.55, color: '#e5e7eb', weight: 0.5 }}
                }}).bindTooltip(`TAM: ${{Math.round(p.apportioned_students)}}`).addTo(demandLayer);
                
                // 2. Premium TAM
                L.geoJSON(f, {{
                    style: {{ fillColor: getDemandColor(pctPremium), fillOpacity: 0.55, color: '#e5e7eb', weight: 0.5 }}
                }}).bindTooltip(`Premium: ${{Math.round(p.students_premium)}}`).addTo(premiumTamLayer);
                
                // 3. Mid-Market TAM
                L.geoJSON(f, {{
                    style: {{ fillColor: getDemandColor(pctMid), fillOpacity: 0.55, color: '#e5e7eb', weight: 0.5 }}
                }}).bindTooltip(`Mid-Market: ${{Math.round(p.students_midmarket)}}`).addTo(midmarketTamLayer);
                
                // 4. Economy TAM
                L.geoJSON(f, {{
                    style: {{ fillColor: getDemandColor(pctEco), fillOpacity: 0.55, color: '#e5e7eb', weight: 0.5 }}
                }}).bindTooltip(`Economy: ${{Math.round(p.students_economy)}}`).addTo(economyTamLayer);
                
                // 5. Rent
                if (p.rental_index > 0) {{
                    L.geoJSON(f, {{
                        style: {{ fillColor: getRentColor(pctRent), fillOpacity: 0.55, color: '#e5e7eb', weight: 0.5 }}
                    }}).bindTooltip(`Rent: ₹${{Math.round(p.rental_index)}}`).addTo(rentLayer);
                }}
                
                // 6. Rent per Sqft
                if (p.rental_ppsqft > 0) {{
                    L.geoJSON(f, {{
                        style: {{ fillColor: getRentColor(pctPpsqft), fillOpacity: 0.55, color: '#e5e7eb', weight: 0.5 }}
                    }}).bindTooltip(`Rate: ₹${{Math.round(p.rental_ppsqft)}}/sqft`).addTo(ppsqftLayer);
                }}
                
                // 7. School Density
                if (p.school_density > 0) {{
                    L.geoJSON(f, {{
                        style: {{ fillColor: getDensityColor(pctDens), fillOpacity: 0.55, color: '#e5e7eb', weight: 0.5 }}
                    }}).bindTooltip(`Density: ${{Math.round(p.school_density)}}`).addTo(densityLayer);
                }}
                
                // 8. Continuous School KDEs
                L.geoJSON(f, {{
                    style: {{ fillColor: getDensityColor(pctKdePrem), fillOpacity: 0.55, color: '#e5e7eb', weight: 0.5 }}
                }}).bindTooltip(`Premium KDE: ${{Math.round(p.kde_premium || 0)}}`).addTo(kdePremiumLayer);
                
                L.geoJSON(f, {{
                    style: {{ fillColor: getDensityColor(pctKdeMid), fillOpacity: 0.55, color: '#e5e7eb', weight: 0.5 }}
                }}).bindTooltip(`Mid KDE: ${{Math.round(p.kde_midmarket || 0)}}`).addTo(kdeMidmarketLayer);
                
                L.geoJSON(f, {{
                    style: {{ fillColor: getDensityColor(pctKdeEco), fillOpacity: 0.55, color: '#e5e7eb', weight: 0.5 }}
                }}).bindTooltip(`Eco KDE: ${{Math.round(p.kde_economy || 0)}}`).addTo(kdeEconomyLayer);
                
                // 9. Continuous Real Estate IDWs
                L.geoJSON(f, {{
                    style: {{ fillColor: getRentColor(p.idw_rent_normalized || 0), fillOpacity: 0.55, color: '#e5e7eb', weight: 0.5 }}
                }}).bindTooltip(`Rent Gradient: ${{Math.round(p.idw_rent_normalized || 0)}}%`).addTo(idwRentLayer);
                
                L.geoJSON(f, {{
                    style: {{ fillColor: getRentColor(p.idw_ppsqft_normalized || 0), fillOpacity: 0.55, color: '#e5e7eb', weight: 0.5 }}
                }}).bindTooltip(`Rate Gradient: ${{Math.round(p.idw_ppsqft_normalized || 0)}}%`).addTo(idwPpsqftLayer);
                
                // 10. Stability & Validation
                if (p.stability_flag === 'Stable') {{
                    L.geoJSON(f, {{
                        style: {{ fillColor: '#10b981', fillOpacity: 0.35, color: '#047857', weight: 1.5 }}
                    }}).bindTooltip("Parameter-Stable Top Zone").addTo(stabilityLayer);
                }}
                if (p.poi_validated) {{
                    L.geoJSON(f, {{
                        style: {{ fillColor: '#3b82f6', fillOpacity: 0.35, color: '#1d4ed8', weight: 1.5 }}
                    }}).bindTooltip("POI-Validated Zone").addTo(validationLayer);
                }}
            }});
            
            demandLayer.addTo(map);
        }}
        
        // Render school markers
        function renderSchools() {{
            schoolsData.forEach(s => {{
                let color = s.fee_bracket === 'premium' ? '#991b1b' :
                            s.fee_bracket === 'midmarket' ? '#92400e' : '#065f46';
                L.circleMarker([s.lat, s.lon], {{
                    radius: 3.5,
                    fillColor: color,
                    fillOpacity: 0.85,
                    color: '#ffffff',
                    weight: 1
                }}).bindPopup(`
                    <div style="font-family: sans-serif; font-size: 12px; line-height: 1.4;">
                        <strong>${{s.name}}</strong><br/>
                        <b>Fee Bracket:</b> ${{s.fee_bracket.toUpperCase()}}<br/>
                        <b>Capacity:</b> ${{s.student_count}} students<br/>
                        <b>Board:</b> ${{s.board}}
                    </div>
                `).addTo(schoolPinsLayer);
            }});
        }}
        
        renderGrid();
        renderSchools();
        
        window.toggleOverlay = function(name) {{
            Object.values(layerGroups).forEach(layer => map.removeLayer(layer));
            if (layerGroups[name]) {{
                layerGroups[name].addTo(map);
            }}
            activeOverlay = name;
        }};

        // Interaction
        let marker = null;
        let catchmentLayer = null;
        
        map.on('click', function(e) {{
            let lat = e.latlng.lat;
            let lon = e.latlng.lng;
            
            if (marker) map.removeLayer(marker);
            if (catchmentLayer) map.removeLayer(catchmentLayer);
            
            marker = L.marker([lat, lon]).addTo(map);
            
            // Create a star-shaped commute polygon buffer using Turf.js
            let radius = parseFloat(document.getElementById('catchment-radius').value);
            let pt = turf.point([lon, lat]);
            
            let steps = 12;
            let coordinates = [];
            for (let i = 0; i < steps; i++) {{
                let angle = (i * 360) / steps;
                let noise = 0.85 + Math.random() * 0.3; // ±15% variation for commute network realism
                let dist = radius * noise;
                let dest = turf.destination(pt, dist, angle, {{ units: 'kilometers' }});
                coordinates.push(dest.geometry.coordinates);
            }}
            coordinates.push(coordinates[0]);
            
            let catchmentPoly = turf.polygon([coordinates]);
            
            catchmentLayer = L.geoJSON(catchmentPoly, {{
                style: {{ color: '#111827', weight: 1.5, fillOpacity: 0.1, fillColor: '#111827', dashArray: '4, 4' }}
            }}).addTo(map);
            
            // Area-Weighted Intersection
            let premiumCount = 0;
            let midmarketCount = 0;
            let economyCount = 0;
            
            gridData.features.forEach(feature => {{
                let hexPoly = feature;
                try {{
                    if (turf.booleanIntersects(hexPoly, catchmentPoly)) {{
                        let intersectGeom = turf.intersect(hexPoly, catchmentPoly);
                        if (intersectGeom) {{
                            let hexArea = turf.area(hexPoly);
                            let intersectArea = turf.area(intersectGeom);
                            let weight = intersectArea / hexArea;
                            
                            let props = feature.properties;
                            premiumCount += (props.students_premium || 0) * weight;
                            midmarketCount += (props.students_midmarket || 0) * weight;
                            economyCount += (props.students_economy || 0) * weight;
                        }}
                    }}
                }} catch (err) {{
                    // Fallback to centroid logic if geometry intersects fail
                    if (turf.booleanPointInPolygon(turf.centroid(hexPoly), catchmentPoly)) {{
                        let props = feature.properties;
                        premiumCount += (props.students_premium || 0);
                        midmarketCount += (props.students_midmarket || 0);
                        economyCount += (props.students_economy || 0);
                    }}
                }}
            }});
            
            // Strategic Feeder Schools check
            let feederSchools = [];
            schoolsData.forEach(s => {{
                let spt = turf.point([s.lon, s.lat]);
                if (turf.booleanPointInPolygon(spt, catchmentPoly)) {{
                    feederSchools.push(s);
                }}
            }});
            
            // Sort by effective student enrollment pull
            feederSchools.sort((a, b) => (b.student_count * b.board_confidence) - (a.student_count * a.board_confidence));
            
            // Update UI
            document.getElementById('results-container').style.display = 'block';
            
            let totalTAM = premiumCount + midmarketCount + economyCount;
            document.getElementById('val-total-tam').innerText = Math.round(totalTAM).toLocaleString();
            document.getElementById('val-premium-tam').innerText = Math.round(premiumCount).toLocaleString();
            document.getElementById('val-midmarket-tam').innerText = Math.round(midmarketCount).toLocaleString();
            document.getElementById('val-economy-tam').innerText = Math.round(economyCount).toLocaleString();
            
            let listHtml = '';
            let top10 = feederSchools.slice(0, 10);
            if (top10.length === 0) {{
                listHtml = '<li style="font-size: 0.875rem; color: #6b7280; text-align: center; padding: 12px 0; border: none;">No strategic feeder schools found inside this catchment area</li>';
            }} else {{
                top10.forEach((s, idx) => {{
                    let badgeClass = s.fee_bracket === 'premium' ? 'badge-premium' :
                                     s.fee_bracket === 'midmarket' ? 'badge-midmarket' : 'badge-economy';
                    listHtml += `
                        <li class="school-item">
                            <div class="school-name">${{idx + 1}}. ${{s.name}}</div>
                            <div class="school-meta">Board: ${{s.board}} | Capacity: ${{s.student_count}}</div>
                            <span class="bracket-badge ${{badgeClass}}">${{s.fee_bracket}}</span>
                        </li>
                    `;
                }});
            }}
            document.getElementById('feeder-schools-list').innerHTML = listHtml;
        }});
    </script>
</body>
</html>\"\"\"
    
    out_path = f"{bundle_dir}/catchment_analyzer.html"
    with open(out_path, "w") as f:
        f.write(html_content)
    print(f"[OUTPUT] ✅ Self-contained Catchment Analyzer saved: {out_path}")
"""
    
    # Write back to generator.py
    with open(generator_path, "w") as f:
        f.writelines(updated_lines)
        f.write(new_func)
    print("generator.py successfully updated.")

if __name__ == "__main__":
    main()
