"""Tests for close-up mode.   Run with:   python -m unittest discover -s tests -t ."""
import json
import unittest

import numpy as np

from aworld import closeup
from aworld.config import load_config
from aworld.world import World


def cfg():
    return load_config(overrides={"world": {"width": 128, "height": 128, "seed": 4242}})


def where_people_are(w):
    p = w.state["people"]
    full = int(w.static["cells"][p["pos"][0]])
    return full % w.shape[1], full // w.shape[1]


class TestCloseUp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = World.create(cfg())
        cls.w.run(360 * 3)
        cls.x, cls.y = where_people_are(cls.w)
        cls.sc = closeup.scene(cls.w, cls.x, cls.y)

    def test_scene_is_plain_json(self):
        json.dumps(self.sc)                       # would fail on numpy types

    def test_people_are_shown_with_a_whole_day(self):
        self.assertGreater(len(self.sc["people"]), 0)
        for p in self.sc["people"]:
            tl = p["timeline"]
            self.assertEqual(tl[0]["t0"], 0)
            self.assertAlmostEqual(tl[-1]["t1"], 24, places=1)
            for a, b in zip(tl, tl[1:]):          # no gaps, no overlaps
                self.assertAlmostEqual(a["t1"], b["t0"], places=1)
            for s in tl:
                self.assertIn(s["act"], closeup.ACTIVITIES)

    def test_everyone_stays_inside_the_view(self):
        size = self.sc["span"] * self.sc["cell_m"]
        for p in self.sc["people"]:
            for s in p["timeline"]:
                for x, y in (s["from"], s["to"]):
                    self.assertTrue(0 <= x <= size and 0 <= y <= size, (p["id"], s))

    def test_same_day_looks_the_same_every_time(self):
        again = closeup.scene(self.w, self.x, self.y)
        self.assertEqual(json.dumps(self.sc, sort_keys=True), json.dumps(again, sort_keys=True))

    def test_watching_does_not_change_history(self):
        """Close-up mode only shows what happened: two identical worlds stay identical
        even if one of them is watched up close every day."""
        a, b = World.create(cfg()), World.create(cfg())
        a.run(200)
        b.run(200)
        for _ in range(30):
            a.step()
            b.step()
            closeup.scene(a, *where_people_are(a))
        self.assertEqual(a.state_hash(), b.state_hash())

    def test_a_place_with_no_people(self):
        sc = closeup.scene(self.w, 2, 2)           # a corner, and almost surely empty
        json.dumps(sc)
        self.assertIn("cells", sc)
        self.assertTrue(np.isfinite(np.array(sc["cells"]["elevation"], dtype=float)).all())


if __name__ == "__main__":
    unittest.main()
