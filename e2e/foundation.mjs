import path from 'node:path';
import { ROOT, parseOptions, discoverChrome, check } from './core.mjs';
import { Journal, services, stopService, launchBrowser, writeJson } from './runtime.mjs';

const options = parseOptions([]);
options.chrome = discoverChrome(options.chrome);
const directory = path.join(ROOT, 'artifacts/phase1/step1-' + Date.now());
const journal = new Journal(directory);
const owned = [];
let browser;
let result;
try {
  const health = await services(options, journal, owned);
  browser = await launchBrowser(options, journal);
  const page = await browser.newPage();
  journal.attach(page, options.backendUrl);
  await page.goto(options.frontendUrl, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('[data-testid="backend-status"][data-status="ok"]', { timeout: 30000 });
  const status = await page.$eval('[data-testid="backend-status"]', element => element.innerText);
  check(status.includes('PostgreSQL'), 'Frontend did not confirm its real backend/database call');
  check(journal.errors.length === 0, 'Browser produced errors');
  await page.screenshot({ path: path.join(directory, 'foundation.png'), fullPage: true });
  result = { status: 'PASS', health, frontendStatus: status };
} catch (error) {
  result = { status: 'FAIL', message: error.message };
  console.error(error.message);
} finally {
  journal.step = 'cleanup';
  if (browser) await browser.close();
  for (const process_ of owned.reverse()) await stopService(process_, journal);
  await journal.flush();
  writeJson(path.join(directory, 'result.json'), result);
}
console.log('Foundation browser:', result.status, directory);
process.exitCode = result.status === 'PASS' ? 0 : 1;
