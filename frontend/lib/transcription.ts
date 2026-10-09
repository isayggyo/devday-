import { readJson } from './api.ts';
export type TranscriptSegment = { id: string; sessionId: string; sequence: number; startMs: number; endMs: number; text: string; revision: number; committedAt: string };
export type TranscriptionUpdate = { status: string; message: string; partial: string; segments: TranscriptSegment[] };

export class TranscriptionController {
  sessionId: string; update: (value: TranscriptionUpdate) => void;
  segments: TranscriptSegment[] = []; partial = ''; status = 'idle'; message = '';
  context: AudioContext | null = null; node: AudioWorkletNode | null = null; socket: WebSocket | null = null;
  queue: { data: ArrayBuffer; end: number }[] = []; after = 0; offset = 0; ready = false; finishing = false;
  timer: ReturnType<typeof setTimeout> | null = null; attempts = 0; finalized: (() => void) | null = null; flushed: (() => void) | null = null;
  constructor(sessionId: string, update: (value: TranscriptionUpdate) => void) { this.sessionId = sessionId; this.update = update; }
  report() { this.update({ status: this.status, message: this.message, partial: this.partial, segments: [...this.segments].sort((a, b) => a.sequence - b.sequence) }); }
  async load() { this.segments = await readJson<TranscriptSegment[]>(await fetch('/api/sessions/' + this.sessionId + '/transcript-segments')); this.after = Math.max(0, ...this.segments.map(segment => segment.endMs)); this.report(); }
  async start(stream: MediaStream, started: number) {
    this.offset = Math.round(performance.now() - started); this.finishing = false;
    this.context = new AudioContext({ sampleRate: 24000 });
    await this.context.audioWorklet.addModule('/pcm-worklet.js');
    if (this.context.sampleRate !== 24000) throw new Error('24kHz 오디오 입력을 지원하지 않습니다. 원본 녹음은 유지됩니다.');
    this.node = new AudioWorkletNode(this.context, 'lecture-pcm');
    const source = this.context.createMediaStreamSource(stream), mute = this.context.createGain(); mute.gain.value = 0;
    source.connect(this.node); this.node.connect(mute); mute.connect(this.context.destination);
    this.node.port.onmessage = event => {
      if (event.data.flushed) { this.flushed?.(); return; }
      const { pcm, start, end } = event.data;
      const first = this.offset + Math.round(start / 24), last = this.offset + Math.round(end / 24);
      const data = new ArrayBuffer(8 + pcm.byteLength), header = new DataView(data);
      header.setUint32(0, first, true); header.setUint32(4, last, true); new Uint8Array(data, 8).set(new Uint8Array(pcm));
      this.queue.push({ data, end: last });
      if (this.queue.length > 240) { this.queue.shift(); this.message = '전사 연결 지연으로 일부 자막 구간이 누락될 수 있습니다. 원본 음성은 보관됩니다.'; this.report(); }
      if (this.ready && this.socket?.readyState === WebSocket.OPEN) this.socket.send(data);
    };
    await this.context.resume(); await this.connect();
  }
  async connect() {
    if (this.finishing) return;
    this.status = 'connecting'; this.ready = false; this.report();
    try {
      const ticket = await readJson<{ token: string; path: string }>(await fetch('/api/sessions/' + this.sessionId + '/transcription-token', { method: 'POST', signal: AbortSignal.timeout(10000) }));
      const base = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://127.0.0.1:8000';
      const url = new URL(ticket.path, base); url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'; url.searchParams.set('token', ticket.token);
      const socket = new WebSocket(url); this.socket = socket;
      socket.onmessage = event => {
        const payload = JSON.parse(event.data);
        if (payload.type === 'stt.ready') {
          this.ready = true; this.attempts = 0; this.status = 'connected'; this.after = Math.max(this.after, payload.afterMs);
          for (const packet of this.queue.filter(packet => packet.end > this.after)) socket.send(packet.data);
        }
        if (payload.type === 'transcript.partial') this.partial = payload.text;
        if (payload.type === 'transcript.final') {
          this.segments = [...this.segments.filter(segment => segment.id !== payload.segment.id), payload.segment]; this.partial = ''; this.after = Math.max(this.after, payload.segment.endMs);
          this.queue = this.queue.filter(packet => packet.end > this.after);
        }
        if (payload.type === 'stt.error' || payload.type === 'stt.warning') { this.status = 'error'; this.message = payload.message; }
        if (payload.type === 'stt.finalized') { this.status = 'finalized'; this.finalized?.(); }
        this.report();
      };
      socket.onclose = () => { this.ready = false; if (!this.finishing) this.reconnect(); };
      socket.onerror = () => { this.message = '전사 연결 오류입니다. 원본 녹음은 계속됩니다.'; this.report(); };
    } catch (error) { this.status = 'error'; this.message = error instanceof Error ? error.message : '전사 연결 실패'; this.report(); this.reconnect(); }
  }
  reconnect() {
    if (this.finishing || this.timer) return;
    this.status = 'reconnecting'; this.report();
    if (++this.attempts > 5) { this.status = 'error'; this.message = '전사 재연결에 실패했습니다. 연결 상태를 확인하고 다시 연결해 주세요.'; this.report(); return; }
    this.timer = setTimeout(() => { this.timer = null; void this.connect(); }, Math.min(5000, 500 * 2 ** this.attempts));
  }
  retry() { this.attempts = 0; if (this.timer) clearTimeout(this.timer); this.timer = null; if (this.socket) { this.socket.onclose = null; this.socket.close(); } void this.connect(); }
  async finish() {
    this.finishing = true; if (this.timer) clearTimeout(this.timer);
    if (this.node) await Promise.race([new Promise<void>(resolve => { this.flushed = resolve; this.node?.port.postMessage('flush'); }), new Promise<void>(resolve => setTimeout(resolve, 500))]);
    if (this.ready && this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: 'finish' }));
      await Promise.race([new Promise<void>(resolve => { this.finalized = resolve; }), new Promise<void>(resolve => setTimeout(resolve, 22000))]);
    }
    this.socket?.close(); this.node?.disconnect(); await this.context?.close(); this.ready = false;
    if (this.status !== 'finalized') { this.status = 'interrupted'; this.message = '전사를 모두 확정하지 못했습니다. 저장된 자막과 원본 녹음을 확인해 주세요.'; }
    this.report();
  }
}
