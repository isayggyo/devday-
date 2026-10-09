class LecturePcm extends AudioWorkletProcessor {
  constructor() {
    super(); this.buffer = []; this.total = 0;
    this.port.onmessage = event => { if (event.data === 'flush') { this.flush(); this.port.postMessage({ flushed: true }); } };
  }
  flush() {
    if (!this.buffer.length) return;
    const pcm = new Int16Array(this.buffer); const start = this.total;
    this.total += pcm.length; this.buffer = [];
    this.port.postMessage({ pcm: pcm.buffer, start, end: this.total }, [pcm.buffer]);
  }
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel) for (const value of channel) this.buffer.push(Math.round(Math.max(-1, Math.min(1, value)) * 32767));
    if (this.buffer.length >= 2048) this.flush();
    return true;
  }
}
registerProcessor('lecture-pcm', LecturePcm);
