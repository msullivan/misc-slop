// Thin wrapper over the simulator's C ABI. No generated glue: the module
// imports nothing, so loading it is one instantiate call.

export const TASKS = ['sprint', 'chase', 'swim', 'jump', 'rough', 'shove', 'walk'];

/** Fetch and compile the simulator once; the module can be posted to workers. */
export async function compileEngine(url) {
  try {
    return await WebAssembly.compileStreaming(fetch(url));
  } catch {
    return WebAssembly.compile(await (await fetch(url)).arrayBuffer());
  }
}

export async function loadEngine(source) {
  // `source` is a URL, a compiled module, a Response/Promise<Response>, or raw bytes.
  let instance;
  if (source instanceof WebAssembly.Module) {
    instance = await WebAssembly.instantiate(source, {});
  } else if (source instanceof ArrayBuffer || ArrayBuffer.isView(source)) {
    ({ instance } = await WebAssembly.instantiate(source, {}));
  } else {
    // Streaming needs the right MIME type; fall back to plain bytes.
    const resp = await (typeof source === 'string' ? fetch(source) : source);
    const spare = resp.clone();
    try {
      ({ instance } = await WebAssembly.instantiateStreaming(resp, {}));
    } catch {
      ({ instance } = await WebAssembly.instantiate(await spare.arrayBuffer(), {}));
    }
  }
  return new Engine(instance.exports);
}

const enc = new TextEncoder();
const dec = new TextDecoder();

class Engine {
  constructor(x) {
    this.x = x;
  }

  f32(ptr, n) {
    return new Float32Array(this.x.memory.buffer, ptr, n);
  }

  withJson(genome, fn) {
    const bytes = enc.encode(typeof genome === 'string' ? genome : JSON.stringify(genome));
    const ptr = this.x.mg_alloc(bytes.length);
    new Uint8Array(this.x.memory.buffer, ptr, bytes.length).set(bytes);
    try {
      return fn(ptr, bytes.length);
    } finally {
      this.x.mg_free(ptr, bytes.length);
    }
  }

  /** The text result of the last call that produced one. */
  out(len) {
    if (!len) throw new Error('simulator rejected the genome');
    // Copy out of wasm memory before decoding: the view dies if memory grows.
    return dec.decode(new Uint8Array(this.x.memory.buffer, this.x.mg_out_ptr(), len).slice());
  }

  // Seeds are doubles holding up to 53 random bits; split for the wasm ABI.
  randomGenome(seed) {
    return JSON.parse(this.out(this.x.mg_random(seed >>> 0, Math.floor(seed / 2 ** 32) >>> 0)));
  }

  mutate(genome, seed) {
    return JSON.parse(
      this.withJson(genome, (p, n) => this.out(this.x.mg_mutate(p, n, seed >>> 0, Math.floor(seed / 2 ** 32) >>> 0)))
    );
  }

  cross(a, b, seed) {
    return JSON.parse(
      this.withJson(a, (pa, na) =>
        this.withJson(b, (pb, nb) => this.out(this.x.mg_cross(pa, na, pb, nb, seed >>> 0, Math.floor(seed / 2 ** 32) >>> 0)))
      )
    );
  }

  /** Score a genome on all trials of a task, as evolution does. */
  evaluate(genome, task, wobble = false) {
    return JSON.parse(this.withJson(genome, (p, n) => this.out(this.x.mg_evaluate(p, n, TASKS.indexOf(task), wobble ? 1 : 0))));
  }

  /** A run under the early, exploitable physics (for the cheat exhibit). */
  legacyEpisode(genome, task) {
    const ptr = this.withJson(genome, (p, n) => this.x.mg_episode_legacy(p, n, TASKS.indexOf(task)));
    if (!ptr) throw new Error('bad genome');
    return new World(this, ptr, task);
  }

  /** An open world: add creatures, set goals, no scoring. */
  world(task, { trial = 0, collide = false } = {}) {
    const ptr = this.x.mg_world_new(TASKS.indexOf(task), trial, collide ? 1 : 0);
    return new World(this, ptr, task);
  }

  /** A raised ring where creatures are solid to each other. */
  arena(radius) {
    return new World(this, this.x.mg_arena_new(radius), 'sumo');
  }

  /** A scored run, exactly as evolution evaluated it. */
  episode(genome, task, trial = 0) {
    const ptr = this.withJson(genome, (p, n) => this.x.mg_episode_new(p, n, TASKS.indexOf(task), trial));
    if (!ptr) throw new Error('bad genome');
    return new World(this, ptr, task);
  }
}

class World {
  constructor(eng, ptr, task) {
    this.eng = eng;
    this.ptr = ptr;
    this.task = task;
  }

  free() {
    if (this.ptr) this.eng.x.mg_world_free(this.ptr);
    this.ptr = 0;
  }

  add(genome, x = 0, y = 0, z = 0, yaw = 0) {
    return this.eng.withJson(genome, (p, n) => this.eng.x.mg_add(this.ptr, p, n, x, y, z, yaw));
  }

  step(n = 1) {
    this.eng.x.mg_step(this.ptr, n);
  }

  get count() {
    return this.eng.x.mg_count(this.ptr);
  }

  get time() {
    return this.eng.x.mg_time(this.ptr);
  }

  get settle() {
    return this.eng.x.mg_settle(this.ptr);
  }

  parts(c = 0) {
    return this.eng.x.mg_parts(this.ptr, c);
  }

  /** Copy of per-part static shape data: 8 floats each. */
  shapes(c = 0) {
    const n = this.parts(c);
    return Float32Array.from(this.eng.f32(this.eng.x.mg_shapes(this.ptr, c), n * 8));
  }

  /** View of per-part pose data (8 floats each); valid until the next call. */
  transforms(c = 0) {
    const n = this.parts(c);
    return this.eng.f32(this.eng.x.mg_transforms(this.ptr, c), n * 8);
  }

  state(c = 0) {
    const s = this.eng.f32(this.eng.x.mg_state(this.ptr, c), 12);
    return {
      com: [s[0], s[1], s[2]],
      goal: [s[3], s[4], s[5]],
      exploded: s[6] > 0,
      mass: s[7],
      vel: [s[8], s[9], s[10]],
      hue: s[11],
    };
  }

  addCrate(x, y, z, half, mass) {
    return this.eng.x.mg_add_crate(this.ptr, x, y, z, half, mass);
  }

  get crates() {
    return this.eng.x.mg_crates(this.ptr);
  }

  /** Pose and size of a crate; a view valid until the next call. */
  crate(i = 0) {
    return this.eng.f32(this.eng.x.mg_crate(this.ptr, i), 10);
  }

  /** How far along +z the creature currently reaches. */
  front(c = 0) {
    return this.eng.x.mg_front(this.ptr, c);
  }

  setGoal(c, x, y, z) {
    this.eng.x.mg_set_goal(this.ptr, c, x, y, z);
  }

  setClock(c, offset) {
    this.eng.x.mg_set_clock(this.ptr, c, offset);
  }

  score() {
    const s = this.eng.f32(this.eng.x.mg_score(this.ptr), 5);
    return { progress: s[0], fitness: s[1], goals: s[2], done: s[3] > 0, seconds: s[4] };
  }

  terrain() {
    const head = Float32Array.from(this.eng.f32(this.eng.x.mg_terrain(this.ptr), 6));
    const nx = head[0];
    if (nx === -2) return { kind: 'water' };
    if (nx === -1) return { kind: 'disc', radius: head[2] };
    if (nx === 0) return { kind: 'flat' };
    const nz = head[1];
    const all = this.eng.f32(this.eng.x.mg_terrain(this.ptr), 6 + nx * nz);
    return {
      kind: 'heights',
      nx,
      nz,
      size: [head[2], head[3]],
      centre: [head[4], head[5]],
      heights: Float32Array.from(all.subarray(6)),
    };
  }
}
