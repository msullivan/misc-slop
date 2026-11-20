// Screenshot the viewer for eyeballing.
// usage: node tools/shot.mjs OUT_PREFIX [--w 1280 --h 800] [--dark] [--js "code"] [--at 2,5,8]
import { createRequire } from 'node:module';
import { execSync } from 'node:child_process';
const require = createRequire(execSync('npm root -g').toString().trim() + '/');
const { chromium } = require('playwright');

const args = process.argv.slice(2);
const prefix = args[0];
const opt = (k, d) => {
  const i = args.indexOf('--' + k);
  return i >= 0 ? args[i + 1] : d;
};
const w = Number(opt('w', 1280));
const h = Number(opt('h', 800));
const at = opt('at', '3').split(',').map(Number);
const js = opt('js', '');
const url = opt('url', 'http://localhost:8765/index.html');

const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: w, height: h }, colorScheme: args.includes('--dark') ? 'dark' : 'light' });
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.log('[console]', m.type(), m.text()); });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
await page.goto(url);
await page.waitForFunction(() => window.menagerie, null, { timeout: 30000 });
if (js) await page.evaluate(js);
// Drive the sim clock ourselves: software GL is far slower than real time.
// (The stage's clock, not the first world's: in Race and Lineage a lane
// that has finished early stops counting.)
const simTime = () => page.evaluate(() => window.menagerie.stage.clock());
for (const t of at) {
  for (let i = 0; i < 600; i++) {
    if ((await simTime()) >= t) break;
    await page.waitForTimeout(100);
  }
  const file = `${prefix}-${String(t).replace('.', '_')}.png`;
  await page.screenshot({ path: file });
  console.log(file, 'sim t=', (await simTime()).toFixed(2));
}
await browser.close();
