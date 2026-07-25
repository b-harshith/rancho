import pandas as pd
import geopandas as gpd
import os
import json

def get_top_hotspots(grid_gdf: gpd.GeoDataFrame, top_n: int = 10) -> list:
    """
    Extract the top N hexes with the highest total TAM (sum of Premium, Mid-Market, and Economy).
    Returns their centroids, index, and segmented TAM numbers.
    """
    df = grid_gdf.copy()
    
    # Ensure all required TAM columns exist
    for col in ["students_premium", "students_midmarket", "students_economy"]:
        if col not in df.columns:
            df[col] = 0.0
            
    df["total_tam"] = df["students_premium"] + df["students_midmarket"] + df["students_economy"]
    
    # Drop rows that are not habitable or have no students
    if "is_habitable" in df.columns:
        df = df[df["is_habitable"] == True]
        
    df = df[df["total_tam"] > 0]
    
    if df.empty:
        return []
        
    top_hexes = df.nlargest(top_n, "total_tam")
    hotspots = []
    
    for idx, row in top_hexes.iterrows():
        # Get centroid
        try:
            centroid = row.geometry.centroid
            lat, lon = float(centroid.y), float(centroid.x)
        except Exception:
            lat, lon = 12.9716, 77.5946 # Fallback to Bangalore center
            
        hotspots.append({
            "hex_id": str(row["hex_id"]),
            "lat": lat,
            "lon": lon,
            "total_tam": float(row["total_tam"]),
            "premium": float(row["students_premium"]),
            "midmarket": float(row["students_midmarket"]),
            "economy": float(row["students_economy"]),
            "ward_name": str(row.get("ward_name", "N/A"))
        })
        
    return hotspots

if __name__ == "__main__":
    # Allow running as a standalone script to analyze the generated output
    import argparse
    parser = argparse.ArgumentParser(description="CatchmentIQ Hotspot Precomputer")
    parser.add_argument("--file", help="Path to hex_scores_res7.geojson")
    args = parser.parse_args()
    
    filepath = args.file
    if not filepath:
        # Look for the latest file in output/
        import glob
        files = glob.glob("output/*/hex_scores_res7.geojson")
        if files:
            filepath = max(files, key=os.path.getmtime)
            print(f"Using latest geojson: {filepath}")
        else:
            print("No output geojson found.")
            exit(1)
            
    if os.path.exists(filepath):
        grid_gdf = gpd.read_file(filepath)
        hotspots = get_top_hotspots(grid_gdf)
        print("\n🏆 Top 10 Catchment Hotspots:")
        print("=" * 60)
        for idx, h in enumerate(hotspots, 1):
            print(f"{idx}. Hex: {h['hex_id']} | Lat: {h['lat']:.5f}, Lon: {h['lon']:.5f} | Ward: {h['ward_name']}")
            print(f"   Total TAM: {h['total_tam']:.1f} (Premium: {h['premium']:.1f}, Mid-Market: {h['midmarket']:.1f}, Economy: {h['economy']:.1f})")
            print("-" * 60)
    else:
        print(f"File not found: {filepath}")
