#!/bin/bash
set -e

# Require a caller-provided Google Maps API key.
: "${GOOGLE_MAPS_API_KEY:?Set GOOGLE_MAPS_API_KEY before running this pipeline.}"
echo "Starting Opportunity Score Pipeline..."

# Run Stage 2 Processing
echo "Running generate_stage2_hex7_affluence.py..."
python3 scripts/active/generate_stage2_hex7_affluence.py

# Run Final Hex Intelligence
echo "Running generate_final_hex_intelligence.py..."
python3 scripts/active/generate_final_hex_intelligence.py

# Run Graph Network & PageRank Analysis
echo "Running export_graph_network.py..."
python3 scripts/experimental/export_graph_network.py

# Copy generated outputs to the web platform's public data directory
echo "Copying output files to web platform data directory..."
cp DATA/final/bangalore_hex7_affluent_family_intelligence_master.json web_platform_vercel_exact_latest/src/public/data/hexes_master.json
cp DATA/final/bangalore_hex7_affluent_family_intelligence.geojson web_platform_vercel_exact_latest/src/public/data/hexes.geojson

echo "Pipeline completed successfully!"
