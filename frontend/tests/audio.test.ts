import assert from 'node:assert/strict';
import test from 'node:test';
import { microphoneMessage } from '../lib/audio-controller.ts';
import { chunkForm, pendingCount, type AudioChunk } from '../lib/audio-backup.ts';

test('permission and device errors give distinct recovery actions', () => {
  assert.match(microphoneMessage(new DOMException('denied', 'NotAllowedError')), /권한/);
  assert.match(microphoneMessage(new DOMException('missing', 'NotFoundError')), /장치를 연결/);
  assert.match(microphoneMessage(new DOMException('busy', 'NotReadableError')), /다른 앱/);
  assert.match(microphoneMessage(new DOMException('gone', 'OverconstrainedError')), /다른 장치/);
});

test('upload serializes the same durable chunk identity and original blob', async () => {
  const chunk: AudioChunk = { id: 'chunk-id', ownerId: 'owner', sessionId: 'session', captureId: 'capture', sequence: 3, startMs: 2000, endMs: 4010,
    blob: new Blob(['unit serialization fixture'], { type: 'audio/webm' }), mimeType: 'audio/webm', uploaded: false, uploadedAt: null };
  const first = chunkForm(chunk), retry = chunkForm(chunk);
  for (const key of ['chunk_id', 'capture_id', 'sequence', 'start_ms', 'end_ms']) assert.equal(first.get(key), retry.get(key));
  assert.equal(first.get('chunk_id'), chunk.id);
  assert.equal(await (first.get('file') as File).text(), await chunk.blob.text());
  assert.equal(pendingCount([chunk, { ...chunk, uploaded: true }]), 1);
});
