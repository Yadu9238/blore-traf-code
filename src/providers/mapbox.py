"""Mapbox traffic-aware routing.

Kept behind a narrow interface so the provider can be swapped for TomTom or HERE
without touching the ingestion or transform layers.
"""
from __future__ import annotations

from src.config import Corridor
from src.providers.base import ProviderError, get_json

BASE_URL = "https://api.mapbox.com/directions/v5/mapbox/driving-traffic"

PROVIDER = "mapbox"


def fetch_corridor(corridor: Corridor, token: str) -> dict:
    """Return live and typical travel time for one corridor."""
    coords = (
        f"{corridor.origin.lon},{corridor.origin.lat};"
        f"{corridor.destination.lon},{corridor.destination.lat}"
    )
    # `annotations` is incompatible with overview=false, and nothing downstream
    # reads the per-leg arrays, so it is omitted to keep the payload small.
    payload = get_json(
        f"{BASE_URL}/{coords}",
        params={
            "access_token": token,
            "overview": "false",
            "alternatives": "false",
        },
    )

    routes = payload.get("routes") or []
    if not routes:
        raise ProviderError(f"No route returned for {corridor.id}")

    route = routes[0]
    live_s = float(route["duration"])
    raw_typical = route.get("duration_typical")
    # Defaulting a missing typical duration to the live one would record a
    # congestion ratio of exactly 1.0 and quietly corrupt the baseline.
    typical_s = float(raw_typical) if raw_typical else None

    return {
        "provider": PROVIDER,
        "duration_live_s": round(live_s, 1),
        "duration_typical_s": round(typical_s, 1) if typical_s else None,
        "distance_m": round(float(route["distance"]), 1),
        "congestion_ratio": round(live_s / typical_s, 4) if typical_s else None,
    }
