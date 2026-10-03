"""The Runner: keeps a world ticking in the background.

It owns one world, its folder on disk and the observer. The web server
talks to the runner, never to the world directly. All access to the
world goes through `self.lock`, so the server can never catch the world
halfway through a day.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

from .config import load_config
from .ecology import BIOMES
from .observer import GRAZERS_PER_UNIT, PREDATORS_PER_UNIT, Observer
from .storage import WorldStore, list_worlds
from .world import World

SPEEDS = {            # label -> simulated days per real second (0 = as fast as possible)
    "1 day/s": 1,
    "1 week/s": 7,
    "1 month/s": 30,
    "1 year/s": 360,
    "max": 0,
}


class Runner:
    def __init__(self, data_dir: str | Path, config_path: str | Path | None = None):
        self.data_dir = Path(data_dir)
        self.worlds_dir = self.data_dir / "worlds"
        self.config_path = config_path
        self.lock = threading.RLock()
        self.running = False
        self.speed = "1 month/s"
        self.pause_on_major = False
        self.measured_days_per_sec = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.world: World | None = None
        self.store: WorldStore | None = None
        self.observer = Observer()
        self.last_major: dict | None = None

    # ── world management ───────────────────────────────────────
    def open_latest_or_create(self) -> None:
        worlds = list_worlds(self.worlds_dir)
        if worlds:
            newest = max(worlds, key=lambda m: m["created_utc"])
            self.open_world(newest["id"])
        else:
            self.create_world(name="First World")

    def create_world(self, name: str, seed: int | None = None, overrides: dict | None = None) -> str:
        cfg = load_config(self.config_path, overrides)
        if seed is not None:
            cfg["world"]["seed"] = int(seed)
        world = World.create(cfg)
        observer = Observer()
        store = WorldStore.create(self.worlds_dir, world, name)
        store.record(0, {}, observer.opening_events(world))
        store.write_checkpoint(world, observer.memory)
        store.commit()
        self._swap(world, store, observer)
        return store.meta["id"]

    def open_world(self, world_id: str) -> None:
        store = WorldStore(self.worlds_dir / world_id)
        world, memory = store.load_world()
        self._swap(world, store, Observer(memory))

    def _swap(self, world: World, store: WorldStore, observer: Observer) -> None:
        with self.lock:
            self.running = False
            if self.store is not None and self.store is not store:
                self.save()
                self.store.close()
            self.world, self.store, self.observer = world, store, observer

    # ── running ────────────────────────────────────────────────
    def start_thread(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="sim", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        with self.lock:
            self.save()
            if self.store:
                self.store.close()

    def _loop(self) -> None:
        last = time.monotonic()
        owed = 0.0          # days we "owe" the clock at the chosen speed
        mark_time, mark_tick = last, 0
        while not self._stop.is_set():
            if not self.running:
                time.sleep(0.05)
                last = mark_time = time.monotonic()
                mark_tick = self.world.tick if self.world else 0
                owed = 0.0
                self.measured_days_per_sec = 0.0
                continue
            now = time.monotonic()
            rate = SPEEDS.get(self.speed, 30)
            if rate == 0:
                days = 30
            else:
                owed = min(owed + (now - last) * rate, rate)   # never try to "catch up" more than 1s
                days = int(owed)
                owed -= days
            last = now
            if days == 0:
                time.sleep(0.01)
                continue
            with self.lock:
                for _ in range(days):
                    if not self.running:
                        break
                    self._advance_one_day()
                tick = self.world.tick
            # Real throughput, measured about once a second.
            if now - mark_time >= 1.0:
                rate_now = (tick - mark_tick) / (now - mark_time)
                self.measured_days_per_sec = max(0.0, rate_now)
                mark_time, mark_tick = now, tick
            time.sleep(0.001)   # let the web server in

    def _advance_one_day(self) -> None:
        world, store = self.world, self.store
        cfg = world.cfg["storage"]
        flows = world.step()
        metrics, events = self.observer.after_step(world, flows, cfg["metrics_every_days"])
        if metrics or events:
            store.record(world.tick, metrics, events)
        if world.tick % cfg["checkpoint_every_days"] == 0:
            store.write_checkpoint(world, self.observer.memory)
            store.thin_checkpoints(world.tick, world.dpy, int(cfg["max_storage_gb"] * 1024 ** 3))
            store.commit()
        majors = [e for e in events if e.get("major")]
        if majors:
            self.last_major = majors[-1]
            if self.pause_on_major:
                self.running = False

    def step_days(self, days: int = 1) -> None:
        with self.lock:
            self.running = False
            for _ in range(max(1, days)):
                self._advance_one_day()
            self.store.commit()

    def save(self) -> None:
        with self.lock:
            if self.world is not None and self.store is not None:
                self.store.write_checkpoint(self.world, self.observer.memory)
                self.store.commit()

    def seek(self, tick: int) -> int:
        """Rewind (or jump ahead) to an exact day. Loads the nearest earlier
        checkpoint and re-simulates forward — deterministic, so the past
        comes back exactly as it was."""
        with self.lock:
            self.running = False
            self.store.commit()
            tick = max(0, int(tick))
            world, memory = self.store.load_world(tick)
            observer = Observer(memory)
            cfg = world.cfg["storage"]
            while world.tick < tick:
                flows = world.step()
                observer.after_step(world, flows, cfg["metrics_every_days"])
            self.world, self.observer = world, observer
            return world.tick

    # ── what the web page asks for ──────────────────────────────
    def status(self) -> dict:
        with self.lock:
            w = self.world
            meta = self.store.meta
            st = w.state
            return {
                "world": {"id": meta["id"], "name": meta["name"], "seed": meta["seed"],
                          "sim_version": meta["sim_version"], "width": w.shape[1], "height": w.shape[0]},
                "tick": w.tick, "year": w.year, "day_of_year": w.day_of_year, "days_per_year": w.dpy,
                "running": self.running, "speed": self.speed, "speeds": list(SPEEDS),
                "pause_on_major": self.pause_on_major,
                "days_per_sec": round(self.measured_days_per_sec, 1),
                "last_major": self.last_major,
                "now": {
                    "grazers": round(float(st["grazers"].sum()) * GRAZERS_PER_UNIT),
                    "predators": round(float(st["predators"].sum()) * PREDATORS_PER_UNIT),
                    "vegetation_pct": round(100.0 * float(st["plants"].sum() / max(w.static["capacity_c"].sum(), 1e-9)), 1),
                },
                "storage": {"world_bytes": self.store.disk_bytes(),
                            "cap_bytes": int(w.cfg["storage"]["max_storage_gb"] * 1024 ** 3),
                            "checkpoints": len(self.store.checkpoint_ticks())},
            }

    def terrain_bytes(self) -> bytes:
        """Unchanging map layers: elevation (int16 metres), biome (uint8), water (uint8: 1 river, 2 lake)."""
        with self.lock:
            s = self.world.static
            elev = np.clip(np.round(s["elevation"]), -32768, 32767).astype("<i2")
            water = (s["river"].astype(np.uint8) + 2 * s["lake"].astype(np.uint8))
            return elev.tobytes() + s["biome"].astype(np.uint8).tobytes() + water.tobytes()

    def frame_bytes(self) -> bytes:
        """Changing layers, each one byte per cell:
        plants, grazers, predators, snow, temperature, rain anomaly."""
        with self.lock:
            w = self.world
            st = w.state

            def q(compact, lo, hi, curve=1.0):
                v = np.clip((compact - lo) / (hi - lo), 0, 1) ** curve
                return w.field(v * 255.0)

            layers = [
                q(st["plants"], 0, 1.0),
                q(st["grazers"], 0, 0.6, 0.5),
                q(st["predators"], 0, 0.15, 0.5),
                q(st["snow"], 0, 40.0),
                np.clip((w.temperature_map() + 40) / 85 * 255, 0, 255),
                q(st["anomaly"], -0.5, 0.5),
            ]
            return b"".join(np.round(l).astype(np.uint8).tobytes() for l in layers)

    def cell(self, x: int, y: int) -> dict:
        with self.lock:
            w = self.world
            s, st = w.static, w.state
            H, W = w.shape
            x, y = int(np.clip(x, 0, W - 1)), int(np.clip(y, 0, H - 1))
            idx = y * W + x
            info = {
                "x": x, "y": y,
                "biome": BIOMES[int(s["biome"][y, x])],
                "elevation_m": round(float(s["elevation"][y, x])),
                "latitude": round(float(s["latitude"][y, x]), 1),
                "temperature_c": round(float(w.temperature_map()[y, x]), 1),
                "yearly_avg_temp_c": round(float(s["annual_temp"][y, x]), 1),
                "yearly_rain_mm": round(float(s["annual_rain"][y, x])),
                "river": bool(s["river"][y, x]), "lake": bool(s["lake"][y, x]),
            }
            pos = np.searchsorted(s["cells"], idx)
            if pos < s["cells"].size and s["cells"][pos] == idx:
                info.update({
                    "vegetation_pct": round(100 * float(st["plants"][pos]), 1),
                    "vegetation_capacity_pct": round(100 * float(s["capacity_c"][pos]), 1),
                    "grazers": round(float(st["grazers"][pos]) * GRAZERS_PER_UNIT, 1),
                    "predators": round(float(st["predators"][pos]) * PREDATORS_PER_UNIT, 1),
                    "snow_cm": round(float(st["snow"][pos]), 1),
                    "rain_this_year_vs_normal_pct": round(100 * float(st["anomaly"][pos])),
                })
            return info
