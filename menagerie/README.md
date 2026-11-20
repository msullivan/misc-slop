# Menagerie

Animals nobody designed. Body plans and gaits are bred from random boxes by
an evolutionary search, scored only on how well they do a job: cover ground,
stay on their legs, chase a flag, shove a crate, swim, jump. The page in
`web/` is a zoo of the results, running the same physics in your browser
that scored them.

In the spirit of Karl Sims's 1994 *Evolving Virtual Creatures*, with a
modern search (MAP-Elites) and a physics engine somebody else wrote.

## Look at it

    cd web && python3 -m http.server 8765
    # then open http://localhost:8765/

Needs a browser with WebAssembly and WebGL. Nothing to build: the compiled
simulator (`web/mg.wasm`) and the evolved creatures (`web/data/`) are checked
in.

What's there:

- **The collection.** Seven habitats. For each, a map of every kind of
  creature evolution kept, sorted by two traits (how many feet, how high off
  the ground). Click a square to meet its occupant.
- **Trial** replays the exact run a creature was scored on, step for step.
  **Roam** lets it loose with no clock; click the ground to plant a flag and
  see if it can steer. **Lineage** lines up its ancestors, founder to
  present, and starts them together. **Race** does the same with each
  family's champion. **Sumo** puts it in a ring with the last creature you
  looked at.
- **Breed your own** runs the evolution live on your machine's cores. Random
  boxes become things that crawl within a minute or so.
- **The one that cheated.** An early sprint champion that scored 17.7 m by
  sitting still and then exploiting a bug in the physics engine to launch
  itself ten metres into the air. Preserved, with the bug, as an exhibit.

## How it works

**Genome.** A tree of boxes. Each box is hinged to its parent somewhere on
one of the parent's faces. Two operators make bodies look like animals
instead of junk piles: `mirror` builds a limb's reflection on the other side
of its parent, and `repeat` builds a chain of copies, each on the tip of the
last. Limbs must be limb-shaped (longer than thick) and may not start out
intersecting each other.

**Muscles.** One hinge per joint, driven by a position motor whose torque
limit scales with the joint's cross-section, so big animals are weak for
their weight the way real ones are.

**Brain.** Each joint follows a body-wide clock:

    osc    = sin(phase) + h2 * sin(2 * phase)
    out    = tanh((amp + wa . sensors) * osc + bias + wb . sensors)

Mirrored and repeated copies of a limb share parameters and differ only by
a phase offset, so one evolved leg yields a trot, a gallop, or a travelling
wave down a tail depending on two numbers. The sensors are the direction to
the goal, which way is up, touch, and the joint's own angle. Most sensor
weights are zero; mutation wakes them up one at a time.

**Search.** [MAP-Elites](https://arxiv.org/abs/1504.04909): rather than one
champion, keep the best creature found for every combination of a few
traits. The variety is what makes the search work, since a mediocre
six-legged thing may be two mutations from a great one. Each habitat is
evolved as several isolated families from different random founders; they
never interbreed, so each finds its own answer.

**Keeping it honest.** Evolution optimises exactly what you measure,
including your bugs. Three defences, all added after catching it cheating:

- Every body comes to rest before its clock starts, so toppling off your own
  legs doesn't count as speed or height.
- A run where the centre of mass gains more than 1 m/s in a single 60th of
  a second is thrown out as a physics glitch.
- Anything about to enter the collection must repeat its performance with
  slightly less grip, slightly weaker muscles, and a small turn at the
  start. Tricks that depend on one lucky collision don't survive that.

Parts also have to earn their keep: within a cell of the map, creatures are
ranked on score discounted 2% per body part, so a limb that does nothing
loses to the same animal without it.

**Same physics everywhere.** The simulator is one Rust crate compiled both
natively (for evolution) and to WebAssembly (for the page), and the two
produce bit-identical trajectories: `tools/check_wasm.mjs` replays every
creature in the collection under WebAssembly and compares scores. Getting
there took routing all transcendental maths through `libm` and working
around one place where Rapier calls the platform's `sin`/`cos` (see the
comment on joint limits in `core/src/sim.rs`).

## Layout

    core/    the simulator: genome, body builder, physics, tasks (Rust, uses Rapier)
    cli/     the evolution loop and diagnostics (native only)
    wasm/    C-ABI exports of core for the browser
    web/     the page: three.js viewer, in-browser breeding, data
    tools/   packing, wasm checks, screenshot and filmstrip scripts

## Re-breeding the collection

    cargo build --release
    tools/campaign.sh                 # hours on a 32-core machine
    tools/pack.py web/data sprint=runs/sprint.json walk=runs/walk.json ...
    cargo build --profile web -p menagerie-wasm --target wasm32-unknown-unknown
    cp target/wasm32-unknown-unknown/web/menagerie_wasm.wasm web/mg.wasm
    node tools/check_wasm.mjs web/mg.wasm runs/sprint.json

Useful while poking at it:

    menagerie smoke sprint 4000              # score random bodies; glitch statistics
    menagerie evolve --task walk --islands 6 --evals 600000 --out runs/walk.json
    menagerie diag sprint genome.json 0 60   # per-step trace of one creature
    node tools/strip.mjs out.png --task walk --from 3 --every 0.1 --frames 9
