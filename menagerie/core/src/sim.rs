//! The simulator: blueprints become jointed rigid bodies in a Rapier world,
//! and each step runs sense -> control -> physics for every creature.

use crate::body::Blueprint;
use crate::genome::{Genome, NS};
use crate::m;
use rapier3d::prelude::*;
use serde::{Deserialize, Serialize};

const TAU: f32 = core::f32::consts::TAU;

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub enum Medium {
    /// Gravity and a floor.
    Land,
    /// No gravity, no floor, drag on every face.
    Water,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct SimParams {
    pub dt: f32,
    /// kg / m^3.
    pub density: f32,
    /// Peak muscle torque per square metre of joint cross-section.
    pub torque_per_area: f32,
    /// Motor spring and damper (acceleration-based, so mass-independent).
    pub stiffness: f32,
    pub damping: f32,
    pub friction: f32,
    /// Fastest a motor target may move, rad/s.
    pub max_rate: f32,
    /// Seconds of standing still before the controller switches on.
    pub settle: f32,
    /// Seconds over which controller output fades in after that.
    pub ramp: f32,
    pub medium: Medium,
    /// Water drag coefficient (times fluid density).
    pub drag: f32,
    /// Whether separate creatures bump into each other.
    pub creatures_collide: bool,
    /// Whether a creature's own parts bump into each other.
    pub self_collide: bool,
    pub solver_iterations: usize,
    /// Radians a scored creature is turned at the start (0 normally; the
    /// robustness check nudges it).
    pub spawn_yaw: f32,
    /// Any part moving faster than this (m/s) means the physics blew up.
    pub max_speed: f32,
    /// Let a land creature come to rest before its trial starts.
    pub preroll: bool,
    /// Use Rapier's rounded-box colliders. Off, because they are where the
    /// catapult glitch lives; kept so the cheat can be shown in the act.
    pub rounded: bool,
}

impl Default for SimParams {
    fn default() -> Self {
        SimParams {
            dt: 1.0 / 60.0,
            density: 600.0,
            torque_per_area: 9000.0,
            stiffness: 300.0,
            damping: 30.0,
            friction: 1.0,
            max_rate: 9.0,
            settle: 0.5,
            ramp: 0.75,
            medium: Medium::Land,
            drag: 600.0,
            creatures_collide: false,
            self_collide: true,
            solver_iterations: 4,
            spawn_yaw: 0.0,
            max_speed: 25.0,
            preroll: true,
            rounded: false,
        }
    }
}

pub struct Creature {
    pub bp: Blueprint,
    pub bodies: Vec<RigidBodyHandle>,
    pub colliders: Vec<ColliderHandle>,
    pub joints: Vec<Option<ImpulseJointHandle>>,
    /// Current motor target per part (index 0, the root, is unused).
    pub target: Vec<f32>,
    /// Smoothed 0..1 touch sensor per part.
    pub contact: Vec<f32>,
    /// Raw touch flags from the last step (anything, own limbs included).
    pub touching: Vec<bool>,
    /// Touching something that isn't part of this creature: the ground,
    /// a crate, somebody else.
    pub grounded: Vec<bool>,
    /// Pairs of this creature's own parts in contact with each other.
    pub self_contacts: Vec<(usize, usize)>,
    /// Hinge angle per part, radians.
    pub angle: Vec<f32>,
    /// Where this creature is trying to go.
    pub goal: Vector,
    pub mass: f32,
    /// Set if the physics went non-finite or absurdly fast.
    pub exploded: bool,
    /// Seconds to add to this creature's clock (lets copies desynchronise).
    pub clock_offset: f32,
}

/// A loose box for creatures to push around.
pub struct Crate {
    pub body: RigidBodyHandle,
    pub half: Vector,
}

pub struct Sim {
    pub world: PhysicsWorld,
    pub params: SimParams,
    pub creatures: Vec<Creature>,
    pub crates: Vec<Crate>,
    pub time: f32,
    pub steps: u32,
    /// Open worlds (races, roaming, the ring) have no scored trial to do
    /// the settling: with this set, muscles hold the rest pose until every
    /// creature has come to rest, and only then does the clock start, as
    /// in a trial.
    pub wait_for_rest: bool,
    calm_steps: u32,
    waited: u32,
}

const GROUND_GROUP: Group = Group::GROUP_1;

fn creature_group(i: usize) -> Group {
    Group::from_bits_truncate(1 << (1 + (i % 30)))
}

/// Terrain shapes the floor can take.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum Terrain {
    Flat,
    /// Height samples on a grid: `nx` by `nz` values row-major (z rows),
    /// spanning `size` metres centred on `centre`.
    Heights {
        nx: usize,
        nz: usize,
        heights: Vec<f32>,
        size: [f32; 2],
        centre: [f32; 2],
    },
    /// A round platform of this radius with its top at y = 0 and a long
    /// drop around it.
    Disc {
        radius: f32,
    },
}

impl Sim {
    pub fn new(params: SimParams, terrain: &Terrain) -> Sim {
        let mut world = PhysicsWorld::new();
        world.integration_parameters.dt = params.dt;
        world.integration_parameters.num_solver_iterations = params.solver_iterations;
        match params.medium {
            Medium::Land => world.gravity = Vector::new(0.0, -9.81, 0.0),
            Medium::Water => world.gravity = Vector::ZERO,
        }
        if params.medium == Medium::Land {
            let groups = InteractionGroups::new(GROUND_GROUP, Group::ALL, InteractionTestMode::And);
            let ground = world.insert_body(RigidBodyBuilder::fixed());
            match terrain {
                Terrain::Flat => {
                    world.insert_collider(
                        ColliderBuilder::cuboid(1000.0, 5.0, 1000.0)
                            .translation(Vector::new(0.0, -5.0, 0.0))
                            .friction(params.friction)
                            .collision_groups(groups),
                        Some(ground),
                    );
                }
                Terrain::Heights {
                    nx,
                    nz,
                    heights,
                    size,
                    centre,
                } => {
                    // Far field: a flat floor just under the lowest sample,
                    // so nothing falls forever off the edge of the grid.
                    world.insert_collider(
                        ColliderBuilder::cuboid(1000.0, 5.0, 1000.0)
                            .translation(Vector::new(0.0, -5.0, 0.0))
                            .friction(params.friction)
                            .collision_groups(groups),
                        Some(ground),
                    );
                    let mut grid = rapier3d::parry::utils::Array2::zeros(*nz, *nx);
                    for z in 0..*nz {
                        for x in 0..*nx {
                            grid[(z, x)] = heights[z * nx + x];
                        }
                    }
                    world.insert_collider(
                        ColliderBuilder::heightfield(grid, Vector::new(size[0], 1.0, size[1]))
                            .translation(Vector::new(centre[0], 0.0, centre[1]))
                            .friction(params.friction)
                            .collision_groups(groups),
                        Some(ground),
                    );
                }
                Terrain::Disc { radius } => {
                    // A raised ring, one metre proud of the floor around it.
                    world.insert_collider(
                        ColliderBuilder::cylinder(0.5, *radius)
                            .translation(Vector::new(0.0, -0.5, 0.0))
                            .friction(params.friction)
                            .collision_groups(groups),
                        Some(ground),
                    );
                    world.insert_collider(
                        ColliderBuilder::cuboid(1000.0, 5.0, 1000.0)
                            .translation(Vector::new(0.0, -6.0, 0.0))
                            .friction(params.friction)
                            .collision_groups(groups),
                        Some(ground),
                    );
                }
            }
        }
        Sim {
            world,
            params,
            creatures: Vec::new(),
            crates: Vec::new(),
            time: 0.0,
            steps: 0,
            wait_for_rest: false,
            calm_steps: 0,
            waited: 0,
        }
    }

    /// Drop a creature into the world with its lowest point just above
    /// `origin`, turned `yaw` radians about the vertical.
    pub fn add_creature(&mut self, genome: &Genome, origin: Vector, yaw: f32) -> usize {
        let bp = Blueprint::build(genome);
        let idx = self.creatures.len();
        let lift = match self.params.medium {
            Medium::Land => -bp.min_y() + 0.02,
            Medium::Water => 0.0,
        };
        let base_rot = Rotation::from_rotation_y(yaw);
        let base = origin + Vector::new(0.0, lift, 0.0);

        // Parts collide with the ground and with the creature's own other
        // parts (hinged pairs are exempted on the joint itself).
        let mine = creature_group(idx);
        let mut filter = GROUND_GROUP;
        if self.params.self_collide {
            filter |= mine;
        }
        if self.params.creatures_collide {
            filter = if self.params.self_collide {
                Group::ALL
            } else {
                Group::ALL & !mine
            };
        }
        let groups = InteractionGroups::new(mine, filter, InteractionTestMode::And);

        let n = bp.parts.len();
        let mut bodies = Vec::with_capacity(n);
        let mut colliders = Vec::with_capacity(n);
        let mut joints = Vec::with_capacity(n);
        let mut mass = 0.0;
        for p in bp.parts.iter() {
            let pose = Pose::from_parts(base + base_rot * p.pos, base_rot * p.rot);
            let rb = RigidBodyBuilder::dynamic()
                .pose(pose)
                .can_sleep(false)
                .linear_damping(0.02)
                .angular_damping(0.05);
            // Plain boxes. Rapier's rounded cuboids look nicer on paper but
            // blew up about one random creature in a hundred (single-step
            // 15+ m/s kicks), which evolution learned to farm as catapults.
            let col = if self.params.rounded {
                let r = 0.15 * p.half.x.min(p.half.y).min(p.half.z);
                ColliderBuilder::round_cuboid(p.half.x - r, p.half.y - r, p.half.z - r, r)
            } else {
                ColliderBuilder::cuboid(p.half.x, p.half.y, p.half.z)
            };
            let col = col
                .density(self.params.density)
                .friction(self.params.friction)
                .restitution(0.0)
                .collision_groups(groups);
            let (bh, ch) = self.world.insert(rb, col);
            mass += self.world.bodies[bh].mass();
            bodies.push(bh);
            colliders.push(ch);
        }
        for (i, p) in bp.parts.iter().enumerate() {
            let Some(parent) = p.parent else {
                joints.push(None);
                continue;
            };
            let max_torque = self.params.torque_per_area * p.joint_area * p.strength;
            // Rapier takes the sine and cosine of the middle of the limit
            // range with the platform's libm, which is the one place native
            // and wasm builds could disagree. Re-centre the hinge so its
            // limits are symmetric: the middle is then exactly zero.
            let centre = 0.5 * (p.lo + p.hi);
            let half = 0.5 * (p.hi - p.lo);
            let frame_parent = p.frame_parent * Rotation::from_rotation_x(centre);
            let joint = GenericJointBuilder::new(JointAxesMask::LOCKED_REVOLUTE_AXES)
                .local_frame1(Pose::from_parts(p.anchor_parent, frame_parent))
                .local_frame2(Pose::from_parts(p.anchor_child, p.frame_child))
                .contacts_enabled(false)
                .limits(JointAxis::AngX, [-half, half])
                .motor_model(JointAxis::AngX, MotorModel::AccelerationBased)
                .motor_position(
                    JointAxis::AngX,
                    -centre,
                    self.params.stiffness,
                    self.params.damping,
                )
                .motor_max_force(JointAxis::AngX, max_torque)
                .build();
            let h = self
                .world
                .insert_impulse_joint(bodies[parent], bodies[i], joint);
            joints.push(Some(h));
        }
        self.creatures.push(Creature {
            bp,
            bodies,
            colliders,
            joints,
            target: vec![0.0; n],
            contact: vec![0.0; n],
            touching: vec![false; n],
            grounded: vec![false; n],
            self_contacts: Vec::new(),
            angle: vec![0.0; n],
            goal: origin + Vector::new(0.0, 0.0, 1000.0),
            mass,
            exploded: false,
            clock_offset: 0.0,
        });
        idx
    }

    /// Put a loose box of the given mass in the world. Creatures see it
    /// as part of the scenery: everything collides with it.
    pub fn add_crate(&mut self, centre: Vector, half: Vector, mass: f32) -> usize {
        let groups = InteractionGroups::new(GROUND_GROUP, Group::ALL, InteractionTestMode::And);
        let volume = 8.0 * half.x * half.y * half.z;
        let (body, _) = self.world.insert(
            RigidBodyBuilder::dynamic()
                .translation(centre)
                .can_sleep(false),
            ColliderBuilder::cuboid(half.x, half.y, half.z)
                .density(mass / volume)
                .friction(0.5)
                .restitution(0.0)
                .collision_groups(groups),
        );
        self.crates.push(Crate { body, half });
        self.crates.len() - 1
    }

    pub fn crate_pos(&self, i: usize) -> Vector {
        self.world.bodies[self.crates[i].body].translation()
    }

    /// Farthest any part of a creature reaches along +z right now.
    pub fn front(&self, c: usize) -> f32 {
        let cr = &self.creatures[c];
        let mut m = f32::MIN;
        for (i, &b) in cr.bodies.iter().enumerate() {
            let rb = &self.world.bodies[b];
            let h = cr.bp.parts[i].half;
            let rot = *rb.rotation();
            let ext = (rot * Vector::X).z.abs() * h.x
                + (rot * Vector::Y).z.abs() * h.y
                + (rot * Vector::Z).z.abs() * h.z;
            m = m.max(rb.translation().z + ext);
        }
        m
    }

    /// Mass-weighted centre of a creature.
    pub fn com(&self, c: usize) -> Vector {
        let cr = &self.creatures[c];
        let mut sum = Vector::ZERO;
        let mut m = 0.0;
        for &b in cr.bodies.iter() {
            let rb = &self.world.bodies[b];
            sum += rb.center_of_mass() * rb.mass();
            m += rb.mass();
        }
        sum / m.max(1e-6)
    }

    /// Mass-weighted mean velocity of a creature.
    pub fn com_vel(&self, c: usize) -> Vector {
        let cr = &self.creatures[c];
        let mut sum = Vector::ZERO;
        let mut m = 0.0;
        for &b in cr.bodies.iter() {
            let rb = &self.world.bodies[b];
            sum += rb.linvel() * rb.mass();
            m += rb.mass();
        }
        sum / m.max(1e-6)
    }

    /// Lowest point of any part of a creature (approximate: box corners).
    pub fn lowest_point(&self, c: usize) -> f32 {
        let cr = &self.creatures[c];
        let mut m = f32::MAX;
        for (i, &b) in cr.bodies.iter().enumerate() {
            let rb = &self.world.bodies[b];
            let h = cr.bp.parts[i].half;
            let rot = *rb.rotation();
            // Extent of an oriented box along world y.
            let ext = (rot * Vector::X).y.abs() * h.x
                + (rot * Vector::Y).y.abs() * h.y
                + (rot * Vector::Z).y.abs() * h.z;
            m = m.min(rb.translation().y - ext);
        }
        m
    }

    /// Is any part of the creature touching the ground (or anything else
    /// that isn't itself)?
    pub fn any_contact(&self, c: usize) -> bool {
        self.creatures[c].grounded.iter().any(|&t| t)
    }

    /// Fraction of the creature's mass that is down: in parts resting on
    /// the ground, or resting on parts of itself that are. A body slumped
    /// on its own folded legs is down, even if only the legs touch floor.
    pub fn grounded_mass(&self, c: usize) -> f32 {
        let cr = &self.creatures[c];
        let mut down_part = cr.grounded.clone();
        loop {
            let mut changed = false;
            for &(i, j) in cr.self_contacts.iter() {
                if down_part[j] && !down_part[i] {
                    down_part[i] = true;
                    changed = true;
                }
            }
            if !changed {
                break;
            }
        }
        let mut down = 0.0;
        let mut total = 0.0;
        for (i, &b) in cr.bodies.iter().enumerate() {
            let m = self.world.bodies[b].mass();
            total += m;
            if down_part[i] {
                down += m;
            }
        }
        down / total.max(1e-6)
    }

    fn control(&mut self) {
        let t = self.time;
        let p = &self.params;
        let dt = p.dt;
        for cr in self.creatures.iter_mut() {
            let n = cr.bp.parts.len();
            let root = &self.world.bodies[cr.bodies[0]];
            let root_rot = *root.rotation();
            let inv = root_rot.inverse();
            let mut to_goal = cr.goal - root.translation();
            if p.medium == Medium::Land {
                to_goal.y = 0.0;
            }
            let dist = to_goal.length();
            let dir = if dist > 1e-4 {
                to_goal / dist
            } else {
                Vector::ZERO
            };
            let gl = inv * dir;
            let up = inv * Vector::Y;

            // Touch sensors.
            cr.self_contacts.clear();
            for i in 0..n {
                let mut touch = false;
                let mut outside = false;
                let me = cr.colliders[i];
                for pair in self.world.narrow_phase.contact_pairs_with(me) {
                    if pair.has_any_active_contact() {
                        touch = true;
                        let other = if pair.collider1 == me {
                            pair.collider2
                        } else {
                            pair.collider1
                        };
                        match cr.colliders.iter().position(|&c| c == other) {
                            None => outside = true,
                            Some(j) => cr.self_contacts.push((i, j)),
                        }
                    }
                }
                cr.touching[i] = touch;
                cr.grounded[i] = outside;
                let x = if touch { 1.0 } else { 0.0 };
                cr.contact[i] += (x - cr.contact[i]) * 0.3;
            }

            let active = t + 1e-6 >= p.settle;
            let gain = if !active {
                0.0
            } else if p.ramp > 0.0 {
                ((t - p.settle) / p.ramp).clamp(0.0, 1.0)
            } else {
                1.0
            };
            let phi = TAU * cr.bp.freq * ((t - p.settle).max(0.0) + cr.clock_offset);

            for i in 1..n {
                let part = &cr.bp.parts[i];
                let parent = part.parent.unwrap();
                // Hinge angle.
                let rp = *self.world.bodies[cr.bodies[parent]].rotation() * part.frame_parent;
                let rc = *self.world.bodies[cr.bodies[i]].rotation() * part.frame_child;
                let q = rp.inverse() * rc;
                let mut ang = 2.0 * m::atan2(q.x, q.w);
                if ang > core::f32::consts::PI {
                    ang -= TAU;
                } else if ang < -core::f32::consts::PI {
                    ang += TAU;
                }
                cr.angle[i] = ang;

                let side = if part.flip { -1.0 } else { 1.0 };
                let range = part.hi.max(-part.lo);
                let s: [f32; NS] = [
                    gl.x * side,
                    gl.y,
                    gl.z,
                    up.x * side,
                    up.y,
                    up.z,
                    cr.contact[i],
                    ang / range,
                ];
                let c = &cr.bp.ctrls[part.gene];
                let ph = phi + part.phase_off + c.phase;
                let ph2 = 2.0 * (phi + part.phase_off) + c.phase2;
                let osc = m::sin(ph) + c.h2 * m::sin(ph2);
                let mut a = c.amp;
                let mut b = c.bias;
                for k in 0..NS {
                    a += c.wa[k] * s[k];
                    b += c.wb[k] * s[k];
                }
                let out = m::tanh(a * osc + b) * gain;
                let want = if out >= 0.0 {
                    out * part.hi
                } else {
                    -out * part.lo
                };
                let max_step = p.max_rate * dt;
                let cur = cr.target[i];
                let next = cur + (want - cur).clamp(-max_step, max_step);
                cr.target[i] = next;
                if let Some(h) = cr.joints[i] {
                    if let Some(j) = self.world.impulse_joints.get_mut(h, false) {
                        let centre = 0.5 * (part.lo + part.hi);
                        j.data.set_motor_position(
                            JointAxis::AngX,
                            next - centre,
                            p.stiffness,
                            p.damping,
                        );
                    }
                }
            }
        }
    }

    /// Quadratic drag on every box face that is moving into the fluid.
    fn fluid_forces(&mut self) {
        let k = self.params.drag;
        let dt = self.params.dt;
        for cr in self.creatures.iter() {
            for (i, &b) in cr.bodies.iter().enumerate() {
                let rb = &mut self.world.bodies[b];
                rb.reset_forces(false);
                rb.reset_torques(false);
                let h = cr.bp.parts[i].half;
                let rot = *rb.rotation();
                let pos = rb.translation();
                let mass = rb.mass();
                let axes = [rot * Vector::X, rot * Vector::Y, rot * Vector::Z];
                let hs = [h.x, h.y, h.z];
                for a in 0..3 {
                    let area = 4.0 * hs[(a + 1) % 3] * hs[(a + 2) % 3];
                    for sign in [-1.0f32, 1.0] {
                        let nrm = axes[a] * sign;
                        let pt = pos + nrm * hs[a];
                        let vn = rb.velocity_at_point(pt).dot(nrm);
                        if vn <= 0.0 {
                            continue;
                        }
                        // Never let one step of drag do more than halve the
                        // face's speed; keeps thin light parts stable.
                        let f = (0.5 * k * area * vn * vn).min(0.5 * mass * vn / dt);
                        rb.add_force_at_point(nrm * -f, pt, false);
                    }
                }
            }
        }
    }

    fn check(&mut self) {
        let max_speed = self.params.max_speed;
        for cr in self.creatures.iter_mut() {
            if cr.exploded {
                continue;
            }
            for &b in cr.bodies.iter() {
                let rb = &self.world.bodies[b];
                let v = rb.linvel();
                let w = rb.angvel();
                let p = rb.translation();
                if !(v.is_finite() && w.is_finite() && p.is_finite())
                    || v.length() > max_speed
                    || w.length() > 2.0 * max_speed
                {
                    cr.exploded = true;
                    break;
                }
            }
        }
    }

    pub fn step(&mut self) {
        self.control();
        if self.params.medium == Medium::Water {
            self.fluid_forces();
        }
        self.world.step();
        self.time += self.params.dt;
        self.steps += 1;
        self.check();
        if self.wait_for_rest && self.params.medium == Medium::Land {
            // Same rule as a scored trial's pre-roll: a third of a second
            // of stillness, or six seconds, whichever comes first.
            let still = (0..self.creatures.len()).all(|c| self.com_vel(c).length() < 0.04);
            self.calm_steps = if still { self.calm_steps + 1 } else { 0 };
            self.waited += 1;
            // (The limit is written exactly as the trial's pre-roll writes
            // it, so the two agree to the step.)
            if self.calm_steps >= 20 || self.waited >= (6.0 / self.params.dt) as u32 {
                self.wait_for_rest = false;
                self.time = 0.0;
            } else {
                // Hold the clock where the controller stays switched off.
                self.time = -1.0;
            }
        }
    }

    /// Worst separation of any hinge's two anchor points, in metres.
    /// Should stay near zero; large values mean the solver is being abused.
    pub fn joint_error(&self, c: usize) -> f32 {
        let cr = &self.creatures[c];
        let mut worst = 0.0f32;
        for (i, part) in cr.bp.parts.iter().enumerate() {
            let Some(parent) = part.parent else { continue };
            let a = self.world.bodies[cr.bodies[parent]]
                .position()
                .transform_point(part.anchor_parent);
            let b = self.world.bodies[cr.bodies[i]]
                .position()
                .transform_point(part.anchor_child);
            worst = worst.max((a - b).length());
        }
        worst
    }

    /// Flat [x, y, z, qx, qy, qz, qw] per part, for rendering.
    pub fn write_transforms(&self, c: usize, out: &mut Vec<f32>) {
        for &b in self.creatures[c].bodies.iter() {
            let rb = &self.world.bodies[b];
            let t = rb.translation();
            let r = rb.rotation();
            out.extend_from_slice(&[t.x, t.y, t.z, r.x, r.y, r.z, r.w]);
        }
    }
}
