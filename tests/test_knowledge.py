"""Tests for Stage 3: knowledge.   Run with:   python -m unittest discover -s tests -t ."""
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from aworld import knowledge as kn
from aworld.config import load_config
from aworld.observer import Observer
from aworld.runner import Runner
from aworld.world import World


def cfg(**k):
    return load_config(overrides={"world": {"width": 128, "height": 128, "seed": 4242}, "knowledge": k})


class TestKnowledge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Very curious people, so discoveries happen within a test's time.
        cls.w = World.create(cfg(experiment_rate=0.05))
        cls.found = []
        for _ in range(360 * 3):
            cls.found += cls.w.step()["people"]["discoveries"]

    def test_something_gets_discovered(self):
        self.assertGreater(len(self.found), 0)

    def test_discoveries_need_their_materials(self):
        s = self.w.static
        for pid, r, cell in self.found:
            needs = kn.RECIPES[r]["needs"]
            if "stone" in needs:
                self.assertGreater(s["stone_c"][cell], 0.2)
            if "clay" in needs:
                self.assertGreater(s["clay_c"][cell], 0.2)

    def test_complex_things_need_their_parts_first(self):
        first = {}
        for pid, r, cell in self.found:
            first.setdefault(kn.RECIPES[r]["key"], len(first))
        if "spear" in first:
            self.assertIn("flake", first)
            self.assertIn("cord", first)

    def test_knowledge_spreads_beyond_discoverers(self):
        discoverers = {pid for pid, _, _ in self.found}
        p = self.w.state["people"]
        knowing = set(p["id"][p["known"] > 0].tolist())
        self.assertGreater(len(knowing - discoverers), 0)

    def test_newborns_know_nothing(self):
        p = self.w.state["people"]
        babies = (self.w.tick - p["birth"]) < 30
        self.assertTrue((p["known"][babies] == 0).all())

    def test_unpractised_knowledge_is_forgotten(self):
        w = World.create(cfg())
        p = w.state["people"]
        p["known"][:] = kn.bit("pot")        # everyone knows pottery…
        p["skill"][:, kn.K["pot"]] = 0.0201  # …but barely, and nobody practises
        w.run(60)
        self.assertEqual(int(kn.knowers(w.state["people"])[kn.K["pot"]]), 0)

    def test_lost_and_rediscovered_events(self):
        w = World.create(cfg())
        obs = Observer()
        ev = obs._discoveries(w, [(1, kn.K["fire"], 0)])
        self.assertEqual(ev[0]["type"], "DISCOVERY")
        w.state["tick"] = 360
        lost = obs._yearly_knowledge(w)                  # nobody actually knows it
        self.assertEqual(lost[0]["type"], "KNOWLEDGE_LOST")
        again = obs._discoveries(w, [(2, kn.K["fire"], 0)])
        self.assertEqual(again[0]["type"], "REDISCOVERY")

    def test_determinism_with_knowledge(self):
        a, b = World.create(cfg(experiment_rate=0.05)), World.create(cfg(experiment_rate=0.05))
        a.run(500)
        b.run(500)
        self.assertEqual(a.state_hash(), b.state_hash())


class TestDeleteWorld(unittest.TestCase):
    def test_delete_worlds(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            cfg_path = tmp / "small.toml"
            text = Path(load_config.__globals__["DEFAULT_CONFIG_PATH"]).read_text()
            cfg_path.write_text(text.replace("width = 256", "width = 64").replace("height = 256", "height = 64"))
            r = Runner(tmp / "data", cfg_path)
            a = r.create_world("A", seed=1)
            b = r.create_world("B", seed=2)
            self.assertEqual(r.delete_world(a), b)                # deleting another world
            self.assertFalse((tmp / "data" / "worlds" / a).exists())
            now = r.delete_world(b)                               # deleting the open one
            self.assertNotEqual(now, b)
            self.assertFalse((tmp / "data" / "worlds" / b).exists())
            with self.assertRaises(ValueError):
                r.delete_world("../../etc")
            r.store.close()
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
