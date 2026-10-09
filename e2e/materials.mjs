import path from 'node:path';
import fs from 'node:fs';
import { randomUUID, createHash } from 'node:crypto';
import { ROOT, parseOptions, discoverChrome, check } from './core.mjs';
import { Journal, services, stopService, launchBrowser, writeJson } from './runtime.mjs';

const options = parseOptions([]);
options.chrome = discoverChrome(options.chrome);
const directory = path.join(ROOT, 'artifacts/phase1/step3-' + Date.now());
const journal = new Journal(directory);
const owned = [];
const headers = { 'X-Dev-User-Id': 'browser-' + randomUUID(), 'X-E2E-Run-Id': randomUUID() };
let browser, page, sessionId, result;
try {
  await services(options, journal, owned);
  browser = await launchBrowser(options, journal);
  page = await browser.newPage();
  journal.attach(page, options.backendUrl);
  await page.setExtraHTTPHeaders(headers);
  await page.goto(options.frontendUrl, { waitUntil: 'networkidle0' });
  await page.waitForSelector('[data-testid="backend-status"][data-status="ok"]');
  await page.type('[data-testid="session-title"]', 'Material vertical slice');
  await page.click('[data-testid="session-create"]');
  await page.waitForFunction(() => document.querySelector('[data-testid="session-state"]')?.dataset.sessionId);
  sessionId = await page.$eval('[data-testid="session-state"]', element => element.dataset.sessionId);
  const input = await page.$('[data-testid="lecture-pdf-input"]');
  await input.uploadFile(path.join(ROOT, 'e2e/fixtures/lecture.pdf'));
  await page.waitForSelector('[data-testid="lecture-upload"]:not([disabled])');
  await page.click('[data-testid="lecture-upload"]');
  await page.waitForSelector('[data-testid="lecture-document"]');
  await page.waitForFunction(() => { const image = document.querySelector('[data-testid="material-page-image"]'); return image?.complete && image.naturalWidth > 0; });
  const documentId = await page.$eval('[data-testid="lecture-document"]', element => element.dataset.documentId);
  const endpoint = options.backendUrl + `/sessions/${sessionId}/materials/${documentId}`;
  const response = await fetch(endpoint, { headers });
  check(response.ok, 'Material lookup failed');
  const material = await response.json();
  check(material.pages.length === 2 && material.processingStatus === 'ready', 'Actual PDF analysis did not return two ready pages');
  const original = await fetch(options.backendUrl + material.originalUrl, { headers });
  const hash = createHash('sha256').update(Buffer.from(await original.arrayBuffer())).digest('hex');
  check(hash === createHash('sha256').update(fs.readFileSync(options.pdf)).digest('hex'), 'Retrieved original differs from fixture');
  await input.uploadFile(path.join(ROOT, 'e2e/fixtures/lecture.pptx'));
  await page.waitForSelector('[data-testid="lecture-upload"]:not([disabled])');
  await page.click('[data-testid="lecture-upload"]');
  await page.waitForFunction(() => document.querySelectorAll('[data-testid="lecture-document"]').length === 2, { timeout: 150000 });
  await page.waitForFunction(() => Array.from(document.querySelectorAll('[data-testid="material-page-image"]')).every(image => image.complete && image.naturalWidth > 0));
  const presentation = await page.$('[data-testid="lecture-document"][data-filename="lecture.pptx"]');
  const presentationId = await presentation.evaluate(element => element.dataset.documentId);
  const presentationResponse = await fetch(options.backendUrl + `/sessions/${sessionId}/materials/${presentationId}`, { headers });
  const pptx = await presentationResponse.json();
  check(presentationResponse.ok && pptx.processingStatus === 'ready' && pptx.pages.length === 2 && pptx.pages[0].text.includes('Retrieval practice'), 'Real PPTX conversion failed');
  await presentation.$eval('[data-testid="material-next-page"]', button => button.click());
  await page.waitForFunction(id => document.querySelector(`[data-document-id="${id}"] img`)?.alt.includes('2페이지'), {}, presentationId);
  await page.reload({ waitUntil: 'networkidle0' });
  await page.waitForFunction(() => { const image = document.querySelector('[data-testid="material-page-image"]'); return image?.complete && image.naturalWidth > 0; });
  check(journal.errors.length === 0, 'Browser/API errors were emitted');
  await page.screenshot({ path: path.join(directory, 'material-pages.png'), fullPage: true });
  result = { status: 'PASS', sessionId, documentId, presentationId, pdfPages: 2, pptxPages: 2, originalSha256: hash, reload: true };
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
console.log('Material browser:', result.status, directory);
process.exitCode = result.status === 'PASS' ? 0 : 1;
