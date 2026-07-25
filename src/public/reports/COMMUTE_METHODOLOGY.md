# Commute Convenience Methodology

The commute score is a free proxy model, not live traffic.

## Components

- Arterial access: nearest routed POI travel time and routed evidence density.
- Road quality proxy: habitability, market support, school access, and hospital access.
- Network redundancy: routed school/hospital evidence plus nearby society/cluster density.
- Route directness: OSRM route distance divided by straight-line distance for nearby schools/hospitals.
- Chokepoint risk proxy: penalties for poor route directness and low route redundancy.
- Traffic pattern proxy: penalties for heavy workplace/school pull and route friction.
- Transit relief: distance to nearest metro station.

## Interpretation

Use this as a first-pass access screen. Confirm road width, frontage, turns, parking, pickup/dropoff behavior, and peak-hour congestion on ground.
