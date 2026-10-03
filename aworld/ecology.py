"""Living landscape: vegetation, grazing animals, predators and snow.

In Stage 1 plants and animals are *population fields* (how much lives in
each cell), not individuals. That's cheap, and it's all future people
will need: places with game, places with fruit, places that are barren.

Food chain:  sun + rain → plants → grazers → predators
"""
from __future__ import annotations

import numpy as np

# ── Biomes (for display and statistics only; nothing in the sim reads them) ──
BIOMES = [
    "Ocean", "Lake", "Ice", "Tundra", "Boreal forest", "Temperate forest",
    "Grassland", "Desert", "Savanna", "Tropical forest", "Mountain",
]


def classify_biomes(ocean, lake, elevation, annual_t, annual_rain) -> np.ndarray:
    b = np.full(ocean.shape, BIOMES.index("Grassland"), dtype=np.uint8)
    hot, rain = annual_t, annual_rain
    b[(hot >= 5) & (hot < 18) & (rain >= 650)] = BIOMES.index("Temperate forest")
    b[(hot >= 18) & (rain < 1100)] = BIOMES.index("Savanna")
    b[(hot >= 18) & (rain >= 1100)] = BIOMES.index("Tropical forest")
    b[(rain < 250) & (hot >= 0)] = BIOMES.index("Desert")
    b[(hot < 5) & (hot >= -2)] = BIOMES.index("Boreal forest")
    b[(hot < -2)] = BIOMES.index("Tundra")
    b[(hot < -9)] = BIOMES.index("Ice")
    b[(elevation > 3200) & (hot >= -9)] = BIOMES.index("Mountain")
    b[lake] = BIOMES.index("Lake")
    b[ocean] = BIOMES.index("Ocean")
    return b


def plant_capacity(annual_rain: np.ndarray, river: np.ndarray, lake: np.ndarray, land: np.ndarray) -> np.ndarray:
    """How much vegetation a cell could hold in an average year (0..1)."""
    wet = np.clip(annual_rain / 1600.0, 0, 1)
    near_water = river | lake
    for axis in (0, 1):
        near_water = near_water | np.roll(near_water, 1, axis) | np.roll(near_water, -1, axis)
    wet = np.where(near_water, np.maximum(wet, 0.55), wet)   # river valleys stay green
    return np.where(land & ~lake, np.sqrt(wet), 0.0)


def neighbour_table(habitable: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Compact list of living cells, and for each one its 4 neighbours' positions
    in that list. A neighbour that is sea/lake points back at the cell itself,
    so nothing ever wanders into the water."""
    H, W = habitable.shape
    cells = np.flatnonzero(habitable.ravel())
    lookup = np.full(H * W, -1, dtype=np.int64)
    lookup[cells] = np.arange(cells.size)
    ys, xs = np.divmod(cells, W)
    nbr = np.empty((4, cells.size), dtype=np.int64)
    for k, (dy, dx) in enumerate(((-1, 0), (1, 0), (0, -1), (0, 1))):
        ny, nx = ys + dy, xs + dx
        inside = (ny >= 0) & (ny < H) & (nx >= 0) & (nx < W)
        j = np.where(inside, lookup[np.clip(ny, 0, H - 1) * W + np.clip(nx, 0, W - 1)], -1)
        nbr[k] = np.where(j >= 0, j, np.arange(cells.size))
    return cells, nbr


def _spread(field: np.ndarray, rate: float, nbr: np.ndarray) -> np.ndarray:
    """Animals wander into neighbouring land. Total population is conserved."""
    total = field[nbr[0]] + field[nbr[1]] + field[nbr[2]] + field[nbr[3]]
    return field + (rate * 0.25) * (total - 4.0 * field)


def step(state: dict, static: dict, cfg: dict, temperature: np.ndarray,
         rain_factor: np.ndarray, daily_rain_mm: np.ndarray) -> dict:
    """Advance the living world by one day.

    All arrays here are "compact": one value per living (land, non-lake) cell.
    Returns that day's flows for statistics.
    """
    e = cfg["ecology"]
    nbr = static["neighbours"]
    K = static["capacity_c"] * np.sqrt(np.clip(rain_factor, 0.0, 2.0))
    P, G, Z, snow = state["plants"], state["grazers"], state["predators"], state["snow"]

    # Snow: falls when it's freezing, melts when it's warm.
    freezing = temperature < 0
    snow += np.where(freezing, daily_rain_mm / 10.0, -np.minimum(snow, 0.4 * np.maximum(temperature, 0)))
    np.clip(snow, 0, 500, out=snow)
    covered = np.minimum(snow / 20.0, 1.0)

    # Plants: grow in warm, wet weather; die back in frost and drought.
    warmth = np.clip(temperature / 15.0, 0, 1) * np.clip((42.0 - temperature) / 10.0, 0, 1)
    grow = e["plant_growth_rate"] * warmth * (1 - covered) * (P * (1 - P / np.maximum(K, 1e-6)) + 0.002 * K)
    dieback = e["plant_dieback_rate"] * (np.clip(-temperature / 10.0, 0, 1) * P + np.clip(P - K, 0, None))
    P += grow - dieback
    np.clip(P, 0, None, out=P)

    # Grazers eat plants; more food = more offspring; deep snow makes winter deadly.
    feeding = G * P / (P + 0.15)
    eaten = np.minimum(e["grazer_appetite"] * feeding, P)
    P -= eaten
    G += e["grazer_growth"] * feeding - e["grazer_death"] * G * (1 + 2 * covered + G / e["grazer_crowding"])
    np.clip(G, 0, None, out=G)

    # Predators hunt grazers.
    hunting = Z * G / (G + 0.08)
    caught = np.minimum(e["predator_appetite"] * hunting, G)
    G -= caught
    Z += e["predator_growth"] * hunting - e["predator_death"] * Z * (1 + covered)
    np.clip(Z, 0, None, out=Z)

    state["grazers"] = G = _spread(G, e["grazer_spread"], nbr)
    state["predators"] = Z = _spread(Z, e["predator_spread"], nbr)

    # Tiny remnants die out locally (no fractional animals).
    G[G < 1e-6] = 0.0
    Z[Z < 1e-6] = 0.0
    return {"eaten": float(eaten.sum()), "caught": float(caught.sum())}
