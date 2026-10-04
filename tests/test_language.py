"""Tests for Stage 4: language.   Run with:   python -m unittest discover -s tests -t ."""
import unittest

import numpy as np

from aworld import language as lg
from aworld.config import load_config
from aworld.observer import CONFIRM_YEARS, GONE_YEARS, Observer
from aworld.world import World


def cfg(**k):
    return load_config(overrides={"world": {"width": 128, "height": 128, "seed": 4242}, "language": k})


class TestWords(unittest.TestCase):
    def test_word_codes_round_trip(self):
        rng = np.random.default_rng(1)
        words = lg.random_words(rng, 200)
        d = lg.digits(words)
        self.assertTrue((lg.encode(d) == words).all())
        self.assertTrue(all(1 <= len(lg.word_str(w)) <= 9 for w in words))

    def test_sound_change_is_small(self):
        rng = np.random.default_rng(2)
        for w in lg.random_words(rng, 100, lengths=(2, 4)):
            v = lg._shift(int(w), rng)
            diff = (lg.digits(np.array(w)) != lg.digits(np.array(v))).sum()
            self.assertLessEqual(diff, 1)

    def test_similarity(self):
        rng = np.random.default_rng(3)
        a = lg.random_words(rng, lg.M, lengths=(2, 4))[None, :]
        b = a.copy()
        c = lg.random_words(rng, lg.M, lengths=(2, 4))[None, :]
        self.assertEqual(lg.similarity(a, b)[0, 0], 1.0)
        self.assertLess(lg.similarity(a, c)[0, 0], 0.2)


class TestLanguageInWorld(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = World.create(cfg())
        cls.coined, cls.births = [], []
        for _ in range(360 * 10):
            out = cls.w.step()["people"]
            cls.coined += out["words"]
            cls.births += out["births"]

    def test_words_get_invented_and_shared(self):
        self.assertGreater(len(self.coined), 0)
        p = self.w.state["people"]
        # A word used by several people for the same thing = shared, not just invented.
        w = p["lex"][:, lg.MI["water"]]
        vals, counts = np.unique(w[w > 0], return_counts=True)
        self.assertGreater(counts.max() if counts.size else 0, 5)

    def test_hardly_any_homonyms(self):
        """One word, one meaning: a word that would clash with another is avoided."""
        p = self.w.state["people"]
        srt = np.sort(p["lex"], axis=1)
        clashes = ((srt[:, 1:] == srt[:, :-1]) & (srt[:, 1:] > 0)).any(axis=1)
        self.assertLess(clashes.mean(), 0.05)

    def test_people_speak_like_their_community(self):
        """People living together share nearly all their words (conformist learning)."""
        p = self.w.state["people"]
        _, inv, _, usual, _ = lg.dictionaries(p["lex"], p["pos"], min_share=0)
        has = p["lex"] > 0
        agree = ((p["lex"] == usual[inv]) & has).sum() / has.sum()
        self.assertGreater(agree, 0.85)

    def test_newborns_have_no_words(self):
        p = self.w.state["people"]
        babies = (self.w.tick - p["birth"]) < 30
        self.assertTrue((p["lex"][babies] == 0).all())

    def test_children_get_names_from_their_mothers_sounds(self):
        named = [b for b in self.births if b[7]]
        self.assertGreater(len(named), 0)

    def test_a_language_is_detected(self):
        import aworld.observer as ob
        old, ob.CANDIDATE_MIN_SPEAKERS = ob.CANDIDATE_MIN_SPEAKERS, 10     # this test world is small
        self.addCleanup(setattr, ob, "CANDIDATE_MIN_SPEAKERS", old)
        obs = Observer()
        events = []
        for _ in range(CONFIRM_YEARS):
            events += obs._yearly_language(self.w)
        self.assertGreaterEqual(len(obs.living_languages()), 1)
        self.assertIn("FIRST_LANGUAGE", [e["type"] for e in events])

    def test_determinism_with_language(self):
        a, b = World.create(cfg()), World.create(cfg())
        a.run(400)
        b.run(400)
        self.assertEqual(a.state_hash(), b.state_hash())


class TestDrift(unittest.TestCase):
    def test_an_isolated_group_slowly_changes_its_words(self):
        """No one is told to change their speech, but small slips and new coinages
        appear and are copied by chance."""
        w = World.create(cfg())
        p = w.state["people"]
        n = p["id"].size
        rng = np.random.default_rng(7)
        start = lg.random_words(rng, lg.M, lengths=(2, 4))
        p["lex"][:] = start
        p["lexs"][:] = 1.0
        p["pos"][:] = p["pos"][0]
        temp = np.full(w.static["cells"].size, 15.0)
        rain = np.zeros_like(temp)
        changed = 0
        for year in range(120):
            for _ in range(360):
                lg.daily(w, (w.tick - p["birth"]) / 360, temp, rain, rng)
                w.state["tick"] += 1
            changed += int(((p["lex"] != start) & (p["lex"] > 0)).sum())
            newborn = rng.random(n) < 0.04                     # the generations turn over
            p["lex"][newborn] = 0
            p["lexs"][newborn] = 0
            p["birth"][newborn] = w.tick
        # New ways of saying things keep appearing and living on in people's speech.
        # (Whether one takes over a whole community is down to chance — with
        # conformist learning, in a group this small, that is rare within a century.)
        self.assertGreater(changed, 0)


class TestDialectsAndAccents(unittest.TestCase):
    def test_accent_changes_sounds_regularly(self):
        rng = np.random.default_rng(9)
        words = lg.random_words(rng, 200, lengths=(2, 4))
        k_to_g = next(i for i, r in enumerate(lg.ACCENT_RULES) if r == ("onset", "k", "g"))
        shifted = lg.apply_accent(words, np.full(words.size, 1 << k_to_g))
        for a, b in zip(words, shifted):
            sa, sb = lg.word_str(a), lg.word_str(b)
            self.assertEqual(sa.replace("k", "g"), sb)       # every k, and only k, becomes g

    def test_small_differences_are_dialects_not_languages(self):
        w = World.create(cfg())
        p = w.state["people"]
        n = p["id"].size
        rng = np.random.default_rng(11)
        a = lg.random_words(rng, lg.M, lengths=(2, 4))
        near = a.copy()
        near[:32] = lg.random_words(rng, 32, lengths=(2, 4))  # about half the words still shared
        half = n // 2
        p["lex"][:half], p["lex"][half:] = a, near
        p["pos"][:half], p["pos"][half:] = 0, w.static["cells"].size - 1
        found = lg.detect(p, lg.region_labels(w))
        self.assertEqual(len(found), 1)                       # one language…
        self.assertEqual(len(found[0]["dialects"]), 2)         # …with two dialects

    def test_language_keeps_its_name_as_it_changes(self):
        w = World.create(cfg())
        p = w.state["people"]
        rng = np.random.default_rng(12)
        p["lex"][:] = lg.random_words(rng, lg.M, lengths=(2, 4))
        obs = Observer()
        for _ in range(CONFIRM_YEARS):
            obs._yearly_language(w)
        name = obs.living_languages()[0]["name"]
        for step in range(6):                                  # words change, a few at a time
            p["lex"][:, step * 4:(step + 1) * 4] = lg.random_words(rng, 4, lengths=(2, 4))
            for _ in range(3):
                obs._yearly_language(w)
        self.assertEqual([l["name"] for l in obs.living_languages()], [name])


class TestLanguageSplit(unittest.TestCase):
    def test_isolated_groups_become_separate_languages(self):
        """Two groups with unrelated vocabularies are two languages, and the census
        reports a split when one group's speech has drifted from its parent."""
        w = World.create(cfg())
        p = w.state["people"]
        n = p["id"].size
        rng = np.random.default_rng(5)
        a = lg.random_words(rng, lg.M, lengths=(2, 4))
        b = lg.random_words(rng, lg.M, lengths=(2, 4))
        half = n // 2
        p["lex"][:half] = a
        p["lex"][half:] = b
        cells = w.static["cells"].size
        p["pos"][:half] = 0                                  # far apart on the map
        p["pos"][half:] = cells - 1
        p["lexs"][:] = 1.0
        def census(obs, times):
            ev = []
            for _ in range(times):
                ev += obs._yearly_language(w)
            return [e["type"] for e in ev]

        obs = Observer()
        census(obs, CONFIRM_YEARS)
        self.assertEqual(len(obs.living_languages()), 2)
        # One language; then half its speakers drift away.
        obs2 = Observer()
        p["lex"][half:] = a
        census(obs2, CONFIRM_YEARS)
        self.assertEqual(len(obs2.living_languages()), 1)
        drifted = a.copy()
        q = int(lg.M * 0.75)
        drifted[:q] = b[:q]                                  # three quarters of its words have changed
        p["lex"][half:] = drifted
        self.assertNotIn("LANGUAGE_SPLIT", census(obs2, 1))  # not announced on a single census…
        self.assertIn("LANGUAGE_SPLIT", census(obs2, CONFIRM_YEARS))   # …only once it lasts
        # And when nobody speaks it any more, it dies.
        p["lex"][half:] = a
        self.assertIn("LANGUAGE_DIED", census(obs2, GONE_YEARS + 1))


if __name__ == "__main__":
    unittest.main()
