"""The Observer: measures the world and writes down its history.

The observer only *reads* the world. Nothing in the simulation depends on
it. Names like "drought" or "population collapse" are labels the observer
applies after the fact; the world itself has no idea it is in a drought.
The same rule applies to people: a "group" is something the observer
detects (people living close together), not something the simulation
knows about. Later the same goes for "village", "chief", "language"...
"""
from __future__ import annotations

import numpy as np

from .ecology import BIOMES
from .people import CAUSES, G, GENES
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


POP_MILESTONES = (100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000)
GROUP_MILESTONES = (2, 3, 5, 10, 20, 50, 100)
AGE_MILESTONES = (50, 60, 70, 80, 90)


def measure_people(world: World) -> dict:
    p = world.state["people"]
    n = p["id"].size
    m = {"population": float(n)}
    if n:
        age = (world.tick - p["birth"]) / world.dpy
        m["median_age"] = float(np.median(age))
        m["occupied_land_pct"] = 100.0 * np.unique(p["pos"]).size / world.static["cells"].size
        mean = p["genes"].mean(axis=0)
        for name in GENES:
            m[f"trait_{name}"] = float(mean[G[name]])
    return m


def find_groups(world: World) -> list[tuple[int, int]]:
    """Clusters of people living within ~2 days' walk of each other.
    Returns [(size, a cell in the group)], largest first."""
    p = world.state["people"]
    if p["id"].size == 0:
        return []
    nbr8 = world.static["neighbours8"]
    occupied = np.unique(p["pos"])
    area = np.unique(np.concatenate([occupied, nbr8[:, occupied].ravel()]))   # occupied + 1-cell margin
    inside = np.zeros(world.static["cells"].size, dtype=bool)
    inside[area] = True
    label = np.full(inside.size, np.iinfo(np.int64).max, dtype=np.int64)
    label[area] = area
    for _ in range(4096):                                  # spread the smallest label through each cluster
        nl = label[area].copy()
        for k in range(8):
            j = nbr8[k, area]
            nl = np.minimum(nl, np.where(inside[j], label[j], nl))
        if np.array_equal(nl, label[area]):
            break
        label[area] = nl
    counts = {}
    for lab, c in zip(*np.unique(label[p["pos"]], return_counts=True)):
        counts[int(lab)] = int(c)
    return sorted(((c, lab) for lab, c in counts.items()), reverse=True)


class Observer:
    """Keeps a little memory (last year's numbers) so it can notice big changes.
    That memory is saved inside each checkpoint, so rewinding stays consistent."""

    def __init__(self, memory: dict | None = None):
        self.memory = memory or {}

    def after_step(self, world: World, flows: dict, metrics_every: int) -> tuple[dict, list[dict]]:
        """Called after every simulated day. Returns (metrics or {}, new events)."""
        events: list[dict] = []
        if world.has_people:
            events += self._count_people(world, flows.get("people", {}))
        metrics = {}
        if world.tick % metrics_every == 0:
            metrics = measure(world, flows)
            if world.has_people:
                metrics.update(measure_people(world))
        if world.day_of_year == 0:
            events += self._yearly(world, metrics or measure(world, flows))
            if world.has_people:
                yearly, ev = self._yearly_people(world)
                metrics.update(yearly)
                events += ev
        return metrics, events

    # ── people ─────────────────────────────────────────────────
    def _count_people(self, world: World, today: dict) -> list[dict]:
        mem = self.memory
        y = mem.setdefault("year_counts", {"births": 0, "deaths": [0] * len(CAUSES), "infant_deaths": 0})
        births, deaths = today.get("births", []), today.get("deaths", [])
        y["births"] += len(births)
        for _, cause, age, _ in deaths:
            y["deaths"][cause] += 1
            y["infant_deaths"] += age < 5
        ev = []
        if births and not mem.get("first_birth"):
            mem["first_birth"] = True
            ev.append({"tick": world.tick, "type": "FIRST_BIRTH", "title": f"Year {world.year}: the first child of this world is born",
                       "data": {"id": births[0][0]}, "major": True})
        return ev

    def _yearly_people(self, world: World) -> tuple[dict, list[dict]]:
        mem = self.memory
        p = world.state["people"]
        n = int(p["id"].size)
        t, yr = world.tick, world.year
        ev = []

        def add(kind, title, major=False, **data):
            ev.append({"tick": t, "type": kind, "title": title, "data": data, "major": major})

        counts = mem.get("year_counts", {"births": 0, "deaths": [0] * len(CAUSES), "infant_deaths": 0})
        deaths = sum(counts["deaths"])
        metrics = {"births_per_year": float(counts["births"]), "deaths_per_year": float(deaths),
                   "child_deaths_pct": 100.0 * counts["infant_deaths"] / max(counts["births"], 1)}
        for k, name in enumerate(CAUSES):
            metrics[f"deaths_{name.split()[0].lower()}"] = float(counts["deaths"][k])

        groups = find_groups(world)
        real = [g for g in groups if g[0] >= 5]
        metrics["groups"] = float(len(real))
        metrics["largest_group"] = float(groups[0][0]) if groups else 0.0

        start = mem.get("pop_at_year_start", n)
        if counts["deaths"][1] >= 5 and counts["deaths"][1] >= 0.05 * max(start, 1):
            add("FAMINE", f"Year {yr}: famine — {counts['deaths'][1]} people starve", True,
                starved=counts["deaths"][1], population=n)
        for ms in POP_MILESTONES:
            if n >= ms and ms not in mem.setdefault("pop_milestones", []):
                mem["pop_milestones"].append(ms)
                add("POPULATION_MILESTONE", f"Year {yr}: the people number {ms:,}", ms >= 1000, population=n)
        for ms in GROUP_MILESTONES:
            if len(real) >= ms and ms not in mem.setdefault("group_milestones", []):
                mem["group_milestones"].append(ms)
                add("GROUPS", f"Year {yr}: people now live in {len(real)} separate groups", ms >= 2 and ms <= 3,
                    groups=len(real))
        if n:
            biomes = np.unique(world.static["biome"].ravel()[world.static["cells"][p["pos"]]])
            seen = mem.setdefault("biomes_lived", [])
            for b in biomes.tolist():
                if b not in seen:
                    seen.append(b)
                    if len(seen) > 1:
                        add("NEW_LAND", f"Year {yr}: people settle in {BIOMES[b].lower()} for the first time", True,
                            biome=BIOMES[b])
            oldest = float(((t - p["birth"]) / world.dpy).max())
            for ms in AGE_MILESTONES:
                if oldest >= ms and ms not in mem.setdefault("age_milestones", []):
                    mem["age_milestones"].append(ms)
                    add("OLD_AGE", f"Year {yr}: someone lives to {ms} for the first time", age=round(oldest, 1))
        if n == 0 and not mem.get("extinct"):
            mem["extinct"] = True
            add("PEOPLE_EXTINCT", f"Year {yr}: the last person has died. The people are gone.", True)
        mem["pop_at_year_start"] = n
        mem["year_counts"] = {"births": 0, "deaths": [0] * len(CAUSES), "infant_deaths": 0}
        return metrics, ev

    def opening_events(self, world: World) -> list[dict]:
        land_pct = 100.0 * float((~world.static["ocean"]).mean())
        ev = [{
            "tick": 0, "type": "WORLD_CREATED",
            "title": f"The world forms — {land_pct:.0f}% land, {int(world.static['river'].sum())} river cells",
            "data": {"seed": world.cfg["world"]["seed"]}, "major": True,
        }]
        if world.has_people:
            p = world.state["people"]
            cell = int(p["pos"][0]) if p["id"].size else 0
            biome = BIOMES[int(world.static["biome"].ravel()[world.static["cells"][cell]])]
            ev.append({"tick": 0, "type": "PEOPLE_APPEAR",
                       "title": f"{p['id'].size} people appear beside fresh water, in {biome.lower()}",
                       "data": {"cell": cell}, "major": True})
            self.memory["biomes_lived"] = [BIOMES.index(biome)]
            self.memory["pop_at_year_start"] = int(p["id"].size)
        return ev

    def _yearly(self, world: World, m: dict) -> list[dict]:
        ev = []
        mem = self.memory
        t, y = world.tick, world.year

        def add(kind, title, major=False, **data):
            ev.append({"tick": t, "type": kind, "title": title, "data": data, "major": major})

        in_drought = m["drought_area_pct"] >= DROUGHT_AREA_PCT
        if in_drought and not mem.get("drought"):
            add("DROUGHT_BEGAN", f"Year {y}: drought grips {m['drought_area_pct']:.0f}% of the land", not world.has_people,
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
                    add(f"{key.upper()}_COLLAPSE", f"Year {y}: {label.lower()} collapse ({change:+.0%})", False,
                        before=round(prev), after=round(now))
                elif change >= 2.0:
                    add(f"{key.upper()}_BOOM", f"Year {y}: {label.lower()} boom ({change:+.0%})",
                        before=round(prev), after=round(now))
            if prev and now == 0:
                add(f"{key.upper()}_EXTINCT", f"Year {y}: {label.lower()} have died out", True)
            mem[key] = now
        return ev
