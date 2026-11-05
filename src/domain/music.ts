import type { Asset, Performer, Project } from "./project";
import { cardBarsOf, loopSteps, stepsPerBar, type CardBars } from "./timing";
import { sectionAt, sectionGain } from "./arrangement";
export { loopBeats, loopBars, loopSteps } from "./timing";

export interface NoteEvent {
  step: number;
  performerId: string;
  velocity: number;
  /** Steps until this note is cut short, for sounds that must never pile up on themselves. */
  hold?: number;
}
export const wrap = (n: number, length = loopSteps): number =>
  ((n % length) + length) % length;

/** How many bars a performer's rhythm card holds. */
export function cardBarsFor(
  p: Pick<Performer, "steps" | "cardBars">
): CardBars {
  return (p.cardBars as CardBars | undefined) ?? cardBarsOf(p.steps);
}

/** The first hole of each card: where a phrase starts again. */
export function phraseStarts(p: Performer): number[] {
  const period = cardBarsFor(p) * stepsPerBar;
  return p.steps.filter(
    (step, i) =>
      i === 0 ||
      Math.floor(p.steps[i - 1] / period) !== Math.floor(step / period)
  );
}

/** The step where the card holding this step ends. */
export function cardEnd(p: Performer, step: number): number {
  const period = cardBarsFor(p) * stepsPerBar;
  return (Math.floor(step / period) + 1) * period;
}

/**
 * Your own recordings are often longer than the gap between their hits: a voice, a phrase, a
 * few beats in a row. Like a sampler pad, each new hit cuts the last one off rather than piling
 * on top of it. The base band's sounds are short and ring out as they always have.
 */
export function cutsItselfOff(p: Performer, asset: Asset | undefined): boolean {
  return (
    p.mode === "phrase" ||
    (p.mode === "repeat_hits" &&
      asset !== undefined &&
      asset.provenance !== "base band" &&
      asset.provenance !== "synthesized demo")
  );
}

export function compileEvents(project: Project): NoteEvent[] {
  const solo = project.performers.some((p) => p.solo);
  return project.performers
    .flatMap((p) => {
      if (p.mute || (solo && !p.solo)) return [];
      const steps =
        p.mode === "repeat_hits"
          ? p.steps
          : p.mode === "phrase"
          ? phraseStarts(p)
          : p.steps.slice(0, 1);
      const counts = new Map<string, number>();
      const events = [...new Set(steps)].flatMap((step) => {
        const section = sectionAt(project, step / 4);
        const index = counts.get(section.id) ?? 0;
        counts.set(section.id, index + 1);
        if (
          (sectionGain(project, p.id, step / 4) === 0 &&
            p.mode !== "continuous_loop") ||
          (section.kind === "bridge" && index % 2 === 1 && p.mode !== "phrase")
        )
          return [];
        return [
          {
            step,
            performerId: p.id,
            velocity:
              (step % 4 === 0 ? 1 : 0.78) *
              (section.kind === "bridge" ? 0.82 : 1),
          } as NoteEvent,
        ];
      });
      if (
        !cutsItselfOff(
          p,
          project.assets.find((a) => a.id === p.assetId)
        )
      )
        return events;
      // Each note holds until the next one sounds (round the end of the song), and a phrase
      // never runs past the end of its card.
      return events.map((event, i) => {
        const next = events[i + 1]?.step ?? events[0].step + loopSteps;
        const until =
          p.mode === "phrase" ? Math.min(next, cardEnd(p, event.step)) : next;
        return { ...event, hold: until - event.step };
      });
    })
    .sort(
      (a, b) => a.step - b.step || a.performerId.localeCompare(b.performerId)
    );
}
export function stepSeconds(step: number, bpm: number, swing: number): number {
  return ((step + (step % 2 ? swing * 0.5 : 0)) * 15) / bpm;
}
export function transformSteps(
  steps: number[],
  kind: "offbeat_echo" | "mirror" | "halve" | "fill"
): number[] {
  const transformed =
    kind === "offbeat_echo"
      ? steps.map((s) => wrap(s + 2))
      : kind === "mirror"
      ? steps.map((s) => loopSteps - 1 - s)
      : kind === "halve"
      ? steps.filter((_, i) => i % 2 === 0)
      : [...steps, loopSteps - 6, loopSteps - 3, loopSteps - 1];
  return [...new Set(transformed)].sort((a, b) => a - b);
}
export function clonePerformer(p: Performer, count: number): Performer {
  return {
    ...structuredClone(p),
    id: crypto.randomUUID(),
    name: `${p.name.replace(/ · \d+$/, "")} · ${count + 1}`,
    position: {
      x: Math.max(-450, Math.min(450, p.position.x + 70)),
      y: Math.max(-250, Math.min(250, p.position.y + 35)),
    },
    steps: transformSteps(p.steps, count % 2 ? "mirror" : "offbeat_echo"),
    gainDb: Math.max(-30, p.gainDb - 4),
    rate: Math.min(3, Math.max(0.25, p.rate * (count % 2 ? 0.75 : 1.25))),
    path: [],
    // A clone finds its own spot rather than standing exactly on the original's.
    wing: undefined,
  };
}
