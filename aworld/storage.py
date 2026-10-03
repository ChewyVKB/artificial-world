"""Saving worlds to disk, and keeping disk use under control.

On disk, each world is a folder:

    data/worlds/<world-id>/
        world.json        who this world is: seed, version, settings
        static.npz        the landscape (saved once)
        checkpoints/      full snapshots of the living world over time
        history.sqlite    the permanent record: statistics and events

Because the simulation is deterministic, we don't need to store every
day. To see any past moment we load the nearest earlier checkpoint and
re-simulate forward. Checkpoints thin out with age (yearly for the last
century, then every decade, then every century) and are thinned further
if the storage cap is reached. The history record is never thinned.
"""
from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import time
from pathlib import Path

import numpy as np

from . import SIM_VERSION, people
from .world import DYNAMIC_FIELDS, World, add_derived

STATIC_SAVE = ("elevation", "ocean", "lake", "river", "flow", "latitude", "annual_temp",
               "annual_rain", "swing", "habitable", "biome", "plant_capacity", "cells",
               "neighbours", "annual_temp_c", "annual_rain_c", "swing_c", "hemisphere_c", "capacity_c",
               "neighbours8", "compact_of", "water_c", "water_dist_c", "cy_c", "cx_c", "stone_c", "clay_c", "wood_c",
               "coast_c", "lake_c", "mount_c")

_CKPT = re.compile(r"^t(\d{12})\.npz$")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return s or "world"


class WorldStore:
    """One world's folder on disk."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.ckpt_dir = self.root / "checkpoints"
        self._db: sqlite3.Connection | None = None

    # ── creating and opening ───────────────────────────────────
    @classmethod
    def create(cls, base: str | Path, world: World, name: str) -> "WorldStore":
        base = Path(base)
        base.mkdir(parents=True, exist_ok=True)
        wid = f"{slugify(name)}-{world.cfg['world']['seed']}"
        n = 2
        while (base / wid).exists():
            wid = f"{slugify(name)}-{world.cfg['world']['seed']}-{n}"
            n += 1
        store = cls(base / wid)
        store.ckpt_dir.mkdir(parents=True)
        meta = {
            "id": wid,
            "name": name,
            "seed": world.cfg["world"]["seed"],
            "sim_version": SIM_VERSION,
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "config": world.cfg,
        }
        (store.root / "world.json").write_text(json.dumps(meta, indent=2))
        np.savez_compressed(store.root / "static.npz", **{k: world.static[k] for k in STATIC_SAVE if k in world.static})
        return store

    @property
    def meta(self) -> dict:
        return json.loads((self.root / "world.json").read_text())

    def load_world(self, tick: int | None = None) -> tuple[World, dict]:
        """Load the latest checkpoint (or the latest at/before `tick`).
        Returns (world, observer memory)."""
        meta = self.meta
        if meta["sim_version"] != SIM_VERSION:
            # Not fatal: the world still loads, but replaying old history may not match exactly.
            print(f"[storage] warning: world made with sim {meta['sim_version']}, running {SIM_VERSION}")
        with np.load(self.root / "static.npz") as z:
            static = add_derived({k: z[k] for k in z.files}, meta["seed"])
        ticks = self.checkpoint_ticks()
        if not ticks:
            raise FileNotFoundError(f"no checkpoints in {self.root}")
        chosen = ticks[-1] if tick is None else max([t for t in ticks if t <= tick] or [ticks[0]])
        state, observer = self.read_checkpoint(chosen)
        return World(meta["config"], static, state), observer

    # ── checkpoints ─────────────────────────────────────────────
    def checkpoint_path(self, tick: int) -> Path:
        return self.ckpt_dir / f"t{tick:012d}.npz"

    def checkpoint_ticks(self) -> list[int]:
        out = []
        for name in os.listdir(self.ckpt_dir):
            m = _CKPT.match(name)
            if m:
                out.append(int(m.group(1)))
        return sorted(out)

    def write_checkpoint(self, world: World, observer: dict) -> Path:
        path = self.checkpoint_path(world.tick)
        buf = io.BytesIO()
        extra = people.save_arrays(world.state["people"]) if world.has_people else {}
        np.savez_compressed(buf, **{k: world.state[k] for k in DYNAMIC_FIELDS}, **extra,
                            _tick=np.int64(world.tick),
                            _observer=np.frombuffer(json.dumps(observer).encode(), dtype=np.uint8))
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(buf.getvalue())
        os.replace(tmp, path)          # atomic: a crash never leaves a half-written save
        return path

    def read_checkpoint(self, tick: int) -> tuple[dict, dict]:
        with np.load(self.checkpoint_path(tick)) as z:
            state = {k: z[k].astype(float) for k in DYNAMIC_FIELDS}
            state["tick"] = int(z["_tick"])
            ppl = people.load_arrays(z)
            if ppl is not None:
                state["people"] = ppl
            observer = json.loads(z["_observer"].tobytes().decode())
        return state, observer

    def disk_bytes(self) -> int:
        total = 0
        for dirpath, _, files in os.walk(self.root):
            for f in files:
                total += os.path.getsize(os.path.join(dirpath, f))
        return total

    def thin_checkpoints(self, current_tick: int, days_per_year: int, max_bytes: int) -> list[int]:
        """Delete checkpoints we no longer need. Returns the ticks removed."""
        ticks = self.checkpoint_ticks()
        keep = set(keep_policy(ticks, current_tick, days_per_year))
        removed = [t for t in ticks if t not in keep]
        for t in removed:
            self.checkpoint_path(t).unlink(missing_ok=True)

        # Still over the cap? Remove the checkpoint whose loss leaves the smallest gap.
        remaining = sorted(keep)
        while self.disk_bytes() > max_bytes and len(remaining) > 2:
            gaps = [(remaining[i + 1] - remaining[i - 1], remaining[i]) for i in range(1, len(remaining) - 1)]
            _, victim = min(gaps)
            self.checkpoint_path(victim).unlink(missing_ok=True)
            remaining.remove(victim)
            removed.append(victim)
        return removed

    # ── permanent history ──────────────────────────────────────
    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = sqlite3.connect(self.root / "history.sqlite", check_same_thread=False)
            self._db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS metrics (
                    tick INTEGER NOT NULL, name TEXT NOT NULL, value REAL NOT NULL,
                    PRIMARY KEY (name, tick)) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, tick INTEGER NOT NULL, type TEXT NOT NULL,
                    title TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}',
                    UNIQUE (tick, type, title));
                CREATE INDEX IF NOT EXISTS events_tick ON events(tick);
                CREATE TABLE IF NOT EXISTS people (
                    id INTEGER PRIMARY KEY, mother INTEGER, father INTEGER, sex INTEGER,
                    birth_tick INTEGER, birth_cell INTEGER, generation INTEGER, genes TEXT,
                    death_tick INTEGER, death_cause TEXT, death_age REAL, death_cell INTEGER);
                CREATE INDEX IF NOT EXISTS people_mother ON people(mother);
                CREATE INDEX IF NOT EXISTS people_father ON people(father);
            """)
            cols = {r[1] for r in self._db.execute("PRAGMA table_info(people)")}
            if "name" not in cols:                       # added in Stage 4
                self._db.execute("ALTER TABLE people ADD COLUMN name TEXT")
        return self._db

    def record(self, tick: int, metrics: dict, events: list[dict]) -> None:
        db = self.db
        if metrics:
            db.executemany("INSERT OR REPLACE INTO metrics VALUES (?,?,?)",
                           [(tick, k, float(v)) for k, v in metrics.items()])
        for e in events:
            db.execute("INSERT OR IGNORE INTO events (tick,type,title,data) VALUES (?,?,?,?)",
                       (e["tick"], e["type"], e["title"], json.dumps(e.get("data", {}))))

    def record_people(self, tick: int, births: list, deaths: list, founders: list | None = None) -> None:
        """The family record: every birth and every death, forever."""
        db = self.db
        rows = [tuple(r) + (None,) * (9 - len(r)) for r in (founders or [])]
        rows += [(b[0], b[1], b[2], b[3], tick, b[4], b[5], json.dumps(b[6]), b[7] if len(b) > 7 else None)
                 for b in births]
        if rows:
            db.executemany("INSERT OR IGNORE INTO people (id,mother,father,sex,birth_tick,birth_cell,generation,genes,name) "
                           "VALUES (?,?,?,?,?,?,?,?,?)", rows)
        if deaths:
            db.executemany("UPDATE people SET death_tick=?, death_cause=?, death_age=?, death_cell=? WHERE id=?",
                           [(tick, people.CAUSES[c], round(a, 2), cell, i) for i, c, a, cell in deaths])

    def person_record(self, pid: int) -> dict | None:
        row = self.db.execute("SELECT id,mother,father,sex,birth_tick,birth_cell,generation,genes,"
                              "death_tick,death_cause,death_age,death_cell,name FROM people WHERE id=?", (pid,)).fetchone()
        if not row:
            return None
        keys = ("id", "mother", "father", "sex", "birth_tick", "birth_cell", "generation", "genes",
                "death_tick", "death_cause", "death_age", "death_cell", "name")
        rec = dict(zip(keys, row))
        rec["genes"] = json.loads(rec["genes"]) if rec["genes"] else None
        return rec

    def children_of(self, pid: int, until_tick: int) -> list[dict]:
        rows = self.db.execute("SELECT id, sex, birth_tick, death_tick, name FROM people WHERE (mother=? OR father=?) "
                               "AND birth_tick<=? ORDER BY birth_tick", (pid, pid, until_tick)).fetchall()
        return [{"id": i, "sex": s, "birth_tick": b, "death_tick": d if d is not None and d <= until_tick else None,
                 "name": nm} for i, s, b, d, nm in rows]

    def names_of(self, ids: list[int]) -> dict:
        if not ids:
            return {}
        q = ",".join("?" * len(ids))
        return {i: n for i, n in self.db.execute(f"SELECT id, name FROM people WHERE id IN ({q})", ids) if n}

    def commit(self) -> None:
        if self._db is not None:
            self._db.commit()

    def metric_series(self, names: list[str] | None = None, max_points: int = 600,
                      until_tick: int | None = None) -> dict:
        """Statistics over time, evenly thinned to at most `max_points` per series."""
        db = self.db
        if names is None:
            names = [r[0] for r in db.execute("SELECT DISTINCT name FROM metrics ORDER BY name")]
        until = until_tick if until_tick is not None else 2 ** 62
        out = {}
        for name in names:
            (count,) = db.execute("SELECT COUNT(*) FROM metrics WHERE name=? AND tick<=?", (name, until)).fetchone()
            stride = max(1, -(-count // max_points))
            rows = db.execute(
                "SELECT tick, value FROM (SELECT tick, value, ROW_NUMBER() OVER (ORDER BY tick) AS rn "
                "FROM metrics WHERE name=? AND tick<=?) WHERE (rn - 1) % ? = 0 ORDER BY tick",
                (name, until, stride)).fetchall()
            out[name] = rows
        return out

    def events(self, limit: int = 200, until_tick: int | None = None) -> list[dict]:
        until = until_tick if until_tick is not None else 2 ** 62
        rows = self.db.execute("SELECT tick,type,title,data FROM events WHERE tick<=? ORDER BY tick DESC, id DESC LIMIT ?",
                               (until, limit)).fetchall()
        return [{"tick": t, "type": ty, "title": ti, "data": json.loads(d)} for t, ty, ti, d in rows]

    def close(self) -> None:
        if self._db is not None:
            self._db.commit()
            self._db.close()
            self._db = None


def keep_policy(ticks: list[int], current_tick: int, days_per_year: int) -> list[int]:
    """Which checkpoints to keep: everything in the last 100 years, one per decade
    back to 1,000 years, then one per century. The first and latest are always kept."""
    if not ticks:
        return []
    keep = {ticks[0], ticks[-1]}
    for t in ticks:
        age_years = (current_tick - t) / days_per_year
        year = t // days_per_year
        on_year = t % days_per_year == 0
        if age_years <= 100:
            keep.add(t)
        elif age_years <= 1000:
            if on_year and year % 10 == 0:
                keep.add(t)
        elif on_year and year % 100 == 0:
            keep.add(t)
    return sorted(keep)


def list_worlds(base: str | Path) -> list[dict]:
    base = Path(base)
    if not base.exists():
        return []
    out = []
    for d in sorted(base.iterdir()):
        if (d / "world.json").exists():
            m = json.loads((d / "world.json").read_text())
            m.pop("config", None)
            out.append(m)
    return out
