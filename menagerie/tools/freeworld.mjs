// Do creatures perform in an open world (race/roam) as they do in a scored trial?
// usage: node tools/freeworld.mjs ARCHIVE.json
import { readFileSync } from 'node:fs';
import { loadEngine } from '../web/engine.js';
const eng = await loadEngine(readFileSync(new URL('../web/mg.wasm', import.meta.url)));
const arch = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const everyone = arch.families.length ? arch.families.flatMap((f) => f.elites) : arch.elites;
let bad = 0;
const ratios = [];
for (const e of everyone) {
  const w = eng.world(arch.task);
  w.add(e.genome, 0, 0, 0, 0);
  // Wait out the settling (the clock sits below zero until it's over),
  // then give it exactly a trial's worth of time.
  let guard = 0;
  do w.step(1); while (w.time < 0 && guard++ < 400);
  const z0 = w.state(0).com[2];
  w.step(Math.round((0.5 + 10) * 60));
  const z = w.state(0).com[2] - z0;
  w.free();
  const ratio = z / e.fitness;
  ratios.push(ratio);
  if (ratio < 0.5) bad++;
}
ratios.sort((a, b) => a - b);
console.log(`${everyone.length} creatures: ${bad} cover less than half their scored distance in the open; median ratio ${ratios[ratios.length >> 1].toFixed(2)}, p10 ${ratios[Math.floor(ratios.length / 10)].toFixed(2)}`);
