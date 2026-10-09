import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { ROOT, parseOptions, discoverChrome, check } from './core.mjs';
import { Journal, services, stopService, launchBrowser, writeJson } from './runtime.mjs';

const options = parseOptions([]);
options.chrome = discoverChrome(options.chrome);
const directory = path.join(ROOT, 'artifacts/phase1/step2-' + Date.now());
const journal = new Journal(directory);
const owned = [];
const headers = { 'X-Dev-User-Id': 'browser-' + randomUUID(), 'X-E2E-Run-Id': randomUUID() };
let browser, page, sessionId, result;
try {
  await services(options, journal, owned);
  check(owned.length === 2, 'Restart persistence test requires exclusive ownership of both servers');
  browser = await launchBrowser(options, journal);
  page = await browser.newPage();
  journal.attach(page, options.backendUrl);
  await page.setExtraHTTPHeaders(headers);
  await page.goto(options.frontendUrl, { waitUntil: 'networkidle0' });
  await page.waitForSelector('[data-testid="backend-status"][data-status="ok"]');
  await page.type('[data-testid="session-title"]', 'Browser persistence lecture');
  await page.click('[data-testid="session-create"]');
  await page.waitForFunction(() => document.querySelector('[data-testid="session-state"]')?.dataset.sessionId);
  sessionId = await page.$eval('[data-testid="session-state"]', element => element.dataset.sessionId);
  check(sessionId, 'UI did not create a real session');
  const url = page.url();
  await page.close();
  // Kill/relaunch the actual backend and frontend. No process-local state survives this.
  for (const service of owned.splice(0).reverse()) await stopService(service, journal);
  await services(options, journal, owned);
  page = await browser.newPage();
  journal.attach(page, options.backendUrl);
  await page.setExtraHTTPHeaders(headers);
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(id => document.querySelector('[data-testid="session-state"]')?.dataset.sessionId === id, {}, sessionId);
  const text = await page.$eval('[data-testid="session-state"]', element => element.innerText);
  check(text.includes('Browser persistence lecture'), 'Restored session lost its title');
  check(journal.errors.length === 0, 'Browser/API emitted errors');
  await page.screenshot({ path: path.join(directory, 'persistent-session.png'), fullPage: true });
  result = { status: 'PASS', sessionId, backendRestart: true, frontendRestart: true, title: text };
} catch (error) {
  result = { status: 'FAIL', message: error.message };
  if (page && !page.isClosed()) await page.screenshot({ path: path.join(directory, 'failure.png') }).catch(() => {});
  console.error(error.message);
} finally {
  if (sessionId) {
    const response = await fetch(options.backendUrl + '/api/e2e/sessions/' + sessionId, { method: 'DELETE', headers }).catch(() => null);
    if (response?.status !== 204) result = { ...result, status: 'FAIL', cleanup: 'Session deletion failed' };
  }
  if (browser) await browser.close();
  for (const service of owned.reverse()) {
    try { await stopService(service, journal); }
    catch (error) { result = { ...result, status: 'FAIL', processCleanup: error.message }; }
  }
  await journal.flush();
  writeJson(path.join(directory, 'result.json'), result);
}
console.log('Session browser:', result.status, directory);
process.exitCode = result.status === 'PASS' ? 0 : 1;
