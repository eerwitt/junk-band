import { z } from "zod";
import {
  CARD_BARS,
  loopBars,
  loopBeats,
  loopSteps,
  repeatCard,
  stepsPerBar,
} from "./timing";

export const motionSchema = z.enum(["still", "hop", "dance", "roll", "glide"]);
export type Motion = z.infer<typeof motionSchema>;
const pointSchema = z.object({
  x: z.number().finite(),
  y: z.number().finite(),
});
export const rigSchema = z
  .object({
    width: z.number().int().min(1).max(2048),
    height: z.number().int().min(1).max(2048),
    body: z.string().startsWith("blob:asset:"),
    parts: z
      .array(
        z.object({
          name: z.enum(["left_arm", "right_arm", "left_leg", "right_leg"]),
          sprite: z.string().startsWith("blob:asset:"),
          pivot: z.object({
            x: z.number().min(0).max(1),
            y: z.number().min(0).max(1),
          }),
          maxAngle: z.number().positive().max(0.5),
        })
      )
      .length(4),
  })
  .refine(
    (rig) => new Set(rig.parts.map((part) => part.name)).size === 4,
    "Rig must include each arm and leg once"
  );
export type Rig = z.infer<typeof rigSchema>;
export const assetSchema = z.object({
  id: z.string(),
  label: z.string().min(1).max(80),
  color: z.string(),
  sprite: z.string(),
  tile: z.number().int().min(0).max(3).optional(),
  audioId: z.string(),
  provenance: z.enum([
    "synthesized demo",
    "raw import",
    "mock candidate",
    "SAM Audio",
    "base band",
    "microphone",
  ]),
  sourceId: z.string().optional(),
  startS: z.number().optional(),
  endS: z.number().optional(),
  sourceSprite: z.string().optional(),
  visualProvenance: z.string().max(200).optional(),
  characterPrompt: z.string().max(300).optional(),
  rig: rigSchema.optional(),
  /** Seconds of sound once its quiet ends are trimmed, to tell a hit from a phrase. */
  lengthS: z.number().positive().max(60).optional(),
});
export type Asset = z.infer<typeof assetSchema>;
export const performerSchema = z.object({
  id: z.string(),
  assetId: z.string(),
  name: z.string().max(80),
  position: pointSchema,
  steps: z
    .array(
      z
        .number()
        .int()
        .min(0)
        .max(loopSteps - 1)
    )
    .max(loopSteps),
  gainDb: z.number().min(-36).max(0),
  pan: z.number().min(-1).max(1),
  rate: z.number().min(0.25).max(3),
  mute: z.boolean(),
  solo: z.boolean(),
  motion: motionSchema,
  exit: z.enum(["continue", "fade", "mute"]),
  /** Its height on the stage sets its note. */
  tuned: z.boolean().optional(),
  /** Where they wait outside the ring, once someone has put them there by hand. */
  wing: pointSchema.optional(),
  /**
   * Pattern hits sound at every hole. A phrase plays the whole sound from the first hole of each
   * card until the card ends. One shot plays once per song, and a sample loop loops freely.
   */
  mode: z.enum(["repeat_hits", "phrase", "one_shot", "continuous_loop"]),
  /** How many bars its rhythm card holds before repeating. Unset, it is read from the steps. */
  cardBars: z
    .number()
    .int()
    .refine((bars) => (CARD_BARS as readonly number[]).includes(bars), {
      message: "A rhythm card is 1, 2, 4 or 8 bars, or the whole song.",
    })
    .optional(),
  path: z
    .array(
      z.object({ beat: z.number().min(0).max(loopBeats), ...pointSchema.shape })
    )
    .max(128),
  pivot: z.object({ x: z.number().min(0).max(1), y: z.number().min(0).max(1) }),
});
export type Performer = z.infer<typeof performerSchema>;
export const sectionSchema = z.object({
  id: z.string().min(1).max(100),
  label: z.string().trim().min(1).max(48),
  startBar: z
    .number()
    .int()
    .min(0)
    .max(loopBars - 1),
  endBar: z.number().int().min(1).max(loopBars),
  kind: z.enum(["groove", "bridge", "solo"]),
  leadId: z.string().nullable(),
  mutedIds: z.array(z.string()).max(24),
});
export type SongSection = z.infer<typeof sectionSchema>;
const SECTION_BARS = 4;
/** Section length in songs from before the song was thirty-two bars. */
const OLD_SECTION_BARS = 2;
const SECTION_LABELS = [
  "Intro",
  "Verse",
  "Lift",
  "Chorus",
  "Break",
  "Verse two",
  "Build",
  "Finale",
];
/** Which of the band, by their place in it, stay on stage for each default section. */
const SECTION_CAST: readonly ((index: number, size: number) => boolean)[] = [
  (index) => index === 0,
  (index, size) => index < Math.ceil(size / 2),
  (index, size) => index < size - 1,
  () => true,
  (index, size) => index === size - 1,
  (index) => index > 0,
  (index) => index !== 1,
  () => true,
];
export function defaultSections(
  performerIds: string[] = [],
  bars: number = SECTION_BARS
): SongSection[] {
  return SECTION_LABELS.map((label, index) => ({
    id: `section-${index}`,
    label,
    startBar: index * bars,
    endBar: (index + 1) * bars,
    kind: "groove",
    leadId: null,
    mutedIds:
      performerIds.length < 2
        ? []
        : performerIds.filter(
            (_, place) => !SECTION_CAST[index](place, performerIds.length)
          ),
  }));
}
/** Four-section songs from before there were eight: each section becomes two of the same. */
function expandToEight(sections: unknown, performers: unknown): unknown {
  const parsed = z.array(sectionSchema).safeParse(sections);
  if (
    !parsed.success ||
    parsed.data.length !== 4 ||
    parsed.data.some((s, i) => s.startBar !== i * 4 || s.endBar !== i * 4 + 4)
  )
    return sections;
  const untouched = parsed.data.every(
    (s) => s.kind === "groove" && !s.mutedIds.length
  );
  if (untouched)
    return defaultSections(
      z
        .array(z.object({ id: z.string() }).loose())
        .catch([])
        .parse(performers)
        .map((p) => p.id),
      OLD_SECTION_BARS
    );
  return parsed.data.flatMap((s) => [
    { ...s, endBar: s.startBar + OLD_SECTION_BARS },
    {
      ...s,
      id: `${s.id}-b`,
      label: `${s.label} II`.slice(0, 48),
      startBar: s.startBar + OLD_SECTION_BARS,
    },
  ]);
}
const OLD_BEATS = loopBeats / 2;
const OLD_STEPS = loopSteps / 2;
const oldPerformerSchema = z
  .object({
    steps: z.array(z.number()),
    position: pointSchema,
    path: z.array(z.object({ beat: z.number(), ...pointSchema.shape })),
  })
  .loose();
const oldSectionSchema = z
  .object({ startBar: z.number(), endBar: z.number() })
  .loose();
/**
 * A path from a sixteen-bar song, walked twice. The old song closed its path at home on its last
 * beat, so that return home stays in the middle and the walk is as quick as it was.
 */
function walkTwice(
  path: z.infer<typeof oldPerformerSchema>["path"],
  home: { x: number; y: number }
): z.infer<typeof oldPerformerSchema>["path"] {
  const last = path.at(-1)?.beat ?? 0;
  const scale = last > OLD_BEATS - 4 ? (OLD_BEATS - 4) / last : 1;
  const knots = path
    .filter((k) => k.beat > 0)
    .map((k) => ({ ...k, beat: k.beat * scale }));
  if (!knots.length) return [];
  if (knots.length * 2 + 1 > 128)
    return knots.map((k) => ({ ...k, beat: k.beat * 2 }));
  return [
    ...knots,
    { beat: OLD_BEATS, ...home },
    ...knots.map((k) => ({ ...k, beat: k.beat + OLD_BEATS })),
  ];
}
/**
 * Sixteen-bar songs become thirty-two: every section lasts twice as long, and each pattern and
 * path plays through twice, so nothing sounds different bar to bar.
 */
function toThirtyTwoBars(value: object): object {
  const song = value as { performers?: unknown; sections?: unknown };
  const performers = Array.isArray(song.performers)
    ? song.performers.map((p: unknown) => {
        const old = oldPerformerSchema.safeParse(p);
        if (!old.success) return p;
        return {
          ...old.data,
          steps: [
            ...old.data.steps,
            ...old.data.steps.map((s) => s + OLD_STEPS),
          ],
          path: walkTwice(old.data.path, old.data.position),
        };
      })
    : song.performers;
  const sections = Array.isArray(song.sections)
    ? song.sections.map((s: unknown) => {
        const old = oldSectionSchema.safeParse(s);
        return old.success
          ? {
              ...old.data,
              startBar: old.data.startBar * 2,
              endBar: old.data.endBar * 2,
            }
          : s;
      })
    : song.sections;
  return {
    ...value,
    schemaVersion: 4,
    ...(song.performers === undefined ? {} : { performers }),
    ...(song.sections === undefined ? {} : { sections }),
  };
}
const projectDataSchema = z.object({
  schemaVersion: z.literal(4),
  /** Set once the base band has joined, so removing its members keeps them removed. */
  baseBandVersion: z.number().int().optional(),
  title: z.string().min(1).max(80),
  bpm: z.number().min(80).max(160),
  swing: z.number().min(0).max(0.6),
  seed: z.number().int(),
  assets: z.array(assetSchema).max(128),
  performers: z.array(performerSchema).max(24),
  sections: z
    .array(sectionSchema)
    .min(1)
    .max(16)
    .default(() => defaultSections()),
});
const legacyProjectSchema = projectDataSchema.extend({
  schemaVersion: z.literal(1),
  performers: z
    .array(
      performerSchema.extend({
        steps: z.array(z.number().int().min(0).max(63)).max(64),
        path: z
          .array(
            z.object({ beat: z.number().min(0).max(16), ...pointSchema.shape })
          )
          .max(128),
      })
    )
    .max(24),
});
/** Any older song as a sixteen-bar, eight-section one (schema 3), or unchanged if it is not one. */
function toSchemaThree(value: object): object {
  if (!("schemaVersion" in value)) return value;
  if (value.schemaVersion === 2) {
    const older = value as { sections?: unknown; performers?: unknown };
    return {
      ...value,
      schemaVersion: 3,
      ...(older.sections === undefined
        ? {}
        : { sections: expandToEight(older.sections, older.performers) }),
    };
  }
  if (value.schemaVersion !== 1) return value;
  const legacy = legacyProjectSchema.safeParse(value);
  if (!legacy.success) return value;
  const sections = (value as { sections?: unknown }).sections;
  const data: Partial<typeof legacy.data> = { ...legacy.data };
  delete data.sections;
  return {
    ...data,
    schemaVersion: 3,
    ...(sections === undefined
      ? {}
      : { sections: expandToEight(sections, legacy.data.performers) }),
    performers: legacy.data.performers.map((p) => ({
      ...p,
      steps: Array.from({ length: 4 }, (_, bar) =>
        p.steps.map((step) => step + bar * 64)
      ).flat(),
      path: p.path.map((point) => ({ ...point, beat: point.beat * 4 })),
      position:
        p.path[0]?.beat === 0 ? { x: p.path[0].x, y: p.path[0].y } : p.position,
    })),
  };
}
export const projectSchema = z.preprocess(
  (value) => {
    if (!value || typeof value !== "object") return value;
    const three = toSchemaThree(value);
    return "schemaVersion" in three && three.schemaVersion === 3
      ? toThirtyTwoBars(three)
      : three;
  },
  projectDataSchema.superRefine((project, ctx) => {
    const assets = new Set(project.assets.map((a) => a.id));
    const ids = new Set(project.performers.map((p) => p.id));
    if (
      new Set(project.sections.map((s) => s.id)).size !==
        project.sections.length ||
      project.sections[0].startBar !== 0 ||
      project.sections.at(-1)!.endBar !== loopBars ||
      project.sections.some(
        (s, i) =>
          s.endBar <= s.startBar ||
          (i > 0 && s.startBar !== project.sections[i - 1].endBar) ||
          (s.leadId !== null && !ids.has(s.leadId)) ||
          (s.kind === "solo" && s.leadId === null) ||
          new Set(s.mutedIds).size !== s.mutedIds.length ||
          s.mutedIds.some((id) => !ids.has(id))
      )
    ) {
      ctx.addIssue({
        code: "custom",
        message:
          "Song sections must cover every bar of the song in order and reference existing characters.",
      });
    }
    if (
      assets.size !== project.assets.length ||
      new Set(project.performers.map((p) => p.id)).size !==
        project.performers.length
    )
      ctx.addIssue({
        code: "custom",
        message: "Duplicate asset or performer IDs.",
      });
    for (const p of project.performers) {
      if (!assets.has(p.assetId))
        ctx.addIssue({
          code: "custom",
          message: `Missing asset for ${p.name}.`,
        });
      if (
        new Set(p.steps).size !== p.steps.length ||
        p.steps.some((step, i) => i > 0 && step < p.steps[i - 1])
      )
        ctx.addIssue({ code: "custom", message: "Duplicate steps." });
      if (p.path.some((k, i) => i > 0 && k.beat <= p.path[i - 1].beat))
        ctx.addIssue({
          code: "custom",
          message: "Path keyframes must increase.",
        });
    }
  })
);
export type Project = z.infer<typeof projectSchema>;

/**
 * How a new sound joins the band. A hit plays on a rhythm. A phrase (a voice, a tune, a few
 * beats recorded in a row) plays whole, once every card. A loop is a phrase the band changes
 * tempo for, so it fills its bars exactly and comes round without a gap.
 */
export type PlayStyle = "hit" | "phrase" | "loop";
const PHRASE_BARS = [1, 2, 4, 8] as const;
/** A phrase may run this much past its card, cut off cleanly, rather than take twice the bars. */
const PHRASE_SPILL = 0.92;
const TEMPO = { min: 80, max: 160 } as const;

const beatsOf = (lengthS: number, bpm: number): number => (lengthS * bpm) / 60;

/** The card a phrase of this length needs: whole bars, and room for all of it. */
export function phraseBars(lengthS: number, bpm: number): number {
  const beats = beatsOf(lengthS, bpm) * PHRASE_SPILL;
  return PHRASE_BARS.find((bars) => bars * 4 >= beats) ?? 8;
}

/** Short sounds are hits; anything longer than a beat and a half is a phrase. */
export function suggestedStyle(lengthS: number, bpm: number): PlayStyle {
  return beatsOf(lengthS, bpm) > 1.5 ? "phrase" : "hit";
}

/**
 * The tempo, nearest the one playing, at which this sound lasts exactly a whole card. None
 * fits when it is too short or too long for any tempo the band can play.
 */
export function tempoToFit(
  lengthS: number,
  bpm: number
): { bpm: number; bars: number } | undefined {
  return PHRASE_BARS.map((bars) => ({
    bars,
    bpm: Math.round(((bars * 4 * 60) / lengthS) * 100) / 100,
  }))
    .filter((fit) => fit.bpm >= TEMPO.min && fit.bpm <= TEMPO.max)
    .sort((a, b) => Math.abs(a.bpm - bpm) - Math.abs(b.bpm - bpm))[0];
}

/** The rhythm card a new sound starts with, for how it plays. A hit keeps the usual one. */
export function playShape(
  style: PlayStyle,
  lengthS: number | undefined,
  bpm: number
): Partial<Pick<Performer, "mode" | "steps" | "cardBars">> {
  if (style === "hit" || lengthS === undefined) return {};
  const fit = style === "loop" ? tempoToFit(lengthS, bpm) : undefined;
  const bars = fit?.bars ?? phraseBars(lengthS, bpm);
  return { mode: "phrase", cardBars: bars, steps: repeatCard([0], bars) };
}

export function makePerformer(
  asset: Asset,
  index: number,
  occupied: Pick<Performer, "position">[] = [],
  shape: Partial<Pick<Performer, "mode" | "steps" | "cardBars">> = {}
): Performer {
  const angle = index * Math.PI * 0.58 - Math.PI * 0.85;
  let position = { x: Math.cos(angle) * 245, y: Math.sin(angle) * 116 };
  const clearance = (point: { x: number; y: number }): number =>
    Math.min(
      ...occupied.map((p) =>
        Math.hypot(point.x - p.position.x, (point.y - p.position.y) * 1.4)
      )
    );
  if (clearance(position) < 120) {
    const choices = [-125, 0, 110].flatMap((y) =>
      [-260, -130, 0, 130, 260].map((x) => ({ x, y }))
    );
    position = choices.reduce(
      (best, point) => (clearance(point) > clearance(best) ? point : best),
      position
    );
  }
  return {
    id: crypto.randomUUID(),
    assetId: asset.id,
    name: asset.label,
    position,
    steps: Array.from(
      { length: loopSteps / 8 },
      (_, i) => i * 8 + (index % 4) * 2
    ),
    gainDb: -9,
    pan: 0,
    rate: 1,
    mute: false,
    solo: false,
    motion: "dance",
    exit: "fade",
    mode: "repeat_hits",
    path: [],
    pivot: { x: 0.5, y: 0.85 },
    ...shape,
  };
}

export function demoProject(alternate = false): Project {
  const labels = ["Tin moon", "Rubber soul", "Bottle bop", "Little spark"];
  const colors = ["#bd7046", "#d7b34e", "#6d9990", "#8b849d"];
  const assets: Asset[] = labels.map((label, i) => ({
    id: `demo-${i}`,
    label,
    color: colors[i],
    sprite: "/sprites.png",
    tile: i,
    audioId: `demo-${i}`,
    provenance: "synthesized demo",
  }));
  const patterns = [
    [0, 6, 10, 16, 24, 30, 32, 38, 42, 48, 56, 62],
    [4, 12, 20, 28, 36, 44, 52, 60],
    [0, 8, 14, 24, 32, 40, 46, 56],
    [2, 6, 10, 14, 18, 22, 26, 30, 34, 38, 42, 46, 50, 54, 58, 60, 62],
  ];
  const positions = [
    { x: -234, y: 38 },
    { x: -70, y: -108 },
    { x: 199, y: -46 },
    { x: 104, y: 132 },
  ];
  return {
    schemaVersion: 4,
    title: alternate ? "Odd hours club" : "Good things make noise",
    bpm: alternate ? 104 : 112,
    swing: 0.12,
    seed: 42,
    sections: defaultSections(assets.map((_, i) => `p-${i}`)),
    assets,
    performers: assets.map((a, i) => ({
      ...makePerformer(a, i),
      id: `p-${i}`,
      steps: repeatCard(
        patterns[i].map((s) => (alternate ? (s + i * 2) % 64 : s)),
        4
      ),
      position: positions[i],
      gainDb: [-7, -11, -14, -17][i],
      motion: i === 2 ? "hop" : "dance",
    })),
  };
}

const everyBar = (pattern: number[]): number[] => repeatCard(pattern, 1);
/** A card of `length` bars with this one-bar pattern on the bars it lists. */
const onBars = (length: number, bars: number[], pattern: number[]): number[] =>
  repeatCard(
    bars.flatMap((bar) => pattern.map((step) => step + bar * stepsPerBar)),
    length
  );

interface BandMember {
  key: string;
  label: string;
  color: string;
  steps: number[];
  position: { x: number; y: number };
  gainDb: number;
  pan: number;
  tuned?: boolean;
  motion?: Performer["motion"];
}

/** On stage in every new session. Tuned members stand at heights that make a chord. */
const BASE_BAND: BandMember[] = [
  {
    key: "kick",
    label: "Thump",
    color: "#c2552d",
    steps: everyBar([0, 6, 8]),
    position: { x: -80, y: 135 },
    gainDb: -6,
    pan: 0,
  },
  {
    key: "hat",
    label: "Tiss",
    color: "#b98a3e",
    steps: everyBar([0, 2, 4, 6, 8, 10, 12, 14]),
    position: { x: 185, y: 45 },
    gainDb: -15,
    pan: 0.25,
  },
  {
    key: "snare",
    label: "Crack",
    color: "#c9673a",
    // A little fill at the end of every four bars, so the phrases can be heard turning over.
    steps: onBars(4, [0, 1, 2, 3], [4, 12])
      .concat(onBars(4, [3], [14, 15]))
      .sort((a, b) => a - b),
    position: { x: 90, y: 135 },
    gainDb: -9,
    pan: 0.08,
  },
  {
    key: "bass",
    label: "Low Rider",
    color: "#d7a93f",
    steps: everyBar([0, 3, 6, 10, 12]),
    position: { x: -275, y: 0 },
    gainDb: -9,
    pan: -0.1,
    tuned: true,
    motion: "glide",
  },
  {
    key: "keys",
    label: "Wheezer",
    color: "#6f9a93",
    steps: everyBar([2, 10]),
    position: { x: -185, y: 40 },
    gainDb: -15,
    pan: -0.25,
    tuned: true,
  },
  {
    key: "marimba",
    label: "Woody",
    color: "#b07f45",
    steps: everyBar([0, 3, 6, 9, 12, 14]),
    position: { x: -100, y: -40 },
    gainDb: -13,
    pan: -0.3,
    tuned: true,
  },
  {
    key: "clap",
    label: "Slap Happy",
    color: "#c8704a",
    steps: onBars(2, [1], [12]),
    position: { x: -240, y: 130 },
    gainDb: -12,
    pan: -0.15,
  },
  {
    key: "glock",
    label: "Rainbow",
    color: "#7a78b5",
    steps: onBars(2, [1], [0, 7, 10]),
    position: { x: 0, y: 40 },
    gainDb: -18,
    pan: 0.2,
    tuned: true,
  },
  {
    key: "laser",
    label: "Pew Pew",
    color: "#8b8f96",
    steps: onBars(4, [3], [12, 14]),
    position: { x: 250, y: -50 },
    gainDb: -20,
    pan: 0.35,
  },
  {
    key: "powerup",
    label: "Gold Star",
    color: "#d9b13b",
    steps: onBars(8, [7], [0]),
    position: { x: 80, y: -55 },
    gainDb: -19,
    pan: 0.1,
  },
  {
    key: "buzzer",
    label: "Game Over",
    color: "#c8402f",
    steps: onBars(loopBars, [loopBars - 1], [14]),
    position: { x: 255, y: 125 },
    gainDb: -16,
    pan: 0.3,
  },
];

/** Who is on stage in each default section, by member. No bar is ever left empty. */
const BASE_SECTION_CAST: string[][] = [
  ["kick", "hat"],
  ["kick", "hat", "snare", "bass"],
  ["kick", "hat", "snare", "bass", "keys", "marimba"],
  BASE_BAND.map((member) => member.key),
  ["hat", "bass", "glock", "laser"],
  ["kick", "hat", "snare", "bass", "keys"],
  ["kick", "hat", "clap", "bass", "marimba", "glock"],
  BASE_BAND.map((member) => member.key),
];
// The low rider walks a little bassline: root, root, a step up, then down to the fifth.
const BASSLINE_HEIGHTS = [0, 0, -40, 80];

const BASE_BAND_VERSION = 1;
const MAX_PERFORMERS = 24;

/**
 * A song saved before the base band existed gets it once. Your own clips stay; the old starter
 * band makes way, since these replace it.
 */
export function withBaseBand(project: Project): Project {
  if (project.baseBandVersion) return project;
  const band = starterProject(project.seed);
  const own = project.performers.filter((p) => !p.assetId.startsWith("demo-"));
  const members = band.performers.slice(
    0,
    Math.max(0, MAX_PERFORMERS - own.length)
  );
  // The old starter band's ids are reused by the new one, so only choices about your own clips
  // carry over: a solo or sit-out for an old member must not land on a new one.
  const ownIds = new Set(own.map((p) => p.id));
  const memberIds = new Set(members.map((p) => p.id));
  const sameShape = project.sections.length === band.sections.length;
  return projectSchema.parse({
    ...project,
    baseBandVersion: BASE_BAND_VERSION,
    assets: [
      ...project.assets.filter((a) => !a.audioId.startsWith("demo-")),
      ...band.assets.filter((a) => members.some((p) => p.assetId === a.id)),
    ],
    performers: [...own, ...members],
    sections: project.sections.map((section, index) => {
      const leadStays = section.leadId !== null && ownIds.has(section.leadId);
      return {
        ...section,
        kind: section.kind === "solo" && !leadStays ? "groove" : section.kind,
        leadId: leadStays ? section.leadId : null,
        mutedIds: [
          ...section.mutedIds.filter((id) => ownIds.has(id)),
          ...(sameShape
            ? band.sections[index].mutedIds.filter((id) => memberIds.has(id))
            : []),
        ],
      };
    }),
  });
}

/** A fresh, playable band; hydration always restores an existing project. */
export function starterProject(
  seed = crypto.getRandomValues(new Uint32Array(1))[0]
): Project {
  let state = seed >>> 0;
  const random = (): number => {
    state += 0x6d2b79f5;
    let value = Math.imul(state ^ (state >>> 15), 1 | state);
    value ^= value + Math.imul(value ^ (value >>> 7), 61 | value);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
  const ids = new Map(BASE_BAND.map((member, i) => [member.key, `p-${i}`]));
  const assets: Asset[] = BASE_BAND.map((member) => ({
    id: `band-${member.key}`,
    label: member.label,
    color: member.color,
    sprite: `/band/${member.key}.png`,
    audioId: `band-${member.key}`,
    provenance: "base band",
  }));
  const performers: Performer[] = BASE_BAND.map((member, i) => ({
    ...makePerformer(assets[i], i),
    id: `p-${i}`,
    position: { ...member.position },
    steps: member.steps,
    gainDb: member.gainDb,
    pan: member.pan,
    motion: member.motion ?? (i % 3 === 2 ? "hop" : "dance"),
    ...(member.tuned ? { tuned: true } : {}),
    path:
      member.key === "bass"
        ? Array.from({ length: loopBars - 1 }, (_, step) => ({
            beat: (step + 1) * 4,
            x: member.position.x + (step % 2 ? 22 : 0),
            y: BASSLINE_HEIGHTS[(step + 1) % BASSLINE_HEIGHTS.length],
          }))
        : [],
  }));
  const allIds = [...ids.values()];
  const sections = defaultSections().map((section, index) => ({
    ...section,
    mutedIds: allIds.filter(
      (id) => !BASE_SECTION_CAST[index].some((key) => ids.get(key) === id)
    ),
  }));
  return projectSchema.parse({
    schemaVersion: 4,
    baseBandVersion: BASE_BAND_VERSION,
    title: "Good things make noise",
    bpm: [104, 108, 112, 116][Math.floor(random() * 4)],
    swing: 0.08 + Math.floor(random() * 5) * 0.02,
    seed: seed >>> 0,
    sections,
    assets,
    performers,
  });
}
