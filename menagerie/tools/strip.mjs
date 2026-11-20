// Filmstrip of a creature in motion, for judging gaits from stills.
// usage: node tools/strip.mjs OUT.png [--task sprint] [--cell x,y | --rank n] [--mode watch]
//        [--from 2.0] [--every 0.2] [--frames 12] [--cols 6] [--yaw r] [--pitch r] [--dist d] [--dark]
import { createRequire } from 'node:module';
import { execSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const require = createRequire(execSync('npm root -g').toString().trim() + '/');
const { chromium } = require('playwright');

const args = process.argv.slice(2);
const out = args[0];
const opt = (k, d) => {
  const i = args.indexOf('--' + k);
  return i >= 0 ? args[i + 1] : d;
};
const task = opt('task', 'sprint');
const from = Number(opt('from', 2));
const every = Number(opt('every', 0.2));
const frames = Number(opt('frames', 12));
const cols = Number(opt('cols', 6));
const mode = opt('mode', 'watch');
const W = 800, H = 560;

const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: W, height: H }, colorScheme: args.includes('--dark') ? 'dark' : 'light' });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
page.on('console', (m) => { if (m.type() === 'error') console.log('[console]', m.text()); });
await page.goto(opt('url', 'http://localhost:8765/index.html'));
await page.waitForFunction(() => window.menagerie, null, { timeout: 30000 });
const info = await page.evaluate(async ({ task, cell, rank, mode, yaw, pitch, dist, trial, family }) => {
  const m = window.menagerie;
  for (const el of document.querySelectorAll('.panel')) el.style.display = 'none';
  m.stage.paused = true;
  await m.showTask(task);
  // Use the page's own resolved archive (the raw data holds pointers).
  const arch = m.stage.archive;
  const pool = family !== null && arch.families && arch.families[family] ? arch.families[family].elites : arch.elites;
  const elites = [...pool].sort((a, b) => b.fitness - a.fitness);
  let e = elites[rank];
  if (cell) e = elites.find((x) => x.cell.join(',') === cell) || e;
  m.selectElite(e);
  m.stage.trial = trial;
  m.setMode(mode);
  if (yaw !== null) m.cam.yaw = yaw;
  if (pitch !== null) m.cam.pitch = pitch;
  if (dist !== null) m.cam.wantDist = dist;
  return { fitness: e.fitness, cell: e.cell, parts: e.eval.parts, name: document.getElementById('binomial').textContent };
}, {
  task, cell: opt('cell', null), rank: Number(opt('rank', 0)), mode, trial: Number(opt('trial', 0)),
  family: opt('family', null) && Number(opt('family')),
  yaw: opt('yaw', null) && Number(opt('yaw')), pitch: opt('pitch', null) && Number(opt('pitch')), dist: opt('dist', null) && Number(opt('dist')),
});
console.log(JSON.stringify(info));
const dir = mkdtempSync(join(tmpdir(), 'strip-'));
const files = [];
await page.evaluate((n) => window.menagerie.advance(n), Math.round(from * 60));
for (let i = 0; i < frames; i++) {
  if (i) await page.evaluate((n) => window.menagerie.advance(n), Math.round(every * 60));
  await page.waitForTimeout(60);
  const f = join(dir, `f${String(i).padStart(3, '0')}.png`);
  await page.screenshot({ path: f });
  files.push(f);
}
await browser.close();
writeFileSync(join(dir, 'montage.py'), `
import sys
from PIL import Image
files = sys.argv[2:]
cols = ${cols}
ims = [Image.open(f).crop((160, 80, 800, 520)).resize((480, 330)) for f in files]
w, h = ims[0].size
rows = (len(ims) + cols - 1) // cols
sheet = Image.new('RGB', (cols * w, rows * h), 'white')
for i, im in enumerate(ims):
    sheet.paste(im, ((i % cols) * w, (i // cols) * h))
sheet.save(sys.argv[1])
`);
execSync(`python3 ${join(dir, 'montage.py')} ${out} ${files.join(' ')}`);
console.log('wrote', out);
