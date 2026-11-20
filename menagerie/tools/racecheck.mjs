// In the page's Race and Lineage views, does each creature cover what it scored?
// usage: node tools/racecheck.mjs [task ...]
import { createRequire } from 'node:module';
import { execSync } from 'node:child_process';
const require = createRequire(execSync('npm root -g').toString().trim() + '/');
const { chromium } = require('playwright');
const tasks = process.argv.slice(2).length ? process.argv.slice(2) : ['walk', 'sprint', 'swim'];
const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
await page.goto('http://localhost:8765/index.html');
await page.waitForFunction(() => window.menagerie, null, { timeout: 30000 });
for (const task of tasks) {
  for (const mode of ['race', 'line']) {
    const out = await page.evaluate(async ({ task, mode }) => {
      const m = window.menagerie;
      await m.showTask(task);
      m.stage.paused = true;
      m.setMode(mode);
      m.advance(Math.round(10.5 * 60));
      const r = m.stage.actors.map((a, i) => `${m.stage.tags[i].textContent.split(' ')[0]} ${a.com.z.toFixed(1)}`);
      m.stage.paused = false;
      return r.join('  ');
    }, { task, mode });
    console.log(`${task} ${mode}: ${out}`);
  }
}
console.log(errors.length ? errors.join('\n') : 'no page errors');
await browser.close();
