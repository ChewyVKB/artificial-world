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

# ── heritable traits ──────────────────────────────────────────────────
# Each has a real trade-off, so evolution has something to work with.
GENES = (
    "size",         # bigger bodies hunt better and handle cold, but need more food
    "insulation",   # tolerate cold; suffer more in heat
    "fertility",    # conceive more easily, but age faster
    "longevity",    # age slower, but bodies cost more to maintain
    "wanderlust",   # how restless — willing to move somewhere unknown
    "sociability",  # how strongly drawn toward other people
)
G = {name: i for i, name in enumerate(GENES)}
GENE_RANGE = np.array([[0.6, 1.4], [0, 1], [0, 1], [0, 1], [0, 1], [0, 1]])
START_GENES = np.array([1.0, 0.2, 0.5, 0.5, 0.3, 0.5])

FEMALE, MALE = 0, 1
CAUSES = ("old age & illness", "starvation", "thirst", "predators")

ARRAYS = {   # name -> dtype; one entry per living person
    "id": np.int64, "sex": np.int8, "birth": np.int64, "pos": np.int64,
    "energy": np.float64, "hydration": np.float64, "health": np.float64,
    "mother": np.int64, "father": np.int64, "partner": np.int64, "gen": np.int32,
    "pregnant_until": np.int64, "pregnant_by": np.int64, "last_birth": np.int64,
}


def empty() -> dict:
    p = {k: np.zeros(0, dtype=t) for k, t in ARRAYS.items()}
    p["genes"] = np.zeros((0, len(GENES)))
    p["next_id"] = 1
    return p


def save_arrays(p: dict) -> dict:
    """Flatten people into named arrays for a checkpoint file."""
    out = {f"people.{k}": p[k] for k in ARRAYS}
    out["people.genes"] = p["genes"]
    out["people.next_id"] = np.int64(p["next_id"])
    return out


def load_arrays(z) -> dict | None:
    if "people.id" not in z:
        return None
    p = {k: z[f"people.{k}"].astype(t) for k, t in ARRAYS.items()}
    p["genes"] = z["people.genes"].astype(float)
    p["next_id"] = int(z["people.next_id"])
    return p


def fingerprint_arrays(p: dict):
    for k in ARRAYS:
        yield np.ascontiguousarray(p[k]).tobytes()
    yield np.ascontiguousarray(p["genes"]).tobytes()
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
        "last_birth": np.full(n, -10 ** 9, dtype=np.int64),
        "genes": np.clip(genes, GENE_RANGE[:, 0], GENE_RANGE[:, 1]),
        "next_id": n + 1,
    })
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
    out = {"births": [], "deaths": []}
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
    is_head = head == np.arange(n)
    hr = np.flatnonzero(is_head)
    group = np.bincount(head, minlength=n)[hr].astype(float)
    here = p["pos"][hr]
    cand = nbr8[:, here]                                      # (9, heads): stay + 8 neighbours
    cand = np.vstack([here[None, :], cand])
    others = crowd[cand] - np.where(np.arange(9)[:, None] == 0, group[None, :], 0)
    food = np.minimum(supply[cand] / (others + group[None, :]), 3.0) / 3.0
    thirst = 1.0 - p["hydration"][hr]
    cold_lim = 12.0 - 16.0 * genes[hr, G["insulation"]]
    comfort = -np.clip(cold_lim[None, :] - temp_c[cand], 0, None) / 10.0
    social = genes[hr, G["sociability"]][None, :] * np.log1p(np.maximum(others, 0)) / 3.0
    crowded = -np.clip(others + group[None, :] - 25.0, 0, None) / 25.0
    noise = rng.normal(0, 1, cand.shape) * (0.05 + 0.35 * genes[hr, G["wanderlust"]])[None, :]
    # People know roughly which way water lies (they can see rivers, follow animals to it).
    wdist = s["water_dist_c"][cand].astype(float)
    water = -(0.25 + 2.5 * thirst[None, :]) * wdist / 1.5
    score = 1.5 * food + water + 0.6 * comfort + social + crowded + noise
    score[0] += 0.15                                          # moving costs effort
    choice = cand[np.argmax(score, axis=0), np.arange(hr.size)]
    new_pos = p["pos"].copy()
    new_pos[hr] = choice
    p["pos"] = new_pos[head]                                  # households move together

    # ── 2. gather, hunt, share ──────────────────────────────────
    pos = p["pos"]
    size = genes[:, G["size"]]
    capacity = np.where(age_y >= 15, cfg["adult_harvest"], np.where(age_y >= 6, 0.35 * cfg["adult_harvest"], 0.0))
    hunt_skill = capacity * size
    want_p = np.bincount(pos, capacity, minlength=ncell)
    want_h = np.bincount(pos, hunt_skill, minlength=ncell)
    frac_p = np.minimum(1.0, plant_supply / np.maximum(want_p, 1e-9))
    frac_h = np.minimum(1.0, hunt_supply / np.maximum(want_h, 1e-9))
    # Each person splits effort between gathering and hunting in proportion to what's available.
    w_p = plant_supply[pos] / np.maximum(supply[pos], 1e-9)
    got = capacity * w_p * frac_p[pos] + hunt_skill * (1 - w_p) * frac_h[pos]
    took_p = np.bincount(pos, capacity * w_p * frac_p[pos], minlength=ncell)
    took_h = np.bincount(pos, hunt_skill * (1 - w_p) * frac_h[pos], minlength=ncell)
    P -= np.minimum(took_p * cfg["plant_cost"], P)
    Gz -= np.minimum(took_h * cfg["hunt_cost"], Gz)

    cold = np.clip(12.0 - 16.0 * genes[:, G["insulation"]] - temp_c[pos], 0, None) / 10.0
    cold *= np.clip(1.3 - 0.5 * size, 0.4, 1.2)               # big bodies keep warm better
    heat = np.clip(temp_c[pos] - (32.0 - 8.0 * genes[:, G["insulation"]]), 0, None) / 8.0
    pregnant = p["pregnant_until"] > tick
    nursing = (tick - p["last_birth"]) < 2 * dpy
    need = np.where(age_y < 6, 0.4, np.where(age_y < 15, 0.7, 1.0)) * size ** 0.75
    need *= (1 + 0.15 * genes[:, G["longevity"]]) * (1 + cold)
    need += 0.2 * pregnant + 0.15 * nursing

    pool = np.bincount(head, got, minlength=n)
    pool_need = np.bincount(head, need, minlength=n)
    food_i = pool[head] * need / np.maximum(pool_need[head], 1e-9)

    # ── 3. body ─────────────────────────────────────────────────
    gap = food_i - need
    p["energy"] = np.clip(p["energy"] + gap / 25.0, 0.0, 1.0)
    starving = (p["energy"] <= 0) & (gap < 0)
    water = s["water_c"][pos] | (rain_mm[pos] > 2.5)
    p["hydration"] = np.where(water, 1.0, np.clip(p["hydration"] - 0.25 - 0.1 * heat, 0, 1))
    thirsty = p["hydration"] <= 0
    p["health"] = np.clip(
        p["health"]
        - starving * 0.04 * (-gap / np.maximum(need, 1e-9))
        - thirsty * 0.12
        - heat * 0.01
        + ((p["energy"] > 0.2) & (p["hydration"] > 0.3)) * 0.01, 0, 1)

    # ── 4. pair up ─────────────────────────────────────────────
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
    newborn = _births(p, due, tick, cfg, rng)
    out["births"] = newborn

    # ── 6. death ──────────────────────────────────────────────
    n = p["id"].size           # includes newborns now
    age_y = (tick - p["birth"]) / dpy
    genes = p["genes"]
    aging = np.exp(1.2 * (genes[:, G["fertility"]] - 0.5) - 1.6 * (genes[:, G["longevity"]] - 0.5))
    yearly = 0.10 * np.exp(-age_y / 1.5) + 0.004 + 0.00025 * np.exp(0.09 * age_y) * aging
    yearly *= 1 + 2.0 * (1 - p["health"])                     # weak bodies get sick
    prey = Z[p["pos"]] * cfg["predator_danger"] * np.where(age_y < 12, 3.0, 1.0)
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


def _births(p: dict, mothers: np.ndarray, tick: int, cfg: dict, rng: np.random.Generator) -> list:
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
        "last_birth": np.full(k, -10 ** 9, dtype=np.int64),
    }
    p["energy"][mothers] = np.maximum(p["energy"][mothers] - 0.15, 0)
    p["last_birth"][mothers] = tick
    p["pregnant_until"][mothers] = -1
    for key, arr in new.items():
        p[key] = np.concatenate([p[key], arr])
    p["genes"] = np.concatenate([p["genes"], child_genes])
    return [(int(new_ids[j]), int(new["mother"][j]), int(new["father"][j]), int(new["sex"][j]),
             int(new["pos"][j]), int(new["gen"][j]), child_genes[j].round(4).tolist()) for j in range(k)]


def _remove(p: dict, rows: np.ndarray) -> None:
    keep = np.ones(p["id"].size, dtype=bool)
    keep[rows] = False
    for key in ARRAYS:
        p[key] = p[key][keep]
    p["genes"] = p["genes"][keep]
