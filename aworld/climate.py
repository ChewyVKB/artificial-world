"""Climate: temperature, rainfall, seasons and wet/dry years.

The map runs from 60°N (top) to 60°S (bottom), so the middle is tropical
and the top and bottom edges are cold. Seasons are opposite in the two
hemispheres, like on Earth.
"""
from __future__ import annotations

import numpy as np

from . import noise
from .rng import stream

LATITUDE_SPAN_DEG = 60.0


def latitude(height: int, width: int) -> np.ndarray:
    """Latitude in degrees for every cell; positive = north."""
    lat = np.linspace(LATITUDE_SPAN_DEG, -LATITUDE_SPAN_DEG, height)
    return np.repeat(lat[:, None], width, axis=1)


def annual_temperature(cfg: dict, lat: np.ndarray, elevation: np.ndarray) -> np.ndarray:
    c = cfg["climate"]
    s2 = np.sin(np.radians(lat)) ** 2
    t = c["equator_temp_c"] - (c["equator_temp_c"] - c["pole_temp_c"]) * s2
    return t - c["lapse_rate_c_per_km"] * np.clip(elevation, 0, None) / 1000.0


def annual_rainfall(cfg: dict, lat: np.ndarray, elevation: np.ndarray, ocean: np.ndarray) -> np.ndarray:
    """Yearly rainfall in mm: wet near coasts and the equator, dry in the subtropics
    and deep inside continents, extra rain on windward mountain slopes."""
    seed = cfg["world"]["seed"]
    H, W = elevation.shape
    base = cfg["climate"]["base_rain_mm"]

    a = np.abs(lat)
    bands = (1.25 * np.exp(-(a / 12.0) ** 2)            # equatorial rain belt
             - 0.40 * np.exp(-((a - 27.0) / 9.0) ** 2)  # subtropical deserts
             + 0.25 * np.exp(-((a - 50.0) / 10.0) ** 2)  # mid-latitude storms
             + 0.55)
    coast = noise.blur(ocean.astype(float), passes=12)   # how much sea is nearby
    variety = noise.fbm(stream(seed, "climate.rain"), H, W, 3.0, octaves=4)
    variety = variety / (np.abs(variety).max() + 1e-9)
    slope = np.clip(elevation - np.roll(elevation, 1, axis=1), 0, None) / 400.0  # winds blow west→east
    rain = base * bands * (0.45 + 0.85 * coast) * (1 + 0.55 * variety) * (1 + np.clip(slope, 0, 1.0))
    return np.clip(rain, 30.0, None)


def season_name(lat_deg: float, day_of_year: int, days_per_year: int) -> str:
    q = int((day_of_year / days_per_year) * 4) % 4
    north = ["Spring", "Summer", "Autumn", "Winter"]
    south = ["Autumn", "Winter", "Spring", "Summer"]
    return (north if lat_deg >= 0 else south)[q]


def next_anomaly(cfg: dict, previous: np.ndarray, year: int, cells: np.ndarray) -> np.ndarray:
    """This year's wet/dry pattern for each living cell. Regional, and partly carried
    over from last year, so multi-year droughts can happen. Values are offsets to
    rainfall (e.g. -0.3 = 30% drier than normal)."""
    c = cfg["climate"]
    w = cfg["world"]
    m = c["climate_memory"]
    fresh = noise.fbm(stream(w["seed"], "climate.anomaly", year), w["height"], w["width"], 2.5, octaves=3)
    fresh = (fresh - fresh.mean()) / (np.std(fresh) + 1e-9)
    return m * previous + np.sqrt(1 - m * m) * c["climate_variability"] * fresh.ravel()[cells]
