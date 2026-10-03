# Artificial World

A persistent simulated world that lives on your homelab. The goal is to watch
life — and eventually people, cultures and civilizations — **emerge** from
simple rules, instead of being scripted.

> **North star:** define the rules of the universe, not the civilization that emerges from it.

**Stage 3: Learning** is here — see [About knowledge](#about-knowledge) below.

**Stage 2: People** (also included): On top of the living landscape from Stage 1
(continents, rivers, climate, seasons, droughts, vegetation, grazing herds,
predators) there are now individual early humans. They start as 60 people in
one mild, green place beside fresh water, with nothing: no language, tools,
fire, farming or leaders. They forage, hunt, drink, pair up, raise children,
age and die. Every child inherits traits from both parents with small
mutations, so the population **evolves** under whatever pressures the land
puts on it.

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
- **Click** anywhere to inspect that spot, including a list of the people
  living there. Click a person to see their life: age, health, family (with
  links to parents, partner and children, alive or dead), and inherited traits.
  Press **Follow** to keep the camera on them as they travel.
- **Show → People** shows population density; in the normal view people appear
  as warm yellow dots (map) or small figures (3D).
- The **People** and **Evolution** charts track population, births, deaths and
  the average of each inherited trait over time.
- **History** lists notable events (droughts, population collapses…).
  These labels are applied by an *observer*; the world itself has no idea it's
  "in a drought".
- **Rewind**: type a year and press Go. The world reloads the nearest earlier
  checkpoint and re-simulates forward — because the simulation is
  deterministic, the past comes back exactly as it was.
- **Worlds**: create a new world from a seed, or switch between saved worlds.

## About the people

What a person *can* do, each day:

- sense the land around them (food, which way water lies, warmth, other people)
- move camp: when food around camp runs low (or restlessness strikes), scout
  the land within ~40 km, pick somewhere better and walk there, up to ~12 km a day
- gather plants and hunt grazing animals — which uses them up
- drink at rivers and lakes, or from rain
- pair with another single adult they meet (never close kin)
- conceive, carry a child for 9 months, nurse it, feed it

Children travel and eat with their mother; partners share food. That's
biology, not a social system. Everything bigger — groups, migrations,
famines, which lands get settled — comes out of those rules.

**Inherited traits**, each with a real trade-off:

| Trait | Helps | Costs |
|---|---|---|
| size | hunting, keeping warm | needs more food |
| insulation | surviving cold | suffering in heat |
| fertility | more children | faster ageing |
| longevity | slower ageing | more food to maintain the body |
| wanderlust | finding new land | more aimless movement |
| sociability | staying near others | crowding |
| curiosity | discovering things | less time foraging |

People don't have names: names need a language, and language hasn't been
invented yet (Stage 4). They're known by number.

Worlds created before Stage 2 have no people and keep running exactly as they
did. To see people, create a **new world** from the Worlds button.

## About knowledge

The rule: **hard-code the chemistry, not the tech tree.** The land holds
materials — flint, wood, clay, fibre (from plants) and hides (from herds). The
world's physics says what those materials *can* become, and what the results
physically do:

| Technique | Needs | Does |
|---|---|---|
| Flaked stone edge | flint | cuts: gathering & hunting +15% |
| Fire-making | wood | warmth, cooking (+15% food), keeps predators away |
| Twisted cord | fibre | binds things |
| Digging stick | wood + stone edge | gathering +25% |
| Hafted spear | wood + stone edge + cord | hunting +60%, safer from predators |
| Woven basket | fibre + cord | gathering +20% |
| Sewn hide clothing | hide + stone edge + cord | cold felt ~6 °C less |
| Fired clay pot | clay + fire | carries water: thirst builds half as fast |
| Hide shelter | wood + hide + cord | cold felt ~3 °C less, safer in harsh seasons |
| Snare trap | cord + wood | extra food without chasing herds |

Nobody starts out knowing any of it. Adults **experiment** with whatever is
around them (more often if they inherited high **curiosity** — which costs
foraging time); most combinations do nothing, and combining three things is
harder than one. Once someone knows a technique they **practise** it and get
better, and people nearby can **learn** it from them (children learn
fastest, skilled teachers are easier to copy). Things they make **wear out**,
so living far from flint means losing your stone tools.

Knowledge **fades if it isn't practised**, and it's **lost** when nobody
living knows it — a group that moves away from clay forgets pottery. It can be
rediscovered later, by anyone. The Knowledge panel shows each technique's
status, when and by whom it was first worked out, and how often it's been lost.

## Deleting worlds

**Worlds → Delete** next to any world erases it — its history and every save
— permanently, after you confirm. If you delete the world that's open, the
viewer switches to your newest other world (or makes a fresh one if none is
left). To start completely fresh: create a new world, then delete the rest.

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
**1 simulated year per second** at max speed with a thousand people, i.e.
~3,000 years per hour.

## Storage

Each world is a folder in `data/worlds/`:

```
world.json       seed, version and the exact settings used
static.npz       the landscape (saved once)
checkpoints/     full snapshots: yearly for the last 100 years,
                 then once a decade, then once a century
history.sqlite   the permanent record: statistics, events, and every person
                 who ever lived (parents, birth, death, cause) — never thinned
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
  people.py    individual humans: senses, movement, food, water, family, birth, death
  knowledge.py materials, what they can become, and discovering/teaching/forgetting it
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
- **Plants and animals are population fields**, not individuals. People are
  individuals; the landscape doesn't need to be.
- **One dependency** (NumPy). No database server, no message bus, no frameworks.

## Roadmap

| Stage | Adds | You'll see |
|---|---|---|
| **1. The World** ✅ | terrain, rivers, climate, seasons, plants & animals, save/rewind, 3D viewer | a living landscape |
| **2. People** ✅ | needs, foraging, aging, births, families, death, inherited traits | bands surviving or starving |
| **3. Learning** ✅ | skills, imitation, material "chemistry", tools, knowledge that can be lost | discoveries spreading and dying out |
| 4. Language | invented words, shared vocabularies, dialects | groups that drift apart in speech |
| 5. Society | sharing, reputation, conflict, group identity | bands forming, splitting, allying |
| 6. Settling | storage, replanting, shelter, building | first camps that stop moving |
| 7. Civilization | property, trade, specialization, leadership | villages, chiefdoms — or collapse |
| 8. History | timelines, family trees, causal tracing, branching worlds | "why did this happen?" from data |
