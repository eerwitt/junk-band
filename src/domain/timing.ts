export const loopBars = 32;
export const beatsPerBar = 4;
export const stepsPerBeat = 4;
export const stepsPerBar = beatsPerBar * stepsPerBeat;
export const loopBeats = loopBars * beatsPerBar;
export const loopSteps = loopBeats * stepsPerBeat;

/**
 * How long a rhythm card can be before it repeats, in bars. The last one is the whole song.
 * Each divides the song, so a card always comes round on the same bar.
 */
export const CARD_BARS = [1, 2, 4, 8, loopBars] as const;
export type CardBars = (typeof CARD_BARS)[number];

/** The shortest card that repeats into exactly these steps, for songs saved without one. */
export function cardBarsOf(steps: readonly number[]): CardBars {
  const held = new Set(steps);
  return (
    CARD_BARS.find((bars) => {
      const period = bars * stepsPerBar;
      return steps.every((step) => held.has((step + period) % loopSteps));
    }) ?? loopBars
  );
}

/** A card's holes repeated over the whole song. */
export function repeatCard(card: readonly number[], bars: number): number[] {
  const period = bars * stepsPerBar;
  const holes = [...new Set(card.filter((s) => s >= 0 && s < period))];
  return Array.from({ length: loopSteps / period }, (_, repeat) =>
    holes.map((step) => step + repeat * period)
  )
    .flat()
    .sort((a, b) => a - b);
}

export function pulseAtAge(age: number, duration: number): number {
  if (age <= 0 || age >= duration) return 0;
  const t = age / duration;
  return Math.sin(Math.PI * t) * (1 - t) * 1.7;
}
