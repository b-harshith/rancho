"""Extract reproducible city-scope boundaries from geoBoundaries India ADM2."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import unary_union


CITY_DISTRICTS = {
    "bengaluru": ["Bangalore"],
    "mumbai": ["Mumbai", "Mumbai Suburban"],
    "hyderabad": ["Hydrabad"],
    "chennai": ["Chennai"],
    "kolkata": ["Kolkata"],
    "pune": ["Pune"],
    "ahmedabad": ["Ahmadabad"],
}

SOURCE = {
    "dataset": "geoBoundaries gbOpen India ADM2",
    "revision": "9469f09",
    "boundary_year": "2021",
    "license": "ODbL 1.0",
    "source_organization": "Pathways Data Pvt. Ltd., lgdirectory.gov.in",
    "api_url": "https://www.geoboundaries.org/api/current/gbOpen/IND/ADM2/",
    "download_url": "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/IND/ADM2/geoBoundaries-IND-ADM2.geojson",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output-dir", default=Path("data/reference/boundaries"), type=Path)
    args = parser.parse_args()

    source = json.loads(args.source.read_text(encoding="utf-8"))
    features_by_name = {
        feature["properties"]["shapeName"]: feature for feature in source["features"]
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for city_id, district_names in CITY_DISTRICTS.items():
        missing = [name for name in district_names if name not in features_by_name]
        if missing:
            raise ValueError(f"{city_id}: source districts not found: {missing}")

        selected = [features_by_name[name] for name in district_names]
        geometries = [shape(feature["geometry"]) for feature in selected]
        boundary = unary_union(geometries)
        if boundary.is_empty or not boundary.is_valid:
            raise ValueError(f"{city_id}: generated boundary is invalid")

        min_lon, min_lat, max_lon, max_lat = boundary.bounds
        centroid = boundary.centroid
        properties = {
            "canonical_city_id": city_id,
            "scope_type": "district_union" if len(selected) > 1 else "district",
            "source_districts": district_names,
            "source_shape_ids": [f["properties"]["shapeID"] for f in selected],
            "source": SOURCE["dataset"],
            "source_revision": SOURCE["revision"],
            "boundary_year": SOURCE["boundary_year"],
            "license": SOURCE["license"],
        }
        output = {
            "type": "FeatureCollection",
            "name": f"{city_id}_boundary",
            "features": [
                {"type": "Feature", "properties": properties, "geometry": mapping(boundary)}
            ],
        }
        boundary_path = args.output_dir / f"{city_id}_boundary.geojson"
        boundary_path.write_text(
            json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        metadata = {
            "canonical_city_id": city_id,
            "generated_on": date.today().isoformat(),
            "scope_policy": "District geometry aligned to the district-based India Post PIN candidate scope; not a municipal or cadastral boundary.",
            "source_districts": district_names,
            "feature_count": len(selected),
            "geometry_type": boundary.geom_type,
            "center": {"lat": centroid.y, "lon": centroid.x},
            "bounds": {"west": min_lon, "south": min_lat, "east": max_lon, "north": max_lat},
            "area_square_degrees": boundary.area,
            "boundary_sha256": sha256(boundary_path),
            "source": SOURCE,
        }
        metadata_path = args.output_dir / f"{city_id}_boundary_metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        print(city_id, boundary.geom_type, metadata["bounds"])


if __name__ == "__main__":
    main()
