import geopandas as gpd
import pandas as pd
import sys
import time

def main():
    start_time = time.time()
    
    print("Loading Bangalore wards geojson...")
    wards_path = "data/boundaries/bangalore_wards.geojson"
    wards_gdf = gpd.read_file(wards_path)
    
    # Project wards to UTM Zone 43N (EPSG:32643) for accurate area calculations in sq meters
    print("Projecting wards to UTM Zone 43N (EPSG:32643)...")
    wards_projected = wards_gdf.to_crs(epsg=32643)
    wards_projected['ward_area_sqm'] = wards_projected.geometry.area
    
    print("Loading Overture Bangalore buildings geojson...")
    buildings_path = "overture/bangalore_buildings.geojson"
    buildings_gdf = gpd.read_file(buildings_path)
    
    print(f"Loaded {len(buildings_gdf)} buildings.")
    
    print("Ensuring valid building geometries...")
    # Filter out invalid or empty geometries
    buildings_gdf = buildings_gdf[buildings_gdf.geometry.is_valid & ~buildings_gdf.geometry.is_empty]
    print(f"{len(buildings_gdf)} valid buildings remaining.")
    
    print("Computing building centroids for clean spatial matching...")
    # Using centroids ensures each building is assigned to exactly one ward and avoids double-counting/boundary issues
    buildings_centroid_gdf = gpd.GeoDataFrame(
        buildings_gdf[['id']], 
        geometry=buildings_gdf.geometry.centroid, 
        crs=buildings_gdf.crs
    )
    
    print("Performing spatial join (centroids within wards)...")
    # Sjoin centroids to wards in EPSG:4326 (faster than projecting all building polygons first)
    joined_centroids = gpd.sjoin(buildings_centroid_gdf, wards_gdf, how='inner', predicate='within')
    
    print(f"Mapped {len(joined_centroids)} buildings to wards.")
    
    # Merge the ward info back to the original building polygons
    print("Mapping ward information back to building polygons...")
    matched_buildings = buildings_gdf.merge(
        joined_centroids[['id', 'name', 'ward']], 
        on='id', 
        how='inner'
    )
    
    print("Projecting matched buildings to UTM Zone 43N to calculate areas...")
    # Project only the matched buildings to save computation time
    matched_buildings_projected = matched_buildings.to_crs(epsg=32643)
    matched_buildings_projected['building_area_sqm'] = matched_buildings_projected.geometry.area
    
    print("Aggregating building statistics per ward...")
    # Group by ward identifier (name and/or ward number)
    # We aggregate count and total area
    building_stats = matched_buildings_projected.groupby(['ward', 'name']).agg(
        building_count=('id', 'count'),
        total_building_area_sqm=('building_area_sqm', 'sum')
    ).reset_index()
    
    # Merge ward area information
    ward_areas = wards_projected[['ward', 'name', 'ward_area_sqm']]
    result = pd.merge(ward_areas, building_stats, on=['ward', 'name'], how='left')
    
    # Fill NaN values for wards with no buildings
    result['building_count'] = result['building_count'].fillna(0).astype(int)
    result['total_building_area_sqm'] = result['total_building_area_sqm'].fillna(0.0)
    
    # Calculate density metrics
    # 1. Building count per sq km of ward area
    result['building_density_count_per_sqkm'] = result['building_count'] / (result['ward_area_sqm'] / 1e6)
    
    # 2. Building area ratio (ratio of building footprint area to ward area)
    result['building_area_ratio'] = result['total_building_area_sqm'] / result['ward_area_sqm']
    
    # Sort by building area ratio descending
    result = result.sort_values(by='building_area_ratio', ascending=False)
    
    output_csv = "ward_building_statistics.csv"
    print(f"Saving results to {output_csv}...")
    result.to_csv(output_csv, index=False)
    
    print("\nSample Output:")
    print(result.head(10).to_string(index=False))
    
    elapsed_time = time.time() - start_time
    print(f"\nExecution completed in {elapsed_time:.2f} seconds.")

if __name__ == "__main__":
    main()
