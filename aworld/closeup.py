"""Close-up mode: one small patch of the world, shown in detail.

The world simulation works in days and 4 km squares. When you zoom in on a
place, this module turns *what the simulation decided today* into a scene
you can watch: where each household camped, who went gathering or hunting,
who fetched water, who made a cord or knapped a blade, who lit the evening
fire, what people said to each other, and what's on their minds.

It is a *rendering* of the simulation, never a second simulation: nothing
here feeds back into the world, so watching doesn't change history. The
small details (exactly where in the square a camp sits, the minute someone
sets off) are filled in from the world seed, so the same day always looks
the same — rewind and watch it again, and it plays out identically.

Thoughts are built only from things that are true in the simulation (hunger,
thirst, cold, sickness, family, what they know and carry), using the
person's own words where they have them.
"""
from __future__ import annotations

import zlib

import numpy as np

from . import knowledge as kn
from . import language as lg
from .ecology import BIOMES
from .people import FEMALE, G, index_of

CELL_M = 4000.0          # metres per world cell
RADIUS = 1               # cells around the focus cell (1 → a 3×3 block, 12 km across)

ACTIVITIES = ("sleep", "wake", "walk", "gather", "hunt", "drink", "make", "firestart", "sit", "talk",
              "carried", "play", "rest", "travel", "lie_sick", "dead")


def _rng(world, *keys) -> np.random.Generator:
    tag = zlib.crc32("closeup".encode())
    return np.random.default_rng([int(world.cfg["world"]["seed"]), tag, *[int(k) & 0x7FFFFFFF for k in keys]])


def _word(p, row, key) -> str | None:
    if "lex" not in p or key not in lg.MI:
        return None
    code = int(p["lex"][row, lg.MI[key]])
    return lg.word_str(code) if code else None


def _say(p, row, key, gloss=None) -> str:
    """Their word for something, with our gloss: «kele» (water) — or just the gloss."""
    w = _word(p, row, key)
    gloss = gloss or lg.MEANINGS[lg.MI[key]][1].split(",")[0]
    return f"«{w}» ({gloss})" if w else gloss


def scene(world, cx: int, cy: int, store=None) -> dict:
    """Everything needed to watch the 3×3 cells around (cx, cy) through the last simulated day."""
    s, st = world.static, world.state
    H, W = world.shape
    cx, cy = int(np.clip(cx, RADIUS + 1, W - 2 - RADIUS)), int(np.clip(cy, RADIUS + 1, H - 2 - RADIUS))
    x0, y0 = cx - RADIUS - 1, cy - RADIUS - 1            # one extra ring of cells for smooth terrain edges
    span = 2 * RADIUS + 3
    out = {"origin": {"x": x0, "y": y0}, "cell_m": CELL_M, "span": span, "focus": {"x": cx, "y": cy},
           "tick": world.tick, "year": world.year, "day_of_year": world.day_of_year, "days_per_year": world.dpy,
           "latitude": round(float(s["latitude"][cy, cx]), 2)}
    out["cells"] = _cells(world, x0, y0, span)
    p = st.get("people")
    today = st.get("today")
    if p is None or p["id"].size == 0:
        out.update(people=[], households=[], animals=_animals(world, x0, y0, span, []), events=[])
        return out
    cells_full = s["cells"][p["pos"]]
    px, py = cells_full % W, cells_full // W
    inside = (px >= cx - RADIUS) & (px <= cx + RADIUS) & (py >= cy - RADIUS) & (py <= cy + RADIUS)
    rows = np.flatnonzero(inside)
    age = (world.tick - p["birth"]) / world.dpy
    rec = _today_index(today, p) if today else None
    households, people = {}, []
    temp_now = float(world.temperature_map()[cy, cx])

    for r in rows:
        r = int(r)
        pid = int(p["id"][r])
        t = rec.get(pid) if rec else None
        head_id = int(today["head"][t]) if t is not None else pid
        hh = households.setdefault(head_id, {"head": head_id, "members": []})
        hh["members"].append(pid)
        people.append(_person(world, p, r, age[r], t, today, x0, y0))

    # Camps: households in the same cell gather round one camp site.
    for hid, hh in households.items():
        hr = index_of(p["id"], np.array([hid]))[0]
        if hr < 0:
            hr = index_of(p["id"], np.array([hh["members"][0]]))[0]
        cell_end = int(s["cells"][p["pos"][hr]])
        t = rec.get(hid) if rec else None
        cell_start = int(s["cells"][today["from"][t]]) if t is not None else cell_end
        hh["camp"] = _camp_spot(world, cell_end, hid, x0, y0)
        hh["start_camp"] = _camp_spot(world, cell_start, hid, x0, y0)
        hh["moved"] = cell_start != cell_end
        fire = bool(today["fire"][t]) if t is not None else False
        hh["fire"] = fire
        hh["shelter"] = bool(any(int(p["items"][index_of(p["id"], np.array([m]))[0]]) & kn.bit("shelter")
                                 for m in hh["members"] if index_of(p["id"], np.array([m]))[0] >= 0))
    animals = _animals(world, x0, y0, span, people)
    _plan_days(world, p, people, households, rec, today, age, x0, y0, animals)
    out["people"] = people
    out["households"] = list(households.values())
    out["animals"] = animals
    out["weather"] = {"temperature_c": round(temp_now, 1),
                      "snow": float(world.field(st["snow"])[cy, cx]),
                      "season": _season(world, cy)}
    def inside_cell(compact):
        full = int(s["cells"][compact])
        return abs(full % W - cx) <= RADIUS and abs(full // W - cy) <= RADIUS
    out["events"] = _events(world, p, today, set(int(p["id"][r]) for r in rows), store, inside_cell)
    return out


def _season(world, cy) -> str:
    from .climate import season_name
    return season_name(float(world.static["latitude"][cy, 0]), world.day_of_year, world.dpy)


def _today_index(today, p) -> dict:
    return {int(i): k for k, i in enumerate(today["ids"])}


def _cells(world, x0, y0, span) -> dict:
    """The coarse map around the scene (the viewer adds the fine detail)."""
    s, st = world.static, world.state
    H, W = world.shape
    ys, xs = np.mgrid[y0:y0 + span, x0:x0 + span]
    ys, xs = np.clip(ys, 0, H - 1), np.clip(xs, 0, W - 1)
    full = ys * W + xs

    def compact(arr, default=0.0):
        j = s["compact_of"][full]
        return np.where(j >= 0, arr[np.maximum(j, 0)], default)

    flow = s["flow"][ys, xs]
    # Which neighbour each river cell flows into (the neighbour carrying more water).
    river_to = []
    for (yy, xx) in zip(*np.nonzero(s["river"][ys, xs])):
        gy, gx = ys[yy, xx], xs[yy, xx]
        best, bf = None, s["flow"][gy, gx]
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                ny, nx = gy + dy, gx + dx
                if (dy or dx) and 0 <= ny < H and 0 <= nx < W and s["flow"][ny, nx] > bf and \
                        (s["river"][ny, nx] or s["lake"][ny, nx] or s["ocean"][ny, nx]):
                    best, bf = (int(nx - x0), int(ny - y0)), s["flow"][ny, nx]
        river_to.append({"from": [int(xx), int(yy)], "to": list(best) if best else None,
                         "flow": float(flow[yy, xx])})
    return {
        "elevation": np.round(s["elevation"][ys, xs]).astype(int).tolist(),
        "biome": [[BIOMES[b] for b in row] for row in s["biome"][ys, xs]],
        "ocean": s["ocean"][ys, xs].astype(int).tolist(),
        "lake": s["lake"][ys, xs].astype(int).tolist(),
        "rivers": river_to,
        "plants": np.round(compact(st["plants"]), 3).tolist(),
        "grazers": np.round(compact(st["grazers"]), 3).tolist(),
        "predators": np.round(compact(st["predators"]), 3).tolist(),
        "snow": np.round(compact(st["snow"]), 1).tolist(),
        "wood": np.round(compact(s["wood_c"]) if "wood_c" in s else np.zeros(full.shape), 2).tolist(),
        "stone": np.round(compact(s["stone_c"]) if "stone_c" in s else np.zeros(full.shape), 2).tolist(),
        "temperature": np.round(world.temperature_map()[ys, xs], 1).tolist(),
    }


def _local(world, cell_full, x0, y0):
    W = world.shape[1]
    return (cell_full % W - x0) * CELL_M, (cell_full // W - y0) * CELL_M


def _camp_spot(world, cell_full, hid, x0, y0):
    """Households in one cell share a camp: it sits near the middle of the square
    (where its stream runs), and each household has its own hearth around it."""
    lx, ly = _local(world, cell_full, x0, y0)
    month = world.tick // 30
    rc = _rng(world, cell_full, month)
    centre = (lx + CELL_M * (0.5 + rc.uniform(-0.12, 0.12)), ly + CELL_M * (0.5 + rc.uniform(-0.12, 0.12)))
    rh = _rng(world, cell_full, hid)
    ang, dist = rh.uniform(0, 2 * np.pi), rh.uniform(10, 38)
    return [round(centre[0] + np.cos(ang) * dist, 1), round(centre[1] + np.sin(ang) * dist, 1)]


def _look(p, r) -> dict:
    """How someone looks, from what they inherited."""
    g = p["genes"][r]
    size = float(g[G["size"]])
    insulation = float(g[G["insulation"]])
    # Skin: darker where ancestors lived under strong sun; we use cold-adaptation as the
    # proxy (it's inherited and tracks the climates a lineage has lived in).
    skin = float(np.clip(0.75 - 0.6 * insulation, 0.1, 0.85))
    hue = (zlib.crc32(str(int(p["mother"][r])).encode()) % 1000) / 1000.0
    return {"size": round(size, 3), "build": round(0.4 + 0.6 * insulation, 2), "skin": round(skin, 2),
            "hair": round(0.15 + 0.5 * hue * (1 - skin), 2), "female": bool(p["sex"][r] == FEMALE)}


def _person(world, p, r, age, t, today, x0, y0) -> dict:
    pid = int(p["id"][r])
    items = int(p["items"][r]) if "items" in p else 0
    known = int(p["known"][r]) if "known" in p else 0
    d = {
        "id": pid, "name": lg.name_str(int(p["name"][r])) if "name" in p and p["name"][r] else None,
        "age": round(float(age), 1), "sex": "female" if p["sex"][r] == FEMALE else "male",
        "look": _look(p, r), "health": round(float(p["health"][r]), 2), "energy": round(float(p["energy"][r]), 2),
        "hydration": round(float(p["hydration"][r]), 2),
        "mother": int(p["mother"][r]), "partner": int(p["partner"][r]),
        "carrying": [rec["key"] for i, rec in enumerate(kn.RECIPES) if rec["lasts"] and items >> i & 1],
        "knows": [rec["key"] for i, rec in enumerate(kn.RECIPES) if known >> i & 1],
        "pregnant": bool(p["pregnant_until"][r] > world.tick),
    }
    if t is not None:
        d["today"] = {"gathered": round(float(today["gathered"][t]), 2), "hunted": round(float(today["hunted"][t]), 2),
                      "food": round(float(today["food"][t]), 2), "need": round(float(today["need"][t]), 2),
                      "drank_at_water": bool(today["drank"][t]), "drank_rain": bool(today["rain_drink"][t]),
                      "fire": bool(today["fire"][t]),
                      "made": [rec["key"] for i, rec in enumerate(kn.RECIPES) if int(today["made"][t]) >> i & 1]}
    d["_row"] = r
    return d


def _plan_days(world, p, people, households, rec, today, age, x0, y0, animals=()):
    """Turn each person's day into a timeline of things you can watch (hours 0–24)."""
    by_id = {pp["id"]: pp for pp in people}
    talk = today.get("talk", []) if today else []
    deaths = {d[0]: d for d in (today.get("deaths", []) if today else [])}
    births = set(today.get("births", []) if today else [])
    for hid, hh in households.items():
        camp, start_camp = hh["camp"], hh["start_camp"]
        members = [by_id[m] for m in hh["members"] if m in by_id]
        # Who lights the fire: the household member most practised at it.
        hh["fire_by"] = None
        if hh["fire"]:
            k = kn.K["fire"]
            best = max((m for m in members if "fire" in m["knows"]),
                       key=lambda m: float(p["skill"][m["_row"], k]), default=None)
            hh["fire_by"] = best["id"] if best else None
            hh["fire_at"] = 18.0 + _rng(world, world.tick, hid, 7).uniform(-0.3, 0.4)
        for m in members:
            m["timeline"], m["thoughts"], m["speech"] = _timeline(world, p, m, hh, camp, start_camp, age[m["_row"]],
                                                                  deaths, births, x0, y0, animals)
    # Speech: put each conversation at a time both are awake and together.
    for k, (sp, hr, meaning, code) in enumerate(talk):
        if sp in by_id:
            rng = _rng(world, world.tick, sp, k)
            t = float(rng.choice([rng.uniform(6.5, 7.5), rng.uniform(19.0, 21.0), rng.uniform(12.0, 13.0)]))
            by_id[sp]["speech"].append({"t": round(t, 2), "word": lg.word_str(code),
                                        "gloss": lg.MEANINGS[meaning][1], "to": hr})
    for m in people:
        m["speech"].sort(key=lambda s_: s_["t"])
        m.pop("_row", None)


def _timeline(world, p, m, hh, camp, start_camp, age, deaths, births, x0, y0, animals=()):
    """A person's day as segments: {t0, t1, act, from, to, item}."""
    rng = _rng(world, world.tick, m["id"])
    seg = []
    thoughts = []
    r = m["_row"]
    home = list(camp)
    near = lambda c, rad: [round(c[0] + rng.uniform(-rad, rad), 1), round(c[1] + rng.uniform(-rad, rad), 1)]
    spot = near(home, 1.2)

    def add(t0, t1, act, a, b=None, item=None):
        seg.append({"t0": round(t0, 2), "t1": round(t1, 2), "act": act, "from": a, "to": b or a, "item": item})

    today = m.get("today", {})
    sick = m["health"] < 0.35
    infant = age < 3
    child = 3 <= age < 12
    old = age >= 60
    moved = hh["moved"]
    start = list(start_camp) if moved else home

    if infant:
        mother = m["mother"]
        add(0, 24, "carried", home, item=mother)
        thoughts.append({"t": 8, "text": "…"})
        return seg, thoughts, []
    add(0, 6 + rng.uniform(-0.3, 0.4), "sleep", start)
    t = seg[-1]["t1"]
    add(t, t + 0.7, "wake", start)
    t = seg[-1]["t1"]
    if m["id"] in deaths:
        cause = deaths[m["id"]][1]
        when = rng.uniform(9, 17)
        add(t, when, "lie_sick" if cause != 3 else "rest", start)
        add(when, 24, "dead", start)
        thoughts += _thoughts(world, p, m, "dying", age)
        return seg, thoughts, []
    if moved:
        # The whole household walks to a new camp.
        add(t, 15.5, "travel", start, home)
        t = 15.5
        thoughts += [{"t": 9, "text": _moving_thought(p, r)}]
    elif sick:
        add(t, 20, "lie_sick", spot)
        t = 20
    elif child:
        playground = near(home, 30)
        add(t, 12, "play", playground, near(home, 30))
        add(12, 13, "sit", spot)
        add(13, 18, "play", near(home, 30), near(home, 40))
        t = 18
    else:
        hunting = today.get("hunted", 0) > 0.6 * max(today.get("gathered", 0), 0.01) and not old
        dist = (rng.uniform(900, 2400) if hunting else rng.uniform(250, 1300)) * (0.5 if old else 1.0)
        ang = rng.uniform(0, 2 * np.pi)
        field = [round(home[0] + np.cos(ang) * dist, 1), round(home[1] + np.sin(ang) * dist, 1)]
        herd = [a for a in animals if a["kind"] == "grazer"]
        if hunting and herd:                                  # hunters go where the herd actually is
            near_a = min(herd, key=lambda a: (a["x"] - home[0]) ** 2 + (a["y"] - home[1]) ** 2)
            if ((near_a["x"] - home[0]) ** 2 + (near_a["y"] - home[1]) ** 2) ** 0.5 < 6000:
                field = [round(near_a["x"] + rng.uniform(-60, 60), 1), round(near_a["y"] + rng.uniform(-60, 60), 1)]
                dist = ((field[0] - home[0]) ** 2 + (field[1] - home[1]) ** 2) ** 0.5
        walk_h = dist / 4000.0 + 0.1
        add(t, t + walk_h, "walk", home, field)
        t = seg[-1]["t1"]
        work = "hunt" if hunting else "gather"
        add(t, 11.8, work, field, near(field, 150 if hunting else 60))
        t = 11.8
        if today.get("drank_at_water"):
            stream = [round(home[0] + rng.uniform(-200, 200), 1), round(home[1] + rng.uniform(-200, 200), 1)]
            add(t, t + 0.5, "drink", field, stream)
            t += 0.5
            add(t, 14.5, work, stream, near(field, 120))
        else:
            add(t, 14.5, work, field, near(field, 120))
        t = 14.5
        add(t, t + walk_h, "walk", seg[-1]["to"], home)
        t = seg[-1]["t1"]
    made = today.get("made", [])
    if made and not sick:
        for item in made:
            add(t, t + 1.0, "make", spot, item=item)
            t = seg[-1]["t1"]
    fire_at = hh.get("fire_at", 18.0)
    if hh.get("fire_by") == m["id"]:
        if t < fire_at - 0.05:
            add(t, fire_at - 0.05, "rest", spot)
        add(max(t, fire_at - 0.05), fire_at + 0.35, "firestart", home)
        t = fire_at + 0.35
    if t < 18.5:
        add(t, 18.5, "rest", spot)
        t = 18.5
    add(t, 21.5 + rng.uniform(-0.5, 0.5), "sit", near(home, 3.5))
    t = seg[-1]["t1"]
    add(t, 24, "sleep", spot)
    thoughts += _thoughts(world, p, m, None, age, hh=hh)
    return seg, thoughts, []


def _moving_thought(p, r):
    return f"Nothing left to eat here. We go — {_say(p, r, 'go', 'go')}."


def _thoughts(world, p, m, mode, age, hh=None) -> list[dict]:
    """A few thoughts through the day, from what's actually true for this person."""
    r = m["_row"]
    today = m.get("today", {})
    out = []

    def at(t, text):
        text = text.strip()
        if not text.startswith("«"):                    # their own words keep their spelling
            text = text[:1].upper() + text[1:]
        out.append({"t": t, "text": text})

    if mode == "dying":
        at(8, "Weak. Cold inside.")
        at(12, f"{_say(p, r, 'mother', 'mother')}…" if age < 30 else "Tired. So tired.")
        return out
    hungry = m["energy"] < 0.3 or today.get("food", 1) < 0.7 * today.get("need", 1)
    thirsty = m["hydration"] < 0.5
    t_now = float(world.temperature_map().ravel()[world.static["cells"][p["pos"][r]]])
    cold = t_now < 12.0 - 16.0 * float(p["genes"][r, G["insulation"]]) - (7 if today.get("fire") else 0)
    at(6.5, "Hungry. " + f"Need {_say(p, r, 'plant', 'food')}." if hungry else
       ("Cold morning." if cold else "Light again. " + ("Rain." if world.state["anomaly"].mean() > 0.2 else "")))
    if today.get("hunted", 0) > today.get("gathered", 0) and age >= 12:
        at(9, f"The {_say(p, r, 'herd', 'herd')} are close. Quiet now.")
        if "spear" in m["carrying"]:
            at(10.5, "Spear ready. Closer… closer.")
    elif age >= 12:
        at(9, f"Looking for {_say(p, r, 'plant', 'roots and seeds')}." +
           (" The digging stick helps." if "digging_stick" in m["carrying"] else ""))
    if thirsty:
        at(12, f"Thirsty. {_say(p, r, 'water', 'water')}…")
    elif today.get("drank_at_water"):
        at(12, f"{_say(p, r, 'river', 'the river')} — cool {_say(p, r, 'water', 'water')}.")
    if m["health"] < 0.6:
        at(13.5, f"{_say(p, r, 'sick', 'sick')}. Everything aches.")
    for item in today.get("made", []):
        name = kn.RECIPES[kn.K[item]]["name"].lower()
        at(15.5, f"Making a {name}. " + _say(p, r, f"tech:{item}", name) + ".")
    if hh and hh.get("fire_by") == m["id"]:
        at(hh["fire_at"], f"Wood, the dry grass, strike — {_say(p, r, 'tech:fire', 'fire')}!")
    elif hh and hh.get("fire"):
        at(19, f"Warm by the {_say(p, r, 'tech:fire', 'fire')}.")
    elif cold:
        at(19, "Cold night coming. No fire.")
    if m["partner"] >= 0:
        partner = index_of(p["id"], np.array([m["partner"]]))[0]
        if partner >= 0:
            pname = lg.name_str(int(p["name"][partner])) if "name" in p and p["name"][partner] else "my mate"
            at(20, f"{pname} is here. Good.")
    mother_alive = index_of(p["id"], np.array([m["mother"]]))[0] >= 0 if m["mother"] >= 0 else False
    if age < 25 and m["mother"] >= 0 and not mother_alive:
        at(21, f"{_say(p, r, 'mother', 'Mother')} is gone.")
    if m["pregnant"]:
        at(14, "The child moves inside me.")
    out.sort(key=lambda d: d["t"])
    return out


def _animals(world, x0, y0, span, people) -> list[dict]:
    """A few herds and predators, placed where the simulation says they are."""
    s, st = world.static, world.state
    H, W = world.shape
    out = []
    for yy in range(span):
        for xx in range(span):
            gy, gx = y0 + yy, x0 + xx
            if not (0 <= gy < H and 0 <= gx < W):
                continue
            j = s["compact_of"][gy * W + gx]
            if j < 0:
                continue
            g, z = float(st["grazers"][j]), float(st["predators"][j])
            rng = _rng(world, world.tick // 5, gy * W + gx, 3)
            n_herd = int(min(18, g * 120))
            if n_herd:
                cx_, cy_ = (xx + rng.uniform(0.2, 0.8)) * CELL_M, (yy + rng.uniform(0.2, 0.8)) * CELL_M
                for k in range(n_herd):
                    out.append({"kind": "grazer", "x": round(cx_ + rng.normal(0, 60), 1),
                                "y": round(cy_ + rng.normal(0, 60), 1), "heading": round(rng.uniform(0, 6.28), 2)})
            if z > 0.02 and rng.random() < min(1.0, z * 8):
                out.append({"kind": "predator", "x": round((xx + rng.uniform(0.1, 0.9)) * CELL_M, 1),
                            "y": round((yy + rng.uniform(0.1, 0.9)) * CELL_M, 1), "heading": round(rng.uniform(0, 6.28), 2)})
    return out


def _events(world, p, today, ids, store, inside_cell=None) -> list[str]:
    """Notable things that happened in this patch today."""
    if not today:
        return []
    out = []
    for b in today.get("births", []):
        r = index_of(p["id"], np.array([b]))[0]
        if r >= 0 and int(b) in ids:
            out.append(f"A child is born: {lg.name_str(int(p['name'][r])) or '#' + str(b)}.")
    for d in today.get("deaths", []):
        if inside_cell is None or inside_cell(int(d[3])):
            out.append(f"#{d[0]} died, aged {d[2]:.0f} ({['of age and illness', 'of hunger', 'of thirst', 'killed by a predator'][d[1]]}).")
    for pid, r_, cell in today.get("discoveries", []):
        if inside_cell is None or inside_cell(int(cell)):
            out.append(f"#{pid} worked out {kn.RECIPES[r_]['name'].lower()} — for the first time.")
    return out[:12]
