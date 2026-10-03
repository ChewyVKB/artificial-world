"""World settings: load them from a TOML file and lock them into a world.

A world's settings never change after creation. That is what makes a
world reproducible: seed + version + settings => one exact history.
"""
from __future__ import annotations

import copy
import json
import tomllib
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "default.toml"


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> dict:
    """Read settings from TOML, then apply overrides like {"world": {"seed": 7}}."""
    with open(path or DEFAULT_CONFIG_PATH, "rb") as f:
        cfg = tomllib.load(f)
    if overrides:
        cfg = merge(cfg, overrides)
    return cfg


def merge(base: dict, overrides: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def config_fingerprint(cfg: dict) -> str:
    """Stable text form of the settings (used in hashes and saved metadata)."""
    return json.dumps(cfg, sort_keys=True, separators=(",", ":"))
