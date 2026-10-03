"""Deterministic random numbers.

Every random draw in the simulation comes from a generator built from
(world seed, purpose, and a time key). That means:

* resuming from a save needs no hidden random state, and
* adding a new random system later doesn't shift any existing one.
"""
from __future__ import annotations

import zlib

import numpy as np


def stream(seed: int, purpose: str, *keys: int) -> np.random.Generator:
    tag = zlib.crc32(purpose.encode("utf-8"))
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence([int(seed), tag, *map(int, keys)])))
