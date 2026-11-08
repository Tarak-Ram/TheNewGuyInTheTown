// AudioWorklet: turns microphone audio (context rate 16 kHz) into 16-bit PCM chunks.
class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = [];
    this.size = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    this.buffer.push(new Float32Array(channel));
    this.size += channel.length;
    if (this.size >= 640) {
      // about 40 ms at 16 kHz: small enough for quick turn-taking
      const out = new Int16Array(this.size);
      let i = 0;
      for (const part of this.buffer) {
        for (let j = 0; j < part.length; j++) {
          const s = Math.max(-1, Math.min(1, part[j]));
          out[i++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
      }
      this.port.postMessage(out.buffer, [out.buffer]);
      this.buffer = [];
      this.size = 0;
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCapture);
