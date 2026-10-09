import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { ROOT, parseOptions, discoverChrome, check } from './core.mjs';
import { Journal, services, stopService, launchBrowser, observeMedia, writeJson } from './runtime.mjs';
const options = parseOptions([]); options.chrome = discoverChrome(options.chrome);
const directory = path.join(ROOT, 'artifacts/phase1/step5-' + Date.now()), journal = new Journal(directory), owned = [];
const headers = { 'X-Dev-User-Id': 'real-ai-' + randomUUID() };
let browser, page, sessionId, result;
let notes;
try {
  await services(options, journal, owned);
  const created = await fetch(options.backendUrl + '/api/e2e/sessions', { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({ run_id: randomUUID() }) });
  check(created.ok, 'Session creation failed'); sessionId = (await created.json()).id;
  browser = await launchBrowser(options, journal); page = await browser.newPage(); await page.setExtraHTTPHeaders(headers);
  journal.attach(page, options.backendUrl); await journal.attachSockets(page, options.backendUrl); await observeMedia(page);
  await page.goto(options.frontendUrl + '/?session=' + sessionId, { waitUntil: 'networkidle0' });
  await page.waitForFunction(id => document.querySelector('[data-testid="session-state"]')?.dataset.sessionId === id, {}, sessionId);
  await page.click('[data-testid="recording-start"]');
  await page.waitForSelector('[data-testid="transcription-status"][data-status="connected"]', { timeout: 30000 });
  await page.waitForSelector('[data-testid="transcript-item"]', { timeout: 45000 });
  let segments = await fetch(options.backendUrl + '/sessions/' + sessionId + '/transcript-segments', { headers }).then(response => response.json());
  check(segments.length && segments.some(segment => /retriev|practice|learn|memory|lecture/i.test(segment.text)), 'Real fixed lecture audio did not produce its spoken concepts');
  const firstId = segments[0].id;
  await page.click('[data-testid="transcription-retry"]');
  await page.waitForSelector('[data-testid="transcription-status"][data-status="connected"]', { timeout: 30000 });
  await page.waitForFunction(() => document.querySelectorAll('[data-testid="transcript-item"]').length >= 2, { timeout: 45000 });
  check((await page.evaluate(() => window.__e2eMedia.snapshot())).recorderStates.includes('recording'), 'STT reconnection stopped original recording');
  if (process.argv.includes('--notes')) {
    await page.waitForSelector('[data-testid="live-note"][data-status="ready"]', { timeout: 60000 });
    notes = await fetch(options.backendUrl + '/sessions/' + sessionId + '/notes', { headers }).then(response => response.json());
    check(notes.some(note => note.status === 'ready' && note.summary.length > 0 && note.sourceRefs.length > 0), 'Real Responses API did not produce a persisted grounded note');
    const transcripts = await fetch(options.backendUrl + '/sessions/' + sessionId + '/transcript-segments', { headers }).then(response => response.json());
    for (const note of notes.filter(note => note.status === 'ready')) for (const ref of note.sourceRefs) check(transcripts.some(segment => segment.id === ref.sourceId && segment.text.includes(ref.excerpt)), 'Live note citation is not grounded in its actual transcript');
  }
  await page.click('[data-testid="recording-stop"]');
  await page.waitForSelector('[data-testid="recording-state"][data-state="stopped"]', { timeout: 35000 });
  await page.waitForFunction(() => document.querySelector('[data-testid="audio-backup"]')?.dataset.pending === '0');
  segments = await fetch(options.backendUrl + '/sessions/' + sessionId + '/transcript-segments', { headers }).then(response => response.json());
  check(new Set(segments.map(segment => segment.id)).size === segments.length && segments.some(segment => segment.id === firstId), 'Reconnection lost or duplicated committed segments');
  check(segments.every((segment, index) => segment.committedAt && segment.revision === 1 && segment.endMs >= segment.startMs && (index === 0 || segment.sequence > segments[index - 1].sequence)), 'Committed transcript order/timestamps are invalid');
  check(journal.errors.length === 0, 'Unexpected browser/API diagnostics');
  await page.screenshot({ path: path.join(directory, 'real-transcription.png'), fullPage: true });
  result = { status: 'PASS', realAI: true, sessionId, segments, notes, reconnectKeptRecording: true };
} catch (error) {
  result = { status: 'FAIL', realAI: true, message: error.message }; console.error(error.message);
  if (page && !page.isClosed()) await page.screenshot({ path: path.join(directory, 'failure.png') }).catch(() => {});
} finally {
  journal.step = 'cleanup'; if (page && !page.isClosed()) await page.evaluate(() => window.__e2eMedia?.release()).catch(() => {});
  if (browser) await browser.close();
  if (sessionId) { const cleanup = await fetch(options.backendUrl + '/api/e2e/sessions/' + sessionId, { method: 'DELETE', headers }); if (cleanup.status !== 204) result.status = 'FAIL'; }
  for (const service of owned.reverse()) { try { await stopService(service, journal); } catch (error) { result = { ...result, status: 'FAIL', cleanup: error.message }; } }
  await journal.flush(); writeJson(path.join(directory, 'result.json'), result);
}
console.log('Real transcription:', result.status, directory); process.exitCode = result.status === 'PASS' ? 0 : 1;
