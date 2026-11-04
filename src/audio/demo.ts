/** Original deterministic synthesis. These are demo sounds, never field recordings. */
export function createDemoBuffer(
  context: BaseAudioContext,
  kind: number
): AudioBuffer {
  const duration = [0.65, 0.32, 1.15, 0.16][kind];
  const rate = context.sampleRate,
    buffer = context.createBuffer(1, Math.ceil(duration * rate), rate);
  const data = buffer.getChannelData(0);
  let random = 491 + kind;
  for (let i = 0; i < data.length; i++) {
    const t = i / rate;
    random = (random * 16807) % 2147483647;
    const noise = random / 1073741824 - 1;
    const attack = Math.min(1, t / 0.003),
      release = Math.min(1, (duration - t) / 0.02);
    const sound =
      kind === 0
        ? Math.sin(
            2 * Math.PI * (49 * t + (8 * (1 - Math.exp(-t * 45))) / 45)
          ) *
            Math.exp(-t * 8) +
          noise * Math.exp(-t * 100) * 0.28
        : kind === 1
        ? noise * Math.exp(-t * 19) * 0.65 +
          Math.sin(t * 2 * Math.PI * 172) * Math.exp(-t * 28) * 0.35
        : kind === 2
        ? (Math.sin(t * 2 * Math.PI * 330) +
            Math.sin(t * 2 * Math.PI * 660) * 0.4 +
            Math.sin(t * 2 * Math.PI * 994) * 0.2) *
          Math.exp(-t * 5) *
          0.42
        : (noise * 0.6 + Math.sin(t * 2 * Math.PI * 7421) * 0.22) *
          Math.exp(-t * 42);
    data[i] = sound * attack * release * 0.8;
  }
  return buffer;
}
