// In the page's Race and Lineage views, does every lane's creature do what
// it was scored doing?
//
// For each habitat, both views, and each of the habitat's trials in turn,
// this runs the lanes to the bell the way the page steps them, then holds
// each lane to two standards:
//   1. an independent replay of that creature on that trial (eng.episode,
//      run on its own) must give the very same number, bit for bit;
//   2. the score evolution recorded for it (the elite's `fitness`, or the
//      ancestor's own in a lineage) must match what the lanes add up to,
//      blending trials as evolution did, to within the rounding of the
//      stored figure.
// Exits non-zero if any lane fails either.
//
// usage: node tools/racecheck.mjs [task ...]     (needs the page served on :8765)
import { createRequire } from 'node:module';
import { execSync } from 'node:child_process';
const require = createRequire(execSync('npm root -g').toString().trim() + '/');
const { chromium } = require('playwright');

const ALL = ['walk', 'sprint', 'rough', 'chase', 'shove', 'swim', 'jump'];
const TRIALS = { chase: 3, rough: 2 };
// Stored scores are rounded to four places (tools/pack.py).
const ROUNDING = 1e-4;
const tasks = process.argv.slice(2).length ? process.argv.slice(2) : ALL;

const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
await page.goto('http://localhost:8765/index.html');
await page.waitForFunction(() => window.menagerie, null, { timeout: 30000 });

let failures = 0;
let lanesChecked = 0;
for (const task of tasks) {
  const trials = TRIALS[task] ?? 1;
  for (const mode of ['race', 'line']) {
    // One run of the view per trial: what each lane scored, and what the
    // same creature scores replayed alone.
    const runs = [];
    for (let trial = 0; trial < trials; trial++) {
      runs.push(
        await page.evaluate(
          async ({ task, mode, trial }) => {
            const m = window.menagerie;
            const s = m.stage;
            if (s.task !== task) await m.showTask(task);
            s.paused = true;
            s.trial = trial;
            m.setMode(mode);
            if (s.mode !== mode) return { error: `the page would not show ${mode}` };
            let steps = 0;
            while (!s.worlds.every((w) => w.score().done) && steps < 3000) {
              m.advance(60);
              steps += 60;
            }
            if (steps >= 3000) return { error: 'the lanes never finished' };
            return {
              trial: s.trial,
              lanes: s.worlds.map((w, i) => {
                const en = s.entries[i];
                const alone = s.eng.episode(en.genome, task, trial);
                while (!alone.score().done) alone.step(30);
                const replay = alone.score().fitness;
                alone.free();
                return { tag: s.tags[i].textContent, lane: w.score().fitness, replay, recorded: en.fitness, drawn: s.actors[i].world === w };
              }),
            };
          },
          { task, mode, trial }
        )
      );
    }
    const bad = [];
    const broken = runs.find((r) => r.error);
    if (broken) bad.push(broken.error);
    else {
      const n = runs[0].lanes.length;
      if (n < 2) bad.push(`only ${n} lane`);
      for (let i = 0; i < n; i++) {
        const tag = runs[0].lanes[i].tag;
        const fits = [];
        for (const [t, r] of runs.entries()) {
          const l = r.lanes[i];
          if (r.trial !== t) bad.push(`asked for trial ${t}, page showed ${r.trial}`);
          if (!l || l.tag !== tag) {
            bad.push(`lane ${i} is not the same creature on every trial`);
            break;
          }
          if (!l.drawn) bad.push(`${tag}: the creature drawn is not the one simulated`);
          if (l.lane !== l.replay) bad.push(`${tag} trial ${t}: lane ${l.lane} but replayed alone ${l.replay}`);
          fits.push(l.lane);
        }
        if (fits.length !== trials) continue;
        // Evolution's rule for several trials: mostly the mean, partly the worst.
        const mean = fits.reduce((a, b) => a + b, 0) / trials;
        const fit = trials > 1 ? 0.7 * mean + 0.3 * Math.min(...fits) : mean;
        const recorded = runs[0].lanes[i].recorded;
        if (!(Math.abs(fit - recorded) <= ROUNDING)) bad.push(`${tag}: lanes give ${fit.toFixed(5)}, recorded ${recorded}`);
        lanesChecked++;
      }
    }
    const show = broken
      ? ''
      : runs[0].lanes
          .map((l, i) => `${l.tag.split(' ')[0] === 'gen' ? l.tag.replace(' ', '') : l.tag.split(' ')[0]} ${runs.map((r) => r.lanes[i].lane.toFixed(2)).join('/')}`)
          .join('  ');
    console.log(`${task} ${mode}: ${show}${bad.length ? '' : '  ok'}`);
    for (const b of bad) console.log(`  MISMATCH ${b}`);
    failures += bad.length;
  }
}
await browser.close();
if (errors.length) console.log('page errors:\n' + errors.join('\n'));
console.log(
  failures || errors.length
    ? `FAILED: ${failures} mismatches, ${errors.length} page errors`
    : `all ${lanesChecked} lanes match their recorded scores (${tasks.join(', ')}); no page errors`
);
process.exit(failures || errors.length ? 1 : 0);
