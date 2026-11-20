// How well do chase creatures actually steer? Flags reached per trial.
// usage: node tools/chase_report.mjs ARCHIVE.json [top_n]
import { readFileSync } from 'node:fs';
import { loadEngine } from '../web/engine.js';
const [archPath, top = '8'] = process.argv.slice(2);
const eng = await loadEngine(readFileSync(new URL('../web/mg.wasm', import.meta.url)));
const arch = JSON.parse(readFileSync(archPath, 'utf8'));
const everyone = arch.families && arch.families.length ? arch.families.flatMap((f) => f.elites) : arch.elites;
const sorted = [...everyone].sort((a, b) => b.fitness - a.fitness).slice(0, Number(top));
for (const e of sorted) {
  const rows = [];
  for (let t = 0; t < 3; t++) {
    const w = eng.episode(e.genome, 'chase', t);
    while (!w.score().done) w.step(30);
    const s = w.score();
    rows.push(`${s.goals} flags/${s.progress.toFixed(1)} m`);
    w.free();
  }
  console.log(`family ${e.family ?? 0} cell ${e.cell} fitness ${e.fitness.toFixed(2)} parts ${e.eval.parts}: ${rows.join(' | ')}`);
}
