// Evolution in the browser. The same algorithm the big offline runs use
// (MAP-Elites with a fluke check), on however many cores this device has.

/** Start one evaluation worker. The single-file build replaces this. */
export const workerFactory = { make: () => new Worker(new URL('./worker.js', import.meta.url), { type: 'module' }) };

const PART_COST = 0.02;
const ROBUST_FRACTION = 0.6;
const FOUNDERS = 240;

// Must match `dims_for` in cli/src/evo.rs.
export function dimsFor(task) {
  if (task === 'swim') {
    return [
      { name: 'parts', lo: 2, hi: 15, bins: 13 },
      { name: 'spread', lo: 0.5, hi: 1.7, bins: 8 },
    ];
  }
  if (task === 'walk') {
    return [
      { name: 'feet', lo: 1, hi: 9, bins: 8 },
      { name: 'stature', lo: 0.4, hi: 2.0, bins: 8 },
    ];
  }
  return [
    { name: 'feet', lo: 1, hi: 9, bins: 8 },
    { name: 'tiptoe', lo: 0, hi: 1, bins: 8 },
  ];
}

function trait(name, e) {
  if (name === 'parts') return e.parts + 0.5;
  if (name === 'feet') return e.feet + 0.5;
  return e[name];
}

function bin(dim, x) {
  const t = Math.min(0.999999, Math.max(0, (x - dim.lo) / (dim.hi - dim.lo)));
  return Math.floor(t * dim.bins);
}

// Rank within a cell: score, discounted a little per body part, so limbs
// that add nothing lose to the same animal without them.
const standing = (e) => e.fitness * (1 - PART_COST) ** e.parts;

export class Nursery {
  constructor(eng, module, task, onChange) {
    this.eng = eng; // main-thread simulator, used for mutation
    this.module = module;
    this.task = task;
    this.onChange = onChange;
    this.dims = dimsFor(task);
    this.cells = new Map();
    this.evals = 0;
    this.flukes = 0;
    this.nextId = 1;
    this.running = false;
    this.workers = [];
    this.idle = [];
    this.checks = []; // candidates awaiting their fluke check
    this.jobs = new Map();
    this.history = [];
    this.startedAt = 0;
    this.elapsed = 0;
    this.lineages = [];
    this.live = true;
    this.error = null;
    this.spawning = null;
  }

  get elites() {
    return [...this.cells.values()];
  }

  get best() {
    let b = null;
    for (const e of this.cells.values()) if (!b || e.fitness > b.fitness) b = e;
    return b;
  }

  get rate() {
    const secs = this.elapsed + (this.running ? (performance.now() - this.startedAt) / 1000 : 0);
    return secs > 0 ? this.evals / secs : 0;
  }

  /** Ancestors of an elite, oldest first, thinned to at most `max`. */
  lineageOf(elite, max = 48) {
    const chain = [];
    for (let e = elite; e; e = e.parent) chain.push(e);
    chain.reverse();
    if (chain.length <= max) return chain;
    return [...Array(max).keys()].map((i) => chain[Math.round((i * (chain.length - 1)) / (max - 1))]);
  }

  async start() {
    if (this.running) return;
    this.error = null;
    this.running = true;
    this.startedAt = performance.now();
    try {
      // One set of workers, however many times Start is pressed while
      // they are still coming up.
      if (!this.workers.length && !this.spawning) {
        this.spawning = this.spawn().finally(() => {
          this.spawning = null;
        });
      }
      if (this.spawning) await this.spawning;
    } catch (err) {
      this.running = false;
      this.error = err.message || String(err);
      throw err;
    }
    this.pump();
  }

  /** Bring up one worker per spare core, each with its own simulator. */
  async spawn() {
    const n = Math.max(1, Math.min(12, (navigator.hardwareConcurrency || 4) - 1));
    const made = [];
    try {
      await Promise.all(
        [...Array(n)].map(
          () =>
            new Promise((resolve, reject) => {
              const w = workerFactory.make();
              made.push(w);
              w.onerror = (e) => reject(new Error(e.message || 'a worker failed to start'));
              w.onmessage = (ev) => {
                if (ev.data.type === 'ready') resolve();
                else if (ev.data.type === 'error') reject(new Error(ev.data.message));
              };
              w.postMessage({ type: 'init', module: this.module });
            })
        )
      );
    } catch (err) {
      for (const w of made) w.terminate();
      throw err;
    }
    for (const w of made) {
      w.onmessage = (ev) => this.done(w, ev.data);
      // A worker that dies later is dropped, along with whatever it held.
      w.onerror = () => this.lose(w);
      this.workers.push(w);
      this.idle.push(w);
    }
  }

  lose(w) {
    w.terminate();
    this.workers = this.workers.filter((x) => x !== w);
    this.idle = this.idle.filter((x) => x !== w);
    for (const [id, job] of this.jobs) if (job.worker === w) this.jobs.delete(id);
  }

  stop() {
    if (!this.running) return;
    this.running = false;
    this.elapsed += (performance.now() - this.startedAt) / 1000;
  }

  /** Pause and give the cores back. Everything bred so far is kept. */
  park() {
    this.stop();
    for (const w of this.workers) w.terminate();
    this.workers = [];
    this.idle = [];
    this.jobs.clear();
  }

  seed() {
    return Math.floor(Math.random() * 2 ** 52);
  }

  index(ev) {
    return this.dims.map((d) => bin(d, trait(d.name, ev)));
  }

  wants(ev) {
    if (!ev || !ev.valid || !(ev.fitness > 0)) return false;
    const old = this.cells.get(this.index(ev).join(','));
    return !old || standing(ev) > standing(old.eval);
  }

  /** Hand every idle worker something to do. */
  pump() {
    while (this.running && this.idle.length) {
      const w = this.idle.pop();
      let job;
      if (this.checks.length) {
        job = { ...this.checks.shift(), wobble: true };
      } else {
        const elites = this.elites;
        let genome;
        let parent = null;
        if (this.evals < FOUNDERS || !elites.length) {
          genome = this.eng.randomGenome(this.seed());
        } else {
          parent = elites[Math.floor(Math.random() * elites.length)];
          genome = parent.genome;
          if (Math.random() < 0.12) {
            const other = elites[Math.floor(Math.random() * elites.length)];
            genome = this.eng.cross(genome, other.genome, this.seed());
          }
          genome = this.eng.mutate(genome, this.seed());
        }
        job = { genome, parent, wobble: false };
      }
      job.id = this.nextId++;
      job.worker = w;
      this.jobs.set(job.id, job);
      w.postMessage({ type: 'eval', id: job.id, genome: job.genome, task: this.task, wobble: job.wobble });
    }
  }

  done(w, msg) {
    if (!this.workers.includes(w)) return;
    this.idle.push(w);
    const job = this.jobs.get(msg.id);
    this.jobs.delete(msg.id);
    if (job) {
      const ev = msg.eval;
      if (!job.wobble) {
        this.evals++;
        // A would-be elite must repeat itself under shaken conditions first.
        if (this.wants(ev)) this.checks.push({ genome: job.genome, parent: job.parent, eval: ev });
      } else if (!(ev && ev.valid && ev.fitness >= ROBUST_FRACTION * job.eval.fitness)) {
        // Couldn't do it twice.
        this.flukes++;
      } else if (this.wants(job.eval)) {
        const cell = this.index(job.eval);
        const wasBest = this.best;
        const elite = {
          cell,
          id: job.id,
          depth: job.parent ? job.parent.depth + 1 : 0,
          born: this.evals,
          fitness: job.eval.fitness,
          eval: job.eval,
          genome: job.genome,
          parent: job.parent,
        };
        this.cells.set(cell.join(','), elite);
        if (!wasBest || elite.fitness > wasBest.fitness) this.history.push({ evals: this.evals, best: elite.fitness });
        this.onChange(elite, !wasBest || elite.fitness > wasBest.fitness);
      }
    }
    this.pump();
  }
}
