# Artificial World

A persistent simulated world that lives on your homelab. The goal is to watch
life — and eventually people, cultures and civilizations — **emerge** from
simple rules, instead of being scripted.

> **North star:** define the rules of the universe, not the civilization that emerges from it.

**Stage 4: Language** is here — see [About language](#about-language) below.
Stage 3 (learning) is described in [About knowledge](#about-knowledge).

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

You need **Docker**. If you don't have it yet:

```bash
sudo apt update && sudo apt install -y git ca-certificates curl
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER      # then log out and back in
```

### Option A — use the ready-made image (recommended)

Every push to `main` is tested and built into an image by GitHub Actions
(see `.github/workflows/docker.yml`) and published as
`ghcr.io/chewyvkb/artificial-world:latest`. You only need a folder with a
`docker-compose.yml` in it:

```bash
mkdir artificial-world && cd artificial-world
curl -fsSLO https://raw.githubusercontent.com/ChewyVKB/artificial-world/main/docker-compose.yml   # or copy it over
docker compose pull
docker compose up -d
```

Settings for the container go in an optional `.env` file next to
`docker-compose.yml` (see `.env.example`):

| Variable | Default | What it does |
|---|---|---|
| `PUID` / `PGID` | 1000 | the user/group that owns the saved files (run `id` on the host to see yours) |
| `TZ` | UTC | time zone for log times, e.g. `America/Chicago` |
| `APP_DATA_DIR` | `./App-Data` | where `DWS/data` (worlds) and `DWS/config` (settings) are kept |

On first start, `DWS/config/default.toml` (the world's settings) is created for
you to edit. The container reports its health at `/health`, so
`docker compose ps` shows **healthy** once the world is running.

**If the repository is private**, the image is private too, so log in once
first: create a GitHub *personal access token (classic)* with only the
`read:packages` scope, then run
`docker login ghcr.io -u ChewyVKB` and paste the token as the password.
(Or make the package public: GitHub → your profile → Packages →
artificial-world → Package settings → Change visibility.)

### Option B — build it yourself from the code

```bash
git clone https://github.com/ChewyVKB/artificial-world.git
cd artificial-world
# add "build: ." under the service in docker-compose.yml first
docker compose up -d --build
```

Either way, open **http://&lt;your-vm-ip&gt;:8285** in a browser on your PC
(find the VM's IP with `hostname -I`). The world runs in the background from
now on, even when the page is closed and after the VM reboots.

### Everyday commands

| What | Command (run in the folder with `docker-compose.yml`) |
|---|---|
| See if it's running | `docker compose ps` |
| See its log | `docker compose logs -f` |
| Stop (saves first) | `docker compose stop` |
| Start again | `docker compose start` |
| Update to the newest image | `docker compose pull && docker compose up -d` |
| Update by building from code | `git pull && docker compose up -d --build` |
| Run the tests | `docker compose run --rm dynamic-world-system python -m unittest discover -s tests -t .` |
| Measure speed on your hardware | `docker compose run --rm dynamic-world-system python -m aworld bench --years 10` |

---

## Using the viewer

- **Start / Pause** (or press space), **+1 day**, **+1 year**.
- **Speed**: from 1 day every 2 minutes (for watching up close) up to **max**.
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

## Watching up close

Click a place (or a person) and press **👁 Watch up close** — or double-click
the 3D land. The view drops down to a 20 km patch of the world: hills and
valleys, rivers and lakes, forests and grass of the right kind for the
climate, grazing herds, the sun and sky moving through the day, stars at
night. And the people who live there, going through their day:

- waking at dawn, walking out to **gather** (bending to dig and pick) or
  **hunt** (with a spear, if they have one), going to the **water** to drink;
- coming back to camp, **making** things they know how to make, one of them
  kneeling to **light the evening fire**; sitting around it, talking, then
  sleeping around the embers; babies carried by their mothers;
- **speech bubbles** when they speak, showing the word they really used in
  their own language and what it means, e.g. «mewo» (water);
- **thought bubbles** for the person you're following ("Looking for «woni»
  (roots and seeds)", "Cold night coming. No fire.") — their thoughts use
  their own words for things;
- a panel with what they're doing now, how fed / watered / healthy they are,
  and a diary of their day so far.

Click anyone to follow them. Drag to look around, scroll to zoom (all the way
out to see the whole patch), **Esc** or **← Back to world** to return.
Entering slows the world to **1 day every 2 minutes** (put back when you
leave); pause and drag the time slider to scrub through the day.

**Important:** close-up mode only *shows* what the simulation decided. Each
day the world works out what everyone did (who gathered how much, who
drank, who lit the fire, who talked to whom with which words); close-up mode
then plays that day out as a scene. The small details — the exact path
someone walked, where they knelt — are filled in for the picture, the same
way every time, and never feed back into the world. So watching changes
nothing, and the world runs just as fast when nobody is watching.

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
| speech | talking, faithful copying of words | needs more food (brain) |

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

## About language

Nothing about any actual language is built in — only the *ability* to make
sounds, link a sound to something two people are both paying attention to, and
copy each other. Every word in the world was coined by someone in it.

- **Talking.** People in the same place talk, several times a day, about what
  matters there and then: the river, a herd, a predator, the cold, the sun and
  the night, being hungry or sick, a stranger, a technique they know — 60 things
  so far. The list only grows: whenever the world gains something new to talk
  about (a new invention, later), people can coin words for it too.
- **Spreading.** A listener who uses a different word may switch to the
  speaker's (children nearly always do). People go with the majority
  (*conformist learning*): a word most people around you use is taken up
  readily, an odd one out rarely — so a community ends up sharing nearly all
  its words. Words nobody uses are forgotten.
- **One word, one meaning.** Nobody coins a word they already use for something
  else, a word that would clash with one you already use isn't taken up, and
  if someone does end up with one word for two things, the weaker meaning loses
  it. Most new words have two syllables, as in early languages, which leaves
  plenty of room for distinct words.
- **Changing.** Copying isn't perfect: now and then a sound slips, and now and
  then someone coins a new way of saying an old thing. Who you happen to talk
  to decides which version wins, so a community's words slowly turn over.
- **Accents.** Sound change is also *regular*, as in real languages: a person
  may start saying every *k* as *g*, or every *a* as *e*. Accents are picked up
  from the people around you (children most of all), so a whole region can
  come to share one. Related languages end up sounding different while staying
  recognisably related (*kele* / *gele*).
- **Mattering.** People who share words teach each other techniques far more
  easily, and a shared word for "predator" means warnings and fewer deaths.
  People prefer to camp among those they can understand. The heritable trait
  **speech** makes people talk more and copy words more faithfully, at the cost
  of a hungrier brain.
- **Names.** Once a mother has a few words she names her children, using the
  sounds of her own speech.

**Languages are identified by the observer, not declared by the simulation.**
Each year it listens region by region (~40 km squares) and measures how often
people from two regions use the same word for the same thing:

| Shared | Means |
|---|---|
| more than ~55% | the same **dialect** |
| ~30–55% | different **dialects** of one language — they can still understand each other |
| less than ~30% | different **languages** — they can't |

A language keeps its identity (and name) for as long as it's spoken in roughly
the same places, however much it changes. A new language is announced only when
a group can no longer understand the people it came from, and only after that
has lasted 5 years; a language is declared dead after 5 years without speakers.
Each language is named after its own word for "us" — or, if its speakers
haven't settled on one, a name made from its own most typical sounds. Dialects
are named by where they're spoken: *Eastern Bo*, *Coastal Bo*, *Highland Bo*.

Expect dialects within a century or two, and separate languages only after many
centuries apart — about as slow, relative to generations, as in real history.

In the viewer: the **Languages** panel lists every language with its speakers,
dialects (and the words that set them apart), where it came from, and its
words; **Show → Languages** maps where each is spoken; a person's page shows
their name, language and dialect, accent, and every word they know.

## About minds

People now carry the past with them. Open anyone and look under **Mind**:

- **Memories** — up to ten things that happened to them: the birth of a
  child, a partner who died (and how), the place a predator killed someone,
  a valley where they ate well, a place they nearly died of thirst, the day
  they worked out how to make something, the first time they met people who
  call themselves by another name. Memories fade (a lost child slowly, a good
  meal quickly); when there's no room, the faintest is forgotten. They die
  with the person.
- **Feelings** — joy, fear, grief and loneliness, each rising with what
  happens and slowly settling back.
- **A goal** — what matters most to them right now: find water, stay safe,
  mourn, look after the baby, find a partner, learn from someone, explore…

What follows from that isn't scripted — there are just a few simple effects:

- households steer clear of places where bad things happened to them, and
  go back to places they remember eating well (so families can start
  following their own seasonal rounds);
- frightened people move away from predator country, even from good land;
- lonely people are pulled harder toward others;
- someone grieving forages less for a while;
- people have words for how they feel (afraid, sad, happy, alone, dead) and
  use them when they feel it.

The **Mood** map layer shows how people feel in each place, and the
**Feelings** chart tracks the world's average joy, fear, grief and
loneliness. Up close, people's thoughts now come from their memories
("Predators took someone here. Stay close.", "«mate»… «gone».").

The strength of each effect is a setting in `[minds]`. These inner lives are
also what the AI voices (Phase C) will work from: an AI can only give someone
believable thoughts if it knows what they remember and how they feel.

**Updating:** new kinds of physics only apply to **new** worlds (an existing
world keeps the rules it was born with). When you update, any new settings
sections are added to your settings file automatically, so the next world
you create gets minds.

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
  language.py  sounds, coining and copying words, sound change, names, finding languages
  minds.py     memories, feelings and goals
  observer.py  measures the world and writes history (read-only)
  closeup.py   turns a simulated day into a scene to watch (read-only)
  storage.py   checkpoints, thinning, storage cap, history database
  runner.py    keeps the world ticking in the background
  server.py    small web server (Python standard library only)
web/           the viewer (one page, three.js for 3D; closeup.js draws close-up mode)
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

The goal is open-ended: people who keep inventing — tools, fire for many uses,
camps, houses, farming, metals, machines — and, if their world allows it,
towns, cities and transport. Each stage adds *physics* (what is possible),
never outcomes.

| Stage | Adds | You'll see |
|---|---|---|
| **1. The World** ✅ | terrain, rivers, climate, seasons, plants & animals, save/rewind, 3D viewer | a living landscape |
| **2. People** ✅ | needs, foraging, aging, births, families, death, inherited traits | bands surviving or starving |
| **3. Learning** ✅ | skills, imitation, a first set of techniques, knowledge that can be lost | discoveries spreading and dying out |
| **4. Language** ✅ | invented words, accents, dialects, languages, names | groups that drift apart in speech |
| 5. Open-ended making | materials with physical properties; processes (strike, cut, heat, mix, shape, bind…); things built from other things, without limit; fire temperatures; uses that follow from properties; every invention gets words | an ever-growing, different set of inventions in every world |
| 6. Building & settling | structures on the map built from real materials (windbreaks → huts → houses → storehouses, walls); staying put; storage | the first camps, then villages, visible in 3D |
| 7. Farming & herding | plants and animals that change when people replant and tame them | fields and herds around settlements |
| 8. Society | memory of others, reputation, sharing, grudges, group identity, leadership | bands, alliances, feuds, chiefs — or none |
| 9. Specialisation & trade | skills that pay off, exchange between people and groups | crafts, markets, maybe money |
| 10. Metals & machines | high-temperature physics (smelting, alloys), levers, wheels, boats | metalworking, carts, river and sea travel |
| 11. Towns & cities | dense building, roads worn by traffic, public works, structures limited by material strength | towns, cities, skylines |
| 12. Power & industry | water, wind and heat as energy; deeper chemistry; more physics as people reach it | mills, engines — wherever they get to |
| alongside | **realism**: A. close-up mode ✅ · B. richer minds (memories, feelings, goals) ✅ · C. AI voices (a local language model gives people real thoughts and conversations, in their own words) · D. experiments with AI-driven decisions | people you can watch, and who feel real |
| ongoing | speed (a compiled core for big worlds), history and "why did this happen?" tools, experiments that compare worlds | |

Nothing on this list is guaranteed to happen in any given world — that's the
point. The physics sets what's possible; the people decide what happens.
