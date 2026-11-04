import type { Performer } from "./project";
import { wrap } from "./music";
import { loopBeats } from "./timing";

export function closedPath(p: Performer): Performer["path"] {
  if (!p.path.length) return [];
  const last = p.path[p.path.length - 1].beat;
  const scale = last > loopBeats - 4 ? (loopBeats - 4) / last : 1;
  return [
    { beat: 0, ...p.position },
    ...p.path
      .filter((k) => k.beat > 0)
      .map((k) => ({ ...k, beat: k.beat * scale })),
    { beat: loopBeats, ...p.position },
  ];
}

export function pathPosition(
  p: Performer,
  beat: number
): { x: number; y: number } {
  const knots = closedPath(p);
  if (!knots.length) return { ...p.position };
  const b = wrap(beat, loopBeats);
  const end = knots.findIndex((k) => k.beat > b);
  const index = Math.max(0, end - 1);
  const a = knots[index],
    z = knots[index + 1];
  const duration = z.beat - a.beat;
  const t = (b - a.beat) / duration;
  const tangent = (i: number, axis: "x" | "y"): number =>
    i === 0 || i === knots.length - 1
      ? 0
      : (knots[i + 1][axis] - knots[i - 1][axis]) /
        (knots[i + 1].beat - knots[i - 1].beat);
  const component = (axis: "x" | "y"): number =>
    (2 * t ** 3 - 3 * t ** 2 + 1) * a[axis] +
    (t ** 3 - 2 * t ** 2 + t) * duration * tangent(index, axis) +
    (-2 * t ** 3 + 3 * t ** 2) * z[axis] +
    (t ** 3 - t ** 2) * duration * tangent(index + 1, axis);
  return { x: component("x"), y: component("y") };
}

export function poseAtBeat(
  p: Performer,
  beat: number,
  reduced = false,
  notePulse = 0
): {
  x: number;
  y: number;
  rotation: number;
  sx: number;
  sy: number;
  elevation: number;
  shadow: number;
} {
  const b = wrap(beat, loopBeats);
  const { x, y } = pathPosition(p, b);
  const phase = b * Math.PI * 2;
  const hop = reduced ? 0 : notePulse * (p.motion === "hop" ? 6 : 4);
  return {
    x,
    y,
    elevation: hop,
    rotation: reduced
      ? 0
      : p.motion === "roll"
      ? (b * Math.PI) / 2
      : p.motion === "dance"
      ? Math.sin(phase / 2) * 0.018 + notePulse * 0.02
      : notePulse * 0.015,
    sx: reduced ? 1 : 1 + notePulse * 0.01,
    sy: reduced ? 1 : 1 - notePulse * 0.014,
    shadow: 1 - hop / 90,
  };
}
export function stageGain(p: Performer, beat: number): number {
  const pose = poseAtBeat(p, beat);
  const radius = Math.hypot(pose.x / 335, pose.y / 185);
  return p.exit === "continue"
    ? 1
    : p.exit === "mute"
    ? Number(radius <= 1.1)
    : Math.max(0, Math.min(1, (1.25 - radius) / 0.2));
}
