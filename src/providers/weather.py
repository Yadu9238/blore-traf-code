"""Open-Meteo current conditions. No API key required.

Rainfall is the strongest single explanatory variable for Bangalore congestion,
so weather is captured on the same cadence as traffic.
"""
from __future__ import annotations

from src.config import Point
from src.providers.base import get_json

BASE_URL = "https://api.open-meteo.com/v1/forecast"

FIELDS = "temperature_2m,precipitation,rain,wind_speed_10m,cloud_cover"


def fetch_weather(point: Point) -> dict:
    payload = get_json(
        BASE_URL,
        params={
            "latitude": point.lat,
            "longitude": point.lon,
            "current": FIELDS,
            "timezone": "UTC",
        },
    )
    current = payload.get("current", {})
    return {
        "weather_observed_at_utc": current.get("time"),
        "temperature_c": current.get("temperature_2m"),
        "precipitation_mm": current.get("precipitation"),
        "rain_mm": current.get("rain"),
        "wind_speed_kmh": current.get("wind_speed_10m"),
        "cloud_cover_pct": current.get("cloud_cover"),
    }
