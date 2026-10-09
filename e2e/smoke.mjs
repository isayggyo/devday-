import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import {
  ROOT, STEPS, selector, normalize, check, sleep, parseOptions, discoverChrome,
  loadFixtures, assertEmptySession, assertSources, NotImplemented, Blocked, errorInfo, statusFor, runStatus, suiteStatus,
} from './core.mjs';
import { Journal, writeJson, api, services, stopService, launchBrowser, mediaPreflight, observeMedia } from './runtime.mjs';

let interrupted = false;
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { interrupted = true; });

async function visible(page, testId, options) {
  try { return await page.waitForSelector(selector(testId), { visible: true, timeout: options.timeoutMs }); }
  catch { check(false, `UI assertion: ${testId} was not visible within ${options.timeoutMs}ms`); }
}
async function waitFor(checkResult, options, message) {
  const deadline = performance.now() + options.timeoutMs;
  while (!interrupted && performance.now() < deadline) {
    const result = await checkResult();
    if (result) return result;
    await sleep(200);
  }
  check(false, `${message} within ${options.timeoutMs}ms${interrupted ? ' (interrupted)' : ''}`);
}
async function screenshot(page, directory, name) {
  if (!page || page.isClosed()) return { unavailable: 'Browser page is not available' };
  try {
    await page.screenshot({ path: path.join(directory, name + '.png'), fullPage: true });
    fs.writeFileSync(path.join(directory, name + '.html'), await page.content());
    return { screenshot: name + '.png', html: name + '.html' };
  } catch (error) { return { unavailable: error.message }; }
}

async function runScenario(number, options, fixture, executionDirectory) {
  const directory = path.join(executionDirectory, `run-${String(number).padStart(2, '0')}`);
  const journal = new Journal(directory);
  const runId = `smoke-${number}-${randomUUID()}`;
  const result = { run: number, runId, startedAt: new Date().toISOString(), steps: [], cleanup: [] };
  const started = performance.now();
  const owned = [];
  const state = {};
  let browser;
  let page;
  let capabilities;
  function ready() { if (!page || !state.sessionId || !state.pageReady) throw new Blocked('Requires successful service startup and app navigation'); }
  function feature(name) {
    ready();
    if (capabilities?.[name] !== true) throw new NotImplemented(`${name}: backend /api/capabilities reports ${String(capabilities?.[name])}`);
  }
  const sessionRoute = () => `/api/sessions/${state.sessionId}`;
  const snapshot = () => api(journal, options, sessionRoute());
  async function step(index, action) {
    journal.step = STEPS[index];
    const begin = performance.now();
    const errorsBefore = journal.errors.length;
    const entry = { number: index + 1, name: STEPS[index], startedAt: new Date().toISOString() };
    try {
      if (interrupted) throw new Blocked('Execution interrupted; cleanup will still run');
      entry.details = await action();
      entry.status = 'PASS';
    } catch (error) {
      entry.status = statusFor(error);
      entry.error = errorInfo(error);
      entry.artifacts = await screenshot(page, directory, `step-${String(index + 1).padStart(2, '0')}-${entry.status.toLowerCase()}`);
      journal.log('step_failure', { status: entry.status, error: entry.error, artifacts: entry.artifacts });
    }
    entry.durationMs = Math.round(performance.now() - begin);
    entry.errors = journal.errors.slice(errorsBefore);
    result.steps.push(entry);
    writeJson(path.join(directory, 'result.partial.json'), result);
    console.log(`Run ${number}/${options.runs} ${index + 1}. ${entry.name}: ${entry.status} (${entry.durationMs}ms)`);
  }
  async function cleanup(label, action) {
    const begin = performance.now();
    try { result.cleanup.push({ name: label, status: 'PASS', details: await action(), durationMs: Math.round(performance.now() - begin) }); }
    catch (error) { result.cleanup.push({ name: label, status: 'FAIL', error: errorInfo(error), durationMs: Math.round(performance.now() - begin) }); journal.log('cleanup_failure', { label, error: errorInfo(error) }); }
  }

  try {
    await step(0, async () => {
      const health = await services(options, journal, owned);
      const session = await api(journal, options, '/api/e2e/sessions', { method: 'POST', body: { run_id: runId }, expected: [201] });
      state.sessionId = session.id;
      check(/^[\w-]+$/.test(state.sessionId), 'Backend must return a safe unique session ID');
      assertEmptySession(session, runId);
      assertEmptySession(await snapshot(), runId);
      capabilities = await api(journal, options, '/api/capabilities');
      check(capabilities && typeof capabilities === 'object', 'Invalid capability response');
      result.sessionId = session.id;
      return { health, initialSession: session, capabilities, attach: options.attach };
    });
    await step(1, async () => {
      if (!state.sessionId) throw new Blocked('Service startup or isolated session creation failed');
      browser = await launchBrowser(options, journal);
      const context = await browser.createBrowserContext();
      page = await context.newPage();
      page.setDefaultTimeout(options.timeoutMs);
      await page.setViewport({ width: 1440, height: 1000 });
      journal.attach(page, options.backendUrl);
      await journal.attachSockets(page, options.backendUrl);
      await observeMedia(page);
      const url = new URL(options.frontendUrl);
      url.searchParams.set('session', state.sessionId);
      const response = await page.goto(url.href, { waitUntil: 'domcontentloaded', timeout: options.startupTimeoutMs });
      check(response?.ok(), `App navigation failed: HTTP ${response?.status()}`);
      await visible(page, 'lecture-app', options);
      await waitFor(async () => page.$eval(selector('session-state'), element => element.dataset.sessionId === new URL(location.href).searchParams.get('session') && element.dataset.state === 'idle'), options, 'Fresh app did not bind to the idle test session');
      const stale = await page.$$(`${selector('transcript-item')}, ${selector('generated-slide')}, ${selector('lecture-document')}`);
      check(stale.length === 0, 'New browser session contains stale documents, captions, or slides');
      assertEmptySession(await snapshot(), runId);
      state.pageReady = true;
      return { url: url.href, browserVersion: await browser.version(), freshProfile: true };
    });
    await step(2, async () => {
      feature('upload');
      const input = await visible(page, 'lecture-pdf-input', options);
      await input.uploadFile(options.pdf);
      const upload = await visible(page, 'lecture-upload', options);
      check(!(await upload.evaluate(element => element.disabled)), 'Upload capability is enabled but the upload button is disabled');
      await upload.click();
      const document = await waitFor(async () => {
        const current = await snapshot();
        return current.documents?.find(item => item.filename === fixture.filename && item.sha256 === fixture.pdfSha256);
      }, options, 'Uploaded PDF was not persisted with its actual filename and SHA-256');
      const ui = await visible(page, 'lecture-document', options);
      const metadata = await ui.evaluate(element => ({ id: element.dataset.documentId, filename: element.dataset.filename, text: element.innerText }));
      check(metadata.id === document.id && metadata.filename === fixture.filename && metadata.text.includes(fixture.filename), 'Uploaded PDF UI does not match backend document');
      state.documentId = document.id;
      return document;
    });
    await step(3, async () => {
      feature('recording');
      if (!state.documentId) throw new Blocked('Recording requires the PDF upload step to pass');
      await (await visible(page, 'recording-start', options)).click();
      const recording = await waitFor(async () => {
        const session = await snapshot();
        const media = await page.evaluate(() => window.__e2eMedia.snapshot());
        const ui = await page.$eval(selector('session-state'), element => element.dataset.state);
        return session.state === 'recording' && session.audio_bytes > 0 && media.tracks.some(track => track.state === 'live') && ui === 'recording' && { session, media };
      }, options, 'Recording did not produce live microphone tracks and actual audio bytes at the backend');
      state.recordingStarted = true;
      return recording;
    });
    await step(4, async () => {
      feature('transcription');
      if (!state.recordingStarted) throw new Blocked('Transcription requires successful microphone recording');
      const caption = await waitFor(async () => {
        return page.evaluate(() => [...document.querySelectorAll('[data-testid="transcript-item"]')].map(element => ({
          id: element.dataset.transcriptId,
          sessionId: element.dataset.sessionId,
          text: element.querySelector('[data-testid="transcript-text"]')?.innerText?.trim(),
          visible: element.getBoundingClientRect().width > 0 && element.getBoundingClientRect().height > 0,
        })).find(item => item.visible && item.text) ?? null);
      }, options, 'No nonempty real-time caption appeared');
      check(caption.id && caption.sessionId === state.sessionId && caption.text, 'Caption must have a real transcript ID, session ID, and nonempty text');
      const transcripts = await api(journal, options, sessionRoute() + '/transcripts');
      check(Array.isArray(transcripts) && transcripts.some(item => {
        const backendText = normalize(item.text);
        const visibleText = normalize(caption.text);
        return item.id === caption.id && item.session_id === state.sessionId && backendText && (backendText.startsWith(visibleText) || visibleText.startsWith(backendText));
      }), 'Visible caption is missing or different in the backend transcript stream');
      state.captionReceived = true;
      return { caption, count: transcripts.length };
    });
    await step(5, async () => {
      feature('slides');
      if (!state.captionReceived || !state.documentId) throw new Blocked('Visual slide generation requires actual transcript and PDF');
      const visual = await waitFor(async () => {
        const slide = await page.$(selector('generated-slide'));
        if (!slide) return false;
        const visual = await slide.evaluate(element => {
        const rectangle = element.getBoundingClientRect();
        const image = element.querySelector('[data-testid="slide-visual"] img, img[data-testid="slide-visual"]');
        const svg = element.querySelector('[data-testid="slide-visual"] svg, svg[data-testid="slide-visual"]');
        const canvas = element.querySelector('[data-testid="slide-visual"] canvas, canvas[data-testid="slide-visual"]');
        let paintedCanvas = false;
        if (canvas?.width && canvas.height) {
          const pixels = canvas.getContext('2d')?.getImageData(0, 0, canvas.width, canvas.height).data;
          if (pixels) for (let index = 4; index < pixels.length; index += 4) if (pixels[index] !== pixels[0] || pixels[index + 1] !== pixels[1] || pixels[index + 2] !== pixels[2] || pixels[index + 3] !== pixels[3]) { paintedCanvas = true; break; }
        }
        return { id: element.dataset.slideId, width: rectangle.width, height: rectangle.height, text: element.querySelector('[data-testid="slide-content"]')?.innerText?.trim(), hasVisual: Boolean((image?.complete && image.naturalWidth > 0) || (svg?.getBoundingClientRect().width > 0 && svg.querySelector('path,rect,circle,line,polygon,polyline,text')) || paintedCanvas) };
        });
        return visual.id && visual.width >= 200 && visual.height >= 100 && visual.text?.length >= 20 && visual.hasVisual ? visual : false;
      }, options, 'No real slide with text and rendered SVG, canvas, or decoded image appeared');
      const slides = await api(journal, options, sessionRoute() + '/slides');
      check(Array.isArray(slides) && slides.some(item => item.id === visual.id && item.session_id === state.sessionId), 'Rendered slide does not exist in this backend session');
      state.slideId = visual.id;
      await page.screenshot({ path: path.join(directory, 'generated-slide.png'), fullPage: true });
      return visual;
    });
    await step(6, async () => {
      feature('provenance');
      if (!state.slideId) throw new Blocked('Content/source validation requires a real generated visual slide');
      const slide = await api(journal, options, sessionRoute() + `/slides/${encodeURIComponent(state.slideId)}`);
      const transcripts = await api(journal, options, sessionRoute() + '/transcripts');
      check(slide.id === state.slideId && slide.session_id === state.sessionId, 'Slide belongs to another session');
      assertSources(slide, state.documentId, transcripts, fixture);
      const ui = await page.evaluate(id => {
        const element = [...document.querySelectorAll('[data-testid="generated-slide"]')].find(item => item.dataset.slideId === id);
        return { text: element?.querySelector('[data-testid="slide-content"]')?.innerText, sources: [...(element?.querySelectorAll('[data-testid="slide-source"]') ?? [])].map(source => ({ text: source.innerText, documentId: source.dataset.documentId, page: Number(source.dataset.page), visible: source.getBoundingClientRect().width > 0 && source.getBoundingClientRect().height > 0 })) };
      }, state.slideId);
      check(normalize(ui.text).includes(normalize(slide.title)) && normalize(ui.text).includes(normalize(slide.body)), 'Visible slide content differs from the saved slide');
      for (const source of slide.sources) check(ui.sources.some(item => item.visible && item.documentId === source.document_id && item.page === source.page && item.text.includes(fixture.filename) && item.text.includes(String(source.page))), 'Readable PDF filename and page citation are missing from the slide');
      return { title: slide.title, body: slide.body, transcriptIds: slide.transcript_ids, sources: slide.sources };
    });
    await step(7, async () => {
      feature('recording');
      const media = await page.evaluate(() => window.__e2eMedia.snapshot());
      if (!state.recordingStarted && !media.tracks.some(track => track.state === 'live')) throw new Blocked('No microphone recording was started');
      await (await visible(page, 'recording-stop', options)).click();
      await waitFor(async () => {
        const media = await page.evaluate(() => window.__e2eMedia.snapshot());
        const session = await snapshot();
        return session.state === 'stopped' && media.tracks.length > 0 && media.tracks.every(track => track.state === 'ended') && media.recorderStates.every(status => status === 'inactive');
      }, options, 'Recording stop did not release microphone tracks and stop the backend session');
      feature('session_end');
      await (await visible(page, 'session-end', options)).click();
      const ended = await waitFor(async () => {
        const session = await snapshot();
        const ui = await page.$eval(selector('session-state'), element => element.dataset.state);
        const openApiSockets = [...journal.webSockets.values()].filter(socket => socket.api);
        return session.state === 'ended' && ui === 'ended' && openApiSockets.length === 0 && session;
      }, options, 'Session did not end in UI/backend or an API WebSocket remained open');
      return ended;
    });
  } finally {
    journal.step = 'cleanup';
    if (page && !page.isClosed()) await cleanup('release_remaining_microphone_tracks', () => page.evaluate(() => window.__e2eMedia?.release()));
    if (browser) await cleanup('close_browser', () => browser.close());
    if (state.sessionId) await cleanup('delete_isolated_session', async () => {
      await api(journal, options, `/api/e2e/sessions/${state.sessionId}`, { method: 'DELETE', expected: [204] });
      await api(journal, options, sessionRoute(), { expected: [404] });
      return { sessionId: state.sessionId, confirmedAbsent: true };
    });
    for (const process_ of owned.reverse()) await cleanup(`stop_${process_.label}`, () => stopService(process_, journal));
    await journal.flush();
    result.diagnostics = journal.errors;
    result.durationMs = Math.round(performance.now() - started);
    result.finishedAt = new Date().toISOString();
    result.status = runStatus(result);
    writeJson(path.join(directory, 'result.json'), result);
  }
  return result;
}

function saveSummary(directory, summary) {
  writeJson(path.join(directory, 'summary.json'), summary);
  const startedKst = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', dateStyle: 'medium', timeStyle: 'medium' }).format(new Date(summary.startedAt));
  const lines = [`# Smoke E2E — ${summary.status}`, '', `Started: ${startedKst} KST`, `Media preflight: ${summary.preflight?.status ?? 'not run'}`, '', '| Step | ' + summary.runs.map(run => `Run ${run.run}`).join(' | ') + ' |', '| --- | ' + summary.runs.map(() => '---').join(' | ') + ' |'];
  for (let index = 0; index < STEPS.length; index++) lines.push(`| ${index + 1}. ${STEPS[index]} | ` + summary.runs.map(run => { const step = run.steps[index]; return step ? `${step.status} (${step.durationMs} ms)` : 'NOT RUN'; }).join(' | ') + ' |');
  lines.push('', 'Every non-PASS scenario exits nonzero. Cleanup is reported separately from normal session termination.', '', ...summary.runs.map(run => `- [Run ${run.run} report](run-${String(run.run).padStart(2, '0')}/result.json): ${run.status}; session ${run.sessionId ?? 'unavailable'}; ${run.durationMs} ms`));
  if (summary.fatal) lines.push('', 'Fatal: ' + summary.fatal.message);
  fs.writeFileSync(path.join(directory, 'summary.md'), lines.join('\n') + '\n');
}

async function main() {
  const options = parseOptions(process.argv.slice(2));
  const directory = path.join(options.artifactsDir, new Date().toISOString().replace(/[:.]/g, '-') + '-' + randomUUID().slice(0, 8));
  const summary = { startedAt: new Date().toISOString(), status: 'RUNNING', requestedRuns: options.runs, runs: [], options };
  writeJson(path.join(options.artifactsDir, 'latest.json'), { directory });
  try {
    options.chrome = discoverChrome(options.chrome);
    const fixture = loadFixtures(options);
    summary.environment = { node: process.version, platform: process.platform, chrome: options.chrome, audioSha256: fixture.audioSha256, pdfSha256: fixture.pdfSha256, wave: fixture.wave };
    const journal = new Journal(path.join(directory, 'media-preflight'));
    const begin = performance.now();
    try {
      const details = await mediaPreflight(options, journal);
      check(journal.errors.length === 0, 'Media preflight produced browser/API errors');
      summary.preflight = { status: 'PASS', details };
    }
    catch (error) { summary.preflight = { status: 'FAIL', error: errorInfo(error) }; }
    summary.preflight.durationMs = Math.round(performance.now() - begin);
    writeJson(path.join(journal.directory, 'result.json'), summary.preflight);
    for (let number = 1; number <= options.runs && !interrupted; number++) {
      summary.runs.push(await runScenario(number, options, fixture, directory));
      saveSummary(directory, summary);
    }
    check(new Set(summary.runs.map(run => run.sessionId).filter(Boolean)).size === summary.runs.filter(run => run.sessionId).length, 'Test runs reused a backend session ID');
    summary.status = suiteStatus(summary, interrupted);
  } catch (error) { summary.status = 'FAIL'; summary.fatal = errorInfo(error); }
  summary.finishedAt = new Date().toISOString();
  summary.exitCode = summary.status === 'PASS' ? 0 : 1;
  saveSummary(directory, summary);
  console.log(`E2E ${summary.status}: ${summary.runs.length}/${options.runs} runs. Report: ${path.join(directory, 'summary.md')}`);
  process.exitCode = summary.exitCode;
}

if (process.argv.includes('--help')) {
  console.log('Usage: node e2e/smoke.mjs --runs=3 [--attach] [--headed]\nOptions: --frontend-url --backend-url --chrome --audio --pdf --artifacts-dir --timeout-ms --startup-timeout-ms');
} else {
  main().catch(error => { console.error(error); process.exitCode = 2; });
}
