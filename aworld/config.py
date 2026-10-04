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
    elif target.exists() and BUNDLED_CONFIG_PATH.exists() and target.resolve() != BUNDLED_CONFIG_PATH.resolve():
        add_new_sections(target, BUNDLED_CONFIG_PATH)
    return target


def add_new_sections(target: Path, defaults: Path) -> list[str]:
    """When an update brings a new kind of physics (a new [section] in the defaults),
    add that section to the user's settings file so NEW worlds get it. Existing
    sections and values are never touched, and existing worlds keep their own settings."""
    with open(target, "rb") as f:
        have = tomllib.load(f)
    text = defaults.read_text()
    with open(defaults, "rb") as f:
        want = tomllib.load(f)
    missing = [k for k in want if k not in have]
    if not missing:
        return []
    # Cut the defaults file into sections (each keeps the comments written under its header).
    chunks, current = {}, None
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]") and not stripped.startswith("[["):
            current = stripped[1:-1].strip()
        if current:
            chunks.setdefault(current, []).append(line)
    with open(target, "a") as f:
        for k in missing:
            f.write("\n" + "".join(chunks.get(k, [])).rstrip() + "\n")
    print(f"[config] added new settings sections to {target}: {', '.join(missing)}")
    return missing


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
