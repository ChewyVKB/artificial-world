"""Knowledge: what people can discover, practise, teach — and forget.

The rule we follow: hard-code the *chemistry*, not the tech tree.

The world contains materials (flint, wood, clay, fibre, hides). This file
lists what those materials can physically be turned into, and what the
results physically do (a sharp edge cuts, fire warms and cooks, a pot holds
water). That's the "physics" of this universe.

Nobody in the world knows any of it. People find these things by
experimenting with whatever is around them: most combinations do nothing.
Once someone knows a technique they get better with practice, and they can
pass it on to people who spend time with them — children learn fastest.
When the last person who knows a technique dies, it's gone, until someone
rediscovers it. Groups that live apart can end up knowing different things.

Names like "Hafted spear" are labels for us, the observers. The people
themselves have no words yet.
"""
from __future__ import annotations

import numpy as np

from . import noise
from .rng import stream

# ── materials found in the land ───────────────────────────────────────
MATERIALS = ("stone", "wood", "clay", "fibre", "hide")

# ── what this universe physically allows ──────────────────────────────
# needs: materials that must be present where the person is, items they must
#        carry ("flake", "cord"), or "fire" (a fire burning in their household today).
# lasts: average days an item survives before breaking or wearing out.
RECIPES = (
    {"key": "flake", "name": "Flaked stone edge", "needs": ("stone",), "lasts": 40,
     "does": "a sharp edge: cuts plants and meat (gathering +15%, hunting +15%)"},
    {"key": "fire", "name": "Fire-making", "needs": ("wood",), "lasts": 0,
     "does": "warmth (cold felt ~7 °C less), cooking (+15% food), keeps predators away"},
    {"key": "cord", "name": "Twisted cord", "needs": ("fibre",), "lasts": 60,
     "does": "binds things together"},
    {"key": "digging_stick", "name": "Digging stick", "needs": ("wood", "flake"), "lasts": 120,
     "does": "reaches roots and tubers (gathering +25%)"},
    {"key": "spear", "name": "Hafted spear", "needs": ("wood", "flake", "cord"), "lasts": 90,
     "does": "reach and a point (hunting +60%, safer from predators)"},
    {"key": "basket", "name": "Woven basket", "needs": ("fibre", "cord"), "lasts": 120,
     "does": "carries more (gathering +20%)"},
    {"key": "clothing", "name": "Sewn hide clothing", "needs": ("hide", "flake", "cord"), "lasts": 300,
     "does": "insulation (cold felt ~6 °C less)"},
    {"key": "pot", "name": "Fired clay pot", "needs": ("clay", "fire"), "lasts": 200,
     "does": "carries water (thirst builds half as fast)"},
    {"key": "shelter", "name": "Hide shelter", "needs": ("wood", "hide", "cord"), "lasts": 360,
     "does": "shelter from weather (cold felt ~3 °C less, fewer deaths in harsh seasons)"},
    {"key": "snare", "name": "Snare trap", "needs": ("cord", "wood"), "lasts": 60,
     "does": "catches small game without chasing it (extra food)"},
)
R = len(RECIPES)
K = {r["key"]: i for i, r in enumerate(RECIPES)}
DUD_COMBINATIONS = 60     # experiments that lead nowhere, for every one that works
FORGET_BELOW = 0.02       # a technique not practised until skill falls below this is forgotten
ITEM_RECIPES = [i for i, r in enumerate(RECIPES) if r["lasts"] > 0]


def bit(key: str) -> int:
    return 1 << K[key]


def enabled(cfg: dict) -> bool:
    return "knowledge" in cfg


# ── materials map ──────────────────────────────────────────────────────
def material_fields(static: dict, seed: int) -> dict:
    """Where flint, clay and wood occur (0..1 per land cell). Fibre and hides
    are alive and come from the plants and herds of the day."""
    hab = static["habitable"]
    H, W = hab.shape
    cells = static["cells"]
    elev = np.maximum(static["elevation"], 0)
    # Flint: patches in uplands and where rivers cut into rock.
    patches = noise.fbm(stream(seed, "materials.flint"), H, W, 10.0, octaves=3)
    upland = np.clip((elev - 150.0) / 900.0, 0, 1)
    stone = np.clip(patches * 1.6 - 0.25, 0, 1) * np.maximum(upland, 0.6 * static["river"])
    # Clay: settles in lowland river valleys and lake shores.
    wet = static["river"] | static["lake"]
    near = noise.blur(wet.astype(float), passes=2) > 0.05
    clay = (near & (elev < 900)) * np.clip(noise.fbm(stream(seed, "materials.clay"), H, W, 12.0, octaves=2) + 0.6, 0, 1)
    # Wood: trees grow where the biome supports them.
    from .ecology import BIOMES
    tree_share = np.zeros(len(BIOMES))
    for name, share in (("Boreal forest", 0.9), ("Temperate forest", 1.0), ("Tropical forest", 1.0),
                        ("Savanna", 0.45), ("Grassland", 0.25), ("Tundra", 0.05), ("Mountain", 0.15)):
        tree_share[BIOMES.index(name)] = share
    wood = tree_share[static["biome"]] * np.clip(static["plant_capacity"] * 1.2, 0, 1)
    return {"stone_c": stone.ravel()[cells], "clay_c": clay.astype(float).ravel()[cells],
            "wood_c": wood.ravel()[cells]}


def available(world, rows: np.ndarray, fire: np.ndarray) -> np.ndarray:
    """Which recipe needs are met for each person right now: bool (len(rows), R)."""
    s, st, p = world.static, world.state, world.state["people"]
    pos = p["pos"][rows]
    have = {
        "stone": s["stone_c"][pos] > 0.2,
        "wood": s["wood_c"][pos] > 0.2,
        "clay": s["clay_c"][pos] > 0.2,
        "fibre": st["plants"][pos] > 0.3,
        "hide": st["grazers"][pos] > 0.02,
        "fire": fire[rows],
        "flake": (p["items"][rows] & bit("flake")) > 0,
        "cord": (p["items"][rows] & bit("cord")) > 0,
    }
    out = np.ones((rows.size, R), dtype=bool)
    for r, rec in enumerate(RECIPES):
        for need in rec["needs"]:
            out[:, r] &= have[need]
    return out


def knows(p: dict, key: str) -> np.ndarray:
    return (p["known"] & bit(key)) > 0


def has(p: dict, key: str) -> np.ndarray:
    return (p["items"] & bit(key)) > 0


# ── effects on daily life ──────────────────────────────────────────────
def effects(world, head: np.ndarray) -> dict:
    """What people's knowledge and belongings do for them today."""
    p, s = world.state["people"], world.static
    n = p["id"].size
    pos = p["pos"]
    # A household has fire today if anyone in it can make fire and there's wood to burn.
    can = knows(p, "fire") & (s["wood_c"][pos] > 0.2)
    fire = np.bincount(head, can.astype(float), minlength=n)[head] > 0
    flake, dig, basket = has(p, "flake"), has(p, "digging_stick"), has(p, "basket")
    spear, cloth, shelter = has(p, "spear"), has(p, "clothing"), has(p, "shelter")
    pot, snare = has(p, "pot"), has(p, "snare")
    return {
        "fire": fire,
        "gather": 1 + 0.15 * flake + 0.25 * dig + 0.20 * basket,
        "hunt": 1 + 0.15 * flake + 0.60 * spear,
        "food": 1 + 0.15 * fire,
        "cold_shift": 7.0 * fire + 6.0 * cloth + 3.0 * shelter,
        "predators": (1 - 0.3 * fire) * (1 - 0.3 * spear),
        "thirst": np.where(pot, 0.5, 1.0),
        "extra_food": 0.4 * snare,
        "weather": np.where(shelter, 0.85, 1.0),
    }


# ── discovering, learning, making ──────────────────────────────────────
def daily(world, age_y: np.ndarray, fire: np.ndarray, rng: np.random.Generator) -> list:
    """Experiments, teaching, making things and wearing them out.
    Returns discoveries: [(person id, recipe index, cell)]."""
    p, kc = world.state["people"], world.cfg["knowledge"]
    n = p["id"].size
    if n == 0:
        return []
    from .people import G
    adult = age_y >= 12
    discoveries = []

    # 1. Experiment: fiddle with what's around; most combinations do nothing.
    curious = p["genes"][:, G["curiosity"]]
    tries = np.flatnonzero(adult & (rng.random(n) < kc["experiment_rate"] * (0.2 + curious)))
    if tries.size:
        pick = rng.integers(0, R + DUD_COMBINATIONS, tries.size)
        real = pick < R
        tries, pick = tries[real], pick[real]
        if tries.size:
            ok = available(world, tries, fire)[np.arange(tries.size), pick]
            # Combining more things at once is harder to get right by chance.
            parts = np.array([len(RECIPES[r]["needs"]) for r in range(R)])[pick]
            ok &= rng.random(pick.size) < 0.5 ** (parts - 1)
            new = ok & ((p["known"][tries] >> pick.astype(np.uint32)) & 1 == 0)
            for i, r in zip(tries[new], pick[new]):
                p["known"][i] |= np.uint32(1 << int(r))
                p["skill"][i, r] = max(p["skill"][i, r], 0.15)
                discoveries.append((int(p["id"][i]), int(r), int(p["pos"][i])))

    # 2. Learn from someone nearby (same place). Children learn fastest.
    order = np.argsort(p["pos"], kind="stable")
    cells_sorted = p["pos"][order]
    start = np.searchsorted(cells_sorted, cells_sorted, side="left")
    size = np.searchsorted(cells_sorted, cells_sorted, side="right") - start
    social = p["genes"][order, G["sociability"]]
    young = age_y[order] < 15
    wants = (size > 1) & (age_y[order] >= 3) & (rng.random(n) < kc["learn_rate"] * (0.3 + social) * np.where(young, 2.0, 1.0))
    L = np.flatnonzero(wants)
    if L.size:
        offs = rng.integers(0, size[L] - 1)
        teacher_sorted = start[L] + offs
        teacher_sorted = np.where(teacher_sorted >= L, teacher_sorted + 1, teacher_sorted)   # not yourself
        learner, teacher = order[L], order[teacher_sorted]
        gap = p["known"][teacher] & ~p["known"][learner]
        bits = ((gap[:, None] >> np.arange(R, dtype=np.uint32)[None, :]) & 1).astype(bool)
        r = np.argmax(rng.random((L.size, R)) * bits, axis=1)            # one thing they don't know yet
        t_skill = p["skill"][teacher, r]
        ease = t_skill                                                  # a skilled teacher is easier to copy
        if "language" in world.cfg and "lex" in p:                      # …and one you can talk to, far easier
            from .language import shared_fraction
            ease = np.minimum(1.0, t_skill * (1 + 2.0 * shared_fraction(p, learner, teacher)))
        learns = bits.any(axis=1) & (rng.random(L.size) < ease)
        lr, rr = learner[learns], r[learns]
        p["known"][lr] |= (np.uint32(1) << rr.astype(np.uint32))
        p["skill"][lr, rr] = np.maximum(p["skill"][lr, rr], 0.3 * t_skill[learns])

    # 3. Make things you know how to make (if the materials are here), and wear things out.
    makers = np.flatnonzero(age_y >= 10)
    if makers.size:
        can = available(world, makers, fire)
        for r in ITEM_RECIPES:
            b = np.uint32(1 << r)
            knows_r = (p["known"][makers] & b) > 0
            lacks = (p["items"][makers] & b) == 0
            chance = 0.05 + 0.25 * p["skill"][makers, r]
            make = knows_r & lacks & can[:, r] & (rng.random(makers.size) < chance)
            rows = makers[make]
            p["items"][rows] |= b
            p["skill"][rows, r] += 0.02 * (1 - p["skill"][rows, r])           # practice makes perfect
    for r in ITEM_RECIPES:
        b = np.uint32(1 << r)
        breaks = ((p["items"] & b) > 0) & (rng.random(n) < 1.0 / RECIPES[r]["lasts"])
        p["items"][breaks] &= ~b
    # Fire is practised whenever it's lit.
    lit = fire & knows(p, "fire")
    p["skill"][lit, K["fire"]] += 0.003 * (1 - p["skill"][lit, K["fire"]])
    # Unused skills fade; a technique nobody practises is eventually forgotten.
    p["skill"] *= 0.9997
    forgot = (p["skill"] < FORGET_BELOW) & ((p["known"][:, None] >> np.arange(R, dtype=np.uint32)[None, :]) & 1).astype(bool)
    if forgot.any():
        mask = (forgot * (1 << np.arange(R))).sum(axis=1).astype(np.uint32)
        p["known"] &= ~mask
    return discoveries


def knowers(p: dict) -> np.ndarray:
    """How many living people know each recipe."""
    return np.array([int(((p["known"] >> np.uint32(r)) & 1).sum()) for r in range(R)])
