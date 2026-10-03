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
        """No one is told to change their speech, but small slips and new coinages,
        copied by chance, change a group's vocabulary over the generations."""
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
        for year in range(120):
            for _ in range(360):
                lg.daily(w, (w.tick - p["birth"]) / 360, temp, rain, rng)
                w.state["tick"] += 1
            newborn = rng.random(n) < 0.04                     # the generations turn over
            p["lex"][newborn] = 0
            p["lexs"][newborn] = 0
            p["birth"][newborn] = w.tick
        _, _, _, now, _ = lg.dictionaries(p["lex"], np.zeros(n, dtype=np.int64))
        changed = int(((now[0] != start) & (now[0] > 0)).sum())
        self.assertGreater(changed, 0)


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
        drifted[:14] = b[:14]                                # a bit over half its words have changed
        p["lex"][half:] = drifted
        self.assertNotIn("LANGUAGE_SPLIT", census(obs2, 1))  # not announced on a single census…
        self.assertIn("LANGUAGE_SPLIT", census(obs2, CONFIRM_YEARS))   # …only once it lasts
        # And when nobody speaks it any more, it dies.
        p["lex"][half:] = a
        self.assertIn("LANGUAGE_DIED", census(obs2, GONE_YEARS + 1))


if __name__ == "__main__":
    unittest.main()
