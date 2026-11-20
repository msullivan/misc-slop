// Evaluation worker for breeding in the browser: one simulator instance,
// scores whatever genomes it is sent.
import { loadEngine } from './engine.js';

let eng = null;
self.onmessage = async (ev) => {
  const m = ev.data;
  if (m.type === 'init') {
    try {
      eng = await loadEngine(m.module);
      self.postMessage({ type: 'ready' });
    } catch (err) {
      self.postMessage({ type: 'error', message: err.message || String(err) });
    }
  } else if (m.type === 'eval') {
    let result = null;
    try {
      result = eng.evaluate(m.genome, m.task, m.wobble);
    } catch {
      result = null;
    }
    self.postMessage({ type: 'eval', id: m.id, eval: result });
  }
};
