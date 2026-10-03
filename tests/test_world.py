"""Tests for the world engine. Run with:   python -m unittest -v"""
import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

import numpy as np

from aworld import ecology
from aworld.config import load_config
from aworld.runner import Runner
from aworld.storage import WorldStore, keep_policy
from aworld.world import World

SMALL = {"world": {"width": 64, "height": 64, "seed": 777}}


def small_cfg(**world):
    return load_config(overrides={"world": {**SMALL["world"], **world}})


class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_history(self):
        a, b = World.create(small_cfg()), World.create(small_cfg())
        a.run(400)
        b.run(400)
        self.assertEqual(a.state_hash(), b.state_hash())

    def test_different_seed_different_world(self):
        a, b = World.create(small_cfg(seed=1)), World.create(small_cfg(seed=2))
        self.assertFalse(np.array_equal(a.static["elevation"], b.static["elevation"]))

    def test_save_and_reload_continues_identically(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            straight = World.create(small_cfg())
            straight.run(800)

            w = World.create(small_cfg())
            w.run(400)
            store = WorldStore.create(tmp, w, "test")
            store.write_checkpoint(w, {})
            reloaded, _ = WorldStore(store.root).load_world()
            reloaded.run(400)
            self.assertEqual(straight.state_hash(), reloaded.state_hash())
        finally:
            shutil.rmtree(tmp)


class TestPhysics(unittest.TestCase):
    def setUp(self):
        self.w = World.create(small_cfg())

    def test_sea_level_respected(self):
        frac = self.w.static["ocean"].mean()
        self.assertAlmostEqual(frac, self.w.cfg["world"]["sea_level"], delta=0.02)

    def test_all_water_reaches_the_sea(self):
        H, W = self.w.shape
        from aworld import terrain
        s = self.w.static
        hydro = terrain.hydrology(s["elevation"], s["ocean"], s["annual_rain"])
        rec = hydro["receiver"].ravel()
        ocean = s["ocean"].ravel()
        for start in np.flatnonzero(~ocean)[::7]:
            cell, hops = start, 0
            while not ocean[cell]:
                cell = rec[cell]
                hops += 1
                self.assertLess(hops, H * W, "water got stuck in a loop")

    def test_wandering_conserves_animals(self):
        nbr = self.w.static["neighbours"]
        g = np.random.default_rng(0).uniform(0, 1, nbr.shape[1])
        self.assertAlmostEqual(ecology._spread(g, 0.2, nbr).sum(), g.sum(), places=6)

    def test_no_life_in_water_and_nothing_negative(self):
        self.w.run(720)
        for k in ("plants", "grazers", "predators", "snow"):
            self.assertTrue((self.w.state[k] >= 0).all(), k)
        full = self.w.field(self.w.state["grazers"])
        self.assertEqual(full[~self.w.static["habitable"]].sum(), 0.0)

    def test_life_persists_for_decades(self):
        self.w.run(360 * 30)
        self.assertGreater(self.w.state["plants"].sum(), 0)
        self.assertGreater(self.w.state["grazers"].sum(), 0)


class TestStorage(unittest.TestCase):
    def test_keep_policy_thins_with_age(self):
        dpy = 360
        ticks = [y * dpy for y in range(0, 3001)]
        kept = keep_policy(ticks, current_tick=3000 * dpy, days_per_year=dpy)
        years = {t // dpy for t in kept}
        self.assertTrue(set(range(2900, 3001)) <= years)        # last century: every year
        self.assertIn(2500, years)
        self.assertNotIn(2501, years)                           # 100–1000 yrs ago: per decade
        self.assertIn(1000, years)
        self.assertNotIn(1010, years)                           # older: per century
        self.assertIn(0, years)

    def test_storage_cap_enforced(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            w = World.create(small_cfg())
            store = WorldStore.create(tmp, w, "cap")
            for _ in range(12):
                w.run(360)
                store.write_checkpoint(w, {})
            cap = store.disk_bytes() // 2
            store.thin_checkpoints(w.tick, 360, cap)
            self.assertLessEqual(store.disk_bytes(), cap)
            self.assertGreaterEqual(len(store.checkpoint_ticks()), 2)
        finally:
            shutil.rmtree(tmp)


class TestRunnerAndServer(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        cfg_path = self.tmp / "small.toml"
        text = Path(load_config.__globals__["DEFAULT_CONFIG_PATH"]).read_text()
        text = text.replace("width = 256", "width = 64").replace("height = 256", "height = 64")
        cfg_path.write_text(text)
        self.runner = Runner(self.tmp / "data", cfg_path)
        self.runner.create_world("Test", seed=5)

    def tearDown(self):
        self.runner.store.close()
        shutil.rmtree(self.tmp)

    def test_rewind_restores_exact_past(self):
        self.runner.step_days(500)
        past = self.runner.world.state_hash()
        self.runner.step_days(1000)
        self.runner.seek(500)
        self.assertEqual(self.runner.world.tick, 500)
        self.assertEqual(self.runner.world.state_hash(), past)

    def test_history_is_recorded(self):
        self.runner.step_days(360 * 3)
        series = self.runner.store.metric_series(["grazers"])
        self.assertGreater(len(series["grazers"]), 50)
        self.assertTrue(any(e["type"] == "WORLD_CREATED" for e in self.runner.store.events()))

    def test_web_api(self):
        from http.server import ThreadingHTTPServer
        from aworld.server import make_handler
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.runner))
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        try:
            def get(path):
                with urllib.request.urlopen(base + path) as r:
                    return r.read()

            def post(path, body):
                req = urllib.request.Request(base + path, json.dumps(body).encode(), method="POST",
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req) as r:
                    return json.loads(r.read())

            self.assertEqual(json.loads(get("/api/status"))["world"]["width"], 64)
            self.assertEqual(len(get("/api/terrain")), 64 * 64 * 4)
            self.assertEqual(len(get("/api/frame")), 64 * 64 * 7)
            self.assertEqual(post("/api/control", {"action": "step", "days": 30})["tick"], 30)
            self.assertIn("biome", json.loads(get("/api/cell?x=32&y=32")))
            self.assertIn(b"<html", get("/").lower())
            post("/api/control", {"action": "step", "days": 400})
            st = json.loads(get("/api/status"))
            self.assertGreater(st["people"]["population"], 0)
            pid = int(self.runner.world.state["people"]["id"][0])
            person = json.loads(get(f"/api/person?id={pid}"))
            self.assertTrue(person["alive"])
            loc = person["location"]
            self.assertTrue(any(x["id"] == pid for x in json.loads(get(f"/api/people?x={loc['x']}&y={loc['y']}"))))
            mother = json.loads(get(f"/api/person?id=1"))          # a founder, alive or dead
            self.assertNotIn("error", mother)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
