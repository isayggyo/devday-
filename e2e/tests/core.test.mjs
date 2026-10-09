import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {
  FIXTURES, STEPS, parseOptions, loadFixtures, inspectWave, discoverChrome,
  assertEmptySession, assertSources, NotImplemented, Blocked, statusFor,
  runStatus, suiteStatus,
} from '../core.mjs';

test('--runs=3 and explicit local origins are parsed', () => {
  const options = parseOptions(['--runs=3', '--backend-url', 'http://localhost:8100', '--timeout-ms=900']);
  assert.equal(options.runs, 3);
  assert.equal(options.backendUrl, 'http://localhost:8100');
  assert.equal(options.timeoutMs, 900);
});
test('invalid repeat counts and remote targets cannot execute', () => {
  for (const value of ['0', '-1', '3.5', 'NaN']) assert.throws(() => parseOptions([`--runs=${value}`]));
  assert.throws(() => parseOptions(['--backend-url=https://example.com']));
  assert.throws(() => parseOptions(['--made-up=true']));
});
test('fixed lecture PDF and non-silent spoken WAV match their hashes', () => {
  const fixture = loadFixtures(parseOptions([]));
  assert.equal(fixture.pages.length, 2);
  assert.equal(fixture.wave.sampleRate, 16000);
  assert.ok(fixture.wave.durationSeconds > 40);
  assert.ok(fixture.wave.rms > 0.001);
});
test('invalid and truncated audio fail instead of using a default microphone', () => {
  assert.throws(() => inspectWave(Buffer.from('not a WAV')));
  const wave = fs.readFileSync(path.join(FIXTURES, 'lecture.wav'));
  assert.throws(() => inspectWave(wave.subarray(0, 80)), /Truncated|fmt\/data/);
});
test('an explicit missing Chrome fails instead of selecting a user browser', () => {
  assert.throws(() => discoverChrome(path.join(FIXTURES, 'missing-chrome.exe')));
});
test('leftover session data cannot be reported as an isolated test run', () => {
  const session = { id: 'test-id', run_id: 'run', state: 'idle', documents: [], transcripts: [], slides: [], audio_bytes: 0 };
  assertEmptySession(session, 'run');
  assert.throws(() => assertEmptySession({ ...session, audio_bytes: 1 }, 'run'), /Stale audio/);
  assert.throws(() => assertEmptySession({ ...session, documents: ['existing document'] }, 'run'), /Stale documents/);
  assert.throws(() => assertEmptySession(session, 'another-run'));
});
test('empty content and absent provenance cannot satisfy the slide assertion', () => {
  assert.throws(() => assertSources({}, 'document', [], {}), /title\/body/);
  assert.throws(() => assertSources({ title: 'x', body: 'x', document_id: 'document', transcript_ids: [] }, 'document', [], {}), /transcript references/);
});
test('NOT_IMPLEMENTED and dependency failures are distinct from PASS', () => {
  assert.equal(statusFor(new NotImplemented('missing')), 'NOT_IMPLEMENTED');
  assert.equal(statusFor(new Blocked('upstream')), 'BLOCKED');
  assert.equal(statusFor(new Error('broken')), 'FAIL');
});
test('partial runs, browser errors, and cleanup failures cannot yield green reports', () => {
  const result = { steps: STEPS.map(() => ({ status: 'PASS' })), cleanup: [{ status: 'PASS' }], diagnostics: [] };
  assert.equal(runStatus(result), 'PASS');
  assert.equal(runStatus({ ...result, steps: result.steps.slice(0, 7) }), 'FAIL');
  assert.equal(runStatus({ ...result, diagnostics: [{}] }), 'FAIL');
  assert.equal(runStatus({ ...result, cleanup: [{ status: 'FAIL' }] }), 'FAIL');
  assert.equal(runStatus({ ...result, steps: result.steps.map((step, index) => index === 4 ? { status: 'NOT_IMPLEMENTED' } : step) }), 'NOT_IMPLEMENTED');
});
test('three completed scenarios and successful media preflight are required', () => {
  const summary = { requestedRuns: 3, preflight: { status: 'PASS' }, runs: [{ status: 'PASS' }, { status: 'PASS' }, { status: 'PASS' }] };
  assert.equal(suiteStatus(summary), 'PASS');
  assert.equal(suiteStatus({ ...summary, runs: summary.runs.slice(0, 2) }), 'FAIL');
  assert.equal(suiteStatus({ ...summary, preflight: { status: 'FAIL' } }), 'FAIL');
  assert.equal(suiteStatus(summary, true), 'FAIL');
  assert.equal(suiteStatus({ ...summary, runs: summary.runs.map(() => ({ status: 'NOT_IMPLEMENTED' })) }), 'NOT_IMPLEMENTED');
});
