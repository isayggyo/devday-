import test from 'node:test';
import assert from 'node:assert/strict';
import { readJson, ApiError } from '../lib/api.ts';

test('JSON transport reads successful response', async () => {
  const value = await readJson<{ status: string }>(Response.json({ status: 'ok' }));
  assert.equal(value.status, 'ok');
});
test('explicit API failures preserve status and code', async () => {
  await assert.rejects(readJson(Response.json({ detail: { code: 'DATABASE_UNAVAILABLE', message: 'database unavailable' } }, { status: 503 })), error => error instanceof ApiError && error.status === 503 && error.code === 'DATABASE_UNAVAILABLE');
});
