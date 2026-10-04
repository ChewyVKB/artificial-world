"""Tests for minds: memories, feelings, goals.   Run with:   python -m unittest discover -s tests -t ."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from aworld import minds
from aworld import people as ppl
from aworld.config import add_new_sections, load_config
from aworld.world import World


def cfg(**minds_overrides):
    c = load_config(overrides={"world": {"width": 128, "height": 128, "seed": 4242}})
    c["minds"].update(minds_overrides)
    return c


class TestMemory(unittest.TestCase):
    def setUp(self):
        self.w = World.create(cfg())
        self.p = self.w.state["people"]

    def test_a_place_is_remembered_once(self):
        for _ in range(3):
            minds.remember(self.p, [0], "plenty", 100, 360, cell=7, power=0.5)
        self.assertEqual(int((self.p["mem_kind"][0] == minds.MK["plenty"]).sum()), 1)

    def test_when_full_the_faintest_is_forgotten(self):
        p = self.p
        for k in range(minds.K):
            minds.remember(p, [0], "plenty", 0, 360, cell=k, power=0.2 + 0.05 * k)
        minds.remember(p, [0], "lost_partner", 0, 360, who=99, power=0.9)
        self.assertIn(minds.MK["lost_partner"], p["mem_kind"][0])
        self.assertNotIn(0, p["mem_cell"][0][p["mem_kind"][0] == minds.MK["plenty"]])   # the weakest (cell 0) went
        # A memory fainter than everything already remembered is not kept.
        minds.remember(p, [0], "hunger", 0, 360, cell=500, power=0.01)
        self.assertNotIn(minds.MK["hunger"], p["mem_kind"][0])

    def test_memories_fade(self):
        minds.remember(self.p, [0], "plenty", 0, 360, cell=3, power=0.6)
        now = minds.strength(self.p, [0], 0, 360).max()
        later = minds.strength(self.p, [0], 360 * 6, 360).max()     # two half-lives on
        self.assertAlmostEqual(later, now / 4, places=3)

    def test_several_memories_for_one_person_at_once(self):
        minds.remember(self.p, [0, 0, 0], "plenty", 10, 360, cell=[1, 2, 3], power=0.5)
        self.assertEqual(int((self.p["mem_kind"][0] == minds.MK["plenty"]).sum()), 3)


class TestFeelings(unittest.TestCase):
    def test_losing_a_partner_brings_grief_and_a_memory(self):
        w = World.create(cfg())
        p = w.state["people"]
        a, b = 0, 1
        p["partner"][a], p["partner"][b] = p["id"][b], p["id"][a]
        dead_id = int(p["id"][b])
        deaths = [(dead_id, 3, 30.0, int(p["pos"][b]))]
        parents = (p["mother"][[b]], p["father"][[b]])
        ppl._remove(p, np.array([b]))
        minds.events(w, p["id"].copy(), p["partner"].copy(), [], deaths, parents, [])
        self.assertGreater(p["feel"][a, minds.F["grief"]], 0.8)
        self.assertIn(minds.MK["lost_partner"], p["mem_kind"][a])
        self.assertIn(dead_id, p["mem_who"][a])
        # Everyone in that place saw the predator: they are afraid of it.
        here = p["pos"] == deaths[0][3]
        self.assertTrue((p["feel"][here & ((w.tick - p["birth"]) / w.dpy >= 4), minds.F["fear"]] >= 0.6).all())

    def test_a_birth_brings_joy(self):
        w = World.create(cfg())
        p = w.state["people"]
        before = float(p["feel"][0, minds.F["joy"]])
        minds.events(w, p["id"].copy(), p["partner"].copy(), [(9999, int(p["id"][0]), -1)], [], ([], []), [])
        self.assertGreater(p["feel"][0, minds.F["joy"]], before + 0.3)
        self.assertIn(minds.MK["child_born"], p["mem_kind"][0])


class TestMindsInWorld(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = World.create(cfg())
        cls.w.run(360 * 8)
        cls.p = cls.w.state["people"]

    def test_people_survive_with_minds(self):
        self.assertGreater(self.p["id"].size, 30)

    def test_feelings_stay_in_range(self):
        self.assertTrue(((self.p["feel"] >= 0) & (self.p["feel"] <= 1)).all())

    def test_lives_leave_memories(self):
        kinds = set(np.unique(self.p["mem_kind"]).tolist())
        for k in ("child_born", "plenty"):
            self.assertIn(minds.MK[k], kinds)

    def test_everyone_has_a_goal(self):
        self.assertTrue(((self.p["goal"] >= 0) & (self.p["goal"] < len(minds.GOALS))).all())
        babies = (self.w.tick - self.p["birth"]) / self.w.dpy < 4
        self.assertTrue((self.p["goal"][babies] == minds.GI["stay close to mother"]).all())

    def test_determinism_with_minds(self):
        a, b = World.create(cfg()), World.create(cfg())
        a.run(500)
        b.run(500)
        self.assertEqual(a.state_hash(), b.state_hash())

    def test_save_and_load_keeps_memories(self):
        out = ppl.save_arrays(self.p)
        back = ppl.load_arrays(out)
        for k in minds.MATRICES:
            self.assertTrue(np.array_equal(back[k], self.p[k]), k)

    def test_worlds_without_minds_have_no_inner_life(self):
        c = cfg()
        c.pop("minds")
        w = World.create(c)
        w.run(400)
        self.assertTrue((w.state["people"]["feel"] == 0).all())
        self.assertTrue((w.state["people"]["mem_kind"] == 0).all())


class TestSettingsUpdate(unittest.TestCase):
    def test_new_sections_are_added_to_an_old_settings_file(self):
        with tempfile.TemporaryDirectory() as d:
            old = Path(d) / "old.toml"
            new = Path(d) / "new.toml"
            old.write_text("[world]\nseed = 7   # mine\n")
            new.write_text("[world]\nseed = 1\n\n[minds]\n# feelings\ngrief_slows_work = 0.2\n")
            self.assertEqual(add_new_sections(old, new), ["minds"])
            c = load_config(old)
            self.assertEqual(c["world"]["seed"], 7)                 # the user's value is untouched
            self.assertEqual(c["minds"]["grief_slows_work"], 0.2)
            self.assertEqual(add_new_sections(old, new), [])         # and only added once


if __name__ == "__main__":
    unittest.main()
