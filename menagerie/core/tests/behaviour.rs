//! Properties the rest of the project leans on.

use menagerie_core::body::Blueprint;
use menagerie_core::env::{evaluate, Episode, Task};
use menagerie_core::genome::{Genome, MAX_PARTS};
use menagerie_core::rapier3d::math::Vector;
use menagerie_core::rng::Rng;

#[test]
fn mutation_gives_valid_genomes_that_differ_from_the_parent() {
    let mut rng = Rng::new(7);
    for _ in 0..40 {
        let mut g = Genome::random(&mut rng);
        for _ in 0..40 {
            let child = g.mutated(&mut rng);
            assert!(child.is_valid());
            let n = Blueprint::build(&child).parts.len();
            assert!((2..=MAX_PARTS).contains(&n));
            // Same genome back means fifty attempts all failed; possible
            // in principle, but it should be vanishingly rare.
            let mut a = child.clone();
            let mut b = g.clone();
            a.hue = 0.0;
            b.hue = 0.0;
            assert!(a != b, "mutation returned a clone");
            g = child;
        }
    }
}

#[test]
fn scoring_the_same_genome_twice_gives_the_same_bits() {
    let mut rng = Rng::new(11);
    for task in [Task::Sprint, Task::Walk, Task::Swim, Task::Shove] {
        for _ in 0..6 {
            let g = Genome::random(&mut rng);
            let a = evaluate(&g, task, &task.params());
            let b = evaluate(&g, task, &task.params());
            assert_eq!(a.fitness.to_bits(), b.fitness.to_bits());
            assert_eq!(a.valid, b.valid);
        }
    }
}

#[test]
fn a_genome_survives_a_trip_through_json() {
    let mut rng = Rng::new(3);
    for _ in 0..50 {
        let g = Genome::random(&mut rng).mutated(&mut rng);
        let text = serde_json::to_string(&g).unwrap();
        let back: Genome = serde_json::from_str(&text).unwrap();
        assert_eq!(g, back);
    }
}

#[test]
fn mirrored_limbs_are_mirror_images() {
    let mut rng = Rng::new(5);
    let mut checked = 0;
    for _ in 0..400 {
        let g = Genome::random(&mut rng);
        let bp = Blueprint::build(&g);
        // Every flipped part hanging directly off the root must have an
        // unflipped twin at the reflected position.
        for p in bp.parts.iter().filter(|p| p.flip && p.parent == Some(0)) {
            let want = Vector::new(-p.pos.x, p.pos.y, p.pos.z);
            let twin = bp
                .parts
                .iter()
                .filter(|q| !q.flip && q.parent == Some(0) && q.gene == p.gene)
                .any(|q| (q.pos - want).length() < 1e-5 && (q.half - p.half).length() < 1e-6);
            assert!(twin, "no mirror twin for a flipped limb");
            checked += 1;
        }
    }
    assert!(checked > 50);
}

/// The creature that taught this project to distrust its physics: under the
/// early settings (rounded colliders, no glitch checks) it flies 17.7 m;
/// under today's rules it is caught and scores nothing.
#[test]
fn the_catapult_only_works_under_the_old_physics() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../web/data/catapult.json");
    let g: Genome = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();

    let mut old = Task::Sprint.params();
    old.rounded = true;
    old.density = 700.0;
    old.torque_per_area = 6000.0;
    old.settle = 1.5;
    old.preroll = false;
    old.max_speed = 1.0e9;
    let mut ep = Episode::new(&g, Task::Sprint, 0, &old);
    ep.run();
    assert!(
        ep.fitness() > 17.0,
        "the cheat no longer reproduces: {}",
        ep.fitness()
    );
    assert!(
        ep.kick > 10.0,
        "launch should be a huge one-step kick, got {}",
        ep.kick
    );

    let honest = evaluate(&g, Task::Sprint, &Task::Sprint.params());
    assert!(
        honest.fitness < 3.0,
        "today's physics should not launch it: {}",
        honest.fitness
    );
}
