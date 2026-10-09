import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
export const FIXTURES = path.join(ROOT, 'e2e', 'fixtures');
export const STEPS = [
  'services_and_health', 'open_app', 'upload_pdf', 'start_recording',
  'receive_transcript', 'generate_visual_slide', 'verify_content_and_sources',
  'stop_recording_and_end_session',
];
export const selector = name => `[data-testid="${name}"]`;
export const normalize = text => String(text ?? '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
export const sha256 = buffer => createHash('sha256').update(buffer).digest('hex');
export const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

export class NotImplemented extends Error {
  constructor(message) { super(message); this.name = 'NotImplemented'; this.code = 'NOT_IMPLEMENTED'; }
}
export class Blocked extends Error {
  constructor(message) { super(message); this.name = 'Blocked'; this.code = 'DEPENDENCY_FAILED'; }
}
export function check(condition, message) { assert.ok(condition, message); }
export function errorInfo(error) {
  return { name: error.name, code: error.code ?? 'ASSERTION_FAILED', message: error.message, stack: error.stack };
}
export function statusFor(error) {
  return error instanceof NotImplemented ? 'NOT_IMPLEMENTED' : error instanceof Blocked ? 'BLOCKED' : 'FAIL';
}

export function runStatus(result) {
  if (result.steps.length !== STEPS.length || result.steps.some(step => step.status === 'FAIL') || result.cleanup.some(step => step.status !== 'PASS') || result.diagnostics.length) return 'FAIL';
  if (result.steps.some(step => step.status === 'NOT_IMPLEMENTED')) return 'NOT_IMPLEMENTED';
  return result.steps.every(step => step.status === 'PASS') ? 'PASS' : 'FAIL';
}
export function suiteStatus(summary, interrupted = false) {
  if (interrupted || summary.preflight?.status !== 'PASS' || summary.runs.length !== summary.requestedRuns) return 'FAIL';
  if (summary.runs.every(run => run.status === 'PASS')) return 'PASS';
  return summary.runs.every(run => run.status === 'NOT_IMPLEMENTED') ? 'NOT_IMPLEMENTED' : 'FAIL';
}

export function parseOptions(arguments_) {
  const options = {
    runs: 1, timeoutMs: 30_000, startupTimeoutMs: 60_000,
    frontendUrl: 'http://127.0.0.1:3000', backendUrl: 'http://127.0.0.1:8000',
    pdf: path.join(FIXTURES, 'lecture.pdf'), audio: path.join(FIXTURES, 'lecture.wav'),
    chrome: process.env.E2E_CHROME, artifactsDir: path.join(ROOT, 'artifacts/e2e'),
    attach: false, headed: false,
  };
  const names = {
    runs: 'runs', 'timeout-ms': 'timeoutMs', 'startup-timeout-ms': 'startupTimeoutMs',
    'frontend-url': 'frontendUrl', 'backend-url': 'backendUrl',
    pdf: 'pdf', audio: 'audio', chrome: 'chrome', 'artifacts-dir': 'artifactsDir',
  };
  for (let index = 0; index < arguments_.length; index++) {
    const argument = arguments_[index];
    if (argument === '--attach' || argument === '--headed') {
      options[argument.slice(2)] = true;
      continue;
    }
    const match = /^--([^=]+)(?:=(.*))?$/.exec(argument);
    check(match && names[match[1]], `Unknown option: ${argument}`);
    const value = match[2] ?? arguments_[++index];
    check(value && !value.startsWith('--'), `Missing value for --${match[1]}`);
    options[names[match[1]]] = ['runs', 'timeout-ms', 'startup-timeout-ms'].includes(match[1]) ? Number(value) : value;
  }
  check(Number.isInteger(options.runs) && options.runs >= 1 && options.runs <= 100, '--runs must be an integer from 1 to 100');
  for (const field of ['timeoutMs', 'startupTimeoutMs']) check(Number.isInteger(options[field]) && options[field] > 0, `${field} must be a positive integer`);
  for (const field of ['frontendUrl', 'backendUrl']) {
    const url = new URL(options[field]);
    check(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname), `${field} must point to a local HTTP app`);
    check(!url.username && !url.password && url.pathname === '/' && !url.search, `${field} must be a local origin`);
    options[field] = url.origin;
  }
  for (const field of ['audio', 'pdf', 'artifactsDir']) options[field] = path.resolve(options[field]);
  return options;
}

export function discoverChrome(explicit) {
  if (explicit) {
    check(fs.existsSync(explicit), `Chrome executable not found: ${explicit}`);
    return path.resolve(explicit);
  }
  const directory = process.env.E2E_CFT_CACHE ?? path.join(os.homedir(), '.cache/gyeol-cft');
  const candidates = [];
  function visit(current, depth) {
    if (depth > 7 || !fs.existsSync(current)) return;
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) visit(full, depth + 1);
      else if (entry.isFile() && ['chrome.exe', 'chrome', 'Google Chrome for Testing'].includes(entry.name)) candidates.push(full);
    }
  }
  visit(directory, 0);
  check(candidates.length > 0, `Chrome for Testing not found in ${directory}. Set E2E_CHROME or --chrome.`);
  candidates.sort((a, b) => b.localeCompare(a, undefined, { numeric: true }));
  return candidates[0];
}

export function inspectWave(buffer) {
  check(buffer.length > 44 && buffer.toString('ascii', 0, 4) === 'RIFF' && buffer.toString('ascii', 8, 12) === 'WAVE', 'Fixture must be a RIFF/WAVE file');
  let format;
  let audio;
  for (let offset = 12; offset + 8 <= buffer.length;) {
    const kind = buffer.toString('ascii', offset, offset + 4);
    const size = buffer.readUInt32LE(offset + 4);
    check(offset + 8 + size <= buffer.length, 'Truncated WAV chunk');
    if (kind === 'fmt ') {
      check(size >= 16, 'Invalid WAV fmt chunk');
      format = {
        encoding: buffer.readUInt16LE(offset + 8), channels: buffer.readUInt16LE(offset + 10),
        sampleRate: buffer.readUInt32LE(offset + 12), bitsPerSample: buffer.readUInt16LE(offset + 22),
      };
    }
    if (kind === 'data') audio = buffer.subarray(offset + 8, offset + 8 + size);
    offset += 8 + size + (size % 2);
  }
  check(format && audio?.length, 'WAV fmt/data chunks are required');
  check(format.encoding === 1 && format.bitsPerSample === 16 && [1, 2].includes(format.channels), 'Use 16-bit PCM mono/stereo WAV');
  const durationSeconds = audio.length / (format.sampleRate * format.channels * 2);
  check(durationSeconds >= 5, 'Lecture WAV must contain at least five seconds of audio');
  let energy = 0;
  for (let index = 0; index + 1 < audio.length; index += 2) energy += (audio.readInt16LE(index) / 32768) ** 2;
  const rms = Math.sqrt(energy / (audio.length / 2));
  check(rms > 0.0001, 'Lecture WAV contains no audible signal');
  return { ...format, durationSeconds, rms };
}

export function loadFixtures(options) {
  const manifest = JSON.parse(fs.readFileSync(path.join(FIXTURES, 'lecture.json'), 'utf8'));
  const pdf = fs.readFileSync(options.pdf);
  const audio = fs.readFileSync(options.audio);
  check(pdf.subarray(0, 5).toString() === '%PDF-', 'Invalid PDF fixture');
  check(sha256(pdf) === manifest.pdf_sha256, 'PDF differs from lecture.json; regenerate the manifest when changing lecture materials');
  check(sha256(audio) === manifest.audio_sha256, 'WAV differs from lecture.json; use the fixed lecture fixture or update its manifest');
  return { ...manifest, filename: path.basename(options.pdf), audioSha256: sha256(audio), pdfSha256: sha256(pdf), wave: inspectWave(audio) };
}

export function assertEmptySession(session, runId) {
  check(session.id && session.run_id === runId && session.state === 'idle', 'Fresh session must be idle and belong to this run');
  for (const key of ['documents', 'transcripts', 'slides']) check(Array.isArray(session[key]) && session[key].length === 0, `Stale ${key} in test session`);
  check(session.audio_bytes === 0, 'Stale audio in test session');
}

export function assertSources(slide, documentId, transcripts, fixture) {
  check(slide.title?.trim() && slide.body?.trim(), 'Slide title/body must contain real content');
  check(slide.document_id === documentId, 'Slide references the wrong uploaded document');
  check(Array.isArray(slide.transcript_ids) && slide.transcript_ids.length > 0, 'Slide has no transcript references');
  check(Array.isArray(transcripts), 'Backend transcripts must be an array');
  for (const id of slide.transcript_ids) check(transcripts.some(item => item.id === id && item.session_id === slide.session_id && item.text?.trim()), `Referenced transcript ${id} does not exist in this session`);
  check(Array.isArray(slide.sources) && slide.sources.length > 0, 'Slide has no document source citations');
  for (const source of slide.sources) {
    check(source.document_id === documentId && source.filename === fixture.filename, 'Source must name the uploaded PDF');
    const page = fixture.pages.find(item => item.page === source.page);
    check(Number.isInteger(source.page) && page, 'Source page is outside the uploaded PDF');
    const quote = normalize(source.excerpt);
    const sourceText = normalize([page.title, ...page.paragraphs].join(' '));
    check(quote.length >= 12 && sourceText.includes(quote), 'Source excerpt is not present on the cited PDF page');
  }
}
