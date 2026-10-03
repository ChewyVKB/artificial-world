"""Smooth random fields ("fractal noise") used to shape land and weather."""
from __future__ import annotations

import numpy as np


def _smooth(t: np.ndarray) -> np.ndarray:
    return t * t * (3.0 - 2.0 * t)


def value_noise(rng: np.random.Generator, height: int, width: int, cells: float) -> np.ndarray:
    """One layer of smooth noise in [-1, 1] with about `cells` bumps across the map."""
    gh = int(np.ceil(cells * height / max(height, width))) + 2
    gw = int(np.ceil(cells * width / max(height, width))) + 2
    lattice = rng.uniform(-1.0, 1.0, size=(gh, gw))
    ys = np.linspace(0, gh - 2, height, endpoint=False)
    xs = np.linspace(0, gw - 2, width, endpoint=False)
    y0 = ys.astype(int)
    x0 = xs.astype(int)
    ty = _smooth(ys - y0)[:, None]
    tx = _smooth(xs - x0)[None, :]
    a = lattice[y0][:, x0]
    b = lattice[y0][:, x0 + 1]
    c = lattice[y0 + 1][:, x0]
    d = lattice[y0 + 1][:, x0 + 1]
    top = a + (b - a) * tx
    bottom = c + (d - c) * tx
    return top + (bottom - top) * ty


def fbm(rng: np.random.Generator, height: int, width: int, cells: float,
        octaves: int = 6, persistence: float = 0.5) -> np.ndarray:
    """Layer several noise octaves: big shapes plus finer detail. Roughly in [-1, 1]."""
    total = np.zeros((height, width))
    amplitude, norm = 1.0, 0.0
    for i in range(octaves):
        total += amplitude * value_noise(rng, height, width, cells * (2 ** i))
        norm += amplitude
        amplitude *= persistence
    return total / norm


def blur(field: np.ndarray, passes: int = 1) -> np.ndarray:
    """Cheap blur (3x3 average, repeated)."""
    out = field.astype(float, copy=True)
    for _ in range(passes):
        p = np.pad(out, 1, mode="edge")
        out = (p[:-2, :-2] + p[:-2, 1:-1] + p[:-2, 2:] +
               p[1:-1, :-2] + p[1:-1, 1:-1] + p[1:-1, 2:] +
               p[2:, :-2] + p[2:, 1:-1] + p[2:, 2:]) / 9.0
    return out
