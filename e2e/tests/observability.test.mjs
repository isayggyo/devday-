import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { ROOT, parseOptions, discoverChrome, NotImplemented, sleep } from '../core.mjs';
import { Journal, api, launchBrowser, observeMedia } from '../runtime.mjs';

async function diagnostic(t) {
  const directory = path.join(ROOT, 'artifacts/harness-tests', randomUUID());
  const journal = new Journal(directory);
  const server = http.createServer((request, response) => {
    if (request.url === '/api/unavailable') {
      response.writeHead(501, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ detail: { code: 'NOT_IMPLEMENTED' } }));
    } else if (request.url === '/api/abort') { response.destroy(); }
    else if (request.url === '/favicon.ico') { response.writeHead(204); response.end(); }
    else { response.writeHead(200, { 'Content-Type': 'text/html' }); response.end('<!doctype html><title>Error capture diagnostic</title><p>Harness diagnostic</p>'); }
  });
  server.on('upgrade', (request, socket) => socket.end('HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n'));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => { await journal.flush(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  return { journal, directory, origin: `http://127.0.0.1:${server.address().port}` };
}

test('HTTP 501 is captured with body, timing, stage, and NOT_IMPLEMENTED classification', async t => {
  const { journal, directory, origin } = await diagnostic(t);
  journal.step = 'upload_pdf';
  await assert.rejects(api(journal, { backendUrl: origin, timeoutMs: 1000 }, '/api/unavailable'), NotImplemented);
  const rows = fs.readFileSync(path.join(directory, 'api-errors.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
  assert.equal(rows[0].status, 501);
  assert.equal(rows[0].step, 'upload_pdf');
  assert.equal(rows[0].body.detail.code, 'NOT_IMPLEMENTED');
  assert.ok(rows[0].durationMs >= 0);
  await assert.rejects(api(journal, { backendUrl: origin, timeoutMs: 1000 }, '/api/abort'));
  assert.ok(journal.errors.some(event => event.type === 'api_error' && event.url.endsWith('/api/abort')));
});

test('real Chrome records console, uncaught JS, HTTP errors, and real media observations', async t => {
  const { journal, directory, origin } = await diagnostic(t);
  const options = parseOptions([]);
  options.chrome = discoverChrome(options.chrome);
  const browser = await launchBrowser(options, journal);
  t.after(() => browser.close());
  const page = await browser.newPage();
  journal.attach(page, origin);
  await journal.attachSockets(page, origin);
  await observeMedia(page);
  await page.goto(origin);
  await page.evaluate(async () => {
    console.error('expected-console-diagnostic');
    setTimeout(() => { throw new Error('expected-uncaught-diagnostic'); }, 0);
    await fetch('/api/unavailable');
    await fetch('/api/abort').catch(() => {});
    await new Promise(resolve => {
      const socket = new WebSocket(location.origin.replace('http:', 'ws:') + '/api/ws-unavailable');
      socket.addEventListener('error', resolve, { once: true });
    });
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    const recorder = new MediaRecorder(stream);
    recorder.start(100);
    await new Promise(resolve => setTimeout(resolve, 350));
    const stopped = new Promise(resolve => recorder.addEventListener('stop', resolve, { once: true }));
    recorder.stop();
    await stopped;
    stream.getTracks().forEach(track => track.stop());
  });
  await sleep(150);
  await journal.flush();
  assert.ok(journal.errors.some(event => event.type === 'console' && event.message === 'expected-console-diagnostic'));
  assert.ok(journal.errors.some(event => event.type === 'page_error' && event.message.includes('expected-uncaught-diagnostic')));
  assert.ok(journal.errors.some(event => event.type === 'api_error' && event.status === 501));
  assert.ok(journal.errors.some(event => event.type === 'api_error' && event.url.endsWith('/api/abort') && event.error));
  assert.ok(journal.errors.some(event => event.type === 'api_error' && event.protocol === 'websocket'));
  const media = await page.evaluate(() => window.__e2eMedia.snapshot());
  assert.ok(media.audioBytes > 0);
  assert.ok(media.tracks.length > 0 && media.tracks.every(track => track.state === 'ended'));
  assert.ok(media.recorderStates.every(state => state === 'inactive'));
  await page.screenshot({ path: path.join(directory, 'diagnostic.png') });
  assert.ok(fs.statSync(path.join(directory, 'browser-console.jsonl')).size > 0);
  assert.ok(fs.statSync(path.join(directory, 'api-errors.jsonl')).size > 0);
});
