//! Tasks: what a creature is asked to do, and how well it did.

use crate::genome::Genome;
use crate::m;
use crate::rng::Rng;
use crate::sim::{Medium, Sim, SimParams, Terrain};
use rapier3d::math::Vector;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Task {
    /// Cover ground in a straight line on a flat floor.
    Sprint,
    /// Reach a series of goals in different directions.
    Chase,
    /// Like sprint, but weightless in a viscous fluid.
    Swim,
    /// Get the lowest part of the body as high off the floor as possible.
    Jump,
    /// Sprint over lumpy ground.
    Rough,
    /// Push a heavy crate as far as possible.
    Shove,
    /// Sprint, but stay up on your legs: the run ends as soon as too much
    /// of the body is resting on the ground.
    Walk,
}

impl Task {
    pub fn parse(s: &str) -> Option<Task> {
        Some(match s {
            "sprint" => Task::Sprint,
            "chase" => Task::Chase,
            "swim" => Task::Swim,
            "jump" => Task::Jump,
            "rough" => Task::Rough,
            "shove" => Task::Shove,
            "walk" => Task::Walk,
            _ => return None,
        })
    }

    pub fn name(self) -> &'static str {
        match self {
            Task::Sprint => "sprint",
            Task::Chase => "chase",
            Task::Swim => "swim",
            Task::Jump => "jump",
            Task::Rough => "rough",
            Task::Shove => "shove",
            Task::Walk => "walk",
        }
    }

    pub fn trials(self) -> usize {
        match self {
            Task::Chase => 3,
            Task::Rough => 2,
            _ => 1,
        }
    }

    /// Seconds of scored activity (after the settling period).
    pub fn seconds(self) -> f32 {
        match self {
            Task::Sprint | Task::Swim | Task::Shove | Task::Walk => 10.0,
            Task::Rough => 12.0,
            Task::Chase => 14.0,
            Task::Jump => 5.0,
        }
    }

    pub fn params(self) -> SimParams {
        let mut p = SimParams::default();
        if self == Task::Swim {
            p.medium = Medium::Water;
        }
        p
    }
}

/// The crate in the shove task: an 80 kg cube, 80 cm on a side, set down
/// this far in front of the creature's nose.
pub const CRATE_HALF: f32 = 0.4;
pub const CRATE_MASS: f32 = 80.0;
pub const CRATE_GAP: f32 = 0.6;

/// In the walk task, at most this fraction of body mass may be in parts
/// that touch the ground at any moment. More than that is a fall.
pub const WALK_MAX_GROUNDED: f32 = 0.4;

/// Longest a creature is given to stop moving before its trial starts, s.
pub const MAX_PREROLL: f32 = 6.0;

/// How far away a new goal is placed, and how close counts as reaching it.
pub const GOAL_DIST: f32 = 7.0;
pub const GOAL_REACH: f32 = 0.9;

/// Compass headings (degrees from +z, positive towards +x) of successive
/// goals in each chase trial.
const CHASE_HEADINGS: [[f32; 6]; 3] = [
    [0.0, 90.0, -90.0, 180.0, 45.0, -135.0],
    [-70.0, 60.0, 170.0, -20.0, 110.0, -100.0],
    [140.0, -140.0, 20.0, -90.0, 90.0, 0.0],
];

/// Lumpy ground for the rough task: smooth hills plus sharper ripples,
/// fading in from a flat pad around the spawn point.
pub fn rough_terrain(trial: usize) -> Terrain {
    let (nx, nz) = (48usize, 96usize);
    let size = [18.0f32, 36.0f32];
    let centre = [0.0f32, 13.0f32];
    let mut rng = Rng::new(0xB0B0 + trial as u64);
    // Long swells you have to climb plus short ripples you trip on.
    let mut waves = Vec::new();
    for i in 0..9 {
        let k = if i < 5 {
            rng.range(0.6, 2.0)
        } else {
            rng.range(3.0, 6.5)
        };
        let th = rng.range(0.0, core::f32::consts::TAU);
        let amp = if i < 5 {
            rng.range(0.05, 0.11)
        } else {
            rng.range(0.015, 0.035)
        };
        waves.push((k * m::cos(th), k * m::sin(th), rng.range(0.0, 6.28), amp));
    }
    let mut heights = vec![0.0f32; nx * nz];
    for iz in 0..nz {
        for ix in 0..nx {
            let x = centre[0] + size[0] * (ix as f32 / (nx - 1) as f32 - 0.5);
            let z = centre[1] + size[1] * (iz as f32 / (nz - 1) as f32 - 0.5);
            let mut h = 0.0;
            for &(kx, kz, ph, a) in waves.iter() {
                h += a * m::sin(kx * x + kz * z + ph);
            }
            // Keep it non-negative-ish and flat near the start.
            let r = (x * x + z * z).sqrt();
            let fade = ((r - 2.0) / 1.5).clamp(0.0, 1.0);
            heights[iz * nx + ix] = (h + 0.18).max(0.0) * fade;
        }
    }
    Terrain::Heights {
        nx,
        nz,
        heights,
        size,
        centre,
    }
}

pub fn terrain_for(task: Task, trial: usize) -> Terrain {
    match task {
        Task::Rough => rough_terrain(trial),
        _ => Terrain::Flat,
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct Eval {
    pub fitness: f32,
    pub valid: bool,
    /// Mean height of the centre of mass, in body lengths.
    pub stature: f32,
    /// Fraction of the time nothing touches the ground.
    pub airborne: f32,
    pub parts: u32,
    pub mass: f32,
    /// Worst hinge separation seen, metres.
    pub joint_err: f32,
    /// Path efficiency: net distance over distance travelled by the COM.
    pub straightness: f32,
    /// How sprawling the body is (radius of gyration in body lengths).
    pub spread: f32,
    /// How many parts regularly touch the ground: the creature's feet,
    /// whatever they look like.
    pub feet: u32,
    /// Fraction of body mass in parts that never regularly touch the
    /// ground: 0 for a slug, near 1 for something up on thin legs.
    pub tiptoe: f32,
    /// Largest one-step gain in centre-of-mass speed over anything seen in
    /// the previous tenth of a second, m/s. Muscles can't do much in a
    /// sixtieth of a second; a big number is a solver glitch. (Comparing
    /// with the recent peak keeps honest rebounds off landings out of it.)
    pub kick: f32,
}

/// One scored run of one creature on one trial of a task. Shared by the
/// evolution loop and the browser, so what you watch is what was scored.
pub struct Episode {
    pub sim: Sim,
    pub task: Task,
    pub trial: usize,
    pub goals_reached: usize,
    /// Metres of progress towards goals so far (sprint: metres along +z).
    pub progress: f32,
    /// Walk task: the creature went down and the run is over.
    pub fell: bool,
    started: bool,
    start: Vector,
    mid: Option<Vector>,
    last_goal_dist: f32,
    best_low: f32,
    height_sum: f32,
    air_steps: u32,
    active_steps: u32,
    path_len: f32,
    last_com: Vector,
    pub joint_err: f32,
    pub kick: f32,
    crate_start: Vector,
    crate_mid: Option<Vector>,
    /// Steps each part spent touching something, while scored.
    touch_steps: Vec<u32>,
    recent_speed: [f32; 6],
    body_len: f32,
}

fn heading(deg: f32) -> Vector {
    let r = deg.to_radians();
    Vector::new(m::sin(r), 0.0, m::cos(r))
}

impl Episode {
    pub fn new(genome: &Genome, task: Task, trial: usize, params: &SimParams) -> Episode {
        let mut sim = Sim::new(params.clone(), &terrain_for(task, trial));
        let c = sim.add_creature(genome, Vector::ZERO, params.spawn_yaw);
        if params.medium == Medium::Land && params.preroll {
            // Let the body come to rest before the clock starts, with the
            // muscles holding the rest pose. Otherwise a tall body can
            // topple into the trial and bank the fall as speed or height.
            sim.time = -1.0e4;
            let mut calm = 0;
            for _ in 0..(MAX_PREROLL / params.dt) as usize {
                sim.step();
                if sim.com_vel(c).length() < 0.04 {
                    calm += 1;
                    if calm >= 20 {
                        break;
                    }
                } else {
                    calm = 0;
                }
            }
            sim.time = 0.0;
            sim.steps = 0;
        }
        if task == Task::Shove {
            let z = sim.front(c) + CRATE_GAP + CRATE_HALF;
            sim.add_crate(
                Vector::new(0.0, CRATE_HALF + 0.01, z),
                Vector::splat(CRATE_HALF),
                CRATE_MASS,
            );
        }
        let body_len = m::cbrt(sim.creatures[c].bp.volume());
        let com = sim.com(c);
        let mut ep = Episode {
            sim,
            task,
            trial,
            goals_reached: 0,
            progress: 0.0,
            fell: false,
            started: false,
            start: com,
            mid: None,
            last_goal_dist: 0.0,
            best_low: 0.0,
            height_sum: 0.0,
            air_steps: 0,
            active_steps: 0,
            path_len: 0.0,
            last_com: com,
            joint_err: 0.0,
            kick: 0.0,
            crate_start: Vector::ZERO,
            crate_mid: None,
            touch_steps: Vec::new(),
            recent_speed: [0.0; 6],
            body_len,
        };
        // Whatever speed it has now is not a kick.
        ep.recent_speed = [ep.sim.com_vel(0).length(); 6];
        ep.place_goal();
        ep
    }

    fn place_goal(&mut self) {
        let com = self.sim.com(0);
        let goal = match self.task {
            Task::Chase => {
                let seq = &CHASE_HEADINGS[self.trial % CHASE_HEADINGS.len()];
                let h = heading(seq[self.goals_reached % seq.len()]);
                Vector::new(com.x, 0.0, com.z) + h * GOAL_DIST
            }
            Task::Shove => self.sim.crate_pos(0),
            _ => Vector::new(0.0, com.y, 1000.0),
        };
        self.sim.creatures[0].goal = goal;
        self.last_goal_dist = self.goal_dist();
    }

    fn goal_dist(&self) -> f32 {
        let com = self.sim.com(0);
        let mut d = self.sim.creatures[0].goal - com;
        if self.sim.params.medium == Medium::Land {
            d.y = 0.0;
        }
        d.length()
    }

    pub fn total_seconds(&self) -> f32 {
        self.sim.params.settle + self.task.seconds()
    }

    /// Length of the trial in whole physics steps. Counting steps rather
    /// than comparing accumulated time avoids a rounding-dependent extra one.
    pub fn total_steps(&self) -> u32 {
        (self.total_seconds() / self.sim.params.dt).round() as u32
    }

    pub fn done(&self) -> bool {
        self.fell || self.sim.steps >= self.total_steps() || self.sim.creatures[0].exploded
    }

    pub fn step(&mut self) {
        if self.task == Task::Shove {
            // Keep the creature's sense of direction on the crate.
            self.sim.creatures[0].goal = self.sim.crate_pos(0);
        }
        self.sim.step();
        let speed = self.sim.com_vel(0).length();
        let recent = self.recent_speed.iter().fold(0.0f32, |a, &b| a.max(b));
        self.kick = self.kick.max(speed - recent);
        let slot = self.sim.steps as usize % self.recent_speed.len();
        self.recent_speed[slot] = speed;
        let t = self.sim.time;
        let settle = self.sim.params.settle;
        if t + 1e-6 < settle {
            return;
        }
        let com = self.sim.com(0);
        if !self.started {
            self.started = true;
            self.start = com;
            self.last_com = com;
            if self.task == Task::Chase {
                // Re-aim from where the creature actually settled.
                self.place_goal();
            } else {
                self.last_goal_dist = self.goal_dist();
            }
            self.best_low = self.sim.lowest_point(0);
            if self.task == Task::Shove {
                self.crate_start = self.sim.crate_pos(0);
            }
        }
        if self.mid.is_none() && t >= settle + 0.5 * self.task.seconds() {
            self.mid = Some(com);
            if self.task == Task::Shove {
                self.crate_mid = Some(self.sim.crate_pos(0));
            }
        }
        self.active_steps += 1;
        self.height_sum += com.y;
        if self.task == Task::Walk && self.sim.grounded_mass(0) > WALK_MAX_GROUNDED {
            self.fell = true;
        }
        let touching = &self.sim.creatures[0].grounded;
        if self.touch_steps.len() != touching.len() {
            self.touch_steps = vec![0; touching.len()];
        }
        for (n, &t) in self.touch_steps.iter_mut().zip(touching.iter()) {
            *n += t as u32;
        }
        if !self.sim.any_contact(0) {
            self.air_steps += 1;
        }
        self.path_len += (com - self.last_com).length();
        self.last_com = com;
        self.joint_err = self.joint_err.max(self.sim.joint_error(0));

        match self.task {
            Task::Chase => {
                let d = self.goal_dist();
                self.progress += self.last_goal_dist - d;
                self.last_goal_dist = d;
                if d < GOAL_REACH {
                    self.goals_reached += 1;
                    self.place_goal();
                }
            }
            Task::Jump => {
                self.best_low = self.best_low.max(self.sim.lowest_point(0));
                self.progress = self.best_low;
            }
            Task::Shove => {
                let mut d = self.sim.crate_pos(0) - self.crate_start;
                d.y = 0.0;
                self.progress = d.length();
            }
            _ => {
                self.progress = com.z - self.start.z;
            }
        }
    }

    /// Fitness of this trial so far.
    pub fn fitness(&self) -> f32 {
        if self.sim.creatures[0].exploded {
            return 0.0;
        }
        match self.task {
            Task::Sprint | Task::Swim | Task::Rough => {
                // A single lunge or a lucky topple shouldn't count: score
                // the whole run, but no more than twice what the second
                // half achieved.
                let total = self.progress;
                let second = match self.mid {
                    Some(m) => self.last_com.z - m.z,
                    None => 0.0,
                };
                total.min(2.0 * second).max(0.0)
            }
            Task::Chase => self.progress.max(0.0),
            Task::Jump => self.best_low.max(0.0),
            // Distance covered before the fall, or by the bell.
            Task::Walk => self.progress.max(0.0),
            Task::Shove => {
                // As with sprinting: one almighty kick shouldn't beat
                // steady pushing, so the second half has to hold up.
                let now = self.sim.crate_pos(0);
                let second = match self.crate_mid {
                    Some(m) => {
                        let mut d = now - m;
                        d.y = 0.0;
                        d.length()
                    }
                    None => 0.0,
                };
                self.progress.min(2.0 * second).max(0.0)
            }
        }
    }

    pub fn run(&mut self) {
        while !self.done() {
            self.step();
        }
    }

    /// (number of parts that regularly touch the ground, fraction of body
    /// mass in parts that don't). "Regularly" is a tenth of the scored time.
    pub fn footing(&self) -> (u32, f32) {
        let cr = &self.sim.creatures[0];
        let need = (self.active_steps / 10).max(1);
        let mut feet = 0;
        let mut off = 0.0;
        let mut total = 0.0;
        for (i, &b) in cr.bodies.iter().enumerate() {
            let m = self.sim.world.bodies[b].mass();
            total += m;
            if self.touch_steps.get(i).copied().unwrap_or(0) >= need {
                feet += 1;
            } else {
                off += m;
            }
        }
        (feet, off / total.max(1e-6))
    }
}

/// The same task under slightly different conditions: a bit less grip, a bit
/// less muscle, a small turn at the start. A real gait shrugs these off; a
/// trick that depends on one lucky collision does not.
pub fn wobbled(params: &SimParams) -> SimParams {
    let mut p = params.clone();
    p.friction *= 0.85;
    p.torque_per_area *= 0.95;
    p.spawn_yaw += 0.06;
    p
}

/// A creature must keep at least this fraction of its score under
/// `wobbled` conditions to be kept.
pub const ROBUST_FRACTION: f32 = 0.6;

/// Joints pulled this far apart mean the solver was being exploited.
pub const MAX_JOINT_ERR: f32 = 0.12;
/// One-step gain in centre-of-mass speed (m/s) beyond which a run is
/// thrown out as a physics glitch. 1.0 m/s per step is six g.
pub const MAX_KICK: f32 = 1.0;

pub fn evaluate(genome: &Genome, task: Task, params: &SimParams) -> Eval {
    let trials = task.trials();
    let mut out = Eval {
        valid: true,
        ..Default::default()
    };
    let mut fit = 0.0;
    let mut worst = f32::MAX;
    for trial in 0..trials {
        let mut ep = Episode::new(genome, task, trial, params);
        ep.run();
        let cr = &ep.sim.creatures[0];
        out.parts = cr.bp.parts.len() as u32;
        out.mass = cr.mass;
        out.spread = cr.bp.spread();
        out.joint_err = out.joint_err.max(ep.joint_err);
        out.kick = out.kick.max(ep.kick);
        if cr.exploded || ep.joint_err > MAX_JOINT_ERR || ep.kick > MAX_KICK {
            out.valid = false;
        }
        let n = ep.active_steps.max(1) as f32;
        out.stature += ep.height_sum / n / ep.body_len / trials as f32;
        out.airborne += ep.air_steps as f32 / n / trials as f32;
        let (feet, tiptoe) = ep.footing();
        out.feet = out.feet.max(feet);
        out.tiptoe += tiptoe / trials as f32;
        let net = (ep.last_com - ep.start).length();
        out.straightness += (net / ep.path_len.max(1e-3)).min(1.0) / trials as f32;
        let f = ep.fitness();
        fit += f / trials as f32;
        worst = worst.min(f);
    }
    // Reward doing every trial, not acing one: blend mean with worst.
    out.fitness = if trials > 1 {
        0.7 * fit + 0.3 * worst
    } else {
        fit
    };
    if !out.valid {
        out.fitness = 0.0;
    }
    out
}
