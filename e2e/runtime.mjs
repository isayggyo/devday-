import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';
import { createRequire } from 'node:module';
import puppeteer from 'puppeteer-core';
import { ROOT, check, sleep, NotImplemented, errorInfo } from './core.mjs';

const require = createRequire(import.meta.url);
export function writeJson(filename, value) {
  fs.mkdirSync(path.dirname(filename), { recursive: true });
  fs.writeFileSync(filename, JSON.stringify(value, null, 2) + '\n');
}

export class Journal {
  constructor(directory) {
    this.directory = directory;
    this.step = 'setup';
    this.errors = [];
    this.pending = new Set();
    this.webSockets = new Map();
    fs.mkdirSync(directory, { recursive: true });
    for (const name of ['events', 'browser-console', 'api-errors']) fs.writeFileSync(path.join(directory, name + '.jsonl'), '');
  }
  log(type, detail = {}, step = this.step) {
    const event = { timestamp: new Date().toISOString(), step, type, ...detail };
    fs.appendFileSync(path.join(this.directory, 'events.jsonl'), JSON.stringify(event) + '\n');
    if (['console', 'page_error', 'browser_crash'].includes(type)) fs.appendFileSync(path.join(this.directory, 'browser-console.jsonl'), JSON.stringify(event) + '\n');
    if (type === 'api_error') fs.appendFileSync(path.join(this.directory, 'api-errors.jsonl'), JSON.stringify(event) + '\n');
    if (detail.fatal) this.errors.push(event);
    return event;
  }
  attach(page, backendUrl) {
    const starts = new WeakMap();
    page.on('console', message => this.log('console', { level: message.type(), message: message.text(), location: message.location(), fatal: message.type() === 'error' }));
    page.on('pageerror', error => this.log('page_error', { message: String(error?.message ?? error), stack: error?.stack, fatal: true }));
    page.on('error', error => this.log('browser_crash', { message: error.message, fatal: true }));
    page.on('request', request => starts.set(request, { started: performance.now(), step: this.step }));
    page.on('requestfailed', request => {
      const info = starts.get(request);
      const expected = this.step === 'cleanup' && request.failure()?.errorText === 'net::ERR_ABORTED';
      const detail = { url: request.url(), method: request.method(), error: request.failure(), durationMs: info ? performance.now() - info.started : null, fatal: !expected, expected };
      this.log('request_failed', detail, info?.step);
      if (request.url().startsWith(backendUrl) || new URL(request.url()).pathname.startsWith('/api/')) this.log('api_error', detail, info?.step);
    });
    page.on('response', response => {
      const request = response.request();
      const info = starts.get(request);
      const event = { url: response.url(), method: request.method(), status: response.status(), durationMs: info ? performance.now() - info.started : null };
      this.log('browser_response', event, info?.step);
      if (response.status() >= 400) {
        const isApi = response.url().startsWith(backendUrl) || new URL(response.url()).pathname.startsWith('/api/');
        this.log(isApi ? 'api_error' : 'http_error', { ...event, fatal: true }, info?.step);
        const pending = response.text().then(body => this.log('error_response_body', { ...event, body: body.slice(0, 12_000) }, info?.step)).catch(error => this.log('error_response_body_unavailable', { ...event, message: error.message }, info?.step));
        this.pending.add(pending);
        pending.finally(() => this.pending.delete(pending));
      }
    });
  }
  async attachSockets(page, backendUrl) {
    const cdp = await page.createCDPSession();
    await cdp.send('Network.enable');
    cdp.on('Network.webSocketCreated', event => {
      const url = new URL(event.url);
      const apiSocket = url.host === new URL(backendUrl).host || url.pathname.startsWith('/api/');
      this.webSockets.set(event.requestId, { url: event.url, api: apiSocket, opened: performance.now() });
      this.log('websocket_open', { url: event.url, api: apiSocket });
    });
    cdp.on('Network.webSocketHandshakeResponseReceived', event => {
      const socket = this.webSockets.get(event.requestId);
      this.log('websocket_handshake', { url: socket?.url, status: event.response.status });
      if (socket?.api && event.response.status >= 400) this.log('api_error', { url: socket.url, status: event.response.status, protocol: 'websocket', fatal: true });
    });
    cdp.on('Network.webSocketFrameError', event => {
      const socket = this.webSockets.get(event.requestId);
      this.log(socket?.api ? 'api_error' : 'websocket_error', { url: socket?.url, message: event.errorMessage, protocol: 'websocket', fatal: socket?.api === true });
    });
    cdp.on('Network.webSocketFrameReceived', event => {
      const socket = this.webSockets.get(event.requestId);
      if (!socket?.api || event.response.opcode !== 1) return;
      try {
        const payload = JSON.parse(event.response.payloadData);
        if (payload.type === 'error' || payload.code === 'NOT_IMPLEMENTED' || payload.error) this.log('api_error', { url: socket.url, protocol: 'websocket', body: payload, fatal: true });
      } catch { /* Non-JSON frames are not application error messages. */ }
    });
    cdp.on('Network.webSocketClosed', event => {
      const socket = this.webSockets.get(event.requestId);
      this.webSockets.delete(event.requestId);
      this.log('websocket_closed', { url: socket?.url, durationMs: socket ? performance.now() - socket.opened : null });
    });
  }
  async flush() {
    if (!this.pending.size) return;
    let timer;
    try { await Promise.race([Promise.allSettled([...this.pending]), new Promise(resolve => { timer = setTimeout(resolve, 5_000); })]); }
    finally { clearTimeout(timer); }
  }
}

export async function api(journal, options, route, { method = 'GET', body, expected = [200], timeoutMs = options.timeoutMs } = {}) {
  const url = options.backendUrl + route;
  const started = performance.now();
  let response;
  try {
    response = await fetch(url, { method, headers: body === undefined ? {} : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(timeoutMs) });
  } catch (error) {
    journal.log('api_error', { url, method, message: error.message, cause: error.cause?.message, code: error.cause?.code, durationMs: performance.now() - started, fatal: true });
    throw error;
  }
  let text;
  try { text = await response.text(); }
  catch (error) { journal.log('api_error', { url, method, status: response.status, message: error.message, durationMs: performance.now() - started, fatal: true }); throw error; }
  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  const detail = { url, method, status: response.status, durationMs: performance.now() - started, body: data, expected: expected.includes(response.status) };
  journal.log('api_response', detail);
  if (!detail.expected) {
    journal.log('api_error', { ...detail, fatal: true });
    if (response.status === 501 || data?.code === 'NOT_IMPLEMENTED' || data?.detail?.code === 'NOT_IMPLEMENTED') throw new NotImplemented(`${method} ${route}: NOT_IMPLEMENTED`);
    check(false, `${method} ${route}: expected HTTP ${expected.join('/')}, received ${response.status}`);
  }
  return data;
}

async function portAvailable(url) {
  const address = new URL(url);
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(Number(address.port || 80), address.hostname.replace(/[\[\]]/g, ''), resolve);
  });
  await new Promise(resolve => server.close(resolve));
}

function startService(label, executable, args, cwd, environment, journal) {
  const filename = path.join(journal.directory, label + '.log');
  const handle = fs.openSync(filename, 'a');
  const child = spawn(executable, args, { cwd, env: environment, windowsHide: true, detached: process.platform !== 'win32', stdio: ['ignore', handle, handle] });
  fs.closeSync(handle);
  child.on('error', error => { child.launchError = error; journal.log('service_error', { label, error: errorInfo(error) }); });
  child.on('exit', (code, signal) => journal.log('service_exit', { label, pid: child.pid, code, signal }));
  journal.log('service_start', { label, executable, args, cwd, pid: child.pid, log: path.basename(filename) });
  return { label, child };
}

async function health(url, service, process_, journal, timeoutMs) {
  const deadline = performance.now() + timeoutMs;
  let lastError;
  while (performance.now() < deadline) {
    if (process_?.launchError) throw process_.launchError;
    check(!process_ || (process_.exitCode === null && process_.signalCode === null), `${service} exited before healthcheck; see service log`);
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(3_000) });
      const body = await response.json();
      if (response.ok && body.status === 'ok' && body.service === service) {
        check(!process_ || process_.exitCode === null, `${service} exited during healthcheck`);
        journal.log('health_ready', { url, status: response.status, body });
        return body;
      }
      lastError = `HTTP ${response.status}: ${JSON.stringify(body)}`;
    } catch (error) { lastError = error.message; }
    journal.log('health_retry', { url, message: lastError, expected: true });
    await sleep(300);
  }
  check(false, `${service} healthcheck timed out after ${timeoutMs}ms: ${lastError}`);
}

export async function services(options, journal, owned) {
  let frontend;
  let backend;
  if (!options.attach) {
    await Promise.all([portAvailable(options.frontendUrl), portAvailable(options.backendUrl)]);
    const python = process.env.E2E_PYTHON ?? path.join(ROOT, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
    check(fs.existsSync(python), 'Backend virtualenv is missing. Run python scripts/setup_e2e.py or set E2E_PYTHON.');
    const environment = { ...process.env, E2E_MODE: '1', FRONTEND_ORIGIN: options.frontendUrl, NEXT_PUBLIC_BACKEND_URL: options.backendUrl, NEXT_TELEMETRY_DISABLED: '1', PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' };
    backend = startService('backend', python, ['-m', 'uvicorn', 'backend.app:app', '--host', new URL(options.backendUrl).hostname.replace(/[\[\]]/g, ''), '--port', new URL(options.backendUrl).port || '80'], ROOT, environment, journal).child;
    owned.push({ label: 'backend', child: backend });
    frontend = startService('frontend', process.execPath, [require.resolve('next/dist/bin/next'), 'dev', '--webpack', '--hostname', new URL(options.frontendUrl).hostname.replace(/[\[\]]/g, ''), '--port', new URL(options.frontendUrl).port || '80'], path.join(ROOT, 'frontend'), environment, journal).child;
    owned.push({ label: 'frontend', child: frontend });
  }
  const checks = await Promise.allSettled([
    health(options.backendUrl + '/health', 'lecture-backend', backend, journal, options.startupTimeoutMs),
    health(options.frontendUrl + '/api/health', 'lecture-frontend', frontend, journal, options.startupTimeoutMs),
  ]);
  for (const result of checks) if (result.status === 'rejected') throw result.reason;
  const values = checks.map(result => result.value);
  check(values[0].e2e_enabled === true, 'Backend must enable isolated E2E session controls (E2E_MODE=1)');
  return values;
}

export async function stopService({ label, child }, journal) {
  if (child.exitCode !== null || child.signalCode !== null || !child.pid) return;
  journal.log('service_stop', { label, pid: child.pid });
  if (process.platform === 'win32') {
    await new Promise((resolve, reject) => {
      const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true });
      killer.on('error', reject);
      killer.on('exit', code => code === 0 || child.exitCode !== null ? resolve() : reject(new Error(`taskkill failed for owned ${label} PID ${child.pid}: ${code}`)));
    });
  } else {
    process.kill(-child.pid, 'SIGTERM');
  }
  const deadline = performance.now() + 5_000;
  while (child.exitCode === null && child.signalCode === null && performance.now() < deadline) await sleep(100);
  if (process.platform !== 'win32' && child.exitCode === null && child.signalCode === null) {
    process.kill(-child.pid, 'SIGKILL');
    const forcedDeadline = performance.now() + 5_000;
    while (child.exitCode === null && child.signalCode === null && performance.now() < forcedDeadline) await sleep(100);
  }
  check(child.exitCode !== null || child.signalCode !== null, `Owned ${label} process did not exit`);
}

export async function launchBrowser(options, journal, profileName = 'profile') {
  const args = [
    '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
    `--use-file-for-fake-audio-capture=${options.audio}`, '--autoplay-policy=no-user-gesture-required',
  ];
  journal.log('browser_launch', { executablePath: options.chrome, args, audioFixture: options.audio });
  const browser = await puppeteer.launch({ executablePath: options.chrome, headless: !options.headed, args, userDataDir: path.join(journal.directory, profileName), timeout: options.startupTimeoutMs, handleSIGINT: false, handleSIGTERM: false, handleSIGHUP: false });
  browser.process()?.stderr?.on('data', chunk => fs.appendFileSync(path.join(journal.directory, 'chrome.log'), chunk));
  journal.log('browser_ready', { version: await browser.version(), pid: browser.process()?.pid });
  return browser;
}

export async function mediaPreflight(options, journal) {
  const server = http.createServer((request, response) => { response.writeHead(200, { 'Content-Type': 'text/html' }); response.end('<!doctype html><title>Real WAV microphone diagnostic</title><p>Microphone fixture diagnostic</p>'); });
  let browser;
  let page;
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
    browser = await launchBrowser(options, journal);
    page = await browser.newPage();
    journal.attach(page, options.backendUrl);
    await page.goto(`http://127.0.0.1:${server.address().port}`, { waitUntil: 'domcontentloaded' });
    const result = await page.evaluate(async () => {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false }, video: false });
      const context = new AudioContext();
      await context.resume();
      const analyser = context.createAnalyser();
      analyser.fftSize = 2048;
      context.createMediaStreamSource(stream).connect(analyser);
      const recorder = new MediaRecorder(stream);
      const chunks = [];
      recorder.addEventListener('dataavailable', event => { if (event.data.size) chunks.push(event.data); });
      const stopped = new Promise(resolve => recorder.addEventListener('stop', resolve, { once: true }));
      recorder.start(250);
      let maxRms = 0;
      for (let index = 0; index < 30; index++) {
        await new Promise(resolve => setTimeout(resolve, 100));
        const samples = new Float32Array(analyser.fftSize);
        analyser.getFloatTimeDomainData(samples);
        maxRms = Math.max(maxRms, Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length));
      }
      recorder.stop();
      await stopped;
      const blob = new Blob(chunks, { type: recorder.mimeType });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (const byte of bytes) binary += String.fromCharCode(byte);
      const track = stream.getAudioTracks()[0];
      const settings = track.getSettings();
      const deviceLabel = track.label;
      stream.getTracks().forEach(item => item.stop());
      await context.close();
      return { maxRms, bytes: bytes.length, mimeType: blob.type, deviceLabel, settings, tracksEnded: stream.getTracks().every(item => item.readyState === 'ended'), recordedBase64: btoa(binary) };
    });
    const { recordedBase64, ...metadata } = result;
    fs.writeFileSync(path.join(journal.directory, 'captured-fixture.webm'), Buffer.from(recordedBase64, 'base64'));
    check(metadata.maxRms > 0.001 && metadata.bytes > 1000 && metadata.tracksEnded, 'Fake microphone WAV capture was empty, silent, or not released');
    journal.log('media_probe_pass', metadata);
    return metadata;
  } catch (error) {
    if (page && !page.isClosed()) {
      try { await page.screenshot({ path: path.join(journal.directory, 'failure.png') }); }
      catch (captureError) { journal.log('screenshot_unavailable', { message: captureError.message }); }
    }
    throw error;
  } finally {
    journal.step = 'cleanup';
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
    await journal.flush();
  }
}

export async function observeMedia(page) {
  await page.evaluateOnNewDocument(() => {
    const tracks = [];
    const recorders = [];
    let bytes = 0;
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (...args) => {
      const stream = await original(...args);
      tracks.push(...stream.getAudioTracks());
      return stream;
    };
    const NativeRecorder = window.MediaRecorder;
    window.MediaRecorder = class extends NativeRecorder {
      constructor(...args) {
        super(...args);
        recorders.push(this);
        this.addEventListener('dataavailable', event => { bytes += event.data.size; });
      }
    };
    window.__e2eMedia = {
      snapshot: () => ({ audioBytes: bytes, tracks: tracks.map(track => ({ id: track.id, state: track.readyState })), recorderStates: recorders.map(recorder => recorder.state) }),
      release: () => { recorders.forEach(recorder => { if (recorder.state !== 'inactive') recorder.stop(); }); tracks.forEach(track => track.stop()); },
    };
  });
}
