//! MAP-Elites: instead of one champion, keep the best creature found for
//! every combination of a few traits (how many parts, how tall it stands).
//! The result is a whole zoo of different body plans, each good at the task
//! in its own way, and the variety itself is what makes the search work.

use menagerie_core::env::{evaluate, wobbled, Eval, Task, ROBUST_FRACTION};
use menagerie_core::genome::Genome;
use menagerie_core::rng::Rng;
use menagerie_core::sim::SimParams;
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::Instant;

/// One ancestor. Elites hold an `Arc` to their node, nodes hold their
/// parent, so exactly the ancestry of living elites stays in memory.
pub struct Node {
    pub id: u64,
    pub parent: Option<Arc<Node>>,
    pub genome: Genome,
    pub fitness: f32,
    pub depth: u32,
    pub born: u64,
}

impl Drop for Node {
    fn drop(&mut self) {
        // Unlink iteratively so a long chain doesn't recurse off the stack.
        let mut next = self.parent.take();
        while let Some(arc) = next {
            match Arc::try_unwrap(arc) {
                Ok(mut node) => next = node.parent.take(),
                Err(_) => break,
            }
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Dim {
    pub name: String,
    pub lo: f32,
    pub hi: f32,
    pub bins: usize,
}

impl Dim {
    fn bin(&self, x: f32) -> usize {
        let t = ((x - self.lo) / (self.hi - self.lo)).clamp(0.0, 0.999_999);
        (t * self.bins as f32) as usize
    }
}

pub fn dims_for(task: Task) -> Vec<Dim> {
    match task {
        // Nothing to stand on in water: sort by size and sprawl instead.
        Task::Swim => vec![
            Dim {
                name: "parts".into(),
                lo: 2.0,
                hi: 15.0,
                bins: 13,
            },
            Dim {
                name: "spread".into(),
                lo: 0.5,
                hi: 1.7,
                bins: 8,
            },
        ],
        // Walkers are all up on their legs by rule, so sort them by how
        // tall they stand instead.
        Task::Walk => vec![
            Dim {
                name: "feet".into(),
                lo: 1.0,
                hi: 9.0,
                bins: 8,
            },
            Dim {
                name: "stature".into(),
                lo: 0.4,
                hi: 2.0,
                bins: 8,
            },
        ],
        _ => vec![
            Dim {
                name: "feet".into(),
                lo: 1.0,
                hi: 9.0,
                bins: 8,
            },
            Dim {
                name: "tiptoe".into(),
                lo: 0.0,
                hi: 1.0,
                bins: 8,
            },
        ],
    }
}

fn descriptor(name: &str, e: &Eval) -> f32 {
    match name {
        "parts" => e.parts as f32 + 0.5,
        "feet" => e.feet as f32 + 0.5,
        "tiptoe" => e.tiptoe,
        "stature" => e.stature,
        "airborne" => e.airborne,
        "spread" => e.spread,
        "straightness" => e.straightness,
        _ => panic!("unknown descriptor {name}"),
    }
}

/// Every part has to earn its keep: within a cell a creature is ranked on
/// its score discounted by this much per body part, so a limb that adds
/// nothing loses to the same animal without it. The score shown is still
/// the plain, undiscounted one.
pub const PART_COST: f32 = 0.02;

fn standing(e: &Eval) -> f32 {
    e.fitness * (1.0 - PART_COST).powi(e.parts as i32)
}

#[derive(Clone)]
pub struct Elite {
    pub node: Arc<Node>,
    pub eval: Eval,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct EliteOut {
    pub cell: Vec<usize>,
    pub id: u64,
    pub depth: u32,
    pub born: u64,
    pub fitness: f32,
    pub eval: Eval,
    pub genome: Genome,
    /// Which isolated family (island) this creature belongs to.
    #[serde(default)]
    pub family: usize,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct Ancestor {
    pub id: u64,
    pub depth: u32,
    pub born: u64,
    pub fitness: f32,
    pub genome: Genome,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct HistoryPoint {
    pub evals: u64,
    pub best: f32,
    pub filled: usize,
    pub qd: f32,
    pub secs: f32,
}

#[derive(Serialize, Deserialize)]
pub struct ArchiveOut {
    pub task: Task,
    pub seed: u64,
    pub evals: u64,
    pub dims: Vec<Dim>,
    pub params: SimParams,
    /// The best creature per cell across all families.
    pub elites: Vec<EliteOut>,
    /// Each family's own complete map.
    #[serde(default)]
    pub families: Vec<FamilyOut>,
    #[serde(default)]
    pub history: Vec<HistoryPoint>,
    /// Sampled ancestry of each family's champion, oldest first.
    pub lineages: Vec<Vec<Ancestor>>,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct FamilyOut {
    pub evals: u64,
    pub elites: Vec<EliteOut>,
    pub history: Vec<HistoryPoint>,
}

pub struct Config {
    pub task: Task,
    pub seed: u64,
    pub evals: u64,
    pub batch: usize,
    pub init: usize,
    pub out: String,
    /// How many isolated families to evolve. The evaluation budget is
    /// split evenly between them.
    pub islands: usize,
    /// Founders handed to each family (may be empty).
    pub seeds: Vec<Vec<Genome>>,
    pub params: SimParams,
}

pub struct Archive {
    pub dims: Vec<Dim>,
    pub cells: Vec<Option<Elite>>,
}

impl Archive {
    pub fn new(dims: Vec<Dim>) -> Self {
        let n = dims.iter().map(|d| d.bins).product();
        Archive {
            dims,
            cells: vec![None; n],
        }
    }

    fn index(&self, e: &Eval) -> usize {
        let mut idx = 0;
        for d in self.dims.iter() {
            idx = idx * d.bins + d.bin(descriptor(&d.name, e));
        }
        idx
    }

    fn cell_coords(&self, mut idx: usize) -> Vec<usize> {
        let mut out = vec![0; self.dims.len()];
        for (k, d) in self.dims.iter().enumerate().rev() {
            out[k] = idx % d.bins;
            idx /= d.bins;
        }
        out
    }

    /// Would this candidate take a cell right now?
    pub fn wants(&self, eval: &Eval) -> bool {
        if !eval.valid || eval.fitness <= 0.0 {
            return false;
        }
        match &self.cells[self.index(eval)] {
            None => true,
            Some(old) => standing(eval) > standing(&old.eval),
        }
    }

    /// Returns true if the candidate took a cell.
    pub fn offer(&mut self, node: Arc<Node>, eval: Eval) -> bool {
        if !eval.valid || eval.fitness <= 0.0 {
            return false;
        }
        let idx = self.index(&eval);
        let better = match &self.cells[idx] {
            None => true,
            Some(old) => standing(&eval) > standing(&old.eval),
        };
        if better {
            self.cells[idx] = Some(Elite { node, eval });
        }
        better
    }

    pub fn filled(&self) -> usize {
        self.cells.iter().filter(|c| c.is_some()).count()
    }

    pub fn best(&self) -> f32 {
        self.cells
            .iter()
            .flatten()
            .map(|e| e.eval.fitness)
            .fold(0.0, f32::max)
    }

    pub fn qd(&self) -> f32 {
        self.cells.iter().flatten().map(|e| e.eval.fitness).sum()
    }
}

/// Up to `max` ancestors evenly spaced along the chain, oldest first,
/// always including the founder and the elite itself.
fn sample_lineage(node: &Arc<Node>, max: usize) -> Vec<Ancestor> {
    let mut chain: Vec<&Node> = Vec::new();
    let mut cur: Option<&Arc<Node>> = Some(node);
    while let Some(n) = cur {
        chain.push(n);
        cur = n.parent.as_ref();
    }
    chain.reverse();
    let n = chain.len();
    let picks: Vec<usize> = if n <= max {
        (0..n).collect()
    } else {
        (0..max).map(|i| i * (n - 1) / (max - 1)).collect()
    };
    picks
        .into_iter()
        .map(|i| {
            let a = chain[i];
            Ancestor {
                id: a.id,
                depth: a.depth,
                born: a.born,
                fitness: a.fitness,
                genome: a.genome.clone(),
            }
        })
        .collect()
}

/// One family's finished (or in-progress) run.
pub struct Island {
    pub arch: Archive,
    pub history: Vec<HistoryPoint>,
    pub evals: u64,
}

fn elites_out(arch: &Archive, family: usize) -> Vec<EliteOut> {
    let mut elites = Vec::new();
    for (i, c) in arch.cells.iter().enumerate() {
        if let Some(e) = c {
            elites.push(EliteOut {
                cell: arch.cell_coords(i),
                id: e.node.id,
                depth: e.node.depth,
                born: e.node.born,
                fitness: e.eval.fitness,
                eval: e.eval.clone(),
                genome: e.node.genome.clone(),
                family,
            });
        }
    }
    elites
}

pub fn snapshot(islands: &[Island], cfg: &Config) -> ArchiveOut {
    let dims = dims_for(cfg.task);
    let families: Vec<FamilyOut> = islands
        .iter()
        .enumerate()
        .map(|(k, isl)| FamilyOut {
            evals: isl.evals,
            elites: elites_out(&isl.arch, k),
            history: isl.history.clone(),
        })
        .collect();
    // Best per cell across families, by the same ranking used within one.
    let n_cells: usize = dims.iter().map(|d| d.bins).product();
    let mut merged: Vec<Option<&EliteOut>> = vec![None; n_cells];
    for fam in families.iter() {
        for e in fam.elites.iter() {
            let mut idx = 0;
            for (c, d) in e.cell.iter().zip(dims.iter()) {
                idx = idx * d.bins + c;
            }
            let better = match merged[idx] {
                None => true,
                Some(old) => standing(&e.eval) > standing(&old.eval),
            };
            if better {
                merged[idx] = Some(e);
            }
        }
    }
    let lineages = islands
        .iter()
        .filter_map(|isl| {
            isl.arch
                .cells
                .iter()
                .flatten()
                .max_by(|a, b| a.eval.fitness.partial_cmp(&b.eval.fitness).unwrap())
                .map(|e| sample_lineage(&e.node, 24))
        })
        .collect();
    ArchiveOut {
        task: cfg.task,
        seed: cfg.seed,
        evals: islands.iter().map(|i| i.evals).sum(),
        dims,
        params: cfg.params.clone(),
        elites: merged.into_iter().flatten().cloned().collect(),
        families,
        history: Vec::new(),
        lineages,
    }
}

fn write_out(path: &str, out: &ArchiveOut) {
    let tmp = format!("{path}.tmp");
    std::fs::write(&tmp, serde_json::to_vec(out).unwrap()).expect("write archive");
    std::fs::rename(&tmp, path).expect("rename archive");
}

/// Offer a batch of evaluated candidates to the archive. Anything that
/// would take a cell must first repeat its performance under wobbled
/// conditions; one-off flukes and physics tricks fail that and are dropped.
fn admit(arch: &mut Archive, cfg: &Config, batch: Vec<(Arc<Node>, Eval)>, stats: &mut Stats) {
    let hopefuls: Vec<(Arc<Node>, Eval)> =
        batch.into_iter().filter(|(_, e)| arch.wants(e)).collect();
    let wob = wobbled(&cfg.params);
    let checks: Vec<Eval> = hopefuls
        .par_iter()
        .map(|(n, _)| evaluate(&n.genome, cfg.task, &wob))
        .collect();
    for ((node, eval), check) in hopefuls.into_iter().zip(checks) {
        if check.valid && check.fitness >= ROBUST_FRACTION * eval.fitness {
            if arch.offer(node, eval) {
                stats.admitted += 1;
            }
        } else {
            stats.flukes += 1;
        }
    }
}

#[derive(Default)]
struct Stats {
    admitted: u64,
    flukes: u64,
}

/// Evolve one family in isolation.
fn run_island(cfg: &Config, k: usize, budget: u64, next_id: &mut u64) -> Island {
    let mut rng = Rng::new(cfg.seed.wrapping_mul(1_000_003).wrapping_add(k as u64));
    let mut arch = Archive::new(dims_for(cfg.task));
    let mut evals: u64 = 0;
    let mut history: Vec<HistoryPoint> = Vec::new();
    let mut stats = Stats::default();
    let t0 = Instant::now();
    let mut last_print = Instant::now();
    let label = format!("{} {}/{}", cfg.task.name(), k + 1, cfg.islands);

    let mut fresh = |genome: Genome, parent: Option<Arc<Node>>, e: &Eval, evals: u64| {
        let node = Arc::new(Node {
            id: *next_id,
            depth: parent.as_ref().map(|p| p.depth + 1).unwrap_or(0),
            parent,
            genome,
            fitness: e.fitness,
            born: evals,
        });
        *next_id += 1;
        node
    };

    // Founders: any seeds we were given, then random genomes.
    let mut founders: Vec<Genome> = cfg.seeds.get(k).cloned().unwrap_or_default();
    while founders.len() < cfg.init {
        founders.push(Genome::random(&mut rng));
    }
    let results: Vec<Eval> = founders
        .par_iter()
        .map(|g| evaluate(g, cfg.task, &cfg.params))
        .collect();
    let mut batch = Vec::new();
    for (g, e) in founders.into_iter().zip(results) {
        evals += 1;
        batch.push((fresh(g, None, &e, evals), e));
    }
    admit(&mut arch, cfg, batch, &mut stats);
    eprintln!(
        "[{label}] founders: {} cells filled, best {:.3}",
        arch.filled(),
        arch.best()
    );

    while evals < budget {
        let living: Vec<&Elite> = arch.cells.iter().flatten().collect();
        let mut kids: Vec<(Option<Arc<Node>>, Genome)> = Vec::with_capacity(cfg.batch);
        for _ in 0..cfg.batch {
            if living.is_empty() {
                // Nothing viable yet: keep sampling random genomes.
                kids.push((None, Genome::random(&mut rng)));
                continue;
            }
            let a = living[rng.below(living.len())];
            let g = if rng.chance(0.12) {
                let b = living[rng.below(living.len())];
                a.node
                    .genome
                    .crossed(&b.node.genome, &mut rng)
                    .mutated(&mut rng)
            } else {
                a.node.genome.mutated(&mut rng)
            };
            kids.push((Some(a.node.clone()), g));
        }
        drop(living);
        let rs: Vec<Eval> = kids
            .par_iter()
            .map(|(_, g)| evaluate(g, cfg.task, &cfg.params))
            .collect();
        let mut batch = Vec::new();
        for ((parent, g), e) in kids.into_iter().zip(rs) {
            evals += 1;
            batch.push((fresh(g, parent, &e, evals), e));
        }
        admit(&mut arch, cfg, batch, &mut stats);

        if last_print.elapsed().as_secs_f32() > 15.0 || evals >= budget {
            last_print = Instant::now();
            let secs = t0.elapsed().as_secs_f32();
            let hp = HistoryPoint {
                evals,
                best: arch.best(),
                filled: arch.filled(),
                qd: arch.qd(),
                secs,
            };
            eprintln!(
                "[{label}] evals {:>8}  {:>5.0}/s  filled {:>3}/{}  best {:>7.3}  qd {:>7.1}  admitted {} flukes {}",
                evals,
                evals as f32 / secs,
                hp.filled,
                arch.cells.len(),
                hp.best,
                hp.qd,
                stats.admitted,
                stats.flukes
            );
            history.push(hp);
        }
    }
    Island {
        arch,
        history,
        evals,
    }
}

/// Evolve every family in turn, saving after each one finishes.
pub fn run(cfg: Config) {
    let budget = cfg.evals / cfg.islands.max(1) as u64;
    let mut next_id: u64 = 1;
    let mut islands: Vec<Island> = Vec::new();
    for k in 0..cfg.islands.max(1) {
        islands.push(run_island(&cfg, k, budget, &mut next_id));
        write_out(&cfg.out, &snapshot(&islands, &cfg));
    }
    let best = islands.iter().map(|i| i.arch.best()).fold(0.0, f32::max);
    eprintln!(
        "[{}] done: {} families, best {:.3}, wrote {}",
        cfg.task.name(),
        islands.len(),
        best,
        cfg.out
    );
}
