/** A run of microphone samples, and the audio-clock frame its first sample was heard at. */
export interface Chunk {
  frame: number;
  data: Float32Array;
}

/**
 * Exactly `lengthS` seconds of what the microphone heard from `startS` on the audio clock. Any
 * moment the microphone missed stays silent, so the take is always the length asked for.
 */
export function cutTake(
  chunks: readonly Chunk[],
  sampleRate: number,
  startS: number,
  lengthS: number
): Float32Array {
  const out = new Float32Array(Math.round(lengthS * sampleRate));
  const first = Math.round(startS * sampleRate);
  for (const chunk of chunks) {
    const from = Math.max(0, first - chunk.frame);
    const to = Math.min(chunk.data.length, first + out.length - chunk.frame);
    for (let i = from; i < to; i++)
      out[chunk.frame + i - first] = chunk.data[i];
  }
  return out;
}

/**
 * The take turned round so it starts where its card starts. Recorded from the second bar of a
 * two-bar card, its first bar belongs at the card's second bar; played from the card's start,
 * it then sounds exactly where it was sung.
 */
export function rotate(samples: Float32Array, shift: number): Float32Array {
  const length = samples.length;
  const turn = ((shift % length) + length) % length;
  if (!turn) return samples.slice();
  const out = new Float32Array(length);
  out.set(samples.subarray(length - turn), 0);
  out.set(samples.subarray(0, length - turn), turn);
  return out;
}

/** Brings a take to a steady level and softens where it starts and stops, in place. */
export function finishTake(
  samples: Float32Array,
  sampleRate: number,
  gain: number
): Float32Array {
  const fade = Math.min(Math.round(0.004 * sampleRate), samples.length >> 1);
  for (let i = 0; i < samples.length; i++) {
    const edge = Math.min(1, (i + 1) / fade, (samples.length - i) / fade);
    samples[i] *= gain * edge;
  }
  return samples;
}

export function peakOf(samples: Float32Array): number {
  let peak = 0;
  for (const value of samples) peak = Math.max(peak, Math.abs(value));
  return peak;
}

const TAP = `class JunkTap extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) this.port.postMessage({ frame: currentFrame, data: channel.slice(0) });
    return true;
  }
}
registerProcessor("junk-tap", JunkTap);`;
const tapped = new WeakSet<BaseAudioContext>();

/** The microphone, heard on the band's own audio clock, so a take lines up with the song. */
export class Microphone {
  private chunks: Chunk[] = [];
  private listening = false;
  /** How loud it is right now, for the meter. */
  level = 0;

  private constructor(
    private readonly context: AudioContext,
    private readonly stream: MediaStream,
    private readonly source: MediaStreamAudioSourceNode,
    private readonly tap: AudioWorkletNode,
    private readonly sink: GainNode
  ) {
    tap.port.onmessage = (event: MessageEvent<Chunk>) => {
      let peak = 0;
      for (const value of event.data.data)
        peak = Math.max(peak, Math.abs(value));
      this.level = Math.max(peak, this.level * 0.9);
      if (this.listening) this.chunks.push(event.data);
    };
  }

  static async open(context: AudioContext): Promise<Microphone> {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        // Keeps the band, coming out of the speakers, out of the take as far as it can.
        echoCancellation: true,
        // Singing is not noise, and a level that drifts would make loops jump.
        noiseSuppression: false,
        autoGainControl: false,
      },
    });
    if (!tapped.has(context)) {
      const url = URL.createObjectURL(
        new Blob([TAP], { type: "text/javascript" })
      );
      try {
        await context.audioWorklet.addModule(url);
      } finally {
        URL.revokeObjectURL(url);
      }
      tapped.add(context);
    }
    const source = context.createMediaStreamSource(stream);
    const tap = new AudioWorkletNode(context, "junk-tap", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      channelCount: 1,
      channelCountMode: "explicit",
    });
    // Pulled by the speakers so it runs, but at no level, so you never hear yourself twice.
    const sink = context.createGain();
    sink.gain.value = 0;
    source.connect(tap);
    tap.connect(sink);
    sink.connect(context.destination);
    return new Microphone(context, stream, source, tap, sink);
  }

  /** Seconds between a sound reaching the microphone and its samples arriving here. */
  get inputLatency(): number {
    const settings = this.stream.getAudioTracks()[0]?.getSettings() as
      | (MediaTrackSettings & { latency?: number })
      | undefined;
    return settings?.latency ?? 0.01;
  }

  get sampleRate(): number {
    return this.context.sampleRate;
  }

  listen(): void {
    this.chunks = [];
    this.listening = true;
  }

  /** Everything heard since `listen`. */
  heard(): Chunk[] {
    this.listening = false;
    return this.chunks;
  }

  close(): void {
    this.listening = false;
    this.tap.port.onmessage = null;
    this.source.disconnect();
    this.tap.disconnect();
    this.sink.disconnect();
    for (const track of this.stream.getTracks()) track.stop();
  }
}
