import type { Performer } from "./project";
import { pathPosition } from "./motion";

/** C minor pentatonic, so no two characters can ever sound wrong together. */
const SCALE = [0, 3, 5, 7, 10];
export const NOTE_ROW_HEIGHT = 40;
const LOWEST_ROW = -5;
const HIGHEST_ROW = 5;

/** The note row for a height on the stage: 0 is the root, and up the stage is higher. */
export function noteRow(y: number): number {
  return Math.max(
    LOWEST_ROW,
    Math.min(HIGHEST_ROW, Math.round(-y / NOTE_ROW_HEIGHT) || 0)
  );
}

export function rowSemitones(row: number): number {
  const octaves = Math.floor(row / SCALE.length);
  return (
    octaves * 12 + SCALE[((row % SCALE.length) + SCALE.length) % SCALE.length]
  );
}

/** How fast to play a character's sample at this moment, including the note its height gives. */
export function playbackRate(p: Performer, beat: number): number {
  if (!p.tuned) return p.rate;
  const { y } = pathPosition(p, beat);
  return p.rate * Math.pow(2, rowSemitones(noteRow(y)) / 12);
}
