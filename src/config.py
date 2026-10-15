"""Configuration loading and shared paths."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config" / "corridors.yml"
RAW_DIR = REPO_ROOT / "data" / "raw"
BRONZE_DIR = REPO_ROOT / "data" / "bronze"
STATUS_PATH = REPO_ROOT / "data" / "status.json"
SERVING_DIR = REPO_ROOT / "data" / "serving"
SILVER_PATH = REPO_ROOT / "data" / "silver" / "observations"
QUARANTINE_PATH = REPO_ROOT / "data" / "quarantine" / "observations"
GOLD_DIR = REPO_ROOT / "data" / "gold"
CHECKPOINT_DIR = REPO_ROOT / "data" / "_checkpoints"
HOLIDAYS_PATH = REPO_ROOT / "config" / "holidays.csv"
IST = "Asia/Kolkata"

# Raw responses are provider-licensed content, so they are deleted after a short
# window. Only our own derived aggregates are retained long term.
RAW_RETENTION_DAYS = int(os.getenv("RAW_RETENTION_DAYS", "7"))


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float


@dataclass(frozen=True)
class Corridor:
    id: str
    name: str
    origin: Point
    destination: Point


@dataclass(frozen=True)
class Settings:
    corridors: list[Corridor]
    city_centre: Point
    mapbox_token: str | None


def _point(raw: dict) -> Point:
    lat, lon = float(raw["lat"]), float(raw["lon"])
    if not (12.0 <= lat <= 14.0) or not (77.0 <= lon <= 78.5):
        raise ValueError(f"Coordinate {lat},{lon} is outside the Bangalore bounding box")
    return Point(lat=lat, lon=lon)


def load_settings(path: Path = CONFIG_PATH) -> Settings:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    corridors = [
        Corridor(
            id=item["id"],
            name=item["name"],
            origin=_point(item["origin"]),
            destination=_point(item["destination"]),
        )
        for item in data["corridors"]
    ]

    ids = [c.id for c in corridors]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"Duplicate corridor ids: {sorted(duplicates)}")

    return Settings(
        corridors=corridors,
        city_centre=_point(data["city_centre"]),
        mapbox_token=os.getenv("MAPBOX_TOKEN"),
    )
