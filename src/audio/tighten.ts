import { encodeWav } from "./wav";

/** Quieter than this share of the loudest moment, before the sound, is lead-in. */
const ONSET_SHARE = 0.06;
/** Quieter than this share of the loudest moment, after the sound, is the room. */
const TAIL_SHARE = 0.01;
/** Kept before the first loud moment, so the attack is not clipped. */
const PRE_ROLL_S = 0.005;
/** Kept after the last audible moment, so the sound dies away rather than stops. */
const TAIL_S = 0.03;
const FADE_IN_S = 0.002;
const FADE_OUT_S = 0.02;
/** Peaks this loud, like the base band's, sit well with the others without clipping. */
const TARGET_PEAK = 0.89;
/** A quiet recording is brought up, but not so far that its hiss becomes a sound. */
const MAX_BOOST = 8;

export interface Bounds {
  startS: number;
  endS: number;
  peak: number;
}

/**
 * Where a recording's sound really starts and stops. A clip is trimmed by hand around a few
 * seconds of video, so it usually starts with a little silence: left in, every hit would land
 * late. The quiet after the sound would also keep it ringing on top of its next hit.
 */
export function tightBounds(
  channels: readonly Float32Array[],
  sampleRate: number
): Bounds {
  const length = channels[0]?.length ?? 0;
  const loudness = (index: number): number => {
    let loudest = 0;
    for (const channel of channels)
      loudest = Math.max(loudest, Math.abs(channel[index]));
    return loudest;
  };
  let peak = 0;
  for (let index = 0; index < length; index++)
    peak = Math.max(peak, loudness(index));
  const whole = { startS: 0, endS: length / sampleRate, peak };
  if (!(peak > 1e-4)) return whole;
  let first = 0;
  while (first < length && loudness(first) < peak * ONSET_SHARE) first++;
  let last = length - 1;
  while (last > first && loudness(last) < peak * TAIL_SHARE) last--;
  const start = Math.max(0, first - Math.round(PRE_ROLL_S * sampleRate));
  const end = Math.min(length, last + 1 + Math.round(TAIL_S * sampleRate));
  return { startS: start / sampleRate, endS: end / sampleRate, peak };
}

export function boostFor(peak: number): number {
  return peak > 1e-4 ? Math.min(MAX_BOOST, TARGET_PEAK / peak) : 1;
}

export interface Tightened {
  blob: Blob;
  /** Seconds of sound kept, when it could be read. */
  lengthS?: number;
  /** Seconds of quiet taken off the front. */
  leadS: number;
}

/** The sound with its quiet ends trimmed and its level evened out, as a WAV. */
export async function tighten(blob: Blob): Promise<Tightened> {
  try {
    const decoded = await new OfflineAudioContext(1, 1, 44100).decodeAudioData(
      await blob.arrayBuffer()
    );
    const rate = decoded.sampleRate;
    const channels = Array.from({ length: decoded.numberOfChannels }, (_, i) =>
      decoded.getChannelData(i)
    );
    const { startS, endS, peak } = tightBounds(channels, rate);
    const start = Math.round(startS * rate);
    const length = Math.max(1, Math.round(endS * rate) - start);
    const gain = boostFor(peak);
    const fadeIn = Math.round(FADE_IN_S * rate);
    const fadeOut = Math.min(Math.round(FADE_OUT_S * rate), length);
    const out = new AudioBuffer({
      length,
      numberOfChannels: channels.length,
      sampleRate: rate,
    });
    channels.forEach((channel, c) => {
      const target = out.getChannelData(c);
      for (let i = 0; i < length; i++) {
        const shape = Math.min(1, (i + 1) / fadeIn, (length - i) / fadeOut);
        target[i] = channel[start + i] * gain * shape;
      }
    });
    return { blob: encodeWav(out), lengthS: length / rate, leadS: startS };
  } catch {
    // An undecodable sound still plays as it is; it is just not trimmed.
    return { blob, leadS: 0 };
  }
}
