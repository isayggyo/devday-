import { readJson } from './api.ts';
import { saveCapture, saveChunk, chunksFor, markUploaded, chunkForm, type AudioChunk } from './audio-backup.ts';
import type { LectureSession } from '../components/session-manager';

export type RecordingState = 'idle' | 'requesting' | 'recording' | 'stopping' | 'stopped' | 'interrupted';
export type CaptureUpdate = { state: RecordingState; pending: number; bytes: number; message: string };

export function microphoneMessage(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') return '마이크 권한이 거부됐습니다. 브라우저 사이트 설정에서 허용한 뒤 다시 시도해 주세요.';
    if (error.name === 'NotFoundError') return '사용 가능한 마이크가 없습니다. 장치를 연결해 주세요.';
    if (error.name === 'NotReadableError') return '마이크를 사용할 수 없습니다. 다른 앱의 마이크 사용을 확인해 주세요.';
    if (error.name === 'OverconstrainedError') return '선택한 마이크가 연결되지 않았습니다. 다른 장치를 선택해 주세요.';
  }
  return error instanceof Error ? error.message : '녹음을 시작할 수 없습니다.';
}

export class AudioController {
  session: LectureSession;
  onUpdate: (value: CaptureUpdate) => void;
  onSession: (value: LectureSession) => void;
  stream: MediaStream | null = null;
  recorder: MediaRecorder | null = null;
  state: RecordingState = 'idle';
  captureId = '';
  sequence = 0;
  lastEnd = 0;
  started = 0;
  bytes = 0;
  message = '';
  saveQueue: Promise<void> = Promise.resolve();
  uploading: Promise<void> | null = null;
  timer: ReturnType<typeof setInterval> | null = null;
  lastTick = Date.now();
  stopped: Promise<void> | null = null;
  unsaved: AudioChunk[] = [];
  onStream: ((stream: MediaStream | null) => void) | null = null;
  alive = true;

  constructor(session: LectureSession, update: (value: CaptureUpdate) => void, changed: (value: LectureSession) => void) {
    this.session = session; this.onUpdate = update; this.onSession = changed;
  }
  get base() { return '/api/sessions/' + this.session.id; }

  async report() {
    const chunks = await chunksFor(this.session.userId, this.session.id).catch(() => []);
    if (this.alive) this.onUpdate({ state: this.state, pending: chunks.filter(chunk => !chunk.uploaded).length + this.unsaved.length, bytes: [...chunks, ...this.unsaved].reduce((total, chunk) => total + chunk.blob.size, 0), message: this.message });
  }

  async refresh() {
    if (this.session.status === 'recording' && !this.recorder) {
      this.state = 'interrupted';
      this.message = '이전 녹음이 중단되었습니다. 미전송 청크를 재전송한 뒤 녹음 상태를 종료해 주세요.';
    } else if (this.session.status === 'finalizing') this.state = 'stopped';
    await this.report();
  }

  async start(deviceId: string) {
    if (this.state === 'recording' || this.state === 'requesting') return;
    this.state = 'requesting'; this.message = ''; await this.report();
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') throw new Error('이 브라우저에서 마이크 녹음을 사용할 수 없습니다. HTTPS 또는 localhost에서 열어 주세요.');
      this.captureId = crypto.randomUUID();
      await saveCapture({ scope: [this.session.userId, this.session.id], captureId: this.captureId, state: 'starting', updatedAt: Date.now() });
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: deviceId ? { deviceId: { exact: deviceId } } : true });
      const mimeType = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'].find(type => MediaRecorder.isTypeSupported(type));
      if (!mimeType) throw new Error('지원되는 음성 녹음 형식을 찾을 수 없습니다.');
      this.recorder = new MediaRecorder(this.stream, { mimeType });
      const session = await readJson<LectureSession>(await fetch(this.base + '/recording/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ captureId: this.captureId }), signal: AbortSignal.timeout(10000) }));
      this.session = session; this.onSession(session);
      this.recorder.addEventListener('dataavailable', event => this.chunk(event));
      this.recorder.addEventListener('error', () => { this.message = '녹음 장치 오류가 발생했습니다. 원본 백업을 확인해 주세요.'; void this.stop(true); });
      this.recorder.addEventListener('stop', () => { if (this.state === 'recording') void this.stop(true); });
      for (const track of this.stream.getTracks()) {
        track.addEventListener('ended', () => { this.message = '마이크 연결이 끊겼습니다. 저장된 청크는 유지됩니다.'; void this.stop(true); });
        track.addEventListener('mute', () => { this.message = '마이크 입력이 일시 중단됐습니다. 장치를 확인해 주세요.'; void this.report(); });
      }
      this.started = performance.now(); this.lastTick = Date.now();
      this.recorder.start(2000); this.state = 'recording';
      await saveCapture({ scope: [session.userId, session.id], captureId: this.captureId, state: 'recording', updatedAt: Date.now() });
      this.onStream?.(this.stream);
      this.timer = setInterval(() => {
        const now = Date.now();
        if (this.state === 'recording' && now - this.lastTick > 6000) { this.message = '절전 또는 녹음 지연을 감지했습니다. 녹음 상태와 원본을 확인해 주세요.'; void this.report(); }
        this.lastTick = now;
        void this.retry();
      }, 5000);
      await this.report();
    } catch (error) {
      this.message = microphoneMessage(error);
      if (this.session.status === 'recording') {
        await this.stop(true);
        return;
      }
      if (this.recorder?.state !== 'inactive') this.recorder?.stop();
      this.stream?.getTracks().forEach(track => track.stop());
      this.stream = null; this.recorder = null; this.state = 'idle';
      await this.report().catch(() => this.onUpdate({ state: 'idle', pending: 0, bytes: 0, message: this.message }));
    }
  }

  chunk(event: BlobEvent) {
    if (!event.data.size) return;
    const end = Math.max(this.lastEnd, Math.round(performance.now() - this.started));
    const chunk: AudioChunk = { id: crypto.randomUUID(), ownerId: this.session.userId, sessionId: this.session.id, captureId: this.captureId,
      sequence: this.sequence++, startMs: this.lastEnd, endMs: end, blob: event.data, mimeType: event.data.type || this.recorder?.mimeType || 'audio/webm', uploaded: false, uploadedAt: null };
    this.lastEnd = end; this.bytes += event.data.size;
    this.saveQueue = this.saveQueue.then(async () => {
      try { await saveChunk(chunk); }
      catch {
        this.unsaved.push(chunk); this.message = '로컬 저장 공간 오류로 녹음을 중단합니다. 임시 메모리 음성을 내려받아 보관해 주세요.';
        void this.stop(true);
      }
      await this.report().catch(() => {});
      void this.retry();
    });
  }

  async retry() {
    if (this.uploading) return this.uploading;
    this.uploading = (async () => {
      try {
        const chunks = await chunksFor(this.session.userId, this.session.id);
        for (const chunk of chunks.filter(chunk => !chunk.uploaded)) {
          const result = await readJson<{ id: string; byteLength: number }>(await fetch(this.base + '/audio/chunks', { method: 'POST', body: chunkForm(chunk), signal: AbortSignal.timeout(10000) }));
          if (result.id !== chunk.id || result.byteLength !== chunk.blob.size) throw new Error('서버 음성 저장 확인에 실패했습니다.');
          await markUploaded(chunk);
        }
        if (this.message.startsWith('음성 전송')) this.message = '';
      } catch (error) { this.message = '음성 전송 대기 중입니다. 로컬 백업을 유지합니다. ' + (error instanceof Error ? error.message : '네트워크를 확인해 주세요.'); }
      finally { this.uploading = null; await this.report().catch(() => {}); }
    })();
    return this.uploading;
  }

  async stop(interrupted = false): Promise<void> {
    if (this.stopped) return this.stopped;
    this.stopped = (async () => {
      this.state = 'stopping'; await this.report().catch(() => {});
      if (this.timer) clearInterval(this.timer); this.timer = null;
      if (this.recorder && this.recorder.state !== 'inactive') {
        const recorder = this.recorder;
        await new Promise<void>(resolve => { recorder.addEventListener('stop', () => resolve(), { once: true }); recorder.stop(); });
      }
      await this.saveQueue;
      this.stream?.getTracks().forEach(track => track.stop());
      this.stream = null; this.onStream?.(null);
      await this.retry();
      try {
        const session = await readJson<LectureSession>(await fetch(this.base + '/recording/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ captureId: this.captureId || undefined }), signal: AbortSignal.timeout(10000) }));
        this.session = session; if (this.alive) this.onSession(session);
        this.state = interrupted ? 'interrupted' : 'stopped';
      } catch (error) { this.state = 'interrupted'; this.message = '녹음은 중지됐지만 서버 상태를 갱신하지 못했습니다. 다시 중지해 주세요. ' + (error instanceof Error ? error.message : ''); }
      await saveCapture({ scope: [this.session.userId, this.session.id], captureId: this.captureId, state: interrupted ? 'interrupted' : 'stopped', updatedAt: Date.now() }).catch(() => {});
      await this.report().catch(() => {});
    })();
    try { await this.stopped; }
    finally { this.stopped = null; }
  }

  async download() {
    await this.saveQueue;
    const saved = await chunksFor(this.session.userId, this.session.id).catch(() => []);
    const chunks = [...saved, ...this.unsaved].sort((left, right) => left.sequence - right.sequence);
    if (!chunks.length) throw new Error('보관된 음성이 없습니다.');
    const blob = new Blob(chunks.map(chunk => chunk.blob), { type: chunks[0].mimeType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url; link.download = 'lecture-' + this.session.id + (blob.type.includes('mp4') ? '.m4a' : blob.type.includes('ogg') ? '.ogg' : '.webm'); link.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }

  dispose() { this.alive = false; if (this.timer) clearInterval(this.timer); if (this.stream) void this.stop(true); }
}
