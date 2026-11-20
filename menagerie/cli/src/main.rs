mod evo;

use menagerie_core::env::{evaluate, Task};
use menagerie_core::genome::Genome;
use menagerie_core::rng::Rng;
use rayon::prelude::*;
use std::collections::HashMap;
use std::time::Instant;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let cmd = args.get(1).map(|s| s.as_str()).unwrap_or("help");
    match cmd {
        "smoke" => smoke(&args[2..]),
        "evolve" => evolve(&args[2..]),
        "eval" => eval_file(&args[2..]),
        "trace" => trace(&args[2..]),
        "diag" => diag(&args[2..]),
        _ => eprintln!(
            "usage:\n  menagerie smoke [task] [n]\n  menagerie evolve --task T --out FILE [--islands N] [--seed N] [--evals N] [--batch N] [--init N] [--from ARCHIVE]... [--threads N]\n  menagerie eval TASK GENOME.json"
        ),
    }
}

/// `--key value` pairs; repeated keys accumulate.
fn flags(args: &[String]) -> HashMap<String, Vec<String>> {
    let mut m: HashMap<String, Vec<String>> = HashMap::new();
    let mut i = 0;
    while i < args.len() {
        let k = args[i].trim_start_matches("--").to_string();
        let v = args.get(i + 1).cloned().unwrap_or_default();
        m.entry(k).or_default().push(v);
        i += 2;
    }
    m
}

fn evolve(args: &[String]) {
    let f = flags(args);
    let get = |k: &str| f.get(k).and_then(|v| v.last()).cloned();
    let task = Task::parse(&get("task").expect("--task")).expect("unknown task");
    if let Some(n) = get("threads").and_then(|s| s.parse::<usize>().ok()) {
        rayon::ThreadPoolBuilder::new()
            .num_threads(n)
            .build_global()
            .unwrap();
    }
    let islands: usize = get("islands")
        .and_then(|s| s.parse().ok())
        .unwrap_or(1)
        .max(1);
    // Founders from earlier runs. Family k of this run descends from
    // family k of each source, so families stay distinct across habitats.
    let mut seeds: Vec<Vec<Genome>> = vec![Vec::new(); islands];
    for path in f.get("from").into_iter().flatten() {
        let data = std::fs::read(path).expect("read --from archive");
        let arch: evo::ArchiveOut = serde_json::from_slice(&data).expect("parse --from archive");
        if arch.families.is_empty() {
            for s in seeds.iter_mut() {
                s.extend(arch.elites.iter().map(|e| e.genome.clone()));
            }
        } else {
            for (k, s) in seeds.iter_mut().enumerate() {
                let fam = &arch.families[k % arch.families.len()];
                s.extend(fam.elites.iter().map(|e| e.genome.clone()));
            }
        }
    }
    let cfg = evo::Config {
        task,
        seed: get("seed").and_then(|s| s.parse().ok()).unwrap_or(1),
        evals: get("evals").and_then(|s| s.parse().ok()).unwrap_or(200_000),
        // Fixed, not scaled to the machine: batch size shapes the search,
        // and a seed should mean the same run everywhere.
        batch: get("batch").and_then(|s| s.parse().ok()).unwrap_or(512),
        init: get("init").and_then(|s| s.parse().ok()).unwrap_or(4000),
        out: get("out").expect("--out"),
        islands,
        seeds,
        params: task.params(),
    };
    evo::run(cfg);
}

fn eval_file(args: &[String]) {
    let task = Task::parse(&args[0]).expect("task");
    let g: Genome = serde_json::from_slice(&std::fs::read(&args[1]).expect("read")).expect("parse");
    let e = evaluate(&g, task, &task.params());
    println!("{}", serde_json::to_string_pretty(&e).unwrap());
}

/// Evaluate a pile of random genomes: timing and sanity statistics.
fn smoke(args: &[String]) {
    let task = Task::parse(args.first().map(|s| s.as_str()).unwrap_or("sprint")).expect("task");
    let n: usize = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(2000);
    let mut params = task.params();
    apply_overrides(&mut params, args);
    let mut rng = Rng::new(1);
    // Random genomes, or the elites of an archive if one is given.
    let genomes: Vec<Genome> = match args.get(2).filter(|a| !a.contains('=')) {
        Some(path) => {
            let arch: evo::ArchiveOut =
                serde_json::from_slice(&std::fs::read(path).expect("read")).expect("parse");
            arch.elites.into_iter().map(|e| e.genome).collect()
        }
        None => (0..n).map(|_| Genome::random(&mut rng)).collect(),
    };
    let n = genomes.len();
    let t0 = Instant::now();
    let evals: Vec<_> = genomes
        .par_iter()
        .map(|g| evaluate(g, task, &params))
        .collect();
    let dt = t0.elapsed().as_secs_f64();
    let valid = evals.iter().filter(|e| e.valid).count();
    let mut fits: Vec<f32> = evals.iter().map(|e| e.fitness).collect();
    fits.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let mut k2: Vec<f32> = evals.iter().map(|e| e.kick).collect();
    k2.sort_by(|a, b| a.partial_cmp(b).unwrap());
    println!(
        "kick p50 {:.3} p90 {:.3} p99 {:.3} p99.9 {:.3} max {:.3}",
        k2[n / 2],
        k2[n * 9 / 10],
        k2[n * 99 / 100],
        k2[n * 999 / 1000],
        k2[n - 1]
    );
    // Save the few worst offenders for a closer look.
    let mut order: Vec<usize> = (0..n).collect();
    order.sort_by(|&a, &b| evals[b].kick.partial_cmp(&evals[a].kick).unwrap());
    for (rank, &i) in order.iter().take(4).enumerate() {
        let path = format!("runs/kick{rank}.json");
        if std::fs::write(&path, serde_json::to_vec(&genomes[i]).unwrap()).is_ok() {
            println!(
                "  {path}: kick {:.2} parts {} valid {}",
                evals[i].kick, evals[i].parts, evals[i].valid
            );
        }
    }
    let mut j2: Vec<f32> = evals.iter().map(|e| e.joint_err).collect();
    j2.sort_by(|a, b| a.partial_cmp(b).unwrap());
    println!(
        "{n} evals in {dt:.2}s = {:.0}/s ({} threads)",
        n as f64 / dt,
        rayon::current_num_threads()
    );
    println!("valid {valid}/{n}");
    println!(
        "fitness p50 {:.3} p90 {:.3} p99 {:.3} max {:.3}",
        fits[n / 2],
        fits[n * 9 / 10],
        fits[n * 99 / 100],
        fits[n - 1]
    );
    println!(
        "joint_err p50 {:.4} p90 {:.4} p99 {:.4} max {:.4}",
        j2[n / 2],
        j2[n * 9 / 10],
        j2[n * 99 / 100],
        j2[n - 1]
    );
    let mean =
        |f: &dyn Fn(&menagerie_core::env::Eval) -> f32| evals.iter().map(f).sum::<f32>() / n as f32;
    println!(
        "mean parts {:.1} stature {:.2} airborne {:.3} spread {:.2}",
        mean(&|e| e.parts as f32),
        mean(&|e| e.stature),
        mean(&|e| e.airborne),
        mean(&|e| e.spread)
    );
}

/// Print the root body's exact state every step, for comparing builds.
fn trace(args: &[String]) {
    use menagerie_core::env::Episode;
    let task = Task::parse(&args[0]).expect("task");
    let g: Genome = serde_json::from_slice(&std::fs::read(&args[1]).expect("read")).expect("parse");
    let mut ep = Episode::new(&g, task, 0, &task.params());
    while !ep.done() {
        ep.step();
        let mut buf = Vec::new();
        ep.sim.write_transforms(0, &mut buf);
        let bits: Vec<String> = buf
            .iter()
            .take(7)
            .map(|f| format!("{:08x}", f.to_bits()))
            .collect();
        println!("{} {}", ep.sim.steps, bits.join(" "));
    }
}

/// Human-readable per-step diagnostics: `menagerie diag TASK GENOME [from_step to_step] [key=value...]`.
fn diag(args: &[String]) {
    use menagerie_core::env::Episode;
    let task = Task::parse(&args[0]).expect("task");
    let g: Genome = serde_json::from_slice(&std::fs::read(&args[1]).expect("read")).expect("parse");
    let from: u32 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(0);
    let to: u32 = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(u32::MAX);
    let mut params = task.params();
    apply_overrides(&mut params, &args[2..]);
    let mut ep = Episode::new(&g, task, 0, &params);
    let mut peak = 0.0f32;
    while !ep.done() {
        ep.step();
        let sim = &ep.sim;
        let cr = &sim.creatures[0];
        let v = sim.com_vel(0).length();
        peak = peak.max(v);
        if sim.steps >= from && sim.steps <= to {
            let speeds: Vec<String> = cr
                .bodies
                .iter()
                .map(|&b| format!("{:.1}", sim.world.bodies[b].linvel().length()))
                .collect();
            let angs: Vec<String> = cr
                .angle
                .iter()
                .skip(1)
                .zip(cr.bp.parts.iter().skip(1))
                .map(|(a, p)| format!("{:.2}[{:.2},{:.2}]", a, p.lo, p.hi))
                .collect();
            let touch: String = cr
                .touching
                .iter()
                .map(|&t| if t { 'x' } else { '.' })
                .collect();
            println!(
                "step {} t={:.3} com_y={:.2} com_v={:.2} jerr={:.3} touch={} v=[{}] ang=[{}]",
                sim.steps,
                sim.time,
                sim.com(0).y,
                v,
                sim.joint_error(0),
                touch,
                speeds.join(" "),
                angs.join(" ")
            );
        }
    }
    println!(
        "fitness {:.3} peak com speed {:.2} max joint err {:.3} exploded {}",
        ep.fitness(),
        peak,
        ep.joint_err,
        ep.sim.creatures[0].exploded
    );
}

/// `key=value` tweaks to the physics parameters, for experiments.
fn apply_overrides(p: &mut menagerie_core::sim::SimParams, args: &[String]) {
    let mut v = serde_json::to_value(&*p).unwrap();
    for a in args {
        if let Some((k, val)) = a.split_once('=') {
            let parsed: serde_json::Value =
                serde_json::from_str(val).unwrap_or(serde_json::Value::String(val.to_string()));
            v[k] = parsed;
        }
    }
    *p = serde_json::from_value(v).expect("bad override");
}
