// Start live breeding in a headless browser, wait, screenshot, report.
// usage: node tools/breedshot.mjs OUT.png [seconds] [task]
import { createRequire } from 'node:module';
import { execSync } from 'node:child_process';
const require = createRequire(execSync('npm root -g').toString().trim() + '/');
const { chromium } = require('playwright');
const [out, secs = '20', task = 'sprint'] = process.argv.slice(2);
const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
page.on('console', (m) => { if (m.type() === 'error') console.log('[console]', m.text()); });
await page.goto('http://localhost:8765/index.html');
await page.waitForFunction(() => window.menagerie, null, { timeout: 30000 });
await page.click('#src-live');
await page.evaluate(async (t) => { await window.menagerie.showTask(t); }, task);
await page.click('#breedgo');
await page.waitForTimeout(Number(secs) * 1000);
const info = await page.evaluate(() => {
  const n = window.menagerie.nursery(window.menagerie.stage.task);
  return { evals: n.evals, cells: n.cells.size, best: n.best && n.best.fitness, flukes: n.flukes, workers: n.workers.length, rate: n.rate, stat: document.getElementById('breedstat').textContent, name: document.getElementById('binomial').textContent };
});
console.log(JSON.stringify(info));
await page.screenshot({ path: out });
await browser.close();
