"""People: individual early humans.

They begin with nothing but their bodies. No language, tools, fire,
farming, leaders or settlements. What they *can* do:

* sense the land around them (food, water, warmth, other people)
* walk one cell (~4 km) a day
* gather plants and hunt grazing animals, which depletes both
* drink where there is fresh water (rivers, lakes, rain)
* pair up, have children, care for their children, grow old and die
* pass their traits on to their children, with small mutations

Families stay together because children depend on their mother, and a
partner shares food with his partner. That's biology, not a social
system. Anything bigger — bands, territories, migrations — has to emerge.

Everything is vectorised (one NumPy array per attribute, one row per
living person), so thousands of people cost only milliseconds a day.
"""
from __future__ import annotations

import numpy as np

from . import knowledge, language

# ── heritable traits ──────────────────────────────────────────────────
# Each has a real trade-off, so evolution has something to work with.
GENES = (
    "size",         # bigger bodies hunt better and handle cold, but need more food
    "insulation",   # tolerate cold; suffer more in heat
    "fertility",    # conceive more easily, but age faster
    "longevity",    # age slower, but bodies cost more to maintain
    "wanderlust",   # how restless — willing to move somewhere unknown
    "sociability",  # how strongly drawn toward other people
    "curiosity",    # tinkers and experiments more — but spends less time foraging
    "speech",       # talks more and copies words more faithfully — but a bigger brain needs more food
)
G = {name: i for i, name in enumerate(GENES)}
GENE_RANGE = np.array([[0.6, 1.4], [0, 1], [0, 1], [0, 1], [0, 1], [0, 1], [0, 1], [0, 1]])
START_GENES = np.array([1.0, 0.2, 0.5, 0.5, 0.3, 0.5, 0.5, 0.3])

FEMALE, MALE = 0, 1
CAUSES = ("old age & illness", "starvation", "thirst", "predators")

ARRAYS = {   # name -> dtype; one entry per living person
    "id": np.int64, "sex": np.int8, "birth": np.int64, "pos": np.int64,
    "energy": np.float64, "hydration": np.float64, "health": np.float64,
    "mother": np.int64, "father": np.int64, "partner": np.int64, "gen": np.int32,
    "pregnant_until": np.int64, "pregnant_by": np.int64, "last_birth": np.int64,
    "target": np.int64,     # where this household is heading (a cell), or -1
    "known": np.uint32,     # techniques this person knows (one bit each, see knowledge.py)
    "items": np.uint32,     # things this person is carrying (one bit each)
    "name": np.int64,       # a word their mother named them with (0 = no name)
}
DEFAULTS = {"known": 0, "items": 0, "name": 0}    # value for fields missing from older saves (else -1)
# Per-person tables: name -> (columns, dtype)
MATRICES = {
    "skill": (knowledge.R, np.float32),     # how good they are at each technique
    "lex": (language.M, np.int32),          # their word for each meaning (0 = none)
    "lexs": (language.M, np.float32),       # how sure they are of that word
}


def empty() -> dict:
    p = {k: np.zeros(0, dtype=t) for k, t in ARRAYS.items()}
    p["genes"] = np.zeros((0, len(GENES)))
    for k, (cols, t) in MATRICES.items():
        p[k] = np.zeros((0, cols), dtype=t)
    p["next_id"] = 1
    return p


def save_arrays(p: dict) -> dict:
    """Flatten people into named arrays for a checkpoint file."""
    out = {f"people.{k}": p[k] for k in ARRAYS}
    out["people.genes"] = p["genes"]
    for k in MATRICES:
        out[f"people.{k}"] = p[k]
    out["people.next_id"] = np.int64(p["next_id"])
    return out


def load_arrays(z) -> dict | None:
    if "people.id" not in z:
        return None
    n = z["people.id"].size
    p = {k: (z[f"people.{k}"].astype(t) if f"people.{k}" in z else np.full(n, DEFAULTS.get(k, -1), dtype=t))
         for k, t in ARRAYS.items()}                    # fields added later get a default
    genes = z["people.genes"].astype(float)
    if genes.shape[1] < len(GENES):                     # traits added later start at the founders' value
        pad = np.repeat(START_GENES[None, genes.shape[1]:], n, axis=0)
        genes = np.concatenate([genes, pad], axis=1)
    p["genes"] = genes
    for k, (cols, t) in MATRICES.items():
        p[k] = z[f"people.{k}"].astype(t) if f"people.{k}" in z else np.zeros((n, cols), dtype=t)
    p["next_id"] = int(z["people.next_id"])
    return p


def fingerprint_arrays(p: dict):
    for k in ARRAYS:
        yield np.ascontiguousarray(p[k]).tobytes()
    yield np.ascontiguousarray(p["genes"]).tobytes()
    for k in MATRICES:
        yield np.ascontiguousarray(p[k]).tobytes()
    yield str(p["next_id"]).encode()


# ── the first people ──────────────────────────────────────────────────
def choose_cradle(static: dict, rng: np.random.Generator) -> int:
    """A good place to begin: mild, green, with fresh water. Returns a compact cell."""
    t = static["annual_temp_c"]
    mild = np.clip(1 - np.abs(t - 19.0) / 7.0, 0, 1)
    score = static["capacity_c"] * mild * static["water_c"]
    best = np.argsort(-score, kind="stable")[:25]
    return int(best[rng.integers(len(best))])


def founders(cfg: dict, static: dict, rng: np.random.Generator, tick: int) -> tuple[dict, int]:
    pc = cfg["people"]
    n = int(pc["start_population"])
    dpy = cfg["world"]["days_per_year"]
    cradle = choose_cradle(static, rng)
    p = empty()
    n_adult = max(2, int(round(n * 0.6)))
    ages = np.concatenate([rng.uniform(17, 38, n_adult), rng.uniform(0, 14, n - n_adult)])
    sex = np.concatenate([np.arange(n_adult) % 2, rng.integers(0, 2, n - n_adult)]).astype(np.int8)
    ids = np.arange(1, n + 1, dtype=np.int64)
    mothers = np.full(n, -1, dtype=np.int64)
    women = ids[:n_adult][sex[:n_adult] == FEMALE]
    mothers[n_adult:] = rng.choice(women, n - n_adult)            # each child belongs to a woman
    genes = START_GENES + rng.normal(0, 0.03, (n, len(GENES)))
    p.update({
        "id": ids, "sex": sex, "birth": (tick - ages * dpy).astype(np.int64),
        "pos": np.full(n, cradle, dtype=np.int64),
        "energy": np.full(n, 0.7), "hydration": np.ones(n), "health": np.ones(n),
        "mother": mothers, "father": np.full(n, -1, dtype=np.int64),
        "partner": np.full(n, -1, dtype=np.int64), "gen": np.zeros(n, dtype=np.int32),
        "pregnant_until": np.full(n, -1, dtype=np.int64), "pregnant_by": np.full(n, -1, dtype=np.int64),
        "last_birth": np.full(n, -10 ** 9, dtype=np.int64), "target": np.full(n, -1, dtype=np.int64),
        "known": np.zeros(n, dtype=np.uint32), "items": np.zeros(n, dtype=np.uint32),
        "name": np.zeros(n, dtype=np.int64),
        "genes": np.clip(genes, GENE_RANGE[:, 0], GENE_RANGE[:, 1]),
        "next_id": n + 1,
    })
    for k, (cols, t) in MATRICES.items():
        p[k] = np.zeros((n, cols), dtype=t)
    return p, cradle


# ── helpers ──────────────────────────────────────────────────────────
def index_of(ids: np.ndarray, wanted: np.ndarray) -> np.ndarray:
    """Row of each wanted id among the living, or -1. (ids are always sorted.)"""
    if ids.size == 0:
        return np.full(wanted.shape, -1, dtype=np.int64)
    pos = np.clip(np.searchsorted(ids, wanted), 0, ids.size - 1)
    return np.where((wanted >= 0) & (ids[pos] == wanted), pos, -1)


def households(p: dict, age_y: np.ndarray) -> np.ndarray:
    """Row of the person each individual travels and eats with.
    Women lead their household; a partnered man joins his partner;
    children (<15) stay with their mother, or their father if she has died."""
    n = p["id"].size
    rows = np.arange(n)
    partner = index_of(p["id"], p["partner"])
    head = np.where((p["sex"] == MALE) & (partner >= 0), partner, rows)
    child = age_y < 15
    mother = index_of(p["id"], p["mother"])
    father = index_of(p["id"], p["father"])
    guardian = np.where(mother >= 0, mother, father)
    ok = child & (guardian >= 0)
    head = np.where(ok, head[np.where(guardian >= 0, guardian, 0)], head)
    # A guardian who is also a child (rare) — fall back to self.
    head = np.where(child & (age_y[head] < 15) & (head != rows), rows, head)
    return head


# ── one day of human life ────────────────────────────────────────────
def step(world, temp_c: np.ndarray, rain_mm: np.ndarray, rng: np.random.Generator) -> dict:
    """Advance every person by one day. Returns births and deaths for the record."""
    p = world.state["people"]
    out = {"births": [], "deaths": [], "discoveries": [], "words": []}
    n = p["id"].size
    if n == 0:
        return out
    cfg = world.cfg["people"]
    s, st = world.static, world.state
    tick, dpy = world.tick, world.dpy
    nbr8 = s["neighbours8"]
    ncell = s["cells"].size
    genes = p["genes"]
    age_y = (tick - p["birth"]) / dpy

    # What the land offers today, per cell.
    P, Gz, Z = st["plants"], st["grazers"], st["predators"]
    plant_supply = cfg["plant_food"] * P
    hunt_supply = cfg["hunt_food"] * Gz / (Gz + 0.03)
    supply = plant_supply + hunt_supply
    crowd = np.bincount(p["pos"], minlength=ncell).astype(float)

    # ── 1. move ─────────────────────────────────────────────────
    head = households(p, age_y)
    hr = np.flatnonzero(head == np.arange(n))                 # household heads decide for everyone
    group = np.bincount(head, minlength=n)[hr].astype(float)
    _move(p, hr, group, supply, crowd, temp_c, world, rng)
    p["pos"] = p["pos"][head]                                 # households move together

    # ── 2. gather, hunt, share ──────────────────────────────────
    pos = p["pos"]
    size = genes[:, G["size"]]
    learning = knowledge.enabled(world.cfg)
    fx = knowledge.effects(world, head) if learning else None
    capacity = np.where(age_y >= 15, cfg["adult_harvest"], np.where(age_y >= 6, 0.35 * cfg["adult_harvest"], 0.0))
    hunt_skill = capacity * size
    if learning:
        tinkering = 1 - 0.1 * genes[:, G["curiosity"]]      # time spent experimenting isn't spent foraging
        capacity = capacity * tinkering * fx["gather"]
        hunt_skill = hunt_skill * tinkering * fx["hunt"]
    want_p = np.bincount(pos, capacity, minlength=ncell)
    want_h = np.bincount(pos, hunt_skill, minlength=ncell)
    frac_p = np.minimum(1.0, plant_supply / np.maximum(want_p, 1e-9))
    frac_h = np.minimum(1.0, hunt_supply / np.maximum(want_h, 1e-9))
    # Each person splits effort between gathering and hunting in proportion to what's available.
    w_p = plant_supply[pos] / np.maximum(supply[pos], 1e-9)
    got = capacity * w_p * frac_p[pos] + hunt_skill * (1 - w_p) * frac_h[pos]
    if learning:
        got = (got + fx["extra_food"] * s["capacity_c"][pos]) * fx["food"]
    took_p = np.bincount(pos, capacity * w_p * frac_p[pos], minlength=ncell)
    took_h = np.bincount(pos, hunt_skill * (1 - w_p) * frac_h[pos], minlength=ncell)
    P -= np.minimum(took_p * cfg["plant_cost"], P)
    Gz -= np.minimum(took_h * cfg["hunt_cost"], Gz)

    shift = fx["cold_shift"] if learning else 0.0
    cold = np.clip(12.0 - 16.0 * genes[:, G["insulation"]] - shift - temp_c[pos], 0, None) / 10.0
    cold *= np.clip(1.3 - 0.5 * size, 0.4, 1.2)               # big bodies keep warm better
    heat = np.clip(temp_c[pos] - (32.0 - 8.0 * genes[:, G["insulation"]]), 0, None) / 8.0
    pregnant = p["pregnant_until"] > tick
    nursing = (tick - p["last_birth"]) < 2 * dpy
    need = np.where(age_y < 6, 0.4, np.where(age_y < 15, 0.7, 1.0)) * size ** 0.75
    need *= (1 + 0.15 * genes[:, G["longevity"]]) * (1 + cold)
    need += 0.2 * pregnant + 0.15 * nursing
    talking = language.enabled(world.cfg)
    if talking:
        need *= 1 + 0.1 * genes[:, G["speech"]]               # a talking brain is expensive

    pool = np.bincount(head, got, minlength=n)
    pool_need = np.bincount(head, need, minlength=n)
    food_i = pool[head] * need / np.maximum(pool_need[head], 1e-9)

    # ── 3. body ─────────────────────────────────────────────────
    gap = food_i - need
    p["energy"] = np.clip(p["energy"] + gap / 25.0, 0.0, 1.0)
    starving = (p["energy"] <= 0) & (gap < 0)
    water = s["water_c"][pos] | (rain_mm[pos] > 2.5)
    thirst_rate = fx["thirst"] if learning else 1.0
    p["hydration"] = np.where(water, 1.0, np.clip(p["hydration"] - (0.25 + 0.1 * heat) * thirst_rate, 0, 1))
    thirsty = p["hydration"] <= 0
    p["health"] = np.clip(
        p["health"]
        - starving * 0.04 * (-gap / np.maximum(need, 1e-9))
        - thirsty * 0.12
        - heat * 0.01
        + ((p["energy"] > 0.2) & (p["hydration"] > 0.3)) * 0.01, 0, 1)

    # ── 4. discover, learn, make things ──────────────────────────
    if learning:
        out["discoveries"] = knowledge.daily(world, age_y, fx["fire"], rng)
    if talking:
        out["words"] = language.daily(world, age_y, temp_c, rain_mm, rng)

    # ── 5. pair up ─────────────────────────────────────────────
    _pair(p, age_y, rng)

    # ── 5. conceive and give birth ───────────────────────────────
    partner = index_of(p["id"], p["partner"])
    fertile = ((p["sex"] == FEMALE) & (age_y >= 16) & (age_y <= 45) & (partner >= 0)
               & ~pregnant & ((tick - p["last_birth"]) > 1.3 * dpy) & (p["energy"] > 0.35))
    together = partner >= 0
    together &= p["pos"] == p["pos"][np.where(partner >= 0, partner, 0)]
    chance = cfg["conception_rate"] * (0.5 + genes[:, G["fertility"]])
    conceive = fertile & together & (rng.random(n) < chance)
    p["pregnant_until"] = np.where(conceive, tick + 270, p["pregnant_until"])
    p["pregnant_by"] = np.where(conceive, p["partner"], p["pregnant_by"])

    due = np.flatnonzero((p["pregnant_until"] == tick) & (p["pregnant_until"] >= 0))
    newborn = _births(p, due, tick, cfg, rng, naming=talking)
    out["births"] = newborn

    # ── 6. death ──────────────────────────────────────────────
    n = p["id"].size           # includes newborns now
    age_y = (tick - p["birth"]) / dpy
    genes = p["genes"]
    aging = np.exp(1.2 * (genes[:, G["fertility"]] - 0.5) - 1.6 * (genes[:, G["longevity"]] - 0.5))
    yearly = 0.10 * np.exp(-age_y / 1.5) + 0.004 + 0.00025 * np.exp(0.09 * age_y) * aging
    yearly *= 1 + 2.0 * (1 - p["health"])                     # weak bodies get sick
    prey = Z[p["pos"]] * cfg["predator_danger"] * np.where(age_y < 12, 3.0, 1.0)
    if learning:                       # fire and spears keep predators off; shelter eases harsh seasons
        guard = np.ones(n)
        guard[: fx["predators"].size] = fx["predators"]
        prey *= guard
        weather = np.ones(n)
        weather[: fx["weather"].size] = fx["weather"]
        yearly *= weather
    if talking:                        # people who can say "predator!" warn each other
        prey *= np.where(language.warned(p), 0.6, 1.0)
    h_old, h_pred = yearly / dpy, prey / dpy
    u = rng.random(n)
    dies_hazard = u < h_old + h_pred
    starved = p["health"] <= 0
    cause = np.where(starved, np.where(p["hydration"] <= 0, 2, 1), np.where(u < h_old, 0, 3))
    dead = np.flatnonzero(starved | dies_hazard)
    if dead.size:
        out["deaths"] = [(int(p["id"][i]), int(cause[i]), float(age_y[i]), int(p["pos"][i])) for i in dead]
        _remove(p, dead)
    return out


def _move(p, hr, group, supply, crowd, temp_c, world, rng) -> None:
    """Where each household goes today.

    Foragers don't drift at random: when the food around camp runs low (or
    restlessness strikes), they scout the land within a couple of days' walk,
    pick somewhere better, and walk there over the following days, up to
    ~12 km a day. Otherwise they make small moves around camp. Thirst
    overrides everything.
    """
    s, cfg = world.static, world.cfg["people"]
    genes = p["genes"]
    radius = int(cfg.get("scouting_radius", 10))
    speed = int(cfg.get("travel_cells_per_day", 3))
    low_food = float(cfg.get("move_when_food_below", 1.5))
    nbr8, cy, cx = s["neighbours8"], s["cy_c"], s["cx_c"]
    H, W = world.shape
    here = p["pos"][hr]
    target = p["target"][hr]
    thirst = 1.0 - p["hydration"][hr]
    wander = genes[hr, G["wanderlust"]]
    insul = genes[hr, G["insulation"]]
    social = genes[hr, G["sociability"]]

    # Once people have a word for "us", they'd rather camp among those who use the same word:
    # people they can understand. (Without language, any company will do.)
    talking = language.enabled(world.cfg)
    if talking:
        us = p["lex"][:, language.MI["people"]].astype(np.int64)
        named = us > 0
        keys, kcount = np.unique(p["pos"][named] * language.WORD_SPACE + us[named], return_counts=True)
        my_us = us[hr]

    def familiar(cells, own, idx, others):
        if not talking:
            return others
        word = my_us[idx]
        k = cells * language.WORD_SPACE + word
        j = np.clip(np.searchsorted(keys, k), 0, max(keys.size - 1, 0))
        hit = (keys.size > 0) & (keys[j] == k) if keys.size else np.zeros(np.shape(k), dtype=bool)
        f = np.where(hit, kcount[j] if keys.size else 0, 0) - own
        return np.where(word > 0, np.maximum(f, 0), others)

    def appeal(cells, own, idx):
        """How good `cells` look to households `idx` (higher is better)."""
        g = group[idx]
        others = crowd[cells] - own
        food = np.minimum(supply[cells] / (others + g), 4.0) / 4.0
        water = -s["water_dist_c"][cells].astype(float) / 2.0
        comfort = -np.clip(12.0 - 16.0 * insul[idx] - temp_c[cells], 0, None) / 10.0
        kin = familiar(cells, own, idx, others)
        # Company is good; company you can talk to is better.
        company = social[idx] * (0.6 * np.log1p(np.maximum(others, 0)) + 0.6 * np.log1p(np.maximum(kin, 0))) / 3.0
        crowded = -np.clip(others + g - 25.0, 0, None) / 25.0
        return 1.5 * food + water + 0.6 * comfort + company + crowded

    # Decide to look for a new camp.
    per_head = supply[here] / np.maximum(crowd[here], 1.0)
    restless = rng.random(hr.size) < 0.004 + 0.03 * wander
    looking = (target < 0) & ((per_head < low_food) | restless) & (thirst < 0.6)
    if looking.any():
        L = np.flatnonzero(looking)
        k = 16
        oy = rng.integers(-radius, radius + 1, (k, L.size))
        ox = rng.integers(-radius, radius + 1, (k, L.size))
        ny = np.clip(cy[here[L]][None, :] + oy, 0, H - 1)
        nx = np.clip(cx[here[L]][None, :] + ox, 0, W - 1)
        cand = s["compact_of"][ny * W + nx]
        ok = cand >= 0
        cand = np.where(ok, cand, here[L][None, :])
        dist = np.maximum(np.abs(oy), np.abs(ox))
        score = appeal(cand, 0.0, L) - 0.3 * dist / radius
        score = np.where(ok, score, -np.inf)
        best = np.argmax(score, axis=0)
        cur = appeal(here[L], group[L], L)
        better = score[best, np.arange(L.size)] > cur + 0.1
        target[L] = np.where(better, cand[best, np.arange(L.size)], -1)

    # Very thirsty households abandon plans and head for water.
    target = np.where(thirst >= 0.6, -1, target)

    # Travel toward targets, a few cells a day; others make small local moves.
    pos = here.copy()
    for _ in range(speed):
        T = np.flatnonzero(target >= 0)
        if T.size == 0:
            break
        opts = np.vstack([pos[T][None, :], nbr8[:, pos[T]]])        # stay + 8 neighbours
        d = np.maximum(np.abs(cy[opts] - cy[target[T]][None, :]), np.abs(cx[opts] - cx[target[T]][None, :]))
        d = d + rng.random(opts.shape) * 0.5                         # break ties, wiggle around obstacles
        pick = opts[np.argmin(d, axis=0), np.arange(T.size)]
        stuck = pick == pos[T]
        pos[T] = pick
        arrived = pos[T] == target[T]
        target[T[arrived | stuck]] = -1

    local = np.flatnonzero((target < 0) & (pos == here))
    if local.size:
        opts = np.vstack([pos[local][None, :], nbr8[:, pos[local]]])
        sc = np.vstack([appeal(opts[j], group[local] if j == 0 else 0.0, local) for j in range(9)])
        sc += (thirst[local] * -s["water_dist_c"][opts].astype(float) * 2.0)
        sc += rng.normal(0, 1, sc.shape) * (0.05 + 0.25 * wander[local])[None, :]
        sc[0] += 0.25                                               # settling in: small moves only if worth it
        pos[local] = opts[np.argmax(sc, axis=0), np.arange(local.size)]

    p["pos"][hr] = pos
    p["target"][hr] = target


def _pair(p: dict, age_y: np.ndarray, rng: np.random.Generator) -> None:
    """Single adults who meet in the same place may pair up (never with close kin)."""
    partner_row = index_of(p["id"], p["partner"])
    p["partner"] = np.where(partner_row >= 0, p["partner"], -1)    # widowed
    single = (p["partner"] < 0) & (age_y >= 16) & (age_y <= 55)
    women = np.flatnonzero(single & (p["sex"] == FEMALE))
    men = np.flatnonzero(single & (p["sex"] == MALE))
    if women.size == 0 or men.size == 0:
        return
    shared = np.intersect1d(p["pos"][women], p["pos"][men])
    if shared.size == 0:
        return
    order_w = rng.permutation(women)
    order_m = rng.permutation(men)
    shared = set(shared.tolist())
    available = {}
    for m in order_m:
        c = int(p["pos"][m])
        if c in shared:
            available.setdefault(c, []).append(int(m))
    ids, mo, fa = p["id"], p["mother"], p["father"]
    for w in order_w:
        pool = available.get(int(p["pos"][w]))
        if not pool:
            continue
        for k, m in enumerate(pool):
            kin = ((mo[w] >= 0 and mo[w] == mo[m]) or (fa[w] >= 0 and fa[w] == fa[m])
                   or mo[w] == ids[m] or fa[w] == ids[m] or mo[m] == ids[w] or fa[m] == ids[w])
            if not kin:
                p["partner"][w], p["partner"][m] = ids[m], ids[w]
                pool.pop(k)
                break


def _births(p: dict, mothers: np.ndarray, tick: int, cfg: dict, rng: np.random.Generator,
            naming: bool = False) -> list:
    if mothers.size == 0:
        return []
    k = mothers.size
    fathers = index_of(p["id"], p["pregnant_by"][mothers])
    mg = p["genes"][mothers]
    fg = np.where((fathers >= 0)[:, None], p["genes"][np.where(fathers >= 0, fathers, 0)], mg)
    pick = rng.random(mg.shape) < 0.5                         # each trait from one parent…
    child_genes = np.where(pick, mg, fg) + rng.normal(0, cfg["mutation"], mg.shape)   # …plus a little mutation
    child_genes = np.clip(child_genes, GENE_RANGE[:, 0], GENE_RANGE[:, 1])
    father_gen = np.where(fathers >= 0, p["gen"][np.where(fathers >= 0, fathers, 0)], 0)
    new_ids = np.arange(p["next_id"], p["next_id"] + k, dtype=np.int64)
    p["next_id"] += k
    new = {
        "id": new_ids, "sex": rng.integers(0, 2, k).astype(np.int8), "birth": np.full(k, tick, dtype=np.int64),
        "pos": p["pos"][mothers].copy(), "energy": np.full(k, 0.6), "hydration": np.ones(k),
        "health": np.ones(k), "mother": p["id"][mothers].copy(), "father": p["pregnant_by"][mothers].copy(),
        "partner": np.full(k, -1, dtype=np.int64),
        "gen": (np.maximum(p["gen"][mothers], father_gen) + 1).astype(np.int32),
        "pregnant_until": np.full(k, -1, dtype=np.int64), "pregnant_by": np.full(k, -1, dtype=np.int64),
        "last_birth": np.full(k, -10 ** 9, dtype=np.int64), "target": np.full(k, -1, dtype=np.int64),
        "known": np.zeros(k, dtype=np.uint32), "items": np.zeros(k, dtype=np.uint32),
        "name": language.name_children(p, mothers, rng) if naming else np.zeros(k, dtype=np.int64),
    }
    p["energy"][mothers] = np.maximum(p["energy"][mothers] - 0.15, 0)
    p["last_birth"][mothers] = tick
    p["pregnant_until"][mothers] = -1
    for key, arr in new.items():
        p[key] = np.concatenate([p[key], arr])
    p["genes"] = np.concatenate([p["genes"], child_genes])
    for key, (cols, t) in MATRICES.items():
        p[key] = np.concatenate([p[key], np.zeros((k, cols), dtype=t)])
    return [(int(new_ids[j]), int(new["mother"][j]), int(new["father"][j]), int(new["sex"][j]),
             int(new["pos"][j]), int(new["gen"][j]), child_genes[j].round(4).tolist(),
             language.name_str(int(new["name"][j]))) for j in range(k)]


def _remove(p: dict, rows: np.ndarray) -> None:
    keep = np.ones(p["id"].size, dtype=bool)
    keep[rows] = False
    for key in ARRAYS:
        p[key] = p[key][keep]
    p["genes"] = p["genes"][keep]
    for key in MATRICES:
        p[key] = p[key][keep]
