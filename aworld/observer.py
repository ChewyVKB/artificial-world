"""The Observer: measures the world and writes down its history.

The observer only *reads* the world. Nothing in the simulation depends on
it. Names like "drought" or "population collapse" are labels the observer
applies after the fact; the world itself has no idea it is in a drought.
(Later, when people exist, the same rule applies to "village", "chief",
"language" and so on.)
"""
from __future__ import annotations

import numpy as np

from .world import World

# Plants and animals are population *fields*. To make numbers readable we
# translate field units into rough head counts. These are display scales only.
GRAZERS_PER_UNIT = 100
PREDATORS_PER_UNIT = 20
DROUGHT_THRESHOLD = -0.15     # rainfall at least 15% below normal
DROUGHT_AREA_PCT = 25.0       # ...across a quarter of all land


def measure(world: World, flows: dict) -> dict:
    s, st = world.static, world.state
    temp, _, _ = world.weather_today()
    land = st["plants"].size
    return {
        "vegetation_pct": 100.0 * float(st["plants"].sum() / max(s["capacity_c"].sum(), 1e-9)),
        "grazers": float(st["grazers"].sum()) * GRAZERS_PER_UNIT,
        "predators": float(st["predators"].sum()) * PREDATORS_PER_UNIT,
        "grazer_range_pct": 100.0 * float((st["grazers"] > 1e-3).sum()) / land,
        "predator_range_pct": 100.0 * float((st["predators"] > 1e-3).sum()) / land,
        "land_temp_c": float(temp.mean()),
        "snow_cover_pct": 100.0 * float((st["snow"] > 1.0).sum()) / land,
        "rain_vs_normal_pct": 100.0 * float(st["anomaly"].mean()),
        "drought_area_pct": 100.0 * float((st["anomaly"] < DROUGHT_THRESHOLD).sum()) / land,
        "food_eaten": flows.get("eaten", 0.0),
        "prey_caught": flows.get("caught", 0.0),
    }


class Observer:
    """Keeps a little memory (last year's numbers) so it can notice big changes.
    That memory is saved inside each checkpoint, so rewinding stays consistent."""

    def __init__(self, memory: dict | None = None):
        self.memory = memory or {}

    def after_step(self, world: World, flows: dict, metrics_every: int) -> tuple[dict, list[dict]]:
        """Called after every simulated day. Returns (metrics or {}, new events)."""
        events: list[dict] = []
        metrics = measure(world, flows) if world.tick % metrics_every == 0 else {}
        if world.day_of_year == 0:
            events += self._yearly(world, metrics or measure(world, flows))
        return metrics, events

    def opening_events(self, world: World) -> list[dict]:
        land_pct = 100.0 * float((~world.static["ocean"]).mean())
        return [{
            "tick": 0, "type": "WORLD_CREATED",
            "title": f"The world forms — {land_pct:.0f}% land, {int(world.static['river'].sum())} river cells",
            "data": {"seed": world.cfg["world"]["seed"]}, "major": True,
        }]

    def _yearly(self, world: World, m: dict) -> list[dict]:
        ev = []
        mem = self.memory
        t, y = world.tick, world.year

        def add(kind, title, major=False, **data):
            ev.append({"tick": t, "type": kind, "title": title, "data": data, "major": major})

        in_drought = m["drought_area_pct"] >= DROUGHT_AREA_PCT
        if in_drought and not mem.get("drought"):
            add("DROUGHT_BEGAN", f"Year {y}: drought grips {m['drought_area_pct']:.0f}% of the land", True,
                area_pct=round(m["drought_area_pct"], 1))
            mem["drought_start"] = y
        elif not in_drought and mem.get("drought"):
            length = y - mem.get("drought_start", y)
            add("DROUGHT_ENDED", f"Year {y}: the rains return after {length} year{'s' * (length != 1)}",
                years=length)
        mem["drought"] = in_drought

        for key, label in (("grazers", "Grazing herds"), ("predators", "Predators")):
            prev = mem.get(key)
            now = m[key]
            if prev and prev > 0:
                change = (now - prev) / prev
                if change <= -0.6:
                    add(f"{key.upper()}_COLLAPSE", f"Year {y}: {label.lower()} collapse ({change:+.0%})", True,
                        before=round(prev), after=round(now))
                elif change >= 2.0:
                    add(f"{key.upper()}_BOOM", f"Year {y}: {label.lower()} boom ({change:+.0%})",
                        before=round(prev), after=round(now))
            if prev and now == 0:
                add(f"{key.upper()}_EXTINCT", f"Year {y}: {label.lower()} have died out", True)
            mem[key] = now
        return ev
