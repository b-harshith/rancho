import h3
from shapely.geometry import Polygon

def get_hex_polygon(hex_id: str) -> Polygon:
    """Convert H3 cell ID to shapely Polygon (with longitude, latitude coordinate ordering)."""
    boundary = h3.cell_to_boundary(hex_id)
    # H3 returns (lat, lon) -> we need (lon, lat) for shapely
    flipped_boundary = [(lon, lat) for lat, lon in boundary]
    return Polygon(flipped_boundary)

def get_latlng_hex(lat: float, lon: float, resolution: int) -> str:
    """Get H3 cell ID for a given lat/lon and resolution."""
    return h3.latlng_to_cell(lat, lon, resolution)

def get_neighbors(hex_id: str, k: int = 1) -> set:
    """Get H3 cell IDs for all neighbors within k-ring radius (including center cell)."""
    return h3.grid_disk(hex_id, k)

def get_neighbors_ring(hex_id: str, k: int = 1) -> set:
    """Get H3 cell IDs for all neighbors at exact ring radius k (excluding center cell)."""
    return h3.grid_ring(hex_id, k)
