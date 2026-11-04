export const loopBars = 16;
export const beatsPerBar = 4;
export const stepsPerBeat = 4;
export const loopBeats = loopBars * beatsPerBar;
export const loopSteps = loopBeats * stepsPerBeat;

export function pulseAtAge(age: number, duration: number): number {
  if (age <= 0 || age >= duration) return 0;
  const t = age / duration;
  return Math.sin(Math.PI * t) * (1 - t) * 1.7;
}
