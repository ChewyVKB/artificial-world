"""Minds: memories, feelings and goals.

Until now people reacted only to the present: hungry → look for food.
Here they get an inner life that carries the past forward:

* **Memories.** Each person keeps a handful of things that happened to them —
  the birth of a child, losing a partner, the place a predator took someone,
  a valley where they ate well, the day they first made fire. Memories fade
  with time (a lost child fades slowly, a good meal quickly), and when there
  is no room the faintest memory is forgotten. Memories die with the person.

* **Feelings.** Four of them, each 0–1, rising with what happens and slowly
  settling back:  joy (fed, warm, with family, a new child), fear (predators
  close, nearly dying), grief (someone they loved died) and loneliness
  (no partner, no company).

* **Goals.** What matters most to them right now — find water, stay safe,
  mourn, find a partner, learn from someone… worked out from their body,
  feelings and situation each day.

None of this is a script: no one is told "grieving people do X". The few
effects are simple and physical-ish, and what follows from them is up to
the world:

* households avoid places where bad things happened to them, and go back
  to places they remember eating well (seasonal rounds can emerge from this);
* a frightened household moves on, even if the food is good;
* lonely people are drawn more strongly toward other people;
* someone grieving has less heart for foraging for a while.

Everything is vectorised and uses only the world's seeded randomness, so
history stays exactly reproducible.
"""
from __future__ import annotations

import numpy as np

# ── feelings ──────────────────────────────────────────────────────────
FEELINGS = ("joy", "fear", "grief", "lonely")
F = {k: i for i, k in enumerate(FEELINGS)}
NF = len(FEELINGS)

# ── memories ──────────────────────────────────────────────────────────
K = 10   # how many things one person can remember at once
#          key             half-life (years)   kind of memory
KINDS = (
    ("none", 1.0, ""),
    ("child_born", 40.0, "person"),
    ("lost_partner", 30.0, "person"),
    ("lost_child", 30.0, "person"),
    ("lost_parent", 25.0, "person"),
    ("lost_kin", 15.0, "person"),
    ("predator", 8.0, "place"),        # someone was killed by predators here
    ("hunger", 3.0, "place"),          # went hungry here
    ("plenty", 3.0, "place"),          # ate well here
    ("discovered", 40.0, "thing"),     # worked out how to make something
    ("learned", 12.0, "thing"),        # was shown how to make something
    ("paired", 30.0, "person"),        # began a life with a partner
    ("thirst", 3.0, "place"),          # nearly died of thirst here
    ("strangers", 10.0, "word"),       # first met people who call themselves something else
)
MK = {k: i for i, (k, _, _) in enumerate(KINDS)}
HALF_LIFE = np.array([h for _, h, _ in KINDS])
GOOD_PLACE = np.zeros(len(KINDS), dtype=bool)
GOOD_PLACE[MK["plenty"]] = True
BAD_PLACE = np.zeros(len(KINDS), dtype=bool)
BAD_PLACE[[MK["predator"], MK["hunger"], MK["thirst"]]] = True

# ── goals ─────────────────────────────────────────────────────────────
GOALS = ("rest", "find water", "find food", "stay safe", "keep warm", "mourn", "look after the baby",
         "find company", "find a partner", "learn", "explore", "stay close to mother")
GI = {k: i for i, k in enumerate(GOALS)}

# Per-person tables (added to people.MATRICES): name -> (columns, dtype)
MATRICES = {
    "feel": (NF, np.float32),
    "mem_kind": (K, np.int8),
    "mem_tick": (K, np.int64),
    "mem_cell": (K, np.int64),
    "mem_who": (K, np.int64),     # the other person (an id), or a word for "strangers"
    "mem_what": (K, np.int64),    # what it was about: a technique, a cause of death…
    "mem_str": (K, np.float32),   # how strong the memory was when it was made
}


def enabled(cfg: dict) -> bool:
    return "minds" in cfg


def strength(p: dict, rows, tick: int, dpy: int) -> np.ndarray:
    """How strong each memory of these people is now (faded with time). Shape (rows, K)."""
    kind = p["mem_kind"][rows].astype(np.int64)
    age_y = (tick - p["mem_tick"][rows]) / dpy
    s = p["mem_str"][rows] * 0.5 ** (age_y / HALF_LIFE[kind])
    return np.where(kind > 0, s, 0.0)


def remember(p: dict, rows, kind: str, tick: int, dpy: int, cell=None, who=None, what=None, power=1.0) -> None:
    """Store a memory for each of `rows`. Place memories of the same place are refreshed,
    not duplicated. If memory is full the faintest thing is forgotten — unless the new
    memory is fainter still, in which case it's simply not kept."""
    rows = np.asarray(rows, dtype=np.int64)
    if rows.size == 0:
        return
    n = rows.size

    def full(v, default):
        return np.broadcast_to(np.asarray(default if v is None else v), (n,)).astype(np.int64)

    cell, who, what = full(cell, -1), full(who, 0), full(what, 0)
    power = np.broadcast_to(np.asarray(power, dtype=np.float64), (n,))
    k = MK[kind]
    todo = np.arange(n)
    while todo.size:                                    # one person may get several memories at once
        _, first = np.unique(rows[todo], return_index=True)
        now, todo = todo[first], np.delete(todo, first)
        r = rows[now]
        cur = strength(p, r, tick, dpy)
        same = np.zeros(cur.shape, dtype=bool)
        if KINDS[k][2] == "place":
            same = (p["mem_kind"][r] == k) & (p["mem_cell"][r] == cell[now][:, None])
        elif KINDS[k][2] == "word":
            same = (p["mem_kind"][r] == k) & (p["mem_who"][r] == who[now][:, None])
        has = same.any(axis=1)
        slot = np.where(has, np.argmax(same, axis=1), np.argmin(cur, axis=1))
        old = cur[np.arange(r.size), slot]
        keep = has | (power[now] > old)
        r, slot, j = r[keep], slot[keep], now[keep]
        p["mem_kind"][r, slot] = k
        p["mem_tick"][r, slot] = tick
        p["mem_cell"][r, slot] = cell[j]
        p["mem_who"][r, slot] = who[j]
        p["mem_what"][r, slot] = what[j]
        p["mem_str"][r, slot] = np.maximum(power[j], old[keep] * has[keep])


def place_feeling(p: dict, heads, cells, tick: int, dpy: int, good: float = 1.0) -> np.ndarray:
    """How people `heads` feel about `cells` (same leading shape as cells' last axis):
    positive for places they remember eating well (weighted by `good`), negative for bad memories."""
    kind = p["mem_kind"][heads]
    st = strength(p, heads, tick, dpy)
    good_w, fond = good, np.where(GOOD_PLACE[kind], st, 0.0)
    bad = np.where(BAD_PLACE[kind], st, 0.0)
    where = p["mem_cell"][heads]
    c = np.asarray(cells)
    match = c[..., None] == where                       # (..., heads, K)
    return good_w * (match * fond).sum(-1) - (match * bad).sum(-1)


def remembered_good_places(p: dict, heads, tick: int, dpy: int) -> np.ndarray:
    """(K, heads) cells each head remembers fondly, or -1."""
    kind = p["mem_kind"][heads]
    st = strength(p, heads, tick, dpy)
    ok = GOOD_PLACE[kind] & (st > 0.05)
    return np.where(ok, p["mem_cell"][heads], -1).T


# ── one day of inner life ─────────────────────────────────────────────
def feel(world, ctx: dict) -> None:
    """Feelings drift with today's circumstances; places leave memories; goals are set."""
    p, s, st, tick, dpy = world.state["people"], world.static, world.state, world.tick, world.dpy
    n = p["id"].size
    if n == 0:
        return
    fl = p["feel"]
    age_y, head, pos = ctx["age_y"], ctx["head"], p["pos"]
    adult = age_y >= 16
    food, need = ctx["food"], ctx["need"]
    ratio = food / np.maximum(need, 1e-9)
    crowd = np.bincount(pos, minlength=s["cells"].size)
    household = np.bincount(head, minlength=n)[head]
    partnered = p["partner"] >= 0
    fire = ctx.get("fire")
    fire = np.zeros(n, dtype=bool) if fire is None else fire

    # Joy: fed, watered, warm, healthy, not alone.
    comfort = np.clip((ratio - 0.6) / 0.8, 0, 1)
    joy_t = (0.15 + 0.3 * comfort + 0.12 * partnered + 0.1 * fire + 0.08 * np.minimum(household - 1, 3) / 3
             + 0.1 * (p["hydration"] > 0.5) - 0.35 * (p["health"] < 0.5) - 0.3 * ctx["cold"].clip(0, 1))
    fl[:, F["joy"]] += 0.05 * (np.clip(joy_t, 0, 1) - fl[:, F["joy"]])
    # Fear: predators about, a body close to failing. It spikes fast and fades over weeks.
    danger = np.clip(st["predators"][pos] * 3.0, 0, 0.3) * ctx["guard"]
    threat = danger + 0.4 * (p["health"] < 0.3) + 0.3 * (p["hydration"] < 0.2)
    fl[:, F["fear"]] = np.maximum(fl[:, F["fear"]] * 0.95, np.minimum(threat, 1.0))
    # Grief fades over months.
    fl[:, F["grief"]] *= 0.993
    # Loneliness: adults without a partner; anyone with no one around.
    alone = crowd[pos] <= 1
    lonely_t = 0.5 * (adult & ~partnered) + 0.4 * alone - 0.2 * (household >= 4)
    fl[:, F["lonely"]] += 0.02 * (np.clip(lonely_t, 0, 1) - fl[:, F["lonely"]])
    np.clip(fl, 0, 1, out=fl)

    # Learned something today (not discovered — that's remembered separately).
    if ctx.get("known_before") is not None:
        new = p["known"] & ~ctx["known_before"]
        found = {(i, r) for i, r, _ in ctx.get("discoveries", [])}
        rows, rs = [], []
        for i in np.flatnonzero(new):
            for r in range(32):
                if int(new[i]) >> r & 1 and (int(p["id"][i]), r) not in found:
                    rows.append(i), rs.append(r)
        if rows:
            remember(p, rows, "learned", tick, dpy, cell=pos[rows], what=rs, power=0.5)
            fl[rows, F["joy"]] = np.minimum(1, fl[rows, F["joy"]] + 0.1)

    # Places leave memories (checked every few days, by those old enough to remember).
    if tick % 5 == 0:
        old = np.flatnonzero(age_y >= 8)
        good = old[ratio[old] >= 1.3]
        remember(p, good, "plenty", tick, dpy, cell=pos[good], power=np.minimum(0.3 + 0.3 * (ratio[good] - 1.3), 0.7))
        hungry = old[p["energy"][old] < 0.08]
        remember(p, hungry, "hunger", tick, dpy, cell=pos[hungry], power=0.6)
        dry = old[p["hydration"][old] <= 0.05]
        remember(p, dry, "thirst", tick, dpy, cell=pos[dry], power=0.7)
    if tick % 10 == 0 and "lex" in p:                  # meeting people who call themselves something else
        from .language import MI, WORD_SPACE
        us = p["lex"][:, MI["people"]].astype(np.int64)
        named = np.flatnonzero((us > 0) & adult)
        if named.size:
            key = pos[named] * WORD_SPACE + us[named]
            order = np.argsort(key, kind="stable")
            kc = pos[named][order]
            lo = np.searchsorted(kc, kc, side="left")
            hi = np.searchsorted(kc, kc, side="right") - 1
            w_sorted = us[named][order]
            first, last = w_sorted[lo], w_sorted[hi]
            other = np.where(w_sorted == first, last, first)
            meets = other != w_sorted
            rows = named[order][meets]
            if rows.size:
                kind = p["mem_kind"][rows]
                seen = ((kind == MK["strangers"]) & (p["mem_who"][rows] == other[meets][:, None])).any(axis=1)
                fresh = rows[~seen]
                remember(p, fresh, "strangers", tick, dpy, cell=pos[fresh], who=other[meets][~seen], power=0.5)

    # Goals: what matters most right now (the first that applies wins).
    curious = ctx["curiosity"]
    cell_known = np.zeros(s["cells"].size, dtype=np.uint32)
    np.bitwise_or.at(cell_known, pos, p["known"])
    could_learn = (cell_known[pos] & ~p["known"]) > 0
    baby = (p["sex"] == 0) & ((tick - p["last_birth"]) < 2 * dpy)
    rules = [
        (age_y < 5, "stay close to mother"),
        (p["hydration"] < 0.4, "find water"),
        (p["energy"] < 0.3, "find food"),
        (fl[:, F["fear"]] > 0.5, "stay safe"),
        (ctx["cold"] > 0.3, "keep warm"),
        (fl[:, F["grief"]] > 0.45, "mourn"),
        (baby, "look after the baby"),
        ((fl[:, F["lonely"]] > 0.45) & alone, "find company"),
        (adult & (age_y <= 45) & ~partnered & (fl[:, F["lonely"]] > 0.25), "find a partner"),
        ((age_y >= 5) & (age_y < 30) & could_learn & (curious > 0.4), "learn"),
        ((ctx["target"] >= 0) | (ctx["wanderlust"] > 0.7), "explore"),
    ]
    goal = np.full(n, GI["rest"], dtype=np.int8)
    decided = np.zeros(n, dtype=bool)
    for cond, g in rules:
        pick = cond & ~decided
        goal[pick] = GI[g]
        decided |= cond
    p["goal"] = goal


def events(world, ids_before: np.ndarray, partner_before: np.ndarray, births: list, deaths: list,
           dead_parents: tuple, discoveries: list) -> None:
    """The big moments: births, pairings, deaths, discoveries. Called at the end of the day.
    `deaths` are (id, cause, age, cell); `dead_parents` = (mothers, fathers) of the dead."""
    p, tick, dpy = world.state["people"], world.tick, world.dpy
    from .people import CAUSES, index_of
    n = p["id"].size
    if n == 0:
        return
    fl = p["feel"]
    age_y = (tick - p["birth"]) / dpy

    def bump(rows, feeling, amount):
        fl[rows, F[feeling]] = np.minimum(1, fl[rows, F[feeling]] + amount)

    # New partners (rows of those who were alive this morning).
    old_rows = index_of(p["id"], ids_before)
    alive = old_rows >= 0
    r = old_rows[alive]
    rows = r[(partner_before[alive] < 0) & (p["partner"][r] >= 0)]
    if rows.size:
        remember(p, rows, "paired", tick, dpy, cell=p["pos"][rows], who=p["partner"][rows], power=0.8)
        bump(rows, "joy", 0.3)
        fl[rows, F["lonely"]] *= 0.4

    # A child is born.
    for b in births:
        rows = index_of(p["id"], np.array([b[1], b[2]]))
        rows = rows[rows >= 0]
        remember(p, rows, "child_born", tick, dpy, cell=p["pos"][rows], who=b[0], power=0.9)
        bump(rows, "joy", 0.4)

    # Discoveries.
    for pid, r_, cell in discoveries:
        row = index_of(p["id"], np.array([pid]))
        row = row[row >= 0]
        remember(p, row, "discovered", tick, dpy, cell=cell, what=r_, power=1.0)
        bump(row, "joy", 0.3)

    # Deaths: those who loved them grieve; those who saw a predator kill fear the place.
    if not deaths:
        return
    dead = np.array([d[0] for d in deaths], dtype=np.int64)
    cause = np.array([d[1] for d in deaths], dtype=np.int64)
    dage = np.array([d[2] for d in deaths], dtype=float)
    dcell = np.array([d[3] for d in deaths], dtype=np.int64)
    dmother, dfather = (np.asarray(x, dtype=np.int64) for x in dead_parents)
    order = np.argsort(dead)
    dead, cause, dage, dcell, dmother, dfather = (a[order] for a in (dead, cause, dage, dcell, dmother, dfather))

    def lookup(ids):                         # which of the dead each id is, or -1
        j = np.clip(np.searchsorted(dead, ids), 0, dead.size - 1)
        return np.where((ids >= 0) & (dead[j] == ids), j, -1)

    def grieve(rows, j, kind, amount):
        if rows.size:
            remember(p, rows, kind, tick, dpy, cell=dcell[j], who=dead[j], what=cause[j],
                     power=np.minimum(np.asarray(amount) + 0.1, 1.0))
            bump(rows, "grief", amount)

    j = lookup(p["partner"])                                     # their partner
    rows = np.flatnonzero(j >= 0)
    grieve(rows, j[rows], "lost_partner", 0.9)
    bump(rows, "lonely", 0.4)
    for parent in ("mother", "father"):                          # their mother or father
        j = lookup(p[parent])
        rows = np.flatnonzero(j >= 0)
        grieve(rows, j[rows], "lost_parent", np.where(age_y[rows] < 15, 0.8, 0.45))
    for par in (dmother, dfather):                               # their child
        rows = index_of(p["id"], par)
        jj = np.flatnonzero(rows >= 0)
        grieve(rows[jj], jj, "lost_child", 0.5 + 0.4 * np.minimum(dage[jj] / 5.0, 1.0))
    has = np.flatnonzero(dmother >= 0)                           # a brother or sister
    if has.size:
        mo_sorted = np.argsort(dmother[has], kind="stable")
        keys = dmother[has][mo_sorted]
        k = np.clip(np.searchsorted(keys, p["mother"]), 0, keys.size - 1)
        sib = np.flatnonzero((p["mother"] >= 0) & (keys[k] == p["mother"]))
        grieve(sib, has[mo_sorted[k[sib]]], "lost_kin", 0.35)
    pred = np.flatnonzero(cause == CAUSES.index("predators"))
    if pred.size:                                                # everyone there saw it happen
        cs = pred[np.argsort(dcell[pred], kind="stable")]
        cells_s = dcell[cs]
        k = np.clip(np.searchsorted(cells_s, p["pos"]), 0, cells_s.size - 1)
        saw = np.flatnonzero((cells_s[k] == p["pos"]) & (age_y >= 4))
        if saw.size:
            remember(p, saw, "predator", tick, dpy, cell=p["pos"][saw], who=dead[cs[k[saw]]], power=0.8)
            bump(saw, "fear", 0.6)


# ── reading a mind (for the viewer) ───────────────────────────────────
def mood_word(f) -> str:
    joy, fear, grief, lonely = (float(x) for x in f)
    if grief > 0.5:
        return "grieving"
    if fear > 0.6:
        return "afraid"
    if lonely > 0.6:
        return "lonely"
    if fear > 0.35:
        return "wary"
    if grief > 0.25:
        return "sad"
    if joy > 0.6:
        return "happy"
    if joy > 0.35:
        return "content"
    if joy < 0.15:
        return "miserable"
    return "uneasy"


def mood(p: dict) -> np.ndarray:
    """One number per person, 0 (wretched) … 1 (happy) — for the map."""
    f = p["feel"]
    return np.clip(0.5 + 0.6 * f[:, F["joy"]] - 0.35 * f[:, F["fear"]] - 0.45 * f[:, F["grief"]]
                   - 0.3 * f[:, F["lonely"]] - 0.15, 0, 1)
