export type AudioChunk = {
  id: string; ownerId: string; sessionId: string; captureId: string; sequence: number;
  startMs: number; endMs: number; blob: Blob; mimeType: string;
  uploaded: boolean; uploadedAt: number | null;
};
export type CaptureMetadata = { scope: string[]; captureId: string; state: 'starting' | 'recording' | 'stopped' | 'interrupted'; updatedAt: number };
const databaseName = 'lecture-audio-backup';

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(databaseName, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      db.createObjectStore('chunks', { keyPath: 'id' }).createIndex('scope', ['ownerId', 'sessionId']);
      db.createObjectStore('captures', { keyPath: 'scope' });
    };
    request.onsuccess = () => { request.result.onversionchange = () => request.result.close(); resolve(request.result); };
    request.onerror = () => reject(request.error ?? new Error('로컬 음성 저장소를 열 수 없습니다.'));
    request.onblocked = () => reject(new Error('다른 탭의 음성 저장소를 닫고 다시 시도해 주세요.'));
  });
}

async function transaction<T>(name: string, mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(name, mode);
    const request = action(tx.objectStore(name));
    tx.oncomplete = () => { db.close(); resolve(request.result); };
    tx.onerror = tx.onabort = () => { db.close(); reject(tx.error ?? request.error ?? new Error('로컬 음성 저장에 실패했습니다.')); };
  });
}

export async function saveChunk(chunk: AudioChunk) { await transaction('chunks', 'readwrite', store => store.put(chunk)); }
export async function chunksFor(ownerId: string, sessionId: string): Promise<AudioChunk[]> {
  const rows = await transaction<AudioChunk[]>('chunks', 'readonly', store => store.index('scope').getAll([ownerId, sessionId]));
  return rows.sort((left, right) => left.sequence - right.sequence);
}
export async function markUploaded(chunk: AudioChunk) { await saveChunk({ ...chunk, uploaded: true, uploadedAt: Date.now() }); }
export async function saveCapture(metadata: CaptureMetadata) { await transaction('captures', 'readwrite', store => store.put(metadata)); }
export async function captureFor(ownerId: string, sessionId: string): Promise<CaptureMetadata | undefined> {
  return transaction('captures', 'readonly', store => store.get([ownerId, sessionId]));
}

export async function deleteSessionBackup(ownerId: string, sessionId: string): Promise<void> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(['chunks', 'captures'], 'readwrite');
    tx.objectStore('captures').delete([ownerId, sessionId]);
    const chunks = tx.objectStore('chunks');
    const request = chunks.index('scope').openKeyCursor(IDBKeyRange.only([ownerId, sessionId]));
    request.onsuccess = () => { const cursor = request.result; if (cursor) { chunks.delete(cursor.primaryKey); cursor.continue(); } };
    tx.oncomplete = () => { db.close(); resolve(); };
    tx.onerror = tx.onabort = () => { db.close(); reject(tx.error ?? new Error('로컬 음성 백업 삭제에 실패했습니다.')); };
  });
}

export function chunkForm(chunk: AudioChunk): FormData {
  const form = new FormData();
  form.set('chunk_id', chunk.id); form.set('capture_id', chunk.captureId);
  form.set('sequence', String(chunk.sequence)); form.set('start_ms', String(chunk.startMs)); form.set('end_ms', String(chunk.endMs));
  form.set('file', chunk.blob, 'chunk-' + chunk.sequence);
  return form;
}

export function pendingCount(chunks: Pick<AudioChunk, 'uploaded'>[]): number {
  return chunks.filter(chunk => !chunk.uploaded).length;
}
