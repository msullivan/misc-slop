//! The renderer draws the rough-ground mesh from the same height samples
//! the simulator collides with. Check they agree on which sample is where.

use menagerie_core::env::rough_terrain;
use menagerie_core::rapier3d::prelude::*;
use menagerie_core::sim::{Sim, SimParams, Terrain};

#[test]
fn height_samples_land_where_the_renderer_expects() {
    let terrain = rough_terrain(0);
    let Terrain::Heights {
        nx,
        nz,
        heights,
        size,
        centre,
    } = &terrain
    else {
        panic!("expected heights")
    };
    let mut sim = Sim::new(SimParams::default(), &terrain);
    sim.world.step();
    let mut checked = 0;
    for iz in (3..*nz - 3).step_by(7) {
        for ix in (3..*nx - 3).step_by(5) {
            let x = centre[0] + size[0] * (ix as f32 / (*nx - 1) as f32 - 0.5);
            let z = centre[1] + size[1] * (iz as f32 / (*nz - 1) as f32 - 0.5);
            let want = heights[iz * nx + ix];
            // Aim a hair inside the cell: a ray straight down a shared
            // triangle edge can slip between the two triangles.
            let ray = Ray::new(
                Vector::new(x + 0.01, 10.0, z + 0.013),
                Vector::new(0.0, -1.0, 0.0),
            );
            let (_, toi) = sim
                .world
                .cast_ray(&ray, 100.0, true, QueryFilter::default())
                .expect("ray hits ground");
            let got = 10.0 - toi;
            // The flat far-field floor sits at y = 0 under the hills.
            let want = want.max(0.0);
            assert!(
                (got - want).abs() < 0.03,
                "at grid ({ix},{iz}) = world ({x:.2},{z:.2}): sim {got:.3}, samples {want:.3}"
            );
            checked += 1;
        }
    }
    assert!(checked > 50);
}
