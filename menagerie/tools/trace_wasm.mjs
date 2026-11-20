// Print the root body's exact state every step (compare with `menagerie trace`).
import { readFileSync } from 'node:fs';
import { loadEngine } from '../web/engine.js';
const [wasmPath, task, genomePath] = process.argv.slice(2);
const eng = await loadEngine(readFileSync(wasmPath));
const w = eng.episode(readFileSync(genomePath, 'utf8'), task, 0);
let step = 0;
while (!w.score().done) {
  w.step(1);
  step++;
  const t = w.transforms(0);
  const bits = new Uint32Array(t.buffer, t.byteOffset, 7);
  console.log(step + ' ' + Array.from(bits, (b) => b.toString(16).padStart(8, '0')).join(' '));
}
