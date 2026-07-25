#!/usr/bin/env python3
import http.server
import socketserver
import json
import os

PORT = 8000
ENRICHED_FILE = "data/raw/bangalore_projects_enriched.jsonl"

class LiveVisualizationHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/data":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            projects = []
            if os.path.exists(ENRICHED_FILE):
                try:
                    with open(ENRICHED_FILE, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip():
                                try:
                                    card = json.loads(line)
                                    # Only include projects with valid coordinates
                                    if card.get("latitude") is not None and card.get("longitude") is not None:
                                        projects.append(card)
                                except Exception:
                                    pass
                except Exception as e:
                    print(f"Error reading file: {e}")
                    
            self.wfile.write(json.dumps({"projects": projects}).encode("utf-8"))
            
        elif self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode("utf-8"))
        else:
            super().do_GET()

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bangalore Real Estate - Live Scraper Map</title>
    
    <!-- Google Fonts -->
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap" rel="stylesheet">
    
    <!-- Leaflet Map CSS & JS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Outfit', sans-serif;
        }

        body {
            background-color: #0b0f19;
            color: #f3f4f6;
            overflow: hidden;
            display: flex;
            height: 100vh;
        }

        #sidebar {
            width: 380px;
            background: rgba(15, 23, 42, 0.85);
            backdrop-filter: blur(16px);
            border-right: 1px solid rgba(255, 255, 255, 0.08);
            display: flex;
            flex-direction: column;
            padding: 24px;
            z-index: 1000;
            box-shadow: 10px 0 30px rgba(0, 0, 0, 0.5);
            overflow-y: auto;
        }

        #map {
            flex: 1;
            height: 100%;
        }

        h1 {
            font-size: 24px;
            font-weight: 800;
            background: linear-gradient(135deg, #38bdf8, #818cf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }

        .status-badge {
            display: inline-flex;
            align-items: center;
            padding: 6px 12px;
            background: rgba(16, 185, 129, 0.1);
            color: #10b981;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 24px;
            border: 1px solid rgba(16, 185, 129, 0.2);
            align-self: flex-start;
        }

        .status-dot {
            width: 8px;
            height: 8px;
            background-color: #10b981;
            border-radius: 50%;
            margin-right: 8px;
            animation: pulse 1.5s infinite;
        }

        @keyframes pulse {
            0% { transform: scale(0.9); opacity: 0.6; }
            50% { transform: scale(1.2); opacity: 1; }
            100% { transform: scale(0.9); opacity: 0.6; }
        }

        .stat-card {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 16px;
            transition: all 0.3s ease;
        }

        .stat-card:hover {
            border-color: rgba(56, 189, 248, 0.3);
            transform: translateY(-2px);
        }

        .stat-label {
            font-size: 12px;
            color: #9ca3af;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .stat-value {
            font-size: 32px;
            font-weight: 800;
            color: #ffffff;
            margin-top: 4px;
        }

        .segment-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 10px;
            padding-bottom: 8px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            font-size: 14px;
        }

        .segment-tag {
            display: flex;
            align-items: center;
        }

        .color-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 8px;
        }

        .legend {
            margin-top: auto;
            padding-top: 20px;
        }

        .leaflet-popup-content-wrapper {
            background: #1e293b !important;
            color: #f3f4f6 !important;
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px !important;
            padding: 6px;
        }

        .leaflet-popup-tip {
            background: #1e293b !important;
        }

        .popup-title {
            font-weight: 800;
            font-size: 15px;
            margin-bottom: 4px;
            color: #38bdf8;
        }
        
        .popup-meta {
            font-size: 12px;
            color: #9ca3af;
            margin-bottom: 8px;
        }
        
        .popup-price {
            font-size: 14px;
            font-weight: 600;
            color: #10b981;
        }
    </style>
</head>
<body>

    <div id="sidebar">
        <h1>Bangalore Real Estate</h1>
        <p style="color: #9ca3af; font-size: 14px; margin-bottom: 12px;">Live Scraper Geolocation Visualizer</p>
        
        <div class="status-badge">
            <div class="status-dot"></div>
            Live Monitoring (Reloads every 50 new points)
        </div>

        <div class="stat-card">
            <div class="stat-label">Mapped Projects</div>
            <div class="stat-value" id="total-mapped">0</div>
        </div>

        <div class="stat-card" style="flex: 1;">
            <div class="stat-label" style="margin-bottom: 8px;">Segments Breakdown</div>
            <div id="segments-container">
                <!-- Dynamic segments -->
            </div>
        </div>
        
        <div class="legend">
            <p style="font-size: 12px; color: #9ca3af; text-align: center;">
                * Radius represents project size (total units).
            </p>
        </div>
    </div>

    <div id="map"></div>

    <script>
        // Init Map centering Bangalore
        const map = L.map('map', {
            zoomControl: false
        }).setView([12.9716, 77.5946], 11);

        // Dark theme tiles
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
            subdomains: 'abcd',
            maxZoom: 20
        }).addTo(map);

        L.control.zoom({ position: 'topright' }).addTo(map);

        let projectMarkers = [];
        let lastCount = 0;

        // Categorization function
        function getSegment(name, desc) {
            name = (name || '').toLowerCase();
            desc = (desc || '').toLowerCase();
            
            if (name.includes('flat') || name.includes('apartment') || name.includes('penthouse') || desc.includes('flat') || desc.includes('apartment') || desc.includes('penthouse')) {
                return 'Apartment';
            }
            if (name.includes('villa') || name.includes('row house') || name.includes('rowhouse') || name.includes('house') || desc.includes('villa') || desc.includes('row house') || desc.includes('rowhouse') || desc.includes('house')) {
                return 'Villa/House';
            }
            if (name.includes('builder floor') || desc.includes('builder floor')) {
                return 'Builder Floor';
            }
            return 'Other';
        }

        const colors = {
            'Apartment': '#38bdf8',
            'Villa/House': '#fbbf24',
            'Builder Floor': '#ec4899',
            'Other': '#a855f7'
        };

        function formatPrice(val) {
            if (!val) return 'Contact Developer';
            if (val >= 10000000) {
                return '₹' + (val / 10000000).toFixed(2) + ' Cr';
            }
            return '₹' + (val / 100000).toFixed(2) + ' Lac';
        }

        async function updateMapData() {
            try {
                const response = await fetch('/api/data');
                const data = await response.json();
                const projects = data.projects;
                
                // Only reload elements if there's a difference of 50 or more new items
                if (projects.length >= lastCount + 50 || lastCount === 0 || projects.length < lastCount) {
                    console.log(`Updating visualization with ${projects.length} points...`);
                    
                    // Clear existing markers
                    projectMarkers.forEach(m => map.removeLayer(m));
                    projectMarkers = [];

                    let segmentCounts = { 'Apartment': 0, 'Villa/House': 0, 'Builder Floor': 0, 'Other': 0 };

                    projects.forEach(p => {
                        const segment = getSegment(p.psmName, p.mhDesc);
                        segmentCounts[segment] = (segmentCounts[segment] || 0) + 1;

                        const lat = parseFloat(p.latitude);
                        const lon = parseFloat(p.longitude);
                        
                        if (isNaN(lat) || isNaN(lon)) return;

                        // Size based on totalUnits, default to 30 if null
                        const units = p.totalUnits ? parseInt(p.totalUnits) : 30;
                        const radius = Math.max(8, Math.min(40, Math.sqrt(units) * 1.5));

                        const marker = L.circleMarker([lat, lon], {
                            radius: radius,
                            fillColor: colors[segment],
                            color: '#ffffff',
                            weight: 1,
                            opacity: 0.4,
                            fillOpacity: 0.65
                        });

                        const popupHtml = `
                            <div class="popup-title">${p.psmName || 'Unnamed Project'}</div>
                            <div class="popup-meta">${p.lmtDName || 'Bangalore'} | ${segment}</div>
                            <div class="popup-meta">Units: ${p.totalUnits || 'N/A'}</div>
                            <div class="popup-price">Price: ${formatPrice(p.minPrice)} - ${formatPrice(p.maxPrice)}</div>
                        `;
                        marker.bindPopup(popupHtml);
                        marker.addTo(map);
                        projectMarkers.push(marker);
                    });

                    // Update UI Counts
                    document.getElementById('total-mapped').innerText = projects.length.toLocaleString();
                    lastCount = projects.length;

                    // Update Breakdown Sidebar
                    let breakdownHtml = '';
                    for (const [seg, count] of Object.entries(segmentCounts)) {
                        breakdownHtml += `
                            <div class="segment-row">
                                <div class="segment-tag">
                                    <div class="color-dot" style="background-color: ${colors[seg]}"></div>
                                    <span>${seg}</span>
                                </div>
                                <span style="font-weight: 600;">${count}</span>
                            </div>
                        `;
                    }
                    document.getElementById('segments-container').innerHTML = breakdownHtml;
                }
            } catch (err) {
                console.error("Error updating map:", err);
            }
        }

        // Poll every 4 seconds
        setInterval(updateMapData, 4000);
        updateMapData();
    </script>
</body>
</html>
"""

def main():
    # Make sure output directory is present
    os.makedirs("data/raw", exist_ok=True)
    
    handler = LiveVisualizationHandler
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        print(f"Visualizer server active at: http://localhost:{PORT}")
        print("Keep this terminal open, and open the URL in your browser to watch the real-time mapping!")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down visualization server.")

if __name__ == "__main__":
    main()
