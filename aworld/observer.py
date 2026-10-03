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

from . import knowledge as kn
from . import language as lg
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


def measure_knowledge(world: World) -> dict:
    p = world.state["people"]
    n = max(p["id"].size, 1)
    counts = kn.knowers(p)
    m = {"techniques_known": float((counts > 0).sum()),
         "techniques_per_person": float(sum(counts)) / n}
    for r, rec in enumerate(kn.RECIPES):
        m[f"know_{rec['key']}_pct"] = 100.0 * counts[r] / n
    return m


def group_labels(world: World) -> np.ndarray:
    """For each person, a label shared by everyone living within ~2 days' walk
    of each other (a chain of occupied cells, with one empty cell of slack)."""
    p = world.state["people"]
    if p["id"].size == 0:
        return np.zeros(0, dtype=np.int64)
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
    return label[p["pos"]]


def find_groups(world: World) -> list[tuple[int, int]]:
    """Clusters of people living within ~2 days' walk of each other.
    Returns [(size, a cell in the group)], largest first."""
    labels = group_labels(world)
    if labels.size == 0:
        return []
    labs, counts = np.unique(labels, return_counts=True)
    return sorted(((int(c), int(l)) for l, c in zip(labs, counts)), reverse=True)


def who(world: World, pid: int) -> str:
    """'Tika (#446)' if the person has a name, else '#446'."""
    from .people import index_of
    p = world.state.get("people")
    if p is not None and "name" in p:
        r = index_of(p["id"], np.array([pid]))[0]
        if r >= 0 and p["name"][r]:
            return f"{lg.name_str(int(p['name'][r]))} (#{pid})"
    return f"#{pid}"


CONFIRM_YEARS = 5            # censuses in a row before a new language is announced
GONE_YEARS = 5               # censuses without a trace before a language is declared dead
CANDIDATE_MIN_SPEAKERS = 25


class Observer:
    """Keeps a little memory (last year's numbers) so it can notice big changes.
    That memory is saved inside each checkpoint, so rewinding stays consistent."""

    def __init__(self, memory: dict | None = None):
        self.memory = memory or {}

    def after_step(self, world: World, flows: dict, metrics_every: int) -> tuple[dict, list[dict]]:
        """Called after every simulated day. Returns (metrics or {}, new events)."""
        events: list[dict] = []
        learning = world.has_people and kn.enabled(world.cfg)
        if world.has_people:
            events += self._count_people(world, flows.get("people", {}))
        talking = world.has_people and lg.enabled(world.cfg)
        if learning:
            events += self._discoveries(world, flows.get("people", {}).get("discoveries", []))
        if talking:
            events += self._words(world, flows.get("people", {}))
        metrics = {}
        if world.tick % metrics_every == 0:
            metrics = measure(world, flows)
            if world.has_people:
                metrics.update(measure_people(world))
            if learning:
                metrics.update(measure_knowledge(world))
            if talking:
                p = world.state["people"]
                metrics["words_per_person"] = float((p["lex"] > 0).sum(axis=1).mean()) if p["id"].size else 0.0
                metrics["languages"] = float(len(self.living_languages()))
        if world.day_of_year == 0:
            events += self._yearly(world, metrics or measure(world, flows))
            if world.has_people:
                yearly, ev = self._yearly_people(world)
                metrics.update(yearly)
                events += ev
            if learning:
                events += self._yearly_knowledge(world)
            if talking:
                events += self._yearly_language(world)
        return metrics, events

    # ── knowledge ──────────────────────────────────────────────
    def _discoveries(self, world: World, found: list) -> list[dict]:
        tech = self.memory.setdefault("tech", {})
        ev = []
        for pid, r, cell in found:
            rec = kn.RECIPES[r]
            t = tech.get(rec["key"])
            if t is None:
                tech[rec["key"]] = {"first_year": world.year, "first_by": pid, "first_cell": cell,
                                    "lost_year": None, "times_lost": 0}
                ev.append({"tick": world.tick, "type": "DISCOVERY", "major": True,
                           "title": f"Year {world.year}: {who(world, pid)} works out {rec['name'].lower()} — a first for this world",
                           "data": {"technique": rec["key"], "person": pid, "cell": cell}})
            elif t["lost_year"] is not None:
                gap = world.year - t["lost_year"]
                t["lost_year"] = None
                ev.append({"tick": world.tick, "type": "REDISCOVERY", "major": True,
                           "title": f"Year {world.year}: {who(world, pid)} rediscovers {rec['name'].lower()}, lost {gap} years ago",
                           "data": {"technique": rec["key"], "person": pid, "cell": cell, "years_lost": gap}})
        return ev

    def _yearly_knowledge(self, world: World) -> list[dict]:
        tech = self.memory.setdefault("tech", {})
        counts = kn.knowers(world.state["people"])
        ev = []
        for r, rec in enumerate(kn.RECIPES):
            t = tech.get(rec["key"])
            if t and t["lost_year"] is None and counts[r] == 0:
                t["lost_year"] = world.year
                t["times_lost"] += 1
                ev.append({"tick": world.tick, "type": "KNOWLEDGE_LOST", "major": True,
                           "title": f"Year {world.year}: {rec['name'].lower()} is lost — no one living knows it any more",
                           "data": {"technique": rec["key"]}})
        return ev

    # ── language ───────────────────────────────────────────────
    def living_languages(self) -> list[dict]:
        return [l for l in self.memory.get("languages", []) if l.get("status", "alive") == "alive"]

    def _words(self, world: World, today: dict) -> list[dict]:
        mem, ev = self.memory, []
        words = today.get("words", [])
        if words and not mem.get("first_word"):
            pid, m, code = words[0]
            mem["first_word"] = True
            ev.append({"tick": world.tick, "type": "FIRST_WORD", "major": True,
                       "title": f"Year {world.year}: #{pid} says the first word ever spoken — "
                                f"“{lg.word_str(code)}”, meaning {lg.MEANINGS[m][1]}",
                       "data": {"person": pid, "word": lg.word_str(code), "meaning": lg.MEANINGS[m][0]}})
        for b in today.get("births", []):
            if len(b) > 7 and b[7] and not mem.get("first_name"):
                mem["first_name"] = True
                ev.append({"tick": world.tick, "type": "FIRST_NAME", "major": True,
                           "title": f"Year {world.year}: a child is given a name for the first time — {b[7]}",
                           "data": {"person": b[0], "name": b[7]}})
        return ev

    def _yearly_language(self, world: World) -> list[dict]:
        """Yearly census of languages: match this year's to those already known,
        and notice new languages, splits and deaths.

        To avoid crying wolf over a few families on the fringe, a new language
        must show up in CONFIRM_YEARS censuses in a row before it's announced,
        and a language must go unheard for GONE_YEARS before it's declared dead."""
        mem, ev = self.memory, []
        reg = mem.setdefault("languages", [])
        p = world.state["people"]
        found = [f for f in lg.detect(p, lg.region_labels(world))]
        known = [l for l in reg if l.get("status", "alive") in ("alive", "candidate")]
        t, yr = world.tick, world.year

        def add(kind, title, **data):
            ev.append({"tick": t, "type": kind, "title": title, "data": data, "major": True})

        claimed: dict[int, list] = {}
        unclaimed = []
        if known and found:
            sim = lg.similarity(np.array([f["words"] for f in found]), np.array([l["words"] for l in known]))
            for i in range(len(found)):
                j = int(np.argmax(sim[i]))
                (claimed.setdefault(j, []) if sim[i, j] >= 0.4 else unclaimed).append(i if sim[i, j] >= 0.4 else (i, None))
        else:
            unclaimed = [(i, None) for i in range(len(found))]
        for j, idxs in claimed.items():
            # The biggest matching group carries the language on; others that matched it
            # but no longer understand that group may be splitting off.
            idxs.sort(key=lambda i: -found[i]["speakers"])
            keep = idxs[0]
            l = known[j]
            l.update(words=[int(x) for x in found[keep]["words"]], speakers=found[keep]["speakers"],
                     regions=found[keep]["regions"], census_year=yr, seen=l.get("seen", 0) + 1, missed=0)
            for i in idxs[1:]:
                unclaimed.append((i, l["id"] if l.get("status", "alive") == "alive" else l.get("parent")))
        for i, parent in unclaimed:
            f = found[i]
            if f["speakers"] < CANDIDATE_MIN_SPEAKERS:
                continue
            lid = mem.get("next_language_id", 1)
            mem["next_language_id"] = lid + 1
            reg.append({"id": lid, "name": None, "status": "candidate", "born_year": yr, "parent": parent,
                        "died_year": None, "words": [int(x) for x in f["words"]], "speakers": f["speakers"],
                        "regions": f["regions"], "census_year": yr, "seen": 1, "missed": 0})
        claimed_ids = {known[j]["id"] for j in claimed}
        for l in known:
            if l["id"] not in claimed_ids:
                l["missed"] = l.get("missed", 0) + 1
                l["seen"] = 0
        # Promote, retire, forget.
        names = {l["name"] for l in reg if l.get("name")}
        alive_before = any(l.get("status", "alive") == "alive" or l.get("died_year") for l in reg if l.get("name"))
        for l in list(reg):
            status = l.get("status", "alive")
            if status == "candidate" and l["seen"] >= CONFIRM_YEARS:
                l["status"] = "alive"
                l["name"] = self._language_name(l["words"], names)
                names.add(l["name"])
                parent = next((x for x in reg if x["id"] == l["parent"] and x.get("name")), None)
                if parent is not None:
                    add("LANGUAGE_SPLIT", f"Year {yr}: {l['name']} has drifted apart from {parent['name']} — "
                                          f"{l['speakers']} people now speak a language of their own",
                        language=l["name"], parent=parent["name"])
                elif not alive_before:
                    add("FIRST_LANGUAGE", f"Year {yr}: the first language takes shape — {l['speakers']} people "
                                          f"share {sum(1 for w in l['words'] if w)} words. They call themselves “{l['name']}”",
                        language=l["name"])
                    alive_before = True
                else:
                    add("LANGUAGE_EMERGED", f"Year {yr}: a new language, {l['name']}, takes shape among "
                                            f"{l['speakers']} people", language=l["name"])
            elif status == "candidate" and l["missed"] >= 2:
                reg.remove(l)
            elif status == "alive" and l.get("missed", 0) >= GONE_YEARS:
                l.update(status="dead", died_year=yr, regions=[], speakers=0)
                add("LANGUAGE_DIED", f"Year {yr}: {l['name']} is no longer spoken", language=l["name"])
        return ev

    @staticmethod
    def _language_name(words, taken: set) -> str:
        """A language is named by its own word for "us" — or, if that's missing or
        already the name of another language, by the next of its own words that is
        free (its word for water, plants, the river...). Related languages keep
        sharing some words, so this keeps their names distinct."""
        order = [lg.MI[k] for k in ("people", "water", "plant", "river", "herd", "eat", "child", "mother")]
        order += [m for m in range(lg.M) if m not in order]
        options = [lg.name_str(int(words[m])) for m in order if int(words[m])]
        for name in options:
            if name not in taken and len(name) >= 2:
                return name
        base = options[0] if options else "Unnamed"
        k = 2
        while f"{base} {k}" in taken:
            k += 1
        return f"{base} {k}"

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
