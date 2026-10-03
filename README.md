# Artificial World

A persistent simulated world that lives on your homelab. The goal is to watch
life — and eventually people, cultures and civilizations — **emerge** from
simple rules, instead of being scripted.

> **North star:** define the rules of the universe, not the civilization that emerges from it.

This is **Stage 1: The World** — a living landscape with continents, rivers,
climate, seasons, wet and dry years, vegetation, grazing herds and predators.
People arrive in Stage 2.

---

## Quick start (on your Ubuntu VM)

You need **Docker** and **git**. If you don't have them yet:

```bash
sudo apt update && sudo apt install -y git ca-certificates curl
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER      # then log out and back in
```

Get the code and start the world:

```bash
git clone https://github.com/<your-username>/artificial-world.git
cd artificial-world
docker compose up -d --build
```

Open **http://&lt;your-vm-ip&gt;:8080** in a browser on your PC.
(Find the VM's IP with `hostname -I`.)

That's it. The world runs in the background from now on, even when the page
is closed and after the VM reboots.

### Everyday commands

| What | Command (run inside the `artificial-world` folder) |
|---|---|
| See if it's running | `docker compose ps` |
| See its log | `docker compose logs -f` |
| Stop (saves first) | `docker compose stop` |
| Start again | `docker compose start` |
| Get updates from GitHub | `git pull && docker compose up -d --build` |
| Run the tests | `docker compose run --rm world python -m unittest discover -s tests -t .` |
| Measure speed on your hardware | `docker compose run --rm world python -m aworld bench --years 10` |

---

## Using the viewer

- **Start / Pause** (or press space), **+1 day**, **+1 year**.
- **Speed**: from 1 day per second (to watch closely) up to **max**.
- **3D / Map**: orbit around a 3D landscape, or use the flat map.
  Drawing happens on your PC's graphics card; the server only sends numbers.
- **Show**: natural colours, vegetation, grazing herds, predators, temperature,
  this year's rain compared to normal, or biomes.
- **Click** anywhere to inspect that spot.
- **History** lists notable events (droughts, population collapses…).
  These labels are applied by an *observer*; the world itself has no idea it's
  "in a drought".
- **Rewind**: type a year and press Go. The world reloads the nearest earlier
  checkpoint and re-simulates forward — because the simulation is
  deterministic, the past comes back exactly as it was.
- **Worlds**: create a new world from a seed, or switch between saved worlds.

## Settings — the laws of physics

Everything tunable is in [`config/default.toml`](config/default.toml), with a
comment on every line. Settings are **locked into a world when it is created**,
so editing the file only affects *new* worlds (create one from the Worlds
button). That keeps every world reproducible:

> same seed + same simulation version + same settings ⇒ the same history, bit for bit.

## Time

One simulation tick is one day; a year is 360 days. The world keeps its own
calendar, completely separate from your clock. Run `bench` to see real speed on
your machine — for reference, the cloud machine this was built on did about
**1 simulated year per second** at max speed, i.e. ~3,500 years per hour.

## Storage

Each world is a folder in `data/worlds/`:

```
world.json       seed, version and the exact settings used
static.npz       the landscape (saved once)
checkpoints/     full snapshots: yearly for the last 100 years,
                 then once a decade, then once a century
history.sqlite   the permanent record: statistics and events (never thinned)
```

A snapshot is about 1 MB, so a 10,000-year world uses roughly 300 MB.
`max_storage_gb` (default 100) is a hard cap: if a world ever reaches it, old
checkpoints are thinned further. The history record is never deleted.

**Backups:** copy the `data` folder. Nothing else holds state.

---

## How it works (for the curious)

```
aworld/
  world.py     The World: state + the one rule "advance one day"
  terrain.py   continents, mountains, lakes, rivers (runs once at birth)
  climate.py   temperature, rainfall, seasons, wet/dry years
  ecology.py   plants → grazers → predators, snow
  observer.py  measures the world and writes history (read-only)
  storage.py   checkpoints, thinning, storage cap, history database
  runner.py    keeps the world ticking in the background
  server.py    small web server (Python standard library only)
web/           the viewer (one page, three.js for 3D)
tests/         determinism, save/load, rewind, physics, storage, web API
```

Design rules the code follows:

- **The engine is pure.** `World.step()` uses no clock, no threads and no
  randomness except streams derived from the seed. That's what makes rewind,
  branching and experiments possible.
- **The observer never changes the world.** Words like "drought", "species" or
  later "village" and "chief" are labels for things we *detect*, not things the
  simulation is told to create.
- **Plants and animals are population fields**, not individuals. People will be
  individuals; the landscape doesn't need to be.
- **One dependency** (NumPy). No database server, no message bus, no frameworks.

## Roadmap

| Stage | Adds | You'll see |
|---|---|---|
| **1. The World** ✅ | terrain, rivers, climate, seasons, plants & animals, save/rewind, 3D viewer | a living landscape |
| 2. People | needs, foraging, aging, births, families, death, inherited traits | bands surviving or starving |
| 3. Learning | skills, imitation, material "chemistry", tools, knowledge that can be lost | discoveries spreading and dying out |
| 4. Language | invented words, shared vocabularies, dialects | groups that drift apart in speech |
| 5. Society | sharing, reputation, conflict, group identity | bands forming, splitting, allying |
| 6. Settling | storage, replanting, shelter, building | first camps that stop moving |
| 7. Civilization | property, trade, specialization, leadership | villages, chiefdoms — or collapse |
| 8. History | timelines, family trees, causal tracing, branching worlds | "why did this happen?" from data |
