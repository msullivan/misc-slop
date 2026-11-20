//! Genome -> blueprint: expand the part tree (with its mirror and repeat
//! operators) into a flat list of boxes, each with a rest pose and a hinge
//! to its parent. Pure geometry; the simulator turns this into rigid bodies.

use crate::genome::{Ctrl, Genome, Part, MAX_PARTS};
use rapier3d::math::{Rotation, Vector};

const HALF_PI: f32 = core::f32::consts::FRAC_PI_2;
const PI: f32 = core::f32::consts::PI;

#[derive(Clone, Debug)]
pub struct PartInst {
    /// Half extents of the box.
    pub half: Vector,
    pub parent: Option<usize>,
    /// Rest pose in the creature's frame (root at the origin).
    pub pos: Vector,
    pub rot: Rotation,
    /// Hinge anchor and frame in the parent's local space.
    pub anchor_parent: Vector,
    pub frame_parent: Rotation,
    /// Hinge anchor and frame in this part's local space. The hinge turns
    /// about the frame's x axis.
    pub anchor_child: Vector,
    pub frame_child: Rotation,
    pub lo: f32,
    pub hi: f32,
    pub strength: f32,
    /// Cross-section area of the joint, which sets muscle strength.
    pub joint_area: f32,
    /// Index into `Blueprint::ctrls`.
    pub gene: usize,
    /// True for the mirror-image side of a mirrored limb.
    pub flip: bool,
    /// Clock offset for this copy (chain position, mirror side).
    pub phase_off: f32,
    pub depth: u8,
}

#[derive(Clone, Debug)]
pub struct Blueprint {
    /// True if the genome asked for more than `MAX_PARTS` bodies and the
    /// rest were left off. Evolution rejects such genomes.
    pub truncated: bool,
    pub parts: Vec<PartInst>,
    pub ctrls: Vec<Ctrl>,
    pub freq: f32,
    pub hue: f32,
}

/// Reflect a rotation through the x=0 plane.
fn mirror_rot(q: Rotation) -> Rotation {
    Rotation::from_xyzw(q.x, -q.y, -q.z, q.w)
}

fn mirror_vec(v: Vector) -> Vector {
    Vector::new(-v.x, v.y, v.z)
}

/// Rotation taking the child's +y axis onto the outward normal of a face.
fn face_rot(face: u8) -> Rotation {
    match face % 6 {
        0 => Rotation::from_rotation_z(-HALF_PI),
        1 => Rotation::from_rotation_z(HALF_PI),
        2 => Rotation::IDENTITY,
        3 => Rotation::from_rotation_x(PI),
        4 => Rotation::from_rotation_x(HALF_PI),
        _ => Rotation::from_rotation_x(-HALF_PI),
    }
}

/// Attachment point on a face, in the parent's local frame.
fn face_point(face: u8, u: f32, v: f32, half: Vector) -> Vector {
    // Keep attachments a little inside the edge so limbs don't hang off
    // corners by a sliver.
    let u = u.clamp(-1.0, 1.0) * 0.85;
    let v = v.clamp(-1.0, 1.0) * 0.85;
    match face % 6 {
        0 => Vector::new(half.x, u * half.y, v * half.z),
        1 => Vector::new(-half.x, u * half.y, v * half.z),
        2 => Vector::new(u * half.x, half.y, v * half.z),
        3 => Vector::new(u * half.x, -half.y, v * half.z),
        4 => Vector::new(u * half.x, v * half.y, half.z),
        _ => Vector::new(u * half.x, v * half.y, -half.z),
    }
}

/// Area of the parent's face a limb is attached to.
fn face_area(face: u8, half: Vector) -> f32 {
    match face % 6 {
        0 | 1 => 4.0 * half.y * half.z,
        2 | 3 => 4.0 * half.x * half.z,
        _ => 4.0 * half.x * half.y,
    }
}

struct Builder {
    parts: Vec<PartInst>,
    truncated: bool,
}

impl Builder {
    /// Instantiate one copy of `gene` on parent instance `parent`.
    /// `chain_k > 0` means this is a chain link attaching to the tip of the
    /// previous copy of itself rather than to the gene's parent.
    #[allow(clippy::too_many_arguments)]
    fn add_part(
        &mut self,
        gene: &Part,
        gene_idx: usize,
        parent: usize,
        flip: bool,
        scale: f32,
        chain_k: usize,
        phase_off: f32,
    ) -> Option<usize> {
        if self.parts.len() >= MAX_PARTS {
            self.truncated = true;
            return None;
        }
        let par = self.parts[parent].clone();
        let half = Vector::new(gene.dims[0], gene.dims[1], gene.dims[2]) * (0.5 * scale);

        // Local transform of the child relative to its parent, unmirrored.
        let (anchor_p, rel_rot, area_parent) = if chain_k == 0 {
            let a = &gene.attach;
            let rot = face_rot(a.face)
                * Rotation::from_rotation_x(a.tilt[0])
                * Rotation::from_rotation_z(a.tilt[1])
                * Rotation::from_rotation_y(a.roll);
            (
                face_point(a.face, a.u, a.v, par.half),
                rot,
                face_area(a.face, par.half),
            )
        } else {
            let rot = Rotation::from_rotation_x(gene.chain_bend[0])
                * Rotation::from_rotation_z(gene.chain_bend[1]);
            (
                Vector::new(0.0, par.half.y, 0.0),
                rot,
                4.0 * par.half.x * par.half.z,
            )
        };
        let anchor_c = Vector::new(0.0, -half.y, 0.0);

        // A frame whose x axis is the hinge axis, in the child's space.
        let axis_frame = if gene.joint.twist {
            Rotation::from_rotation_z(HALF_PI) // x -> y
        } else {
            Rotation::from_rotation_y(-gene.joint.axis) // x -> (cos, 0, sin)
        };

        // Inside a mirrored subtree every local transform is reflected.
        // Boxes are symmetric, so the shapes themselves don't change.
        let (anchor_p, rel_rot, frame_c) = if flip {
            (
                mirror_vec(anchor_p),
                mirror_rot(rel_rot),
                mirror_rot(axis_frame),
            )
        } else {
            (anchor_p, rel_rot, axis_frame)
        };
        // The parent-side hinge frame coincides with the child's at rest,
        // so the rest pose is hinge angle zero.
        let frame_p = rel_rot * frame_c;

        let rot = par.rot * rel_rot;
        let pos = par.pos + par.rot * anchor_p - rot * anchor_c;
        let area_child = 4.0 * half.x * half.z;

        self.parts.push(PartInst {
            half,
            parent: Some(parent),
            pos,
            rot,
            anchor_parent: anchor_p,
            frame_parent: frame_p,
            anchor_child: anchor_c,
            frame_child: frame_c,
            lo: gene.joint.lo.min(-0.05),
            hi: gene.joint.hi.max(0.05),
            strength: gene.joint.strength.clamp(0.05, 1.0),
            joint_area: area_parent.min(area_child),
            gene: gene_idx,
            flip,
            phase_off,
            depth: par.depth + 1,
        });
        Some(self.parts.len() - 1)
    }

    /// Build one side of `gene`'s chain on `parent`, then everything that
    /// hangs off it. `gene_idx` is the gene's preorder index.
    fn add_chain(
        &mut self,
        gene: &Part,
        gene_idx: usize,
        parent: usize,
        flip: bool,
        scale: f32,
        phase_base: f32,
    ) {
        let reps = gene.repeat.clamp(1, 5) as usize;
        let mut copies: Vec<(usize, f32, f32)> = Vec::with_capacity(reps);
        let mut prev = parent;
        let mut s = scale;
        for k in 0..reps {
            let phase = phase_base + k as f32 * gene.ctrl.chain_phase;
            match self.add_part(gene, gene_idx, prev, flip, s, k, phase) {
                Some(i) => {
                    copies.push((i, s, phase));
                    prev = i;
                    s *= gene.taper.clamp(0.5, 1.2);
                }
                None => break,
            }
        }
        if copies.is_empty() {
            return;
        }
        let mut child_idx = gene_idx + 1;
        for child in gene.children.iter() {
            let sites: &[(usize, f32, f32)] = match child.on {
                0 => &copies[..],
                1 => &copies[..1],
                _ => &copies[copies.len() - 1..],
            };
            for &(site, site_scale, site_phase) in sites {
                self.add_sides(child, child_idx, site, flip, site_scale, site_phase);
            }
            child_idx += child.count_genes();
        }
    }

    /// Build `gene` on `parent`, plus its mirror image if it has one.
    fn add_sides(
        &mut self,
        gene: &Part,
        gene_idx: usize,
        parent: usize,
        flip: bool,
        scale: f32,
        phase: f32,
    ) {
        let start = self.parts.len();
        self.add_chain(gene, gene_idx, parent, flip, scale, phase);
        if !gene.mirror || self.parts.len() == start {
            return;
        }
        let mark = self.parts.len();
        self.add_chain(
            gene,
            gene_idx,
            parent,
            !flip,
            scale,
            phase + gene.ctrl.mirror_phase,
        );
        // If the mirror image landed on top of the original (limb on the
        // mirror plane), drop it: a doubled limb is just a strength cheat.
        if self.parts.len() > mark {
            let first_new = &self.parts[mark];
            let orig = &self.parts[start];
            if (first_new.pos - orig.pos).length() < 0.5 * orig.half.x.min(orig.half.z) {
                self.parts.truncate(mark);
            }
        }
    }
}

fn collect_ctrls(p: &Part, out: &mut Vec<Ctrl>) {
    out.push(p.ctrl.clone());
    for c in p.children.iter() {
        collect_ctrls(c, out);
    }
}

impl Blueprint {
    pub fn build(g: &Genome) -> Blueprint {
        let root = &g.root;
        let mut ctrls = Vec::new();
        collect_ctrls(root, &mut ctrls);
        let mut b = Builder {
            parts: Vec::new(),
            truncated: false,
        };
        b.parts.push(PartInst {
            half: Vector::new(root.dims[0], root.dims[1], root.dims[2]) * 0.5,
            parent: None,
            pos: Vector::ZERO,
            rot: Rotation::IDENTITY,
            anchor_parent: Vector::ZERO,
            frame_parent: Rotation::IDENTITY,
            anchor_child: Vector::ZERO,
            frame_child: Rotation::IDENTITY,
            lo: 0.0,
            hi: 0.0,
            strength: 0.0,
            joint_area: 0.0,
            gene: 0,
            flip: false,
            phase_off: 0.0,
            depth: 0,
        });
        let mut child_idx = 1;
        for child in root.children.iter() {
            b.add_sides(child, child_idx, 0, false, 1.0, 0.0);
            child_idx += child.count_genes();
        }
        Blueprint {
            truncated: b.truncated,
            parts: b.parts,
            ctrls,
            freq: g.freq,
            hue: g.hue,
        }
    }

    /// True if any two parts that are not hinged to each other intersect
    /// in the rest pose. Such bodies are rejected: limbs sprouting through
    /// one another look like a junk pile and collide with themselves.
    pub fn self_intersects(&self) -> bool {
        let n = self.parts.len();
        for i in 0..n {
            for j in (i + 1)..n {
                if self.parts[i].parent == Some(j) || self.parts[j].parent == Some(i) {
                    continue;
                }
                if obb_overlap(&self.parts[i], &self.parts[j], 0.97) {
                    return true;
                }
            }
        }
        false
    }

    /// Lowest point of the rest pose, in the creature frame.
    pub fn min_y(&self) -> f32 {
        let mut m = f32::MAX;
        for p in &self.parts {
            for sx in [-1.0f32, 1.0] {
                for sy in [-1.0f32, 1.0] {
                    for sz in [-1.0f32, 1.0] {
                        let c = p.pos
                            + p.rot * Vector::new(sx * p.half.x, sy * p.half.y, sz * p.half.z);
                        m = m.min(c.y);
                    }
                }
            }
        }
        m
    }

    /// Radius of gyration of the rest pose in body lengths: small for
    /// compact lumps, large for sprawling or stringy bodies.
    pub fn spread(&self) -> f32 {
        let mut total = 0.0;
        let mut centre = Vector::ZERO;
        for p in &self.parts {
            let v = 8.0 * p.half.x * p.half.y * p.half.z;
            total += v;
            centre += p.pos * v;
        }
        centre /= total.max(1e-9);
        let mut acc = 0.0;
        for p in &self.parts {
            let v = 8.0 * p.half.x * p.half.y * p.half.z;
            acc += v * ((p.pos - centre).length_squared() + p.half.length_squared() / 3.0);
        }
        (acc / total.max(1e-9)).sqrt() / crate::m::cbrt(total).max(1e-6)
    }

    pub fn volume(&self) -> f32 {
        self.parts
            .iter()
            .map(|p| 8.0 * p.half.x * p.half.y * p.half.z)
            .sum()
    }
}

/// Separating-axis test for two oriented boxes, each shrunk by `shrink`.
fn obb_overlap(a: &PartInst, b: &PartInst, shrink: f32) -> bool {
    let ax = [a.rot * Vector::X, a.rot * Vector::Y, a.rot * Vector::Z];
    let bx = [b.rot * Vector::X, b.rot * Vector::Y, b.rot * Vector::Z];
    let ha = [a.half.x * shrink, a.half.y * shrink, a.half.z * shrink];
    let hb = [b.half.x * shrink, b.half.y * shrink, b.half.z * shrink];
    let d = b.pos - a.pos;
    let separated = |axis: Vector| -> bool {
        let len2 = axis.length_squared();
        if len2 < 1e-10 {
            return false;
        }
        let ra: f32 = (0..3).map(|k| ha[k] * ax[k].dot(axis).abs()).sum();
        let rb: f32 = (0..3).map(|k| hb[k] * bx[k].dot(axis).abs()).sum();
        d.dot(axis).abs() > ra + rb
    };
    for k in 0..3 {
        if separated(ax[k]) || separated(bx[k]) {
            return false;
        }
    }
    for i in 0..3 {
        for j in 0..3 {
            if separated(ax[i].cross(bx[j])) {
                return false;
            }
        }
    }
    true
}
