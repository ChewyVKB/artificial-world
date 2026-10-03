"""Tests for Stage 2: people.   Run with:   python -m unittest discover -s tests -t ."""
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from aworld import people
from aworld.config import load_config
from aworld.observer import find_groups
from aworld.storage import WorldStore
from aworld.world import World


def cfg(**people_overrides):
    return load_config(overrides={"world": {"width": 128, "height": 128, "seed": 4242},
                                  "people": people_overrides})


class TestPeople(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = World.create(cfg())
        cls.births, cls.deaths = [], []
        for _ in range(360 * 15):
            out = cls.w.step()["people"]
            cls.births += out["births"]
            cls.deaths += out["deaths"]

    def test_people_survive_and_have_children(self):
        self.assertGreater(self.w.state["people"]["id"].size, 0)
        self.assertGreater(len(self.births), 20)

    def test_people_only_live_on_land(self):
        p = self.w.state["people"]
        self.assertTrue(self.w.static["habitable"].ravel()[self.w.static["cells"][p["pos"]]].all())

    def test_ids_are_unique_and_sorted(self):
        ids = self.w.state["people"]["id"]
        self.assertTrue((np.diff(ids) > 0).all())

    def test_young_children_stay_with_their_mother(self):
        p = self.w.state["people"]
        age = (self.w.tick - p["birth"]) / self.w.dpy
        mother = people.index_of(p["id"], p["mother"])
        kids = np.flatnonzero((age < 15) & (mother >= 0))
        self.assertGreater(kids.size, 0)
        self.assertTrue((p["pos"][kids] == p["pos"][mother[kids]]).all())

    def test_no_close_kin_partners(self):
        p = self.w.state["people"]
        partner = people.index_of(p["id"], p["partner"])
        for i in np.flatnonzero(partner >= 0):
            j = partner[i]
            self.assertEqual(p["partner"][j], p["id"][i], "partnership must be mutual")
            same_mother = p["mother"][i] >= 0 and p["mother"][i] == p["mother"][j]
            self.assertFalse(same_mother)
            self.assertNotIn(p["id"][j], (p["mother"][i], p["father"][i]))

    def test_children_inherit_traits_within_range(self):
        g = self.w.state["people"]["genes"]
        self.assertTrue((g >= people.GENE_RANGE[:, 0]).all() and (g <= people.GENE_RANGE[:, 1]).all())
        for _, mother, father, _, _, _, genes in self.births[:50]:
            self.assertEqual(len(genes), len(people.GENES))

    def test_groups_are_found(self):
        groups = find_groups(self.w)
        self.assertGreaterEqual(len(groups), 1)
        self.assertEqual(sum(size for size, _ in groups), self.w.state["people"]["id"].size)


class TestPeopleDeterminism(unittest.TestCase):
    def test_same_seed_same_people(self):
        a, b = World.create(cfg()), World.create(cfg())
        a.run(800)
        b.run(800)
        self.assertEqual(a.state_hash(), b.state_hash())

    def test_save_load_with_people(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            straight = World.create(cfg())
            straight.run(1000)
            w = World.create(cfg())
            w.run(500)
            store = WorldStore.create(tmp, w, "ppl")
            store.write_checkpoint(w, {})
            again, _ = WorldStore(store.root).load_world()
            again.run(500)
            self.assertEqual(straight.state_hash(), again.state_hash())
        finally:
            shutil.rmtree(tmp)

    def test_checkpoints_from_before_travel_still_load(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            w = World.create(cfg())
            w.run(100)
            store = WorldStore.create(tmp, w, "old")
            path = store.write_checkpoint(w, {})
            with np.load(path) as z:                       # drop the newer field, as old saves lack it
                data = {k: z[k] for k in z.files if k != "people.target"}
            np.savez_compressed(path, **data)
            again, _ = WorldStore(store.root).load_world()
            self.assertTrue((again.state["people"]["target"] == -1).all())
            again.run(100)
        finally:
            shutil.rmtree(tmp)

    def test_households_travel(self):
        w = World.create(cfg())
        start = set(w.state["people"]["pos"].tolist())
        visited = set()
        for _ in range(360 * 3):
            w.step()
            visited |= set(w.state["people"]["pos"].tolist())
        self.assertGreater(len(visited - start), 40)

    def test_worlds_without_people_still_work(self):
        c = cfg()
        del c["people"]
        w = World.create(c)
        w.run(100)
        self.assertFalse(w.has_people)

    def test_hunting_takes_from_the_land(self):
        w = World.create(cfg())
        cell = w.state["people"]["pos"][0]
        w2 = World.create(cfg())
        del w2.state["people"]
        w.step()
        w2.step()
        self.assertLess(w.state["plants"][cell], w2.state["plants"][cell] + 1e-12)


if __name__ == "__main__":
    unittest.main()
