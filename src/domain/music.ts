import type { Performer, Project } from "./project";
import { loopSteps } from "./timing";
import { sectionAt, sectionGain } from "./arrangement";
export { loopBeats, loopBars, loopSteps } from "./timing";

export interface NoteEvent {
  step: number;
  performerId: string;
  velocity: number;
}
export const wrap = (n: number, length = loopSteps): number =>
  ((n % length) + length) % length;
export function compileEvents(project: Project): NoteEvent[] {
  const solo = project.performers.some((p) => p.solo);
  return project.performers
    .flatMap((p) => {
      if (p.mute || (solo && !p.solo)) return [];
      const steps = p.mode === "repeat_hits" ? p.steps : p.steps.slice(0, 1);
      const counts = new Map<string, number>();
      return [...new Set(steps)].flatMap((step) => {
        const section = sectionAt(project, step / 4);
        const index = counts.get(section.id) ?? 0;
        counts.set(section.id, index + 1);
        if (
          (sectionGain(project, p.id, step / 4) === 0 &&
            p.mode !== "continuous_loop") ||
          (section.kind === "bridge" && index % 2 === 1)
        )
          return [];
        return [
          {
            step,
            performerId: p.id,
            velocity:
              (step % 4 === 0 ? 1 : 0.78) *
              (section.kind === "bridge" ? 0.82 : 1),
          },
        ];
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
