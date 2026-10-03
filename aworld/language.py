"""Language: words invented, shared, and drifting apart.

What's built in is only the *ability*: people can make sounds, link a
sound to something they're both paying attention to, and copy each
other. Every actual word is invented by someone in the world.

How it works (a version of the "naming game" studied by linguists):

* Two people in the same place talk about something that matters right
  there — the river, a herd, a predator, the cold, a technique they know.
* If the speaker has no word for it, they may invent one: a few random
  syllables.
* If the listener already uses the same word, it's reinforced for both.
  If not, the listener may switch to the speaker's word (children almost
  always do).
* Copying isn't perfect: now and then a sound shifts (ka → ga, u → o).
  Inside a group those slips get corrected by everyone else; between
  groups that never meet, they pile up. That's how dialects — and then
  separate languages — form.
* Words nobody uses fade away.

Sharing words has real effects: people who speak alike teach each other
techniques far more easily, and a shared word for "predator" lets people
warn each other.

Names: once a mother has a few words, she names her children, using the
sounds of her own speech.

Identifying "a language" is the observer's job (see `detect`), not the
simulation's: people just talk.
"""
from __future__ import annotations

import numpy as np

from .knowledge import RECIPES

# ── sounds ─────────────────────────────────────────────────────────────
ONSETS = ("", "p", "b", "m", "t", "d", "n", "s", "k", "g", "h", "l", "r", "w", "y")
VOWELS = ("a", "e", "i", "o", "u")
NSYL = len(ONSETS) * len(VOWELS)        # 75 possible syllables, coded 1..75
BASE = NSYL + 1
MAXSYL = 4
WORD_SPACE = BASE ** MAXSYL             # word codes fit in int32
# Sounds that slip into each other when a word is passed on.
ONSET_SHIFTS = [("p", "b"), ("p", "m"), ("t", "d"), ("t", "n"), ("t", "s"), ("k", "g"), ("k", "h"),
                ("l", "r"), ("w", "y"), ("", "h"), ("m", "n"), ("s", "h")]
VOWEL_SHIFTS = [("a", "e"), ("e", "i"), ("o", "u"), ("a", "o")]

# ── things people talk about ───────────────────────────────────────────
MEANINGS = (
    ("people", "us, our people"), ("water", "water"), ("plant", "edible plants"), ("herd", "herd animals"),
    ("predator", "predator, danger"), ("river", "river"), ("rain", "rain"), ("cold", "cold"),
    ("snow", "snow"), ("child", "child"), ("mother", "mother"), ("eat", "eat, food"),
    ("go", "go, travel"), ("stone", "stone"), ("clay", "clay"), ("wood", "wood"),
) + tuple((f"tech:{r['key']}", r["name"].lower()) for r in RECIPES)
M = len(MEANINGS)
MI = {k: i for i, (k, _) in enumerate(MEANINGS)}
N_BASE = 16                                  # meanings before the techniques


def enabled(cfg: dict) -> bool:
    return "language" in cfg


# ── word codes ↔ text ──────────────────────────────────────────────────
def syllable(code: int) -> str:
    c = code - 1
    return ONSETS[c // len(VOWELS)] + VOWELS[c % len(VOWELS)]


def digits(words: np.ndarray) -> np.ndarray:
    """Word codes → syllable codes, shape (..., MAXSYL); 0 = no syllable."""
    w = np.asarray(words, dtype=np.int64)
    out = np.zeros(w.shape + (MAXSYL,), dtype=np.int64)
    for i in range(MAXSYL):
        out[..., i] = w % BASE
        w = w // BASE
    return out


def encode(d: np.ndarray) -> np.ndarray:
    d = np.asarray(d, dtype=np.int64)
    return sum(d[..., i] * BASE ** i for i in range(d.shape[-1])).astype(np.int64)


def word_str(code: int) -> str:
    return "".join(syllable(int(s)) for s in digits(np.array(code)) if s)


def name_str(code: int) -> str | None:
    s = word_str(code)
    return s.capitalize() if s else None


def random_words(rng: np.random.Generator, k: int, pool: np.ndarray | None = None,
                 lengths=(1, 4)) -> np.ndarray:
    """k new words of 1–3 syllables; syllables drawn from `pool` if given (a language's own sounds)."""
    n = rng.integers(lengths[0], lengths[1], k)
    if pool is not None and pool.size:
        syl = pool[rng.integers(0, pool.size, (k, MAXSYL))]
    else:
        syl = rng.integers(1, NSYL + 1, (k, MAXSYL))
    syl[np.arange(MAXSYL)[None, :] >= n[:, None]] = 0
    return encode(syl)


def _shift(code: int, rng: np.random.Generator) -> int:
    """One small sound change in a word."""
    d = digits(np.array(code)).tolist()
    used = [i for i, s in enumerate(d) if s]
    if not used:
        return code
    i = used[int(rng.integers(len(used)))]
    c = d[i] - 1
    on, vo = ONSETS[c // len(VOWELS)], VOWELS[c % len(VOWELS)]
    if rng.random() < 0.55:
        pairs = [p for p in VOWEL_SHIFTS if vo in p]
        a, b = pairs[int(rng.integers(len(pairs)))]
        vo = b if vo == a else a
    else:
        pairs = [p for p in ONSET_SHIFTS if on in p]
        if pairs:
            a, b = pairs[int(rng.integers(len(pairs)))]
            on = b if on == a else a
    d[i] = ONSETS.index(on) * len(VOWELS) + VOWELS.index(vo) + 1
    return int(encode(np.array(d)))


# ── what's worth talking about here, now ───────────────────────────────
def salient(world, age_y: np.ndarray, temp_c: np.ndarray, rain_mm: np.ndarray) -> np.ndarray:
    p, s, st = world.state["people"], world.static, world.state
    pos = p["pos"]
    n = pos.size
    out = np.zeros((n, M), dtype=bool)
    for k in ("people", "water", "plant", "eat", "go"):
        out[:, MI[k]] = True
    out[:, MI["herd"]] = st["grazers"][pos] > 0.02
    out[:, MI["predator"]] = st["predators"][pos] > 0.01
    out[:, MI["river"]] = s["water_c"][pos]
    out[:, MI["rain"]] = rain_mm[pos] > 2.5
    out[:, MI["cold"]] = temp_c[pos] < 5
    out[:, MI["snow"]] = st["snow"][pos] > 1
    recent_mother = (world.tick - p["last_birth"]) < 10 * world.dpy
    out[:, MI["child"]] = (age_y < 15) | recent_mother
    out[:, MI["mother"]] = (age_y < 15) | recent_mother
    if "stone_c" in s:
        for k in ("stone", "clay", "wood"):
            out[:, MI[k]] = s[f"{k}_c"][pos] > 0.2
    known = p["known"].astype(np.int64)
    for r in range(len(RECIPES)):
        out[:, N_BASE + r] = (known >> r) & 1
    return out


# ── one day of talk ────────────────────────────────────────────────────
def daily(world, age_y: np.ndarray, temp_c: np.ndarray, rain_mm: np.ndarray, rng: np.random.Generator) -> list:
    """Conversations between people in the same place.
    Returns new words: [(person id, meaning index, word code)]."""
    p, lc = world.state["people"], world.cfg["language"]
    n = p["id"].size
    if n < 2:
        return []
    from .people import G
    lex, strength = p["lex"], p["lexs"]
    speech = p["genes"][:, G["speech"]]

    order = np.argsort(p["pos"], kind="stable")
    cs = p["pos"][order]
    start = np.searchsorted(cs, cs, side="left")
    size = np.searchsorted(cs, cs, side="right") - start
    talks = (size > 1) & (age_y[order] >= 3) & (rng.random(n) < lc["talk_rate"] * (0.3 + speech[order]))
    L = np.flatnonzero(talks)
    invented = []
    if L.size:
        offs = rng.integers(0, size[L] - 1)
        other = start[L] + offs
        other = np.where(other >= L, other + 1, other)
        sp, hr = order[L], order[other]
        listening = age_y[hr] >= 1                                  # babies don't pick up words yet
        sp, hr, L = sp[listening], hr[listening], L[listening]
        sal = salient(world, age_y, temp_c, rain_mm)[sp]
        m = np.argmax(rng.random(sal.shape) * sal, axis=1)          # one thing to talk about
        ws = lex[sp, m].astype(np.int64)

        # No word yet? Maybe make one up.
        coin = (ws == 0) & (rng.random(L.size) < lc["invent_rate"] * (0.2 + speech[sp]))
        if coin.any():
            new = random_words(rng, int(coin.sum()))
            ws[coin] = new
            lex[sp[coin], m[coin]] = new
            strength[sp[coin], m[coin]] = 0.3
            invented = [(int(p["id"][a]), int(b), int(c)) for a, b, c in zip(sp[coin], m[coin], new)]

        # Now and then someone says it a new way anyway (slang, a new coinage). Most
        # of these die out; a few catch on locally. This keeps vocabularies turning over.
        fresh = (ws > 0) & (rng.random(L.size) < lc.get("innovate_rate", 0.0))
        if fresh.any():
            alt = random_words(rng, int(fresh.sum()), lengths=(1, 4))
            ws[fresh] = alt
            lex[sp[fresh], m[fresh]] = alt
            strength[sp[fresh], m[fresh]] = 0.35

        said = ws > 0
        sp, hr, m, ws = sp[said], hr[said], m[said], ws[said]
        wh = lex[hr, m].astype(np.int64)
        same = wh == ws
        # Understood: both grow more sure of the word.
        strength[sp[same], m[same]] = np.minimum(strength[sp[same], m[same]] + 0.1, 1.0)
        strength[hr[same], m[same]] = np.minimum(strength[hr[same], m[same]] + 0.1, 1.0)
        # Not understood: the listener may switch to the speaker's word. Who you
        # happen to talk to matters more than how sure anyone is, so a new way of
        # saying something can, by chance, spread through a whole community —
        # which is how languages slowly change.
        d = ~same
        child = age_y[hr[d]] < 12
        p_adopt = np.minimum(np.where(wh[d] == 0, 0.9, lc.get("switch_rate", 0.25)) * np.where(child, 2.0, 1.0), 1.0)
        adopt = rng.random(d.sum()) < p_adopt
        ah, am, aw = hr[d][adopt], m[d][adopt], ws[d][adopt]
        # Copying isn't perfect: sometimes a sound slips.
        slip = rng.random(ah.size) < lc["sound_change"] * (1.2 - speech[ah])
        aw = aw.copy()
        for j in np.flatnonzero(slip):
            aw[j] = _shift(int(aw[j]), rng)
        lex[ah, am] = aw
        strength[ah, am] = 0.25
        # Saying a word keeps it fresh in the speaker's mind.
        strength[sp, m] = np.minimum(strength[sp, m] + 0.05, 1.0)

    # Unused words fade, and are forgotten.
    strength *= 0.9993
    gone = (strength < 0.03) & (lex > 0)
    lex[gone] = 0
    return invented


# ── what language is good for ──────────────────────────────────────────
def shared_fraction(p: dict, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """How much of their vocabulary two people share (0..1), for each pair a[i], b[i]."""
    la, lb = p["lex"][a], p["lex"][b]
    both = (la > 0) | (lb > 0)
    same = (la == lb) & (la > 0)
    return same.sum(axis=1) / np.maximum(both.sum(axis=1), 4)


def warned(p: dict) -> np.ndarray:
    """People who share a word for "predator" with someone else in the same place
    can warn each other."""
    w = p["lex"][:, MI["predator"]].astype(np.int64)
    out = np.zeros(w.size, dtype=bool)
    has = np.flatnonzero(w > 0)
    if has.size:
        key = p["pos"][has] * WORD_SPACE + w[has]
        _, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
        out[has] = cnt[inv] >= 2
    return out


def name_children(p: dict, mothers: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """A name for each newborn, made from the sounds of the mother's own words.
    0 (no name) if she has fewer than three words."""
    names = np.zeros(mothers.size, dtype=np.int64)
    for j, mo in enumerate(mothers):
        words = p["lex"][mo][p["lex"][mo] > 0]
        if words.size >= 3:
            pool = digits(words).ravel()
            pool = pool[pool > 0]
            names[j] = random_words(rng, 1, pool, lengths=(2, 4))[0]
    return names


# ── the observer's view: which languages exist? ───────────────────────
MIN_GROUP = 5          # people in a group before we look at how it speaks
MIN_SPEAKERS = 10
MIN_VOCAB = 4          # shared words before we call it a language
SAME_LANGUAGE = 0.5    # groups sharing at least this much vocabulary speak the same language
MIN_OVERLAP = 4        # meanings both must have words for before we compare at all
PERSON_MATCH = 0.4     # an individual speaks a language if this much of their vocabulary matches it


REGION = 10           # cells (~40 km) per side of the squares we survey speech in


def region_labels(world) -> np.ndarray:
    """Split people into squares of the map for the language survey. (Groups that
    are spread along a continuous coast or river can still speak differently at
    either end, so we listen region by region.)"""
    p, s = world.state["people"], world.static
    pos = p["pos"]
    return (s["cy_c"][pos] // REGION) * 100000 + s["cx_c"][pos] // REGION


def dictionaries(lex: np.ndarray, labels: np.ndarray, min_share: float = 0.4) -> tuple:
    """Each group's usual word for each meaning (if at least `min_share` of the group use it)."""
    groups, inv, counts = np.unique(labels, return_inverse=True, return_counts=True)
    Gn = groups.size
    words = np.zeros((Gn, M), dtype=np.int64)
    share = np.zeros((Gn, M))
    for m in range(M):
        w = lex[:, m].astype(np.int64)
        has = w > 0
        if not has.any():
            continue
        key = inv[has].astype(np.int64) * WORD_SPACE + w[has]
        uk, c = np.unique(key, return_counts=True)
        g, word = uk // WORD_SPACE, uk % WORD_SPACE
        order = np.lexsort((-c, g))
        first = np.r_[True, g[order][1:] != g[order][:-1]]
        sel = order[first]
        words[g[sel], m] = word[sel]
        share[g[sel], m] = c[sel] / counts[g[sel]]
    words[share < min_share] = 0
    return groups, inv, counts, words, share


def similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Vocabulary similarity between word lists a (X, M) and b (Y, M) → (X, Y).
    Words count as shared if identical, or the same length differing by one sound."""
    da, db = digits(a)[:, None], digits(b)[None, :]
    both = (a[:, None] > 0) & (b[None, :] > 0)
    diff = (da != db).sum(axis=-1)
    length = (da > 0).sum(axis=-1)
    close = (diff == 0) | ((diff <= 1) & (length >= 2) & ((da > 0) == (db > 0)).all(axis=-1))
    n = both.sum(axis=-1)
    return np.where(n >= MIN_OVERLAP, (close & both).sum(axis=-1) / np.maximum(n, 1), 0.0)


def detect(p: dict, labels: np.ndarray) -> list[dict]:
    """Languages as an outside linguist would see them: groups that understand
    each other, with the words they share."""
    if p["id"].size == 0:
        return []
    groups, inv, counts, words, share = dictionaries(p["lex"], labels)
    big = np.flatnonzero(counts >= MIN_GROUP)
    if big.size == 0:
        return []
    sim = similarity(words[big], words[big])
    clusters = {k: [k] for k in range(big.size)}
    # Average-linkage clustering: keep merging the two most similar clusters while,
    # on average, their regions still understand each other. (Unlike chaining
    # neighbour to neighbour, this lets the far ends of a dialect chain become
    # separate languages once they drift far enough apart.)
    link = sim.astype(float).copy()
    np.fill_diagonal(link, -1)
    alive = list(range(big.size))
    sizes = {k: 1 for k in alive}
    while len(alive) > 1:
        sub = link[np.ix_(alive, alive)]
        i, j = np.unravel_index(np.argmax(sub), sub.shape)
        if sub[i, j] < SAME_LANGUAGE:
            break
        a, b = alive[i], alive[j]
        na, nb = sizes[a], sizes[b]
        link[a, :] = (link[a, :] * na + link[b, :] * nb) / (na + nb)
        link[:, a] = link[a, :]
        link[a, a] = -1
        sizes[a] = na + nb
        clusters[a] += clusters.pop(b)
        alive.remove(b)
    clusters = {k: [big[i] for i in v] for k, v in clusters.items()}
    out = []
    for members in clusters.values():
        rows = np.flatnonzero(np.isin(inv, members))
        # A whole language has dialects, so its word for something is simply the most
        # common one among its speakers (if at least a fifth of them use it).
        _, _, _, w, sh = dictionaries(p["lex"][rows], np.zeros(rows.size, dtype=np.int64), min_share=0.2)
        vocab = int((w[0] > 0).sum())
        if rows.size >= MIN_SPEAKERS and vocab >= MIN_VOCAB:
            out.append({"words": w[0], "share": sh[0], "speakers": int(rows.size), "rows": rows,
                        "regions": [int(groups[g]) for g in members]})
    out.sort(key=lambda d: -d["speakers"])
    return out


def classify(p: dict, languages: list[dict]) -> np.ndarray:
    """Which known language each person speaks (index into `languages`), or -1.
    A person speaks the language whose words theirs mostly match (allowing for
    a slipped sound here and there)."""
    n = p["id"].size
    if not languages or n == 0:
        return np.full(n, -1)
    D = np.array([l["words"] for l in languages], dtype=np.int64)            # (L, M)
    out = np.full(n, -1)
    for start in range(0, n, 4000):                                           # in chunks, to keep memory small
        lex = p["lex"][start:start + 4000].astype(np.int64)
        sim = similarity(lex, D) if lex.size else np.zeros((0, len(languages)))
        best = np.argmax(sim, axis=1)
        out[start:start + 4000] = np.where(sim[np.arange(lex.shape[0]), best] >= PERSON_MATCH, best, -1)
    return out
