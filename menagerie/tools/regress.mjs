import { createRequire } from 'node:module';
import { execSync } from 'node:child_process';
const require = createRequire(execSync('npm root -g').toString().trim() + '/');
const { chromium } = require('playwright');
const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
await page.goto('http://localhost:8765/index.html');
await page.waitForFunction(() => window.menagerie, null, { timeout: 30000 });
const state = () => page.evaluate(() => {
  const m = window.menagerie; const s = m.stage;
  return { task: s.task, mode: s.mode, elite: s.elite ? document.getElementById('binomial').textContent : null, exhibit: !!s.exhibit, actors: s.actors.length,
    live: !!(s.archive && s.archive.live), gen: !document.getElementById('gen').hidden, workers: Object.values(window.__n || {}).length };
});
const log = async (label) => console.log(label, JSON.stringify(await state()));
await log('boot');
// 1. live breeding, then back to the collection: no hijack.
await page.click('#src-live'); await log('live-empty');
await page.evaluate(() => { const s = document.getElementById('genslider'); s.value = '0'; s.dispatchEvent(new Event('input')); });
await page.click('#breedgo'); await page.click('#breedgo'); await page.click('#breedgo');
await page.waitForTimeout(9000);
const n1 = await page.evaluate(() => { const n = window.menagerie.nursery('sprint'); return { workers: n.workers.length, evals: n.evals, cells: n.cells.size, running: n.running, flukes: n.flukes }; });
console.log('nursery', JSON.stringify(n1));
await page.click('#map button:not(.empty)');
await log('live-picked');
await page.click('#src-zoo'); await page.waitForTimeout(500); await log('back-to-zoo');
const n2 = await page.evaluate(() => { const n = window.menagerie.nursery; return Object.keys(n).length; });
await page.evaluate(() => { window.menagerie.stage.paused = true; });
for (let i = 0; i < 6; i++) { await page.evaluate(() => window.menagerie.advance(120)); }
await page.evaluate(() => { window.menagerie.stage.paused = false; });
await page.waitForTimeout(4000);
await log('zoo-after-trial');
// 2. cheat, sumo, families, habitats
await page.click('#cheat'); await page.waitForTimeout(300); await log('cheat');
for (const t of ['walk', 'chase', 'shove']) { await page.evaluate(async (t) => { await window.menagerie.showTask(t); }, t); await log(t);
  for (const m of ['roam', 'line', 'race', 'fight', 'watch']) { await page.evaluate((m) => window.menagerie.setMode(m), m); await page.evaluate(() => { window.menagerie.stage.paused = true; window.menagerie.advance(90); window.menagerie.stage.paused = false; }); }
}
await log('end');
console.log(errors.length ? errors.join('\n') : 'no errors');
await browser.close();
