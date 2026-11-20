// Print a creature's centre of mass over a scored run.
// usage: node tools/com.mjs ARCHIVE.json [rank|x,y] [every_steps]
import { readFileSync } from 'node:fs';
import { loadEngine } from '../web/engine.js';
const [archPath, which = '0', every = '30'] = process.argv.slice(2);
const eng = await loadEngine(readFileSync(new URL('../web/mg.wasm', import.meta.url)));
const arch = JSON.parse(readFileSync(archPath, 'utf8'));
const sorted = [...arch.elites].sort((a, b) => b.fitness - a.fitness);
const e = which.includes(',') ? arch.elites.find((x) => x.cell.join(',') === which) : sorted[Number(which)];
console.log('cell', e.cell, 'fitness', e.fitness, 'parts', e.eval.parts);
const w = eng.episode(e.genome, arch.task, 0);
let step = 0;
while (!w.score().done) {
  w.step(1);
  step++;
  if (step % Number(every) === 0) {
    const s = w.state(0);
    const sp = Math.hypot(...s.vel);
    console.log(`t=${(step / 60).toFixed(2)} com=(${s.com.map((v) => v.toFixed(2)).join(', ')}) speed=${sp.toFixed(2)}`);
  }
}
