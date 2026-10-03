"""Landscape generation: continents, mountains, lakes and rivers.

This runs once, when a world is born. The result never changes during
Stage 1 (later stages may add erosion, earthquakes, rising seas...).
"""
from __future__ import annotations

import heapq

import numpy as np

from . import noise
from .rng import stream

# 8 neighbours: (dy, dx)
NEIGHBOURS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def generate_heightmap(cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    """Return (elevation in metres, ocean mask). Ocean depth is negative elevation."""
    w = cfg["world"]
    seed, H, W = w["seed"], w["height"], w["width"]
    scale = w["continent_scale"]

    base = noise.fbm(stream(seed, "terrain.base"), H, W, scale, octaves=7)
    ridges = 1.0 - np.abs(noise.fbm(stream(seed, "terrain.ridges"), H, W, scale * 2.0, octaves=5))
    ridge_mask = np.clip(noise.fbm(stream(seed, "terrain.ridgemask"), H, W, scale * 0.8, octaves=3) + 0.1, 0, 1)

    # Sink the map edges into the sea so the world is a set of islands/continents in one ocean.
    yy, xx = np.mgrid[0:H, 0:W]
    dy = (yy / (H - 1)) * 2 - 1
    dx = (xx / (W - 1)) * 2 - 1
    # Blend of round and square distance from the centre, so land fades out
    # well before the map border and coastlines don't follow the box.
    r = 0.5 * np.sqrt(dx ** 2 + dy ** 2) / np.sqrt(2) * 1.25 + 0.5 * np.maximum(np.abs(dx), np.abs(dy))
    edge = np.clip(r - 0.58, 0, None) / 0.42

    h = base + 0.55 * ridge_mask * ridges ** 3 - 1.4 * edge ** 1.5
    h = (h - h.min()) / (h.max() - h.min())

    sea = np.quantile(h, w["sea_level"])
    ocean = h <= sea
    elevation = np.where(
        ocean,
        -(sea - h) / max(sea, 1e-9) * 4000.0,                     # ocean depth down to -4 km
        np.clip((h - sea) / max(1 - sea, 1e-9), 0, None) ** 1.6 * w["mountain_height_m"],  # flatter lowlands, sharp peaks
    )
    # Fine roughness (tens of metres) so rivers meander instead of running in straight lines.
    rough = noise.fbm(stream(seed, "terrain.rough"), H, W, scale * 24.0, octaves=3)
    elevation = np.where(ocean, elevation, np.maximum(elevation + 25.0 * rough, 1.0))
    return elevation, ocean


def hydrology(elevation: np.ndarray, ocean: np.ndarray, rain: np.ndarray) -> dict:
    """Work out where water flows.

    Uses "priority flood": flood the land inward from the sea, always
    taking the lowest cell next. Each land cell then drains toward the
    cell it was reached from, so every drop of rain eventually finds the
    sea. Hollows that have to be filled to drain become lakes.
    """
    H, W = elevation.shape
    n = H * W
    elev = elevation.ravel()
    filled = elev.copy()
    receiver = np.full(n, -1, dtype=np.int64)
    done = np.zeros(n, dtype=bool)

    heap: list[tuple[float, int]] = []
    for idx in np.flatnonzero(ocean.ravel()):
        done[idx] = True
        heap.append((float(elev[idx]), int(idx)))
    heapq.heapify(heap)

    while heap:
        level, idx = heapq.heappop(heap)
        y, x = divmod(idx, W)
        for dy, dx in NEIGHBOURS:
            ny, nx = y + dy, x + dx
            if 0 <= ny < H and 0 <= nx < W:
                j = ny * W + nx
                if not done[j]:
                    done[j] = True
                    filled[j] = max(elev[j], level + 1e-3)
                    receiver[j] = idx
                    heapq.heappush(heap, (float(filled[j]), j))

    # Flow accumulation: visit cells from highest to lowest, passing rain downhill.
    order = np.lexsort((np.arange(n), -filled))
    flow = rain.ravel().astype(float).copy()
    flow[ocean.ravel()] = 0.0
    for idx in order:
        r = receiver[idx]
        if r >= 0:
            flow[r] += flow[idx]

    filled = filled.reshape(H, W)
    flow = flow.reshape(H, W)
    land = ~ocean
    lake = land & ((filled - elevation) > 25.0)
    mean_rain = float(rain[land].mean()) if land.any() else 1.0
    river_threshold = mean_rain * 60.0       # water gathered from ~60 average cells
    river = land & ~lake & (flow > river_threshold)
    return {
        "filled": filled,
        "receiver": receiver.reshape(H, W),
        "flow": flow,
        "lake": lake,
        "river": river,
    }
