// Does the browser build reproduce the fitness evolution recorded natively?
// usage: node tools/check_wasm.mjs web/mg.wasm runs/some-archive.json
import { readFileSync } from 'node:fs';
import { loadEngine } from '../web/engine.js';

const [wasmPath, archivePath] = process.argv.slice(2);
const eng = await loadEngine(readFileSync(wasmPath));
const arch = JSON.parse(readFileSync(archivePath, 'utf8'));
const trials = { chase: 3, rough: 2 }[arch.task] ?? 1;
let worst = 0;
let bad = 0;
const t0 = performance.now();
// Every creature of every family, not just the merged map.
const everyone = arch.families && arch.families.length ? arch.families.flatMap((f) => f.elites) : arch.elites;
for (const e of everyone) {
  const fits = [];
  for (let t = 0; t < trials; t++) {
    const w = eng.episode(e.genome, arch.task, t);
    while (!w.score().done) w.step(30);
    fits.push(w.score().fitness);
    w.free();
  }
  const mean = fits.reduce((a, b) => a + b, 0) / trials;
  const fit = trials > 1 ? 0.7 * mean + 0.3 * Math.min(...fits) : mean;
  const err = Math.abs(fit - e.fitness);
  worst = Math.max(worst, err);
  if (err > 1e-4) {
    bad++;
    if (bad <= 5) console.log(`mismatch id ${e.id}: native ${e.fitness} wasm ${fit}`);
  }
}
const ms = performance.now() - t0;
console.log(`${arch.task}: ${everyone.length} creatures, ${bad} mismatched, worst error ${worst.toExponential(2)}, ${(ms / everyone.length / trials).toFixed(1)} ms per episode`);
process.exit(bad ? 1 : 0);
