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
# In the Docker image, a pristine copy of the settings ships here.
BUNDLED_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.defaults" / "default.toml"


def ensure_config(path: str | Path | None = None) -> Path:
    """Make sure the settings file exists. If it's missing (e.g. an empty folder
    was mounted into the container), copy in the bundled defaults."""
    target = Path(path) if path else DEFAULT_CONFIG_PATH
    if not target.exists() and BUNDLED_CONFIG_PATH.exists():
        import shutil
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BUNDLED_CONFIG_PATH, target)
        print(f"[config] no settings file found — wrote the defaults to {target}")
    return target


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> dict:
    """Read settings from TOML, then apply overrides like {"world": {"seed": 7}}."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not path.exists() and BUNDLED_CONFIG_PATH.exists():
        path = BUNDLED_CONFIG_PATH
    with open(path, "rb") as f:
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
