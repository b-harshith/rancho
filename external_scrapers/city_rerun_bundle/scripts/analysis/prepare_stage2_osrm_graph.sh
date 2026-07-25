#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROUTING_DIR="${ROOT_DIR}/DATA/routing"
PBF_PATH="${ROUTING_DIR}/southern-zone-latest.osm.pbf"
OSRM_BASE="${ROUTING_DIR}/southern-zone-latest.osrm"
CAR_PROFILE="/opt/homebrew/opt/osrm-backend/share/osrm/profiles/car.lua"
PBF_URL="https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf"

mkdir -p "${ROUTING_DIR}"

if [[ ! -s "${PBF_PATH}" || "$(stat -f%z "${PBF_PATH}")" -lt 500000000 ]]; then
  echo "Downloading or resuming Southern Zone OSM extract..."
  curl -L -C - "${PBF_URL}" -o "${PBF_PATH}"
fi

if [[ "$(stat -f%z "${PBF_PATH}")" -lt 500000000 ]]; then
  echo "OSM extract still looks incomplete: ${PBF_PATH}" >&2
  exit 1
fi

echo "Building OSRM graph..."
osrm-extract -p "${CAR_PROFILE}" "${PBF_PATH}"
osrm-partition "${OSRM_BASE}"
osrm-customize "${OSRM_BASE}"

echo
echo "OSRM graph is ready."
echo "Start OSRM with:"
echo "osrm-routed --algorithm mld --port 5001 \"${OSRM_BASE}\""
