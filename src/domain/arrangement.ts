import type { Project, SongSection } from "./project";
import { loopBars, loopBeats } from "./timing";

export function sectionAt(project: Project, beat: number): SongSection {
  const bar = (((beat % loopBeats) + loopBeats) % loopBeats) / 4;
  return project.sections.find(
    (section) => bar >= section.startBar && bar < section.endBar
  )!;
}

export function sectionGain(
  project: Project,
  performerId: string,
  beat: number
): number {
  const section = sectionAt(project, beat);
  if (section.mutedIds.includes(performerId)) return 0;
  return section.kind === "solo" && section.leadId !== performerId ? 0.55 : 1;
}

export function sectionMixKey(project: Project): string {
  return JSON.stringify(
    project.sections.map((section) => [
      section.startBar,
      section.endBar,
      section.kind,
      section.leadId,
      [...section.mutedIds].sort(),
    ])
  );
}

/** The parts of the arrangement that bars depend on, leaving out who is on stage. */
export function sectionShapeKey(project: Project): string {
  return JSON.stringify(
    project.sections.map((section) => [
      section.startBar,
      section.endBar,
      section.kind,
      section.leadId,
    ])
  );
}

export function setPart(
  project: Project,
  sectionId: string,
  performerId: string,
  present: boolean
): void {
  const section = project.sections.find((s) => s.id === sectionId);
  if (!section || !project.performers.some((p) => p.id === performerId))
    throw new Error("Choose a section and character.");
  const others = section.mutedIds.filter((id) => id !== performerId);
  section.mutedIds = present ? others : [...others, performerId];
}

export function setSectionKind(
  project: Project,
  id: string,
  kind: SongSection["kind"],
  leadId?: string
): void {
  const section = project.sections.find((section) => section.id === id);
  if (!section) throw new Error("That section no longer exists.");
  if (kind === "solo" && !project.performers.some((p) => p.id === leadId))
    throw new Error("Choose a character for the solo.");
  if (section.kind !== kind)
    section.label =
      kind === "bridge" ? "Bridge" : kind === "solo" ? "Solo" : "Groove";
  const wasSolo = section.kind === "solo";
  section.kind = kind;
  section.leadId = kind === "solo" ? leadId! : null;
  // A solo decides who is on stage. Otherwise changing the feel keeps who sits out.
  if (kind === "solo")
    section.mutedIds = project.performers
      .filter((p) => p.id !== leadId)
      .map((p) => p.id);
  else if (wasSolo) section.mutedIds = [];
}

export function splitSection(
  project: Project,
  id: string,
  bar: number
): string {
  const index = project.sections.findIndex((section) => section.id === id);
  const section = project.sections[index];
  if (
    !section ||
    !Number.isInteger(bar) ||
    bar <= section.startBar ||
    bar >= section.endBar
  )
    throw new Error("Place the playhead inside this section to split it.");
  const next = {
    ...structuredClone(section),
    id: crypto.randomUUID(),
    startBar: bar,
    label: `${section.label} II`.slice(0, 48),
  };
  section.endBar = bar;
  project.sections.splice(index + 1, 0, next);
  return next.id;
}

export function resizeSection(
  project: Project,
  id: string,
  endBar: number
): void {
  const index = project.sections.findIndex((section) => section.id === id);
  const section = project.sections[index],
    next = project.sections[index + 1];
  if (
    !section ||
    !next ||
    !Number.isInteger(endBar) ||
    endBar <= section.startBar ||
    endBar >= next.endBar
  )
    throw new Error("Keep at least one bar in each neighboring section.");
  section.endBar = endBar;
  next.startBar = endBar;
}

export function joinNext(project: Project, id: string): void {
  const index = project.sections.findIndex((section) => section.id === id);
  const section = project.sections[index],
    next = project.sections[index + 1];
  if (!section || !next)
    throw new Error("There is no following section to join.");
  section.endBar = next.endBar;
  project.sections.splice(index + 1, 1);
}

export function togglePart(
  project: Project,
  sectionId: string,
  performerId: string
): void {
  const section = project.sections.find((s) => s.id === sectionId);
  if (!section || !project.performers.some((p) => p.id === performerId))
    throw new Error("Choose a section and character.");
  section.mutedIds = section.mutedIds.includes(performerId)
    ? section.mutedIds.filter((id) => id !== performerId)
    : [...section.mutedIds, performerId];
}

export const songBars = loopBars;
