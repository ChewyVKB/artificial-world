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

# Accents: regular sound changes. A person with the rule "k→g" says (and so
# passes on) every k as g. Accents are learned from the people around you, so a
# whole region can come to share one — which is how related languages end up
# sounding different from each other.
ACCENT_RULES = ([("onset", a, b) for a, b in ONSET_SHIFTS] + [("onset", b, a) for a, b in ONSET_SHIFTS]
                + [("vowel", a, b) for a, b in VOWEL_SHIFTS] + [("vowel", b, a) for a, b in VOWEL_SHIFTS])
assert len(ACCENT_RULES) <= 32

# ── things people talk about ───────────────────────────────────────────
# The list only ever grows (new entries go at the end), so words people already
# have keep their meaning when the world learns about something new.
MEANINGS = (
    ("people", "us, our people"), ("water", "water"), ("plant", "edible plants"), ("herd", "herd animals"),
    ("predator", "predator, danger"), ("river", "river"), ("rain", "rain"), ("cold", "cold"),
    ("snow", "snow"), ("child", "child"), ("mother", "mother"), ("eat", "eat, food"),
    ("go", "go, travel"), ("stone", "stone"), ("clay", "clay"), ("wood", "wood"),
) + tuple((f"tech:{r['key']}", r["name"].lower()) for r in RECIPES) + (
    ("sun", "sun"), ("moon", "moon"), ("night", "night"), ("day", "day"), ("sky", "sky"), ("star", "star"),
    ("wind", "wind"), ("ground", "earth, ground"), ("tree", "tree"), ("fish", "fish"), ("bird", "bird"),
    ("mountain", "mountain"), ("sea", "sea"), ("lake", "lake"), ("hot", "hot"), ("sick", "sick"),
    ("hungry", "hungry"), ("thirsty", "thirsty"), ("old", "old"), ("dying", "dying"), ("father", "father"),
    ("mate", "mate, partner"), ("stranger", "stranger"), ("i", "I, me"), ("you", "you"), ("give", "give"),
    ("good", "good"), ("bad", "bad"), ("big", "big"), ("small", "small"), ("one", "one"), ("two", "two"),
    ("many", "many"), ("sleep", "sleep"),
)
M = len(MEANINGS)
MI = {k: i for i, (k, _) in enumerate(MEANINGS)}
N_BASE = 16                                  # meanings before the techniques
ALWAYS = ("people", "water", "plant", "eat", "go", "sun", "moon", "night", "day", "sky", "star", "wind",
          "ground", "bird", "i", "you", "give", "good", "bad", "big", "small", "one", "two", "many", "sleep")


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


WORD_LENGTHS = (0.12, 0.5, 0.38)     # how often a new word has 1, 2 or 3 syllables (like early languages: mostly 2)


def random_words(rng: np.random.Generator, k: int, pool: np.ndarray | None = None,
                 lengths=None) -> np.ndarray:
    """k new words; syllables drawn from `pool` if given (a language's own sounds).
    `lengths` = (min, max+1) syllables, uniformly; by default mostly two-syllable words."""
    if lengths is None:
        n = rng.choice(np.arange(1, 4), k, p=WORD_LENGTHS)
    else:
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


def apply_accent(words: np.ndarray, accents: np.ndarray) -> np.ndarray:
    """Pronounce each word with the matching person's accent (their sound rules)."""
    words = np.asarray(words, dtype=np.int64)
    if words.size == 0 or not np.any(accents):
        return words
    d = digits(words)
    has = d > 0
    onset, vowel = (d - 1) // len(VOWELS), (d - 1) % len(VOWELS)
    acc = np.asarray(accents, dtype=np.int64)[:, None]
    for r, (kind, a, b) in enumerate(ACCENT_RULES):
        on = ((acc >> r) & 1).astype(bool) & has
        if not on.any():
            continue
        if kind == "onset":
            hit = on & (onset == ONSETS.index(a))
            onset = np.where(hit, ONSETS.index(b), onset)
        else:
            hit = on & (vowel == VOWELS.index(a))
            vowel = np.where(hit, VOWELS.index(b), vowel)
    d = np.where(has, onset * len(VOWELS) + vowel + 1, 0)
    return encode(d)


def accent_str(accent: int) -> list[str]:
    return [f"{a or '∅'}→{b or '∅'}" for r, (_, a, b) in enumerate(ACCENT_RULES) if int(accent) >> r & 1]


# ── what's worth talking about here, now ───────────────────────────────
def salient(world, age_y: np.ndarray, temp_c: np.ndarray, rain_mm: np.ndarray) -> np.ndarray:
    p, s, st = world.state["people"], world.static, world.state
    pos = p["pos"]
    n = pos.size
    out = np.zeros((n, M), dtype=bool)
    for k in ALWAYS:
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
    if "coast_c" in s:
        out[:, MI["sea"]] = s["coast_c"][pos]
        out[:, MI["mountain"]] = s["mount_c"][pos]
        out[:, MI["lake"]] = s["lake_c"][pos]
        out[:, MI["fish"]] = s["water_c"][pos] | s["coast_c"][pos]
    if "wood_c" in s:
        out[:, MI["tree"]] = s["wood_c"][pos] > 0.2
    out[:, MI["hot"]] = temp_c[pos] > 28
    out[:, MI["sick"]] = p["health"] < 0.6
    out[:, MI["dying"]] = p["health"] < 0.3
    out[:, MI["hungry"]] = p["energy"] < 0.3
    out[:, MI["thirsty"]] = p["hydration"] < 0.5
    out[:, MI["old"]] = age_y > 45
    out[:, MI["mate"]] = p["partner"] >= 0
    out[:, MI["father"]] = (age_y < 15) | ((p["sex"] == 1) & (p["partner"] >= 0))
    # Someone around who calls their people by a different name: a stranger.
    us = p["lex"][:, MI["people"]].astype(np.int64)
    named = us > 0
    if named.any():
        pairs = np.unique(np.stack([pos[named], us[named]]), axis=1)
        kinds = np.bincount(pairs[0], minlength=s["cells"].size)
        out[:, MI["stranger"]] = kinds[pos] > 1
    return out


# ── one day of talk ────────────────────────────────────────────────────
def daily(world, age_y: np.ndarray, temp_c: np.ndarray, rain_mm: np.ndarray, rng: np.random.Generator) -> list:
    """A day's talk: several rounds of conversation between people in the same place.
    Returns new words: [(person id, meaning index, word code)]."""
    out = []
    for _ in range(int(world.cfg["language"].get("rounds_per_day", 1))):
        out += _talk(world, age_y, temp_c, rain_mm, rng)
    p = world.state["people"]
    if world.tick % 30 == 0:
        drop_homonyms(p)
    # Unused words fade, and are forgotten.
    p["lexs"] *= 0.9993
    gone = (p["lexs"] < 0.03) & (p["lex"] > 0)
    p["lex"][gone] = 0
    return out


def _talk(world, age_y, temp_c, rain_mm, rng) -> list:
    """One round of conversations."""
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
        # Accents rub off on people (children most), and now and then someone
        # starts saying a sound a new way.
        if "accent" in p:
            acc = p["accent"]
            catch = rng.random(L.size) < lc.get("accent_rate", 0.01) * np.where(age_y[hr] < 15, 5.0, 1.0)
            acc[hr[catch]] = acc[sp[catch]]
            new = np.flatnonzero(rng.random(L.size) < lc.get("accent_innovate", 0.0002))
            for j in new:
                acc[sp[j]] ^= np.uint32(1 << int(rng.integers(len(ACCENT_RULES))))
        sal = salient(world, age_y, temp_c, rain_mm)[sp]
        m = np.argmax(rng.random(sal.shape) * sal, axis=1)          # one thing to talk about
        ws = lex[sp, m].astype(np.int64)

        # No word yet? Maybe make one up.
        coin = (ws == 0) & (rng.random(L.size) < lc["invent_rate"] * (0.2 + speech[sp]))
        if coin.any():
            who = sp[coin]
            new = random_words(rng, int(coin.sum()))
            if "accent" in p:
                new = apply_accent(new, p["accent"][who])
            # Nobody coins a word they already use for something else.
            for _ in range(6):
                clash = (lex[who] == new[:, None]).any(axis=1)
                if not clash.any():
                    break
                fresh_words = random_words(rng, int(clash.sum()))
                if "accent" in p:
                    fresh_words = apply_accent(fresh_words, p["accent"][who[clash]])
                new[clash] = fresh_words
            ws[coin] = new
            lex[sp[coin], m[coin]] = new
            strength[sp[coin], m[coin]] = 0.3
            invented = [(int(p["id"][a]), int(b), int(c)) for a, b, c in zip(sp[coin], m[coin], new)]

        # Now and then someone says it a new way anyway (slang, a new coinage). Most
        # of these die out; a few catch on locally. This keeps vocabularies turning over.
        fresh = (ws > 0) & (rng.random(L.size) < lc.get("innovate_rate", 0.0))
        if fresh.any():
            alt = random_words(rng, int(fresh.sum()))
            ws[fresh] = alt
            lex[sp[fresh], m[fresh]] = alt
            strength[sp[fresh], m[fresh]] = 0.35

        said = ws > 0
        sp, hr, m, ws, L = sp[said], hr[said], m[said], ws[said], L[said]
        wh = lex[hr, m].astype(np.int64)
        same = wh == ws
        # Understood: both grow more sure of the word.
        strength[sp[same], m[same]] = np.minimum(strength[sp[same], m[same]] + 0.1, 1.0)
        strength[hr[same], m[same]] = np.minimum(strength[hr[same], m[same]] + 0.1, 1.0)
        # Not understood: the listener may switch to the speaker's word. Who you
        # happen to talk to matters more than how sure anyone is, so a new way of
        # saying something can, by chance, spread through a whole community —
        # which is how languages slowly change.
        #
        # People also go with the majority (conformist learning): a listener checks
        # the word against what a few others around them say. A word most people
        # nearby use is taken up readily; an odd one out rarely is.
        d = ~same
        child = age_y[hr[d]] < 12
        base = np.where(wh[d] == 0, 0.9, lc.get("switch_rate", 0.25) * 2) * np.where(child, 2.0, 1.0)
        k = int(lc.get("conformity_sample", 4))
        Ld = L[d]
        others = order[start[Ld][None, :] + rng.integers(0, np.maximum(size[Ld], 1)[None, :], (k, Ld.size))]
        heard = lex[others, m[d][None, :]].astype(np.int64)
        n_s = 1 + (heard == ws[d][None, :]).sum(axis=0)           # the speaker + others saying it their way
        n_h = 1 + (heard == wh[d][None, :]).sum(axis=0)           # the listener + others saying it theirs
        a = float(lc.get("conformity", 2.0))
        majority = n_s ** a / (n_s ** a + n_h ** a)
        p_adopt = np.minimum(np.where(wh[d] == 0, base, base * majority), 1.0)
        adopt = rng.random(d.sum()) < p_adopt
        ah, am, aw = hr[d][adopt], m[d][adopt], ws[d][adopt]
        # Copying isn't perfect: sometimes a sound slips.
        slip = rng.random(ah.size) < lc["sound_change"] * (1.2 - speech[ah])
        aw = aw.copy()
        for j in np.flatnonzero(slip):
            aw[j] = _shift(int(aw[j]), rng)
        if "accent" in p:                       # the listener says it their own way
            aw = apply_accent(aw, p["accent"][ah])
        # A word that would sound the same as one the listener already uses for
        # something else would only confuse: such words aren't taken up.
        clash = (lex[ah] == aw[:, None]).any(axis=1) & (lex[ah, am] != aw)
        ah, am, aw = ah[~clash], am[~clash], aw[~clash]
        lex[ah, am] = aw
        strength[ah, am] = 0.25
        # Saying a word keeps it fresh in the speaker's mind.
        strength[sp, m] = np.minimum(strength[sp, m] + 0.05, 1.0)

    return invented


def drop_homonyms(p: dict) -> int:
    """If someone uses one word for two different things, the meaning they're less
    sure of loses it (they'll pick up or coin another word for it). Returns how
    many words were dropped."""
    lex, strength = p["lex"], p["lexs"]
    srt = np.sort(lex, axis=1)
    rows = np.flatnonzero(((srt[:, 1:] == srt[:, :-1]) & (srt[:, 1:] > 0)).any(axis=1))
    dropped = 0
    for r in rows:
        words, inv, counts = np.unique(lex[r], return_inverse=True, return_counts=True)
        for wi in np.flatnonzero((counts > 1) & (words > 0)):
            ms = np.flatnonzero(inv == wi)
            keep = ms[np.argmax(strength[r, ms])]
            for m_ in ms:
                if m_ != keep:
                    lex[r, m_] = 0
                    strength[r, m_] = 0
                    dropped += 1
    return dropped


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
# Linguists' rule of thumb: people who share most of their basic words speak
# dialects of one language; people who share only a minority can't understand
# each other and speak different languages (which may still be related).
MIN_GROUP = 5          # people in a region before we listen to how it speaks
MIN_SPEAKERS = 10
MIN_VOCAB = 4          # shared words before we call it a language
DIALECT = 0.55         # regions sharing at least this much speak the same dialect
SAME_LANGUAGE = 0.3    # ...at least this much: the same language (mutually intelligible)
RELATED = 0.15         # ...at least this much: related languages (a common ancestor shows)
MIN_OVERLAP = 6        # meanings both must have words for before we compare at all
PERSON_MATCH = 0.35    # an individual speaks a language if this much of their vocabulary matches it
REGION = 10            # cells (~40 km) per side of the squares we survey speech in


def region_labels(world) -> np.ndarray:
    """Split people into squares of the map for the language survey. (Groups that
    are spread along a continuous coast or river can still speak differently at
    either end, so we listen region by region.)"""
    p, s = world.state["people"], world.static
    pos = p["pos"]
    return (s["cy_c"][pos] // REGION) * 100000 + s["cx_c"][pos] // REGION


def region_centre(label: int) -> tuple[float, float]:
    """(y, x) in cells of a region's centre."""
    return ((label // 100000) + 0.5) * REGION, ((label % 100000) + 0.5) * REGION


def dictionaries(lex: np.ndarray, labels: np.ndarray, min_share: float = 0.4) -> tuple:
    """Each group's usual word for each meaning (if at least `min_share` of the group use it)."""
    groups, inv, counts = np.unique(labels, return_inverse=True, return_counts=True)
    Gn = groups.size
    m_count = lex.shape[1]
    words = np.zeros((Gn, m_count), dtype=np.int64)
    share = np.zeros((Gn, m_count))
    for m in range(m_count):
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
    a, b = np.asarray(a, dtype=np.int64), np.asarray(b, dtype=np.int64)
    out = np.zeros((a.shape[0], b.shape[0]))
    for i0 in range(0, a.shape[0], 256):                 # in blocks, to keep memory small
        aa = a[i0:i0 + 256]
        da, db = digits(aa)[:, None], digits(b)[None, :]
        both = (aa[:, None] > 0) & (b[None, :] > 0)
        diff = (da != db).sum(axis=-1)
        length = (da > 0).sum(axis=-1)
        close = (diff == 0) | ((diff <= 1) & (length >= 2) & ((da > 0) == (db > 0)).all(axis=-1))
        n = both.sum(axis=-1)
        out[i0:i0 + 256] = np.where(n >= MIN_OVERLAP, (close & both).sum(axis=-1) / np.maximum(n, 1), 0.0)
    return out


def region_similarity(lex: np.ndarray, inv: np.ndarray, regions: np.ndarray) -> np.ndarray:
    """How well people from two regions understand each other: for every meaning,
    how often a random speaker from one region and one from the other use the
    same word — scaled so that a region compared with itself scores 1. (This copes
    with mixed regions, where newcomers and locals speak differently.)"""
    keep = np.isin(inv, regions)
    rows = np.flatnonzero(keep)
    r_index = np.full(inv.max() + 1, -1)
    r_index[regions] = np.arange(regions.size)
    r = r_index[inv[rows]]
    sizes = np.bincount(r, minlength=regions.size).astype(float)
    sub = lex[rows].astype(np.int64)
    m_idx = np.broadcast_to(np.arange(sub.shape[1]), sub.shape)
    has = sub > 0
    key = m_idx[has] * WORD_SPACE + sub[has]
    rr = np.broadcast_to(r[:, None], sub.shape)[has]
    uk, kinv = np.unique(key, return_inverse=True)
    F = np.zeros((regions.size, uk.size))
    np.add.at(F, (rr, kinv), 1.0)
    F /= np.maximum(sizes, 1)[:, None]
    S = F @ F.T
    d = np.sqrt(np.maximum(np.diag(S), 1e-12))
    return S / d[:, None] / d[None, :]


def _agglomerate(sim: np.ndarray, weights: np.ndarray, cuts: tuple) -> list[list[list[int]]]:
    """Average-linkage clustering. Returns the clusters (lists of item indices) at
    each threshold in `cuts` (descending)."""
    n = sim.shape[0]
    link = sim.astype(float).copy()
    np.fill_diagonal(link, -1)
    clusters = {k: [k] for k in range(n)}
    size = {k: float(weights[k]) for k in range(n)}
    alive = list(range(n))
    out = []
    for cut in cuts:
        while len(alive) > 1:
            sub = link[np.ix_(alive, alive)]
            i, j = np.unravel_index(np.argmax(sub), sub.shape)
            if sub[i, j] < cut:
                break
            a, b = alive[i], alive[j]
            na, nb = size[a], size[b]
            link[a, :] = (link[a, :] * na + link[b, :] * nb) / (na + nb)
            link[:, a] = link[a, :]
            link[a, a] = -1
            size[a] = na + nb
            clusters[a] += clusters.pop(b)
            alive.remove(b)
        out.append([list(v) for v in clusters.values()])
    return out


def detect(p: dict, labels: np.ndarray, static: dict | None = None) -> list[dict]:
    """Languages as an outside linguist would see them, each with its dialects.

    Regions whose speech is nearly the same form a dialect; dialects that can
    still understand each other form a language."""
    if p["id"].size == 0:
        return []
    groups, inv, counts, words, share = dictionaries(p["lex"], labels)
    big = np.flatnonzero(counts >= MIN_GROUP)
    if big.size == 0:
        return []
    sim = region_similarity(p["lex"], inv, big)
    dialect_cut, language_cut = _agglomerate(sim, counts[big], (DIALECT, SAME_LANGUAGE))
    dialect_of = {}
    for d, members in enumerate(dialect_cut):
        for k in members:
            dialect_of[k] = d
    out = []
    for members in language_cut:
        regions = big[members]
        rows = np.flatnonzero(np.isin(inv, regions))
        if rows.size < MIN_SPEAKERS:
            continue
        # A whole language has dialects, so its word for something is the most
        # common one among its speakers (if at least a fifth of them use it).
        _, _, _, w, sh = dictionaries(p["lex"][rows], np.zeros(rows.size, dtype=np.int64), min_share=0.2)
        if int((w[0] > 0).sum()) < MIN_VOCAB:
            continue
        dialects = []
        for d in sorted({dialect_of[k] for k in members}):
            d_regions = big[[k for k in members if dialect_of[k] == d]]
            d_rows = np.flatnonzero(np.isin(inv, d_regions))
            _, _, _, dw, _ = dictionaries(p["lex"][d_rows], np.zeros(d_rows.size, dtype=np.int64), min_share=0.3)
            cy = np.mean([region_centre(int(groups[r]))[0] for r in d_regions])
            cx = np.mean([region_centre(int(groups[r]))[1] for r in d_regions])
            feats = {}
            if static is not None and "coast_c" in static:
                pos = p["pos"][d_rows]
                feats = {"coast": float(static["coast_c"][pos].mean()), "mountain": float(static["mount_c"][pos].mean()),
                         "lake": float(static["lake_c"][pos].mean()), "river": float(static["water_c"][pos].mean())}
            dialects.append({"regions": [int(groups[r]) for r in d_regions], "speakers": int(d_rows.size),
                             "words": dw[0], "centre": (float(cy), float(cx)), "features": feats})
        # What a visitor would hear most: the biggest dialect's words, where the
        # language as a whole hasn't settled on one.
        main = max(dialects, key=lambda d: d["speakers"]) if dialects else None
        display = np.where(w[0] > 0, w[0], main["words"] if main is not None else 0)
        out.append({"words": w[0], "display": display, "share": sh[0], "speakers": int(rows.size), "rows": rows,
                    "regions": [int(groups[g]) for g in regions], "dialects": dialects,
                    "region_speakers": {int(groups[g]): int(counts[g]) for g in regions}})
    out.sort(key=lambda d: -d["speakers"])
    return out


def classify(p: dict, languages: list[dict]) -> np.ndarray:
    """Which known language each person speaks (index into `languages`), or -1.
    A person speaks the language whose words theirs mostly match (allowing for
    a slipped sound here and there)."""
    n = p["id"].size
    if not languages or n == 0:
        return np.full(n, -1)
    D = np.array([list(l["words"]) + [0] * (M - len(l["words"])) for l in languages], dtype=np.int64)  # (L, M)
    out = np.full(n, -1)
    for start in range(0, n, 4000):
        lex = p["lex"][start:start + 4000].astype(np.int64)
        sim = similarity(lex, D)
        best = np.argmax(sim, axis=1)
        out[start:start + 4000] = np.where(sim[np.arange(lex.shape[0]), best] >= PERSON_MATCH, best, -1)
    return out


def sound_name(words: np.ndarray, taken: set, rng_seed: int) -> str:
    """A name built from a language's own most typical sounds (used only when it
    has no settled word for "us")."""
    d = digits(np.asarray(words, dtype=np.int64)[np.asarray(words) > 0]).ravel()
    d = d[d > 0]
    if d.size == 0:
        return "Unnamed"
    syl, cnt = np.unique(d, return_counts=True)
    common = syl[np.argsort(-cnt, kind="stable")][:6]
    rng = np.random.default_rng(rng_seed)
    for _ in range(50):
        k = int(rng.integers(2, 4))
        name = "".join(syllable(int(x)) for x in rng.choice(common, k)).capitalize()
        if name not in taken:
            return name
    return f"{name} {len(taken) + 1}"
