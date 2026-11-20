//! The genome: a tree of box-shaped body parts, each hinged to its parent,
//! with two operators that make bodies look like animals instead of junk
//! piles: `mirror` (bilateral symmetry) and `repeat` (segmentation).
//!
//! Every part also carries the parameters of the little oscillator-plus-
//! reflex controller that drives its hinge. Mirrored and repeated copies
//! share those parameters, so a limb evolved once works on both sides and
//! on every segment.

use crate::rng::Rng;
use serde::{Deserialize, Serialize};

/// Number of sensor channels each joint controller sees.
pub const NS: usize = 8;
/// Hard cap on instantiated parts per creature.
pub const MAX_PARTS: usize = 14;
/// Hard cap on parts in the genome tree (before mirror/repeat expansion).
pub const MAX_GENES: usize = 8;
pub const MAX_DEPTH: usize = 4;

pub const DIM_MIN: f32 = 0.12;
pub const DIM_MAX: f32 = 0.90;
/// Limbs are limb-shaped: at least this many times longer than thick.
pub const LIMB_ASPECT: f32 = 1.5;
pub const LIMB_THICK_MIN: f32 = 0.09;
pub const LIMB_THICK_MAX: f32 = 0.36;
pub const LIMB_LEN_MIN: f32 = 0.2;
pub const FREQ_MIN: f32 = 0.4;
pub const FREQ_MAX: f32 = 2.2;

const PI: f32 = core::f32::consts::PI;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Genome {
    /// Base oscillator frequency in Hz, shared by the whole body.
    pub freq: f32,
    /// Cosmetic: 0..1 hue, drifts slowly so relatives look related.
    pub hue: f32,
    pub root: Part,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Part {
    /// Full box extents in metres. The part's long axis is +y, and it is
    /// attached to its parent at the centre of its -y face.
    pub dims: [f32; 3],
    pub attach: Attach,
    pub joint: Joint,
    pub ctrl: Ctrl,
    /// Also build a mirror image of this part (and everything hanging off
    /// it), reflected through the parent's local x=0 plane.
    pub mirror: bool,
    /// Build a chain of this many copies, each attached to the tip of the
    /// previous one.
    pub repeat: u8,
    /// Size multiplier applied to each successive copy in a chain.
    pub taper: f32,
    /// How the chain curls: tilt of each copy relative to the previous.
    pub chain_bend: [f32; 2],
    /// Which copies of the *parent's* chain this part attaches to:
    /// 0 = every copy, 1 = first only, 2 = last only.
    pub on: u8,
    pub children: Vec<Part>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Attach {
    /// Parent face: 0..6 = +x -x +y -y +z -z.
    pub face: u8,
    /// Position on that face, each in [-1, 1].
    pub u: f32,
    pub v: f32,
    /// Lean away from the face normal, radians.
    pub tilt: [f32; 2],
    /// Spin about the part's own long axis, radians.
    pub roll: f32,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Joint {
    /// Hinge about the part's long axis instead of across it.
    pub twist: bool,
    /// Direction of a bending hinge within the attachment plane, radians.
    pub axis: f32,
    /// Joint limits in radians; rest pose is angle 0.
    pub lo: f32,
    pub hi: f32,
    /// Fraction of the maximum muscle torque this joint may use.
    pub strength: f32,
}

/// Controller for one hinge:
///
/// ```text
/// osc    = sin(phi + phase) + h2 * sin(2*phi + phase2)
/// out    = tanh((amp + wa . sensors) * osc + bias + wb . sensors)
/// target = out mapped onto [lo, hi]
/// ```
///
/// where `phi` is the body-wide clock, shifted by `chain_phase` per chain
/// segment and by `mirror_phase` on mirrored copies.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Ctrl {
    pub amp: f32,
    pub bias: f32,
    pub phase: f32,
    pub h2: f32,
    pub phase2: f32,
    pub chain_phase: f32,
    pub mirror_phase: f32,
    pub wa: [f32; NS],
    pub wb: [f32; NS],
}

/// Round to four decimals. Genomes are stored as JSON; keeping every number
/// short makes the files a third the size and loses nothing, because the
/// quantised value is what gets evaluated.
fn q4(x: f32) -> f32 {
    (x * 10000.0).round() / 10000.0
}

fn wrap_pi(x: f32) -> f32 {
    let mut y = (x + PI) % (2.0 * PI);
    if y < 0.0 {
        y += 2.0 * PI;
    }
    y - PI
}

fn jig(rng: &mut Rng, x: f32, lo: f32, hi: f32, sigma: f32) -> f32 {
    (x + rng.normal() * sigma * (hi - lo)).clamp(lo, hi)
}

fn jig_wrap(rng: &mut Rng, x: f32, sigma: f32) -> f32 {
    wrap_pi(x + rng.normal() * sigma * 2.0 * PI)
}

impl Ctrl {
    pub fn random(rng: &mut Rng) -> Self {
        Ctrl {
            amp: rng.range(0.4, 1.4) * if rng.chance(0.5) { 1.0 } else { -1.0 },
            bias: rng.range(-0.3, 0.3),
            phase: rng.range(-PI, PI),
            h2: 0.0,
            phase2: rng.range(-PI, PI),
            chain_phase: rng.range(-PI, PI),
            mirror_phase: if rng.chance(0.5) { PI } else { 0.0 },
            wa: [0.0; NS],
            wb: [0.0; NS],
        }
    }

    pub fn mutate(&mut self, rng: &mut Rng, rate: f32, sigma: f32) {
        if rng.chance(rate) {
            self.amp = jig(rng, self.amp, -1.6, 1.6, sigma);
        }
        if rng.chance(rate) {
            self.bias = jig(rng, self.bias, -1.2, 1.2, sigma);
        }
        if rng.chance(rate) {
            self.phase = jig_wrap(rng, self.phase, sigma);
        }
        if rng.chance(rate) {
            self.h2 = jig(rng, self.h2, -0.8, 0.8, sigma);
        }
        if rng.chance(rate) {
            self.phase2 = jig_wrap(rng, self.phase2, sigma);
        }
        if rng.chance(rate) {
            self.chain_phase = jig_wrap(rng, self.chain_phase, sigma);
        }
        if rng.chance(rate) {
            // Mostly snap between in-phase and anti-phase, sometimes drift.
            if rng.chance(0.3) {
                self.mirror_phase = if self.mirror_phase.abs() > PI / 2.0 {
                    0.0
                } else {
                    PI
                };
            } else {
                self.mirror_phase = jig_wrap(rng, self.mirror_phase, sigma * 0.5);
            }
        }
        // Sensor weights are sparse: most stay zero, mutation wakes up one
        // at a time and occasionally puts one back to sleep.
        for w in self.wa.iter_mut().chain(self.wb.iter_mut()) {
            if rng.chance(rate * 0.25) {
                if *w != 0.0 && rng.chance(0.15) {
                    *w = 0.0;
                } else {
                    *w = jig(rng, *w, -2.0, 2.0, sigma);
                }
            }
        }
    }
}

impl Ctrl {
    fn quantize(&mut self) {
        for x in [
            &mut self.amp,
            &mut self.bias,
            &mut self.phase,
            &mut self.h2,
            &mut self.phase2,
            &mut self.chain_phase,
            &mut self.mirror_phase,
        ] {
            *x = q4(*x);
        }
        for w in self.wa.iter_mut().chain(self.wb.iter_mut()) {
            *w = q4(*w);
        }
    }
}

impl Part {
    /// Clamp a non-root part to limb proportions.
    fn limbify(&mut self) {
        let len = self.dims[1].clamp(LIMB_LEN_MIN, DIM_MAX);
        let cap = (len / LIMB_ASPECT).min(LIMB_THICK_MAX);
        self.dims = [
            self.dims[0].clamp(LIMB_THICK_MIN, cap),
            len,
            self.dims[2].clamp(LIMB_THICK_MIN, cap),
        ];
        for c in self.children.iter_mut() {
            c.limbify();
        }
    }

    fn quantize(&mut self) {
        for d in self.dims.iter_mut() {
            *d = q4(*d);
        }
        let a = &mut self.attach;
        a.u = q4(a.u);
        a.v = q4(a.v);
        a.tilt = [q4(a.tilt[0]), q4(a.tilt[1])];
        a.roll = q4(a.roll);
        let j = &mut self.joint;
        j.axis = q4(j.axis);
        j.lo = q4(j.lo);
        j.hi = q4(j.hi);
        j.strength = q4(j.strength);
        self.taper = q4(self.taper);
        self.chain_bend = [q4(self.chain_bend[0]), q4(self.chain_bend[1])];
        self.ctrl.quantize();
        for c in self.children.iter_mut() {
            c.quantize();
        }
    }

    pub fn random(rng: &mut Rng, depth: usize) -> Self {
        let long = rng.range(0.25, 0.8);
        let thick = rng.range(LIMB_THICK_MIN, 0.3);
        let thick2 = rng.range(LIMB_THICK_MIN, 0.3);
        let lo = -rng.range(0.3, 1.2);
        let hi = rng.range(0.3, 1.2);
        let mut p = Part {
            dims: [thick, long, thick2],
            attach: Attach {
                face: rng.below(6) as u8,
                u: rng.range(-1.0, 1.0),
                v: rng.range(-1.0, 1.0),
                tilt: [rng.range(-0.6, 0.6), rng.range(-0.6, 0.6)],
                roll: rng.range(-PI, PI),
            },
            joint: Joint {
                twist: rng.chance(0.1),
                axis: rng.range(0.0, PI),
                lo,
                hi,
                strength: rng.range(0.5, 1.0),
            },
            ctrl: Ctrl::random(rng),
            mirror: rng.chance(0.5),
            repeat: if rng.chance(0.2) {
                2 + rng.below(2) as u8
            } else {
                1
            },
            taper: rng.range(0.75, 1.0),
            chain_bend: [0.0, 0.0],
            on: rng.below(3) as u8,
            children: Vec::new(),
        };
        if depth < 2 && rng.chance(0.3) {
            p.children.push(Part::random(rng, depth + 1));
        }
        p
    }

    fn mutate_shape(&mut self, rng: &mut Rng, rate: f32, sigma: f32, is_root: bool) {
        // Jitter each dimension over its own legal range, so the step
        // size suits the range and values don't pile up on the clamps.
        for (k, d) in self.dims.iter_mut().enumerate() {
            if rng.chance(rate) {
                let (lo, hi) = if is_root {
                    (DIM_MIN, DIM_MAX)
                } else if k == 1 {
                    (LIMB_LEN_MIN, DIM_MAX)
                } else {
                    (LIMB_THICK_MIN, LIMB_THICK_MAX)
                };
                *d = jig(rng, *d, lo, hi, sigma);
            }
        }
        if is_root {
            return;
        }
        let a = &mut self.attach;
        if rng.chance(rate) {
            a.u = jig(rng, a.u, -1.0, 1.0, sigma);
        }
        if rng.chance(rate) {
            a.v = jig(rng, a.v, -1.0, 1.0, sigma);
        }
        for t in a.tilt.iter_mut() {
            if rng.chance(rate) {
                *t = jig(rng, *t, -1.1, 1.1, sigma);
            }
        }
        if rng.chance(rate) {
            a.roll = jig_wrap(rng, a.roll, sigma);
        }
        if rng.chance(rate * 0.3) {
            a.face = rng.below(6) as u8;
        }
        let j = &mut self.joint;
        if rng.chance(rate) {
            j.axis = jig_wrap(rng, j.axis, sigma);
        }
        if rng.chance(rate) {
            j.lo = jig(rng, j.lo, -1.5, -0.1, sigma);
        }
        if rng.chance(rate) {
            j.hi = jig(rng, j.hi, 0.1, 1.5, sigma);
        }
        if rng.chance(rate) {
            j.strength = jig(rng, j.strength, 0.2, 1.0, sigma);
        }
        if rng.chance(rate * 0.15) {
            j.twist = !j.twist;
        }
        if rng.chance(rate) {
            self.taper = jig(rng, self.taper, 0.6, 1.1, sigma);
        }
        for b in self.chain_bend.iter_mut() {
            if rng.chance(rate) {
                *b = jig(rng, *b, -0.6, 0.6, sigma);
            }
        }
    }

    pub fn count_genes(&self) -> usize {
        1 + self.children.iter().map(|c| c.count_genes()).sum::<usize>()
    }

    pub fn depth(&self) -> usize {
        1 + self.children.iter().map(|c| c.depth()).max().unwrap_or(0)
    }

    /// Number of bodies this subtree expands to, given how many copies of
    /// its parent's chain exist.
    fn count_inst(&self, parent_copies: usize, is_root: bool) -> usize {
        let attach_sites = if is_root {
            1
        } else if self.on == 0 {
            parent_copies
        } else {
            1
        };
        let sides = if self.mirror && !is_root { 2 } else { 1 };
        let reps = if is_root {
            1
        } else {
            self.repeat.clamp(1, 5) as usize
        };
        let mine = reps;
        let kids: usize = self
            .children
            .iter()
            .map(|c| c.count_inst(reps, false))
            .sum();
        attach_sites * sides * (mine + kids)
    }
}

/// The `idx`-th part in preorder.
fn nth_mut<'a>(p: &'a mut Part, idx: &mut usize) -> Option<&'a mut Part> {
    if *idx == 0 {
        return Some(p);
    }
    *idx -= 1;
    for c in p.children.iter_mut() {
        if let Some(found) = nth_mut(c, idx) {
            return Some(found);
        }
    }
    None
}

fn for_each_mut(p: &mut Part, f: &mut impl FnMut(&mut Part)) {
    f(p);
    for c in p.children.iter_mut() {
        for_each_mut(c, f);
    }
}

impl Genome {
    pub fn random(rng: &mut Rng) -> Self {
        loop {
            let mut root = Part::random(rng, 0);
            root.dims = [
                rng.range(0.2, 0.7),
                rng.range(0.15, 0.5),
                rng.range(0.3, 0.9),
            ];
            root.mirror = false;
            root.repeat = 1;
            root.children.clear();
            let n = 1 + rng.below(3);
            for _ in 0..n {
                root.children.push(Part::random(rng, 1));
            }
            let mut g = Genome {
                freq: rng.range(0.6, 1.8),
                hue: rng.f32(),
                root,
            };
            g.quantize();
            if g.is_valid() {
                return g;
            }
        }
    }

    pub fn quantize(&mut self) {
        self.freq = q4(self.freq);
        self.hue = q4(self.hue);
        for c in self.root.children.iter_mut() {
            c.limbify();
        }
        self.root.quantize();
    }

    pub fn num_genes(&self) -> usize {
        self.root.count_genes()
    }

    /// How many rigid bodies this genome builds.
    pub fn num_parts(&self) -> usize {
        self.root.count_inst(1, true)
    }

    pub fn is_valid(&self) -> bool {
        if self.num_genes() > MAX_GENES || self.root.depth() > MAX_DEPTH {
            return false;
        }
        // Judge the body actually built: a mirrored limb sitting on the
        // mirror plane is built once, whatever the gene count suggests.
        let bp = crate::body::Blueprint::build(self);
        (2..=MAX_PARTS).contains(&bp.parts.len()) && !bp.truncated && !bp.self_intersects()
    }

    /// Return a mutated copy. Always returns a valid genome that differs
    /// from the parent in at least one place.
    pub fn mutated(&self, rng: &mut Rng) -> Genome {
        for _ in 0..50 {
            let mut g = self.clone();
            let n = 1 + rng.below(3);
            for _ in 0..n {
                g.mutate_once(rng);
            }
            g.quantize();
            // Some mutations do nothing (removing a limb from a part that
            // has none, say). Don't spend an evaluation on a clone.
            if g == *self || !g.is_valid() {
                continue;
            }
            g.hue = q4((g.hue + rng.normal() * 0.012).rem_euclid(1.0));
            return g;
        }
        self.clone()
    }

    fn mutate_once(&mut self, rng: &mut Rng) {
        let n = self.num_genes();
        let r = rng.f32();
        // The root has no hinge, so its controller is never used: when
        // retuning a controller, pick among the limbs.
        let pick = if r < 0.38 && n > 1 {
            1 + rng.below(n - 1)
        } else {
            rng.below(n)
        };
        let is_root = pick == 0;
        if (0.62..0.72).contains(&r) {
            // Nudge every controller a little, and the clock.
            self.freq = jig(rng, self.freq, FREQ_MIN, FREQ_MAX, 0.05);
            for c in self.root.children.iter_mut() {
                for_each_mut(c, &mut |p| p.ctrl.mutate(rng, 0.25, 0.03));
            }
            return;
        }
        let part = nth_mut(&mut self.root, &mut { pick }).expect("index in range");
        if r < 0.38 {
            // Retune one part's controller.
            let sigma = if rng.chance(0.3) { 0.25 } else { 0.08 };
            part.ctrl.mutate(rng, 0.4, sigma);
        } else if r < 0.62 {
            // Reshape one part.
            let sigma = if rng.chance(0.3) { 0.2 } else { 0.06 };
            part.mutate_shape(rng, 0.35, sigma, is_root);
        } else if r < 0.80 {
            // Grow a new limb.
            let mut child = Part::random(rng, 3);
            child.children.clear();
            part.children.push(child);
        } else if r < 0.86 {
            // Lose a limb.
            if !part.children.is_empty() {
                let i = rng.below(part.children.len());
                part.children.remove(i);
            }
        } else if r < 0.90 {
            // Duplicate a limb somewhere else on the same parent.
            if !part.children.is_empty() {
                let i = rng.below(part.children.len());
                let mut dup = part.children[i].clone();
                dup.attach.face = rng.below(6) as u8;
                dup.attach.u = rng.range(-1.0, 1.0);
                dup.attach.v = rng.range(-1.0, 1.0);
                dup.ctrl.phase = wrap_pi(dup.ctrl.phase + rng.range(-PI, PI));
                part.children.push(dup);
            }
        } else if r < 0.94 {
            if !is_root {
                part.mirror = !part.mirror;
            }
        } else if r < 0.98 {
            if !is_root {
                let up = rng.chance(0.5);
                part.repeat = if up {
                    (part.repeat + 1).min(5)
                } else {
                    part.repeat.saturating_sub(1).max(1)
                };
            }
        } else if !is_root {
            part.on = rng.below(3) as u8;
        }
    }

    /// Graft a random limb of `other` onto a random part of `self`.
    pub fn crossed(&self, other: &Genome, rng: &mut Rng) -> Genome {
        for _ in 0..20 {
            let mut g = self.clone();
            let mut donors: Vec<&Part> = Vec::new();
            fn walk<'a>(p: &'a Part, out: &mut Vec<&'a Part>) {
                for c in p.children.iter() {
                    out.push(c);
                    walk(c, out);
                }
            }
            walk(&other.root, &mut donors);
            if donors.is_empty() {
                return g;
            }
            let donor = donors[rng.below(donors.len())].clone();
            let pick = rng.below(g.num_genes());
            let part = nth_mut(&mut g.root, &mut { pick }).expect("index in range");
            if !part.children.is_empty() && rng.chance(0.6) {
                let i = rng.below(part.children.len());
                part.children[i] = donor;
            } else {
                part.children.push(donor);
            }
            if rng.chance(0.5) {
                g.freq = other.freq;
            }
            g.quantize();
            if g.is_valid() {
                return g;
            }
        }
        self.clone()
    }
}
