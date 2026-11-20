//! Browser bindings: a plain C ABI over the simulator, so the page needs no
//! generated glue and the exact code that scored a creature during evolution
//! is the code that animates it on screen.
//!
//! Pointers returned by the `mg_*` getters point into buffers owned by the
//! world and stay valid until the next call on that world.

use menagerie_core::env::{terrain_for, Episode, Task};
use menagerie_core::genome::Genome;
use menagerie_core::rapier3d::math::Vector;
use menagerie_core::sim::{Sim, Terrain};

enum Inner {
    Free(Sim),
    Scored(Episode),
}

pub struct World {
    inner: Inner,
    terrain: Terrain,
    buf: Vec<f32>,
}

impl World {
    fn sim(&self) -> &Sim {
        match &self.inner {
            Inner::Free(s) => s,
            Inner::Scored(e) => &e.sim,
        }
    }
    fn sim_mut(&mut self) -> &mut Sim {
        match &mut self.inner {
            Inner::Free(s) => s,
            Inner::Scored(e) => &mut e.sim,
        }
    }
}

const TASKS: [Task; 7] = [
    Task::Sprint,
    Task::Chase,
    Task::Swim,
    Task::Jump,
    Task::Rough,
    Task::Shove,
    Task::Walk,
];

fn task_from(id: u32) -> Task {
    TASKS[(id as usize) % TASKS.len()]
}

#[no_mangle]
pub extern "C" fn mg_alloc(len: usize) -> *mut u8 {
    let mut v = Vec::<u8>::with_capacity(len.max(1));
    let p = v.as_mut_ptr();
    core::mem::forget(v);
    p
}

/// # Safety
/// `ptr`/`len` must come from `mg_alloc(len)`.
#[no_mangle]
pub unsafe extern "C" fn mg_free(ptr: *mut u8, len: usize) {
    drop(Vec::from_raw_parts(ptr, 0, len.max(1)));
}

unsafe fn genome_from(ptr: *const u8, len: usize) -> Option<Genome> {
    let bytes = core::slice::from_raw_parts(ptr, len);
    serde_json::from_slice(bytes).ok()
}

/// An open world for the given task's terrain and physics, with no
/// creatures and no scoring. `collide` makes creatures solid to each other.
#[no_mangle]
pub extern "C" fn mg_world_new(task: u32, trial: u32, collide: u32) -> *mut World {
    let task = task_from(task);
    let terrain = terrain_for(task, trial as usize);
    let mut params = task.params();
    params.creatures_collide = collide != 0;
    let mut sim = Sim::new(params, &terrain);
    sim.wait_for_rest = true;
    Box::into_raw(Box::new(World {
        inner: Inner::Free(sim),
        terrain,
        buf: Vec::new(),
    }))
}

/// A scored episode: one creature on one trial, exactly as evolution ran it.
///
/// # Safety
/// `json` must point to `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn mg_episode_new(
    json: *const u8,
    len: usize,
    task: u32,
    trial: u32,
) -> *mut World {
    let task = task_from(task);
    let Some(g) = genome_from(json, len) else {
        return core::ptr::null_mut();
    };
    let terrain = terrain_for(task, trial as usize);
    let ep = Episode::new(&g, task, trial as usize, &task.params());
    Box::into_raw(Box::new(World {
        inner: Inner::Scored(ep),
        terrain,
        buf: Vec::new(),
    }))
}

/// # Safety
/// `w` must be a live world pointer; it is dead after this call.
#[no_mangle]
pub unsafe extern "C" fn mg_world_free(w: *mut World) {
    if !w.is_null() {
        drop(Box::from_raw(w));
    }
}

/// Add a creature at (x, z) facing `yaw`. Returns its index or -1.
///
/// # Safety
/// `w` must be live; `json` must point to `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn mg_add(
    w: *mut World,
    json: *const u8,
    len: usize,
    x: f32,
    y: f32,
    z: f32,
    yaw: f32,
) -> i32 {
    let w = &mut *w;
    let Some(g) = genome_from(json, len) else {
        return -1;
    };
    match &mut w.inner {
        Inner::Free(sim) => sim.add_creature(&g, Vector::new(x, y, z), yaw) as i32,
        Inner::Scored(_) => -1,
    }
}

/// # Safety
/// `w` must be live.
#[no_mangle]
pub unsafe extern "C" fn mg_step(w: *mut World, n: u32) {
    let w = &mut *w;
    for _ in 0..n {
        match &mut w.inner {
            Inner::Free(sim) => sim.step(),
            Inner::Scored(ep) => {
                if !ep.done() {
                    ep.step()
                }
            }
        }
    }
}

/// # Safety
/// `w` must be live.
#[no_mangle]
pub unsafe extern "C" fn mg_count(w: *const World) -> u32 {
    (*w).sim().creatures.len() as u32
}

/// # Safety
/// `w` must be live.
#[no_mangle]
pub unsafe extern "C" fn mg_parts(w: *const World, c: u32) -> u32 {
    (*w).sim()
        .creatures
        .get(c as usize)
        .map(|c| c.bp.parts.len() as u32)
        .unwrap_or(0)
}

/// Per part: half extents (3), depth, mirrored flag, gene index, parent
/// index (-1 for the root), rounding radius. Eight floats each.
///
/// # Safety
/// `w` must be live.
#[no_mangle]
pub unsafe extern "C" fn mg_shapes(w: *mut World, c: u32) -> *const f32 {
    let w = &mut *w;
    let mut buf = core::mem::take(&mut w.buf);
    buf.clear();
    if let Some(cr) = w.sim().creatures.get(c as usize) {
        for p in cr.bp.parts.iter() {
            let r = 0.15 * p.half.x.min(p.half.y).min(p.half.z);
            buf.extend_from_slice(&[
                p.half.x,
                p.half.y,
                p.half.z,
                p.depth as f32,
                if p.flip { 1.0 } else { 0.0 },
                p.gene as f32,
                p.parent.map(|x| x as f32).unwrap_or(-1.0),
                r,
            ]);
        }
    }
    w.buf = buf;
    w.buf.as_ptr()
}

/// Per part: position (3) and rotation quaternion xyzw (4), then the touch
/// sensor (1). Eight floats each.
///
/// # Safety
/// `w` must be live.
#[no_mangle]
pub unsafe extern "C" fn mg_transforms(w: *mut World, c: u32) -> *const f32 {
    let w = &mut *w;
    let mut buf = core::mem::take(&mut w.buf);
    buf.clear();
    let sim = w.sim();
    if let Some(cr) = sim.creatures.get(c as usize) {
        for (i, &b) in cr.bodies.iter().enumerate() {
            let rb = &sim.world.bodies[b];
            let t = rb.translation();
            let r = rb.rotation();
            buf.extend_from_slice(&[t.x, t.y, t.z, r.x, r.y, r.z, r.w, cr.contact[i]]);
        }
    }
    w.buf = buf;
    w.buf.as_ptr()
}

/// Creature summary: centre of mass (3), goal (3), exploded flag, mass,
/// velocity (3), hue. Twelve floats.
///
/// # Safety
/// `w` must be live.
#[no_mangle]
pub unsafe extern "C" fn mg_state(w: *mut World, c: u32) -> *const f32 {
    let w = &mut *w;
    let mut buf = core::mem::take(&mut w.buf);
    buf.clear();
    let sim = w.sim();
    if let Some(cr) = sim.creatures.get(c as usize) {
        let com = sim.com(c as usize);
        let v = sim.com_vel(c as usize);
        buf.extend_from_slice(&[
            com.x,
            com.y,
            com.z,
            cr.goal.x,
            cr.goal.y,
            cr.goal.z,
            if cr.exploded { 1.0 } else { 0.0 },
            cr.mass,
            v.x,
            v.y,
            v.z,
            cr.bp.hue,
        ]);
    }
    w.buf = buf;
    w.buf.as_ptr()
}

/// # Safety
/// `w` must be live.
#[no_mangle]
pub unsafe extern "C" fn mg_set_goal(w: *mut World, c: u32, x: f32, y: f32, z: f32) {
    if let Some(cr) = (*w).sim_mut().creatures.get_mut(c as usize) {
        cr.goal = Vector::new(x, y, z);
    }
}

/// Shift a creature's internal clock so copies don't move in lockstep.
///
/// # Safety
/// `w` must be live.
#[no_mangle]
pub unsafe extern "C" fn mg_set_clock(w: *mut World, c: u32, offset: f32) {
    if let Some(cr) = (*w).sim_mut().creatures.get_mut(c as usize) {
        cr.clock_offset = offset;
    }
}

/// # Safety
/// `w` must be live.
#[no_mangle]
pub unsafe extern "C" fn mg_time(w: *const World) -> f32 {
    (*w).sim().time
}

/// Seconds of standing still before the controller starts.
///
/// # Safety
/// `w` must be live.
#[no_mangle]
pub unsafe extern "C" fn mg_settle(w: *const World) -> f32 {
    (*w).sim().params.settle
}

/// Scored episodes only: progress, fitness, goals reached, done flag,
/// total seconds. Five floats (zeros for open worlds).
///
/// # Safety
/// `w` must be live.
#[no_mangle]
pub unsafe extern "C" fn mg_score(w: *mut World) -> *const f32 {
    let w = &mut *w;
    let mut buf = core::mem::take(&mut w.buf);
    buf.clear();
    match &w.inner {
        Inner::Scored(ep) => buf.extend_from_slice(&[
            ep.progress,
            ep.fitness(),
            ep.goals_reached as f32,
            if ep.done() { 1.0 } else { 0.0 },
            ep.total_seconds(),
        ]),
        Inner::Free(_) => buf.extend_from_slice(&[0.0; 5]),
    }
    w.buf = buf;
    w.buf.as_ptr()
}

/// Terrain for rendering: [nx, nz, size_x, size_z, centre_x, centre_z,
/// heights...]. `nx` is 0 for flat ground, -1 for a disc (then size_x is
/// its radius), -2 for open water.
///
/// # Safety
/// `w` must be live.
#[no_mangle]
pub unsafe extern "C" fn mg_terrain(w: *mut World) -> *const f32 {
    let w = &mut *w;
    let mut buf = core::mem::take(&mut w.buf);
    buf.clear();
    let water = w.sim().params.medium == menagerie_core::sim::Medium::Water;
    match &w.terrain {
        _ if water => buf.extend_from_slice(&[-2.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        Terrain::Flat => buf.extend_from_slice(&[0.0; 6]),
        Terrain::Disc { radius } => buf.extend_from_slice(&[-1.0, 0.0, *radius, 0.0, 0.0, 0.0]),
        Terrain::Heights {
            nx,
            nz,
            heights,
            size,
            centre,
        } => {
            buf.extend_from_slice(&[
                *nx as f32, *nz as f32, size[0], size[1], centre[0], centre[1],
            ]);
            buf.extend_from_slice(heights);
        }
    }
    w.buf = buf;
    w.buf.as_ptr()
}

// ---------------------------------------------------------------------
// Breeding in the browser: the same genome operators and scoring the
// native evolution loop uses, one call each. Results that are text come
// back through a shared output buffer (`mg_out_ptr` / `mg_out_len`).

use menagerie_core::env::{evaluate, wobbled};
use menagerie_core::rng::Rng;
use std::sync::Mutex;

static OUT: Mutex<Vec<u8>> = Mutex::new(Vec::new());

fn set_out(bytes: Vec<u8>) -> usize {
    let mut out = OUT.lock().unwrap();
    *out = bytes;
    out.len()
}

#[no_mangle]
pub extern "C" fn mg_out_ptr() -> *const u8 {
    OUT.lock().unwrap().as_ptr()
}

#[no_mangle]
pub extern "C" fn mg_out_len() -> usize {
    OUT.lock().unwrap().len()
}

fn seed64(lo: u32, hi: u32) -> u64 {
    (hi as u64) << 32 | lo as u64
}

/// A random founder genome. Returns the JSON length (see `mg_out_ptr`).
#[no_mangle]
pub extern "C" fn mg_random(seed_lo: u32, seed_hi: u32) -> usize {
    let g = Genome::random(&mut Rng::new(seed64(seed_lo, seed_hi)));
    set_out(serde_json::to_vec(&g).unwrap())
}

/// A mutated copy of a genome. Returns the JSON length, 0 on bad input.
///
/// # Safety
/// `json` must point to `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn mg_mutate(
    json: *const u8,
    len: usize,
    seed_lo: u32,
    seed_hi: u32,
) -> usize {
    let Some(g) = genome_from(json, len) else {
        return 0;
    };
    let child = g.mutated(&mut Rng::new(seed64(seed_lo, seed_hi)));
    set_out(serde_json::to_vec(&child).unwrap())
}

/// A limb of `b` grafted onto `a`. Returns the JSON length, 0 on bad input.
///
/// # Safety
/// Both pointers must be readable for their lengths.
#[no_mangle]
pub unsafe extern "C" fn mg_cross(
    a: *const u8,
    a_len: usize,
    b: *const u8,
    b_len: usize,
    seed_lo: u32,
    seed_hi: u32,
) -> usize {
    let (Some(ga), Some(gb)) = (genome_from(a, a_len), genome_from(b, b_len)) else {
        return 0;
    };
    let child = ga.crossed(&gb, &mut Rng::new(seed64(seed_lo, seed_hi)));
    set_out(serde_json::to_vec(&child).unwrap())
}

/// Score a genome on every trial of a task; `wobble` selects the slightly
/// perturbed conditions used to weed out flukes. Returns the length of the
/// result JSON (an `Eval`), 0 on bad input.
///
/// # Safety
/// `json` must point to `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn mg_evaluate(json: *const u8, len: usize, task: u32, wobble: u32) -> usize {
    let Some(g) = genome_from(json, len) else {
        return 0;
    };
    let task = task_from(task);
    let params = if wobble != 0 {
        wobbled(&task.params())
    } else {
        task.params()
    };
    let eval = evaluate(&g, task, &params);
    set_out(serde_json::to_vec(&eval).unwrap())
}

/// A scored episode with the old rounded-box colliders and no glitch
/// checks: the conditions under which evolution found the catapult.
///
/// # Safety
/// `json` must point to `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn mg_episode_legacy(json: *const u8, len: usize, task: u32) -> *mut World {
    let task = task_from(task);
    let Some(g) = genome_from(json, len) else {
        return core::ptr::null_mut();
    };
    let terrain = terrain_for(task, 0);
    let mut params = task.params();
    params.rounded = true;
    params.density = 700.0;
    params.torque_per_area = 6000.0;
    params.settle = 1.5;
    params.preroll = false;
    params.max_speed = 1.0e9;
    let ep = Episode::new(&g, task, 0, &params);
    Box::into_raw(Box::new(World {
        inner: Inner::Scored(ep),
        terrain,
        buf: Vec::new(),
    }))
}

// ---------------------------------------------------------------------
// Crates and the sumo ring.

/// A round platform of the given radius where creatures are solid to each
/// other. Add two and see who stays on.
#[no_mangle]
pub extern "C" fn mg_arena_new(radius: f32) -> *mut World {
    let terrain = Terrain::Disc { radius };
    let mut params = Task::Sprint.params();
    params.creatures_collide = true;
    let mut sim = Sim::new(params, &terrain);
    sim.wait_for_rest = true;
    Box::into_raw(Box::new(World {
        inner: Inner::Free(sim),
        terrain,
        buf: Vec::new(),
    }))
}

/// Drop a cubic crate into an open world. Returns its index or -1.
///
/// # Safety
/// `w` must be live.
#[no_mangle]
pub unsafe extern "C" fn mg_add_crate(
    w: *mut World,
    x: f32,
    y: f32,
    z: f32,
    half: f32,
    mass: f32,
) -> i32 {
    match &mut (*w).inner {
        Inner::Free(sim) => sim.add_crate(Vector::new(x, y, z), Vector::splat(half), mass) as i32,
        Inner::Scored(_) => -1,
    }
}

/// # Safety
/// `w` must be live.
#[no_mangle]
pub unsafe extern "C" fn mg_crates(w: *const World) -> u32 {
    (*w).sim().crates.len() as u32
}

/// Crate pose and size: position (3), rotation xyzw (4), half extents (3).
///
/// # Safety
/// `w` must be live.
#[no_mangle]
pub unsafe extern "C" fn mg_crate(w: *mut World, i: u32) -> *const f32 {
    let w = &mut *w;
    let mut buf = core::mem::take(&mut w.buf);
    buf.clear();
    let sim = w.sim();
    if let Some(c) = sim.crates.get(i as usize) {
        let rb = &sim.world.bodies[c.body];
        let t = rb.translation();
        let r = rb.rotation();
        buf.extend_from_slice(&[
            t.x, t.y, t.z, r.x, r.y, r.z, r.w, c.half.x, c.half.y, c.half.z,
        ]);
    } else {
        buf.extend_from_slice(&[0.0; 10]);
    }
    w.buf = buf;
    w.buf.as_ptr()
}

/// How far ahead (+z) a creature currently reaches.
///
/// # Safety
/// `w` must be live.
#[no_mangle]
pub unsafe extern "C" fn mg_front(w: *const World, c: u32) -> f32 {
    let sim = (*w).sim();
    if (c as usize) < sim.creatures.len() {
        sim.front(c as usize)
    } else {
        0.0
    }
}
