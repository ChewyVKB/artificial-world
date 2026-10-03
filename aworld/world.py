"""The World: everything that exists, and the rule for advancing one day.

One tick = one day. `World.step()` depends only on the current state, the
settings and the seed: no clocks, no threads, no randomness that isn't
derived from the seed. Run the same world twice and you get the same
history, bit for bit.

Living things are stored "compactly": one value per land cell (sea and
lake cells hold no plants or animals, so we don't spend memory or CPU on
them). `World.field()` expands a compact array back to the full map.
"""
from __future__ import annotations

import hashlib

import numpy as np

from . import SIM_VERSION, climate, ecology, terrain
from .config import config_fingerprint
from .rng import stream

# The parts of the world that change over time (what a save file stores).
DYNAMIC_FIELDS = ("plants", "grazers", "predators", "snow", "anomaly")


class World:
    def __init__(self, cfg: dict, static: dict, state: dict):
        self.cfg = cfg
        self.static = static
        self.state = state
        self.dpy = cfg["world"]["days_per_year"]
        self.shape = (cfg["world"]["height"], cfg["world"]["width"])

    @classmethod
    def create(cls, cfg: dict) -> "World":
        static = build_static(cfg)
        return cls(cfg, static, initial_state(cfg, static))

    # ── time ────────────────────────────────────────────────────
    @property
    def tick(self) -> int:
        return int(self.state["tick"])

    @property
    def year(self) -> int:
        return self.tick // self.dpy

    @property
    def day_of_year(self) -> int:
        return self.tick % self.dpy

    def weather_today(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(temperature °C, rain multiplier, rain mm) for each land cell, today."""
        s = self.static
        phase = 2 * np.pi * self.day_of_year / self.dpy
        temp = s["annual_temp_c"] + s["swing_c"] * np.sin(phase)
        rain_factor = np.clip(1.0 + self.state["anomaly"], 0.05, None)
        # Rain comes mostly in each hemisphere's warm half of the year.
        seasonal = 1.0 + 0.45 * np.sin(phase) * s["hemisphere_c"]
        rain_mm = s["annual_rain_c"] / self.dpy * rain_factor * seasonal
        return temp, rain_factor, rain_mm

    def step(self) -> dict:
        """Advance one day. Returns that day's flows (food eaten, prey caught)."""
        if self.day_of_year == 0 and self.tick > 0:
            self.state["anomaly"] = climate.next_anomaly(
                self.cfg, self.state["anomaly"], self.year, self.static["cells"])
        temp, rain_factor, rain_mm = self.weather_today()
        flows = ecology.step(self.state, self.static, self.cfg, temp, rain_factor, rain_mm)
        self.state["tick"] = self.tick + 1
        return flows

    def run(self, days: int) -> None:
        for _ in range(days):
            self.step()

    # ── viewing ─────────────────────────────────────────────────
    def field(self, compact: np.ndarray, fill: float = 0.0) -> np.ndarray:
        """Expand a per-land-cell array to the full map."""
        out = np.full(self.shape[0] * self.shape[1], fill, dtype=float)
        out[self.static["cells"]] = compact
        return out.reshape(self.shape)

    def temperature_map(self) -> np.ndarray:
        """Today's temperature everywhere, sea included (°C)."""
        phase = 2 * np.pi * self.day_of_year / self.dpy
        return self.static["annual_temp"] + self.static["swing"] * np.sin(phase)

    # ── identity ────────────────────────────────────────────────
    def state_hash(self) -> str:
        """Fingerprint of the exact world state. Equal hashes = identical worlds."""
        h = hashlib.sha256()
        h.update(SIM_VERSION.encode())
        h.update(config_fingerprint(self.cfg).encode())
        h.update(str(self.tick).encode())
        for name in DYNAMIC_FIELDS:
            h.update(np.ascontiguousarray(self.state[name]).tobytes())
        return h.hexdigest()


def build_static(cfg: dict) -> dict:
    """Everything decided once, at the birth of the world."""
    w = cfg["world"]
    H, W = w["height"], w["width"]
    elevation, ocean = terrain.generate_heightmap(cfg)
    lat = climate.latitude(H, W)
    annual_rain = climate.annual_rainfall(cfg, lat, elevation, ocean)
    hydro = terrain.hydrology(elevation, ocean, annual_rain)
    annual_temp = climate.annual_temperature(cfg, lat, elevation)
    swing = cfg["climate"]["seasonal_swing_c"] * np.sin(np.radians(lat)) * 1.15
    land = ~ocean
    habitable = land & ~hydro["lake"]
    capacity = ecology.plant_capacity(annual_rain, hydro["river"], hydro["lake"], land)
    cells, neighbours = ecology.neighbour_table(habitable)

    def compact(a):
        return np.ascontiguousarray(a.ravel()[cells], dtype=float)

    return {
        # full-map layers
        "elevation": elevation,
        "ocean": ocean,
        "lake": hydro["lake"],
        "river": hydro["river"],
        "flow": hydro["flow"],
        "latitude": lat,
        "annual_temp": annual_temp,
        "annual_rain": annual_rain,
        "swing": swing,
        "habitable": habitable,
        "biome": ecology.classify_biomes(ocean, hydro["lake"], elevation, annual_temp, annual_rain),
        "plant_capacity": capacity,
        # compact (per land cell) copies used by the daily step
        "cells": cells,
        "neighbours": neighbours,
        "annual_temp_c": compact(annual_temp),
        "annual_rain_c": compact(annual_rain),
        "swing_c": compact(swing),
        "hemisphere_c": compact(np.sign(lat)),
        "capacity_c": compact(capacity),
    }


def initial_state(cfg: dict, static: dict) -> dict:
    n = static["cells"].size
    rng = stream(cfg["world"]["seed"], "init.life")
    K = static["capacity_c"]
    return {
        "tick": 0,
        "plants": K * rng.uniform(0.3, 0.8, n),
        "grazers": 0.05 * K * rng.uniform(0.5, 1.5, n),     # start near a natural balance
        "predators": 0.04 * K * rng.uniform(0.5, 1.5, n),
        "snow": np.zeros(n),
        "anomaly": climate.next_anomaly(cfg, np.zeros(n), 0, static["cells"]),
    }
