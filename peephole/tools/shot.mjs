// Screenshot the page. usage: node tools/shot.mjs OUT.png [--w 1200] [--h 900] [--dark] [--url URL] [--js code] [--full]
import { createRequire } from 'node:module';
import { execSync } from 'node:child_process';
// Playwright from wherever it is installed: PLAYWRIGHT_DIR, else the global npm root.
const require = createRequire((process.env.PLAYWRIGHT_DIR || execSync('npm root -g').toString().trim()) + '/');
const { chromium } = require('playwright');
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf('--' + k); return i >= 0 ? args[i + 1] : d; };
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: Number(opt('w', 1200)), height: Number(opt('h', 900)) }, colorScheme: args.includes('--dark') ? 'dark' : 'light' });
page.on('console', (m) => { if (m.type() === 'error') console.log('[console]', m.text()); });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
await page.goto(opt('url', 'http://localhost:8766/index.html'));
await page.waitForSelector('.card', { timeout: 15000 });
const js = opt('js', '');
if (js) { await page.evaluate(js); await page.waitForTimeout(600); }
await page.waitForTimeout(500);
console.log('scrollWidth', await page.evaluate(() => document.documentElement.scrollWidth), 'cards', await page.evaluate(() => document.querySelectorAll('.card').length));
await page.screenshot({ path: args[0], fullPage: args.includes('--full') });
await browser.close();
