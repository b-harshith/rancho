"""School normalization, geocoding, and evidence-based merge adapters."""

from .merge import haversine_km, reconcile

__all__ = ["haversine_km", "reconcile"]
