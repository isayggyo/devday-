import path from 'node:path';
import { randomUUID, createHash } from 'node:crypto';
import { ROOT, parseOptions, discoverChrome, check } from './core.mjs';
import { Journal, services, stopService, launchBrowser, observeMedia, writeJson } from './runtime.mjs';

const options = parseOptions([]);
options.chrome = discoverChrome(options.chrome);
const directory = path.join(ROOT, 'artifacts/phase1/step4-' + Date.now());
const journal = new Journal(directory);
const owned = [];
const headers = { 'X-Dev-User-Id': 'browser-' + randomUUID() };
let browser, page, sessionId, result;

async function localChunks() {
  return page.evaluate(async () => {
    const rows = await new Promise((resolve, reject) => {
      const open = indexedDB.open('lecture-audio-backup', 1);
      open.onsuccess = () => {
        const db = open.result, tx = db.transaction('chunks'), request = tx.objectStore('chunks').getAll();
        tx.oncomplete = () => { db.close(); resolve(request.result); };
        tx.onerror = () => reject(tx.error);
      };
      open.onerror = () => reject(open.error);
    });
    return Promise.all(rows.map(async row => ({ id: row.id, sequence: row.sequence, uploaded: row.uploaded, byteLength: row.blob.size,
      sha256: Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await row.blob.arrayBuffer())), byte => byte.toString(16).padStart(2, '0')).join('') })));
  });
}

try {
  await services(options, journal, owned);
  const create = await fetch(options.backendUrl + '/api/e2e/sessions', { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({ run_id: randomUUID() }) });
  check(create.status === 201, 'Isolated session creation failed');
  sessionId = (await create.json()).id;
  journal.step = 'permission_denied';
  // Automatic permission approval must be disabled to test a real denial.
  browser = await launchBrowser(options, journal, 'permission-profile', false);
  let context = await browser.createBrowserContext();
  await context.overridePermissions(options.frontendUrl, []);
  page = await context.newPage();
  journal.attach(page, options.backendUrl);
  await observeMedia(page);
  await page.setExtraHTTPHeaders(headers);
  await page.goto(options.frontendUrl + '/?session=' + sessionId, { waitUntil: 'networkidle0' });
  await page.waitForFunction(id => document.querySelector('[data-testid="session-state"]')?.dataset.sessionId === id, {}, sessionId);
  await page.click('[data-testid="recording-start"]');
  await page.waitForFunction(() => document.body.innerText.includes('마이크 권한이 거부'));
  check((await fetch(options.backendUrl + '/sessions/' + sessionId, { headers }).then(response => response.json())).status === 'created', 'Denied microphone permission started a backend recording');
  await browser.close();
  journal.step = 'actual_recording';
  browser = await launchBrowser(options, journal);
  context = await browser.createBrowserContext();
  page = await context.newPage();
  journal.attach(page, options.backendUrl);
  await observeMedia(page);
  await page.setExtraHTTPHeaders(headers);
  await page.goto(options.frontendUrl + '/?session=' + sessionId, { waitUntil: 'networkidle0' });
  await page.waitForFunction(id => document.querySelector('[data-testid="session-state"]')?.dataset.sessionId === id, {}, sessionId);
  await page.click('[data-testid="recording-start"]');
  await page.waitForSelector('[data-testid="recording-state"][data-state="recording"]');
  await page.waitForFunction(() => Number(document.querySelector('[data-testid="audio-backup"]')?.dataset.bytes) > 0 && document.querySelector('[data-testid="audio-backup"]')?.dataset.pending === '0');
  const before = await localChunks();
  check(before.length && before.every(chunk => chunk.uploaded && chunk.byteLength > 0), 'IndexedDB did not durably acknowledge real audio');
  check(journal.errors.length === 0, 'Unexpected diagnostics before deliberate network outage');

  journal.step = 'expected_offline';
  await page.setOfflineMode(true);
  await page.waitForFunction(() => Number(document.querySelector('[data-testid="audio-backup"]')?.dataset.pending) >= 2, { timeout: 20000 });
  const offline = await localChunks();
  const media = await page.evaluate(() => window.__e2eMedia.snapshot());
  check(offline.filter(chunk => !chunk.uploaded).length >= 2, 'Offline chunks were not backed up');
  check(media.tracks.some(track => track.state === 'live') && media.recorderStates.includes('recording'), 'Network outage stopped original recording');
  await page.screenshot({ path: path.join(directory, 'offline-backup.png'), fullPage: true });

  await page.setOfflineMode(false);
  await page.click('[data-testid="audio-retry"]');
  await page.waitForFunction(() => document.querySelector('[data-testid="audio-backup"]')?.dataset.pending === '0', { timeout: 30000 });
  await page.click('[data-testid="recording-stop"]');
  await page.waitForSelector('[data-testid="recording-state"][data-state="stopped"]');
  await page.waitForFunction(() => document.querySelector('[data-testid="audio-backup"]')?.dataset.pending === '0');
  const captured = await localChunks();
  const server = await fetch(options.backendUrl + '/sessions/' + sessionId + '/audio', { headers }).then(response => response.json());
  check(captured.length === server.chunks.length && captured.length > before.length, 'Recovered server/local chunk counts differ');
  for (const chunk of captured) {
    const saved = server.chunks.find(item => item.id === chunk.id);
    check(chunk.uploaded && saved?.sha256 === chunk.sha256 && saved?.byteLength === chunk.byteLength, 'Actual recorded bytes changed or were not acknowledged');
  }
  const recording = await fetch(options.backendUrl + '/sessions/' + sessionId + '/audio/file', { headers });
  check(recording.ok, 'Stored original recording could not be retrieved');
  const originalBytes = Buffer.from(await recording.arrayBuffer());
  const localHash = await page.evaluate(async () => {
    const rows = await new Promise(resolve => {
      const open = indexedDB.open('lecture-audio-backup', 1);
      open.onsuccess = () => { const db = open.result, tx = db.transaction('chunks'), request = tx.objectStore('chunks').getAll(); tx.oncomplete = () => { db.close(); resolve(request.result); }; };
    });
    const blob = new Blob(rows.sort((a, b) => a.sequence - b.sequence).map(row => row.blob));
    return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer())), byte => byte.toString(16).padStart(2, '0')).join('');
  });
  check(createHash('sha256').update(originalBytes).digest('hex') === localHash, 'Object-storage recording differs from the actual IndexedDB backup');
  const duplicate = await page.evaluate(async id => {
    const chunk = await new Promise(resolve => {
      const open = indexedDB.open('lecture-audio-backup', 1);
      open.onsuccess = () => { const db = open.result, tx = db.transaction('chunks'), request = tx.objectStore('chunks').getAll(); tx.oncomplete = () => { db.close(); resolve(request.result[0]); }; };
    });
    const form = new FormData();
    for (const [key, value] of Object.entries({ chunk_id: chunk.id, capture_id: chunk.captureId, sequence: chunk.sequence, start_ms: chunk.startMs, end_ms: chunk.endMs })) form.set(key, String(value));
    form.set('file', chunk.blob, 'retry.webm');
    const response = await fetch('/api/sessions/' + id + '/audio/chunks', { method: 'POST', body: form });
    return { status: response.status, ...await response.json() };
  }, sessionId);
  check(duplicate.status === 201 && duplicate.deduplicated === true, 'A repeated real chunk was not deduplicated');
  const stoppedMedia = await page.evaluate(() => window.__e2eMedia.snapshot());
  check(stoppedMedia.tracks.every(track => track.state === 'ended') && stoppedMedia.recorderStates.every(state => state === 'inactive'), 'Stop left microphone tracks or recorders active');
  journal.step = 'restored_online';
  await page.reload({ waitUntil: 'networkidle0' });
  await page.waitForFunction(() => Number(document.querySelector('[data-testid="audio-backup"]')?.dataset.bytes) > 0);
  check(journal.errors.every(error => error.step === 'expected_offline'), 'Unexpected errors outside deliberate network outage');
  await page.screenshot({ path: path.join(directory, 'recording-preserved.png'), fullPage: true });
  result = { status: 'PASS', sessionId, microphonePermissionDenied: true, actualFixtureCapture: true, offlineCaptureContinued: true, localChunks: captured, serverBytes: server.byteLength, originalSha256: localHash, deduplicated: true, expectedOfflineErrors: journal.errors.length, reload: true };
} catch (error) {
  result = { status: 'FAIL', message: error.message };
  if (page && !page.isClosed()) await page.screenshot({ path: path.join(directory, 'failure.png') }).catch(() => {});
  console.error(error.message);
} finally {
  journal.step = 'cleanup';
  if (page && !page.isClosed()) { await page.setOfflineMode(false).catch(() => {}); await page.evaluate(() => window.__e2eMedia?.release()).catch(() => {}); }
  if (browser) await browser.close();
  if (sessionId) {
    const response = await fetch(options.backendUrl + '/api/e2e/sessions/' + sessionId, { method: 'DELETE', headers }).catch(() => null);
    if (response?.status !== 204) result = { ...result, status: 'FAIL', cleanup: 'Session deletion failed' };
  }
  for (const service of owned.reverse()) {
    try { await stopService(service, journal); }
    catch (error) { result = { ...result, status: 'FAIL', processCleanup: error.message }; }
  }
  await journal.flush();
  writeJson(path.join(directory, 'result.json'), result);
}
console.log('Audio browser:', result.status, directory);
process.exitCode = result.status === 'PASS' ? 0 : 1;
