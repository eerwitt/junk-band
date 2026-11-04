import { describe, it } from "node:test";
import { AudioEngine } from "../dist/modules/audio/engine.js";
import assert from "node:assert/strict";
import {
  demoProject,
  starterProject,
  withBaseBand,
  projectSchema,
  rigSchema,
  makePerformer,
} from "../dist/modules/domain/project.js";
import {
  compileEvents,
  clonePerformer,
  stepSeconds,
  transformSteps,
} from "../dist/modules/domain/music.js";
import {
  poseAtBeat,
  stageGain,
  pathPosition,
} from "../dist/modules/domain/motion.js";
import {
  loopBeats,
  loopSteps,
  pulseAtAge,
} from "../dist/modules/domain/timing.js";
import {
  noteRow,
  playbackRate,
  rowSemitones,
} from "../dist/modules/domain/pitch.js";

it("preserves off-stage drops and paths while rejecting non-finite coordinates", () => {
  const project = demoProject();
  project.performers[0].position = { x: -1900, y: -850 };
  project.performers[0].path = [{ beat: 4, x: -2100, y: 950 }];
  const restored = projectSchema.parse(JSON.parse(JSON.stringify(project)));
  assert.deepEqual(
    restored.performers[0].position,
    project.performers[0].position
  );
  assert.deepEqual(restored.performers[0].path, project.performers[0].path);
  for (const x of [NaN, Infinity, -Infinity]) {
    project.performers[0].position.x = x;
    assert.equal(projectSchema.safeParse(project).success, false);
  }
});

it("preserves complete joint rigs and rejects ambiguous or invalid attachments", () => {
  const rig = {
    width: 1024,
    height: 1536,
    body: "blob:asset:body",
    parts: ["left_arm", "right_arm", "left_leg", "right_leg"].map((name) => ({
      name,
      sprite: `blob:asset:${name}`,
      pivot: { x: 0.5, y: 0.7 },
      maxAngle: 0.2,
    })),
  };
  const project = demoProject();
  project.assets[0].rig = rig;
  assert.deepEqual(projectSchema.parse(project).assets[0].rig, rig);
  const duplicate = structuredClone(rig);
  duplicate.parts[1].name = "left_arm";
  assert.equal(rigSchema.safeParse(duplicate).success, false);
  const detached = structuredClone(rig);
  detached.parts[0].pivot.x = 1.2;
  assert.equal(rigSchema.safeParse(detached).success, false);
  const unsafe = structuredClone(rig);
  unsafe.parts[0].maxAngle = 1;
  assert.equal(rigSchema.safeParse(unsafe).success, false);
});

it("places imported characters in available space beside small starter bands", () => {
  for (let seed = 1; seed < 40; seed++) {
    const project = starterProject(seed);
    const added = makePerformer(
      project.assets[0],
      project.performers.length,
      project.performers
    );
    assert(
      project.performers.every(
        (p) =>
          Math.hypot(
            added.position.x - p.position.x,
            (added.position.y - p.position.y) * 1.4
          ) >= 120
      )
    );
  }
});
import {
  setSectionKind,
  sectionGain,
  splitSection,
  resizeSection,
  joinNext,
  togglePart,
  setPart,
} from "../dist/modules/domain/arrangement.js";

describe("musical contract", () => {
  it("starts every new session with the base band and its sound effects", () => {
    for (let seed = 0; seed < 10; seed++) {
      const project = starterProject(seed);
      assert.deepEqual(project, starterProject(seed));
      assert.equal(projectSchema.safeParse(project).success, true);
      assert.equal(project.performers.length, 11);
      assert.ok(project.assets.every((a) => a.provenance === "base band"));
      assert.ok(project.assets.every((a) => a.audioId.startsWith("band-")));
      assert.ok(project.assets.every((a) => a.sprite.startsWith("/band/")));
      const events = compileEvents(project);
      for (let bar = 0; bar < 16; bar++)
        assert.ok(
          events.some((e) => e.step >= bar * 16 && e.step < (bar + 1) * 16),
          `bar ${bar + 1} has something playing`
        );
      for (const section of project.sections)
        assert.ok(section.mutedIds.length < project.performers.length);
      assert.equal(project.sections.length, 8);
    }
  });
  it("gives a song saved before the base band the band once, keeping your own clips", () => {
    const saved = demoProject();
    const clip = {
      ...saved.assets[0],
      id: "mine",
      label: "My tin",
      audioId: "clip-1",
      sprite: "blob:asset:art-1",
      provenance: "SAM Audio",
    };
    saved.assets.push(clip);
    saved.performers.push({
      ...saved.performers[0],
      id: "my-tin",
      assetId: "mine",
      name: "My tin",
    });
    saved.sections[1].mutedIds = ["my-tin", "p-0"];
    saved.sections[2].kind = "solo";
    saved.sections[2].leadId = "p-1";
    assert.equal(saved.baseBandVersion, undefined);
    const merged = withBaseBand(saved);
    assert.equal(projectSchema.safeParse(merged).success, true);
    assert.equal(merged.performers.length, 12);
    assert.ok(merged.performers.some((p) => p.id === "my-tin"));
    assert.ok(merged.assets.some((a) => a.id === "mine"));
    assert.ok(!merged.assets.some((a) => a.audioId.startsWith("demo-")));
    assert.ok(merged.assets.some((a) => a.audioId === "band-kick"));
    assert.ok(
      merged.sections[1].mutedIds.includes("my-tin"),
      "Your choices stay"
    );
    assert.equal(merged.sections[2].kind, "groove", "A solo needs its lead");
    assert.equal(merged.sections[2].leadId, null);
    // Thump is p-0 in the new band and is on stage in the verse, whatever old p-0 was doing.
    assert.ok(!merged.sections[1].mutedIds.includes("p-0"));
    assert.equal(merged.bpm, saved.bpm, "It is still your song");
    // Removing band members keeps them removed.
    const trimmed = structuredClone(merged);
    trimmed.performers = trimmed.performers.filter((p) => p.id !== "p-0");
    trimmed.assets = trimmed.assets.filter((a) => a.id !== "band-kick");
    for (const section of trimmed.sections)
      section.mutedIds = section.mutedIds.filter((id) => id !== "p-0");
    assert.equal(withBaseBand(trimmed), trimmed);
    assert.equal(withBaseBand(starterProject(4)).performers.length, 11);
    // A full stage only takes who fits.
    const full = demoProject();
    full.assets.push(clip);
    full.performers = Array.from({ length: 20 }, (_, i) => ({
      ...saved.performers[0],
      id: `mine-${i}`,
      assetId: "mine",
    }));
    for (const section of full.sections) section.mutedIds = [];
    assert.equal(withBaseBand(full).performers.length, 24);
  });
  it("gives height a note, always in the scale, and leaves untuned sounds alone", () => {
    assert.equal(rowSemitones(0), 0);
    assert.equal(rowSemitones(1), 3);
    assert.equal(rowSemitones(5), 12);
    assert.equal(rowSemitones(-5), -12);
    assert.equal(rowSemitones(-1), -2);
    assert.equal(noteRow(0), 0);
    assert.equal(noteRow(-40), 1);
    assert.equal(noteRow(80), -2);
    assert.equal(
      noteRow(-5000),
      5,
      "A character off the top keeps the top note"
    );
    assert.equal(noteRow(5000), -5);
    for (let row = -5; row <= 5; row++)
      assert.ok(
        [0, 3, 5, 7, 10].includes(((rowSemitones(row) % 12) + 12) % 12),
        `row ${row} stays in the scale`
      );
    const project = starterProject(1);
    const bass = project.performers.find((p) => p.assetId === "band-bass");
    assert.ok(bass.tuned && bass.path.length > 0);
    const rates = new Set(
      Array.from({ length: 16 }, (_, bar) => playbackRate(bass, bar * 4 + 0.01))
    );
    assert.ok(rates.size >= 3, "The bass walks a line of different notes");
    const kick = project.performers.find((p) => p.assetId === "band-kick");
    assert.equal(
      playbackRate({ ...kick, position: { x: 0, y: -200 } }, 0),
      kick.rate
    );
    const lifted = {
      ...kick,
      tuned: true,
      position: { x: 0, y: -200 },
      path: [],
    };
    assert.ok(Math.abs(playbackRate(lifted, 0) - kick.rate * 2) < 1e-9);
  });
  it("compiles sixteen populated bars with bounded events and swung offbeats", () => {
    const events = compileEvents(demoProject());
    assert.ok(events.length > 100);
    for (let bar = 0; bar < 16; bar++)
      assert.ok(
        events.some((e) => e.step >= bar * 16 && e.step < (bar + 1) * 16),
        `bar ${bar + 1} has something playing`
      );
    assert.ok(
      events.every(
        (event) =>
          Number.isInteger(event.step) &&
          event.step >= 0 &&
          event.step < loopSteps
      )
    );
    assert.deepEqual(
      events.map((event) => event.step),
      events.map((event) => event.step).sort((a, b) => a - b)
    );
    assert.equal(stepSeconds(64, 120, 0), 8);
    assert.equal(stepSeconds(loopSteps, 120, 0), 32);
    for (let quarter = 0; quarter < 4; quarter++)
      assert.ok(
        events.some(
          (e) => e.step >= quarter * 64 && e.step < (quarter + 1) * 64
        )
      );
    assert.ok(stepSeconds(1, 120, 0.5) > stepSeconds(1, 120, 0));
    assert.equal(stepSeconds(16, 120, 0.5), 2);
  });
  it("clones share media and keep independent, different rhythms", () => {
    const original = demoProject().performers[0],
      clone = clonePerformer(original, 1);
    assert.notEqual(original.id, clone.id);
    assert.equal(original.assetId, clone.assetId);
    assert.notDeepEqual(original.steps, clone.steps);
    assert.ok(clone.gainDb < original.gainDb);
    clone.steps.push(63);
    assert.ok(!original.steps.includes(63));
    original.rate = 3;
    assert.ok(clonePerformer(original, 2).rate <= 3);
  });
  it("respects mute, solo and once-per-loop playback modes", () => {
    const project = demoProject();
    project.performers[1].solo = true;
    assert.ok(
      compileEvents(project).every(
        (event) => event.performerId === project.performers[1].id
      )
    );
    project.performers[1].mute = true;
    assert.equal(compileEvents(project).length, 0);
    project.performers = [project.performers[0]];
    for (const mode of ["one_shot", "continuous_loop"]) {
      project.performers[0].mode = mode;
      assert.equal(compileEvents(project).length, 1);
    }
  });
  it("wraps and deduplicates transformed notes", () => {
    assert.deepEqual(transformSteps([0, 254, 255], "offbeat_echo"), [0, 1, 2]);
    assert.deepEqual(transformSteps([0, 255], "fill"), [0, 250, 253, 255]);
  });
});
describe("deterministic motion and persistence schema", () => {
  it("seeks to the same exact pose independent of prior evaluations", () => {
    const performer = demoProject().performers[0],
      pose = poseAtBeat(performer, 7.25);
    poseAtBeat(performer, 13);
    poseAtBeat(performer, 3);
    assert.deepEqual(poseAtBeat(performer, 7.25), pose);
    assert.deepEqual(poseAtBeat(performer, 7.25 + loopBeats), pose);
    assert.deepEqual(
      poseAtBeat(performer, 0),
      poseAtBeat(performer, loopBeats)
    );
  });
  it("gates offstage audio from world paths while preserving phase", () => {
    const performer = demoProject().performers[0];
    performer.position = { x: 0, y: 0 };
    performer.path = [
      { beat: 0, x: 0, y: 0 },
      { beat: 12, x: 600, y: 0 },
    ];
    performer.exit = "mute";
    assert.equal(stageGain(performer, 0), 1);
    assert.equal(stageGain(performer, 12), 0);
    assert.equal(poseAtBeat(performer, 6).x, 300);
    performer.exit = "continue";
    assert.equal(stageGain(performer, 12), 1);
  });
  it("closes a drawn path at home with no position or velocity jump", () => {
    const p = demoProject().performers[0];
    p.path = [
      { beat: 0, ...p.position },
      { beat: 25, x: 300, y: -120 },
      { beat: 56, x: 200, y: 180 },
    ];
    assert.deepEqual(pathPosition(p, 0), p.position);
    assert.deepEqual(pathPosition(p, loopBeats), p.position);
    const near = pathPosition(p, loopBeats - 0.001);
    assert.ok(Math.hypot(near.x - p.position.x, near.y - p.position.y) < 0.001);
    const previous = pathPosition(p, loopBeats - 0.002);
    assert.ok(
      Math.hypot(near.x - previous.x, near.y - previous.y) / 0.001 < 0.1
    );
  });
  it("upgrades old four-bar scenes without losing their groove or assets", () => {
    const legacy = demoProject();
    legacy.schemaVersion = 1;
    for (const p of legacy.performers)
      p.steps = p.steps.filter((step) => step < 64);
    const original = structuredClone(legacy);
    const upgraded = projectSchema.parse(legacy);
    assert.equal(upgraded.schemaVersion, 3);
    assert.deepEqual(upgraded.assets, original.assets);
    for (let i = 0; i < 4; i++)
      assert.deepEqual(
        upgraded.performers[i].steps,
        Array.from({ length: 4 }, (_, repeat) =>
          original.performers[i].steps.map((step) => step + repeat * 64)
        ).flat()
      );
    assert.equal(legacy.schemaVersion, 1);
  });
  it("gives note pulses a bounded envelope without pulsing before a note", () => {
    assert.equal(pulseAtAge(-0.1, 0.25), 0);
    assert.equal(pulseAtAge(0, 0.25), 0);
    assert.equal(pulseAtAge(0.25, 0.25), 0);
    assert.ok(pulseAtAge(0.08, 0.25) > 0.8);
    for (let time = 0; time < 1; time += 0.001)
      assert.ok(pulseAtAge(time, 0.25) <= 1);
    const performer = demoProject().performers[0];
    assert.equal(poseAtBeat(performer, 3.2, false, 0).elevation, 0);
    assert.equal(poseAtBeat(performer, 3.2, false, 1).elevation, 4);
    assert.equal(poseAtBeat(performer, 3.2, true, 1).elevation, 0);
  });
  it("round trips and rejects orphaned assets, duplicate notes and unordered paths", () => {
    const project = demoProject();
    assert.deepEqual(
      projectSchema.parse(JSON.parse(JSON.stringify(project))),
      project
    );
    const orphan = structuredClone(project);
    orphan.performers[0].assetId = "missing";
    assert.equal(projectSchema.safeParse(orphan).success, false);
    const duplicate = structuredClone(project);
    duplicate.performers[0].steps = [0, 0];
    assert.equal(projectSchema.safeParse(duplicate).success, false);
    project.performers[0].path = [
      { beat: 8, x: 0, y: 0 },
      { beat: 4, x: 20, y: 10 },
    ];
    assert.equal(projectSchema.safeParse(project).success, false);
  });
});
describe("song arrangement", () => {
  it("makes a bridge sparser without rewriting the original patterns", () => {
    const project = demoProject(),
      original = structuredClone(project);
    const before = compileEvents(project).filter(
      (e) => e.step >= 32 && e.step < 64
    );
    setSectionKind(project, "section-1", "bridge");
    const after = compileEvents(project).filter(
      (e) => e.step >= 32 && e.step < 64
    );
    assert.ok(after.length < before.length && after.length > 0);
    assert.deepEqual(
      project.performers.map((p) => p.steps),
      original.performers.map((p) => p.steps)
    );
    assert.deepEqual(
      compileEvents(project).filter((e) => e.step < 32),
      compileEvents(original).filter((e) => e.step < 32)
    );
  });
  it("focuses a solo locally and lets backing parts rejoin quietly", () => {
    const project = demoProject();
    setSectionKind(project, "section-2", "solo", "p-2");
    assert.ok(
      compileEvents(project)
        .filter((e) => e.step >= 64 && e.step < 96)
        .every((e) => e.performerId === "p-2")
    );
    assert.equal(sectionGain(project, "p-0", 17), 0);
    assert.equal(sectionGain(project, "p-0", 9), 1);
    togglePart(project, "section-2", "p-0");
    assert.equal(sectionGain(project, "p-0", 17), 0.55);
    assert.equal(sectionGain(project, "p-2", 17), 1);
    assert.equal(projectSchema.safeParse(project).success, true);
  });
  it("splits, resizes and joins without losing continuous sixteen-bar coverage", () => {
    const project = demoProject();
    splitSection(project, "section-1", 3);
    assert.equal(project.sections.length, 9);
    resizeSection(project, "section-0", 1);
    assert.equal(project.sections[1].startBar, 1);
    joinNext(project, "section-0");
    assert.equal(project.sections.length, 8);
    assert.equal(project.sections[0].endBar, 3);
    assert.equal(projectSchema.safeParse(project).success, true);
    assert.throws(() => splitSection(project, "section-0", 0));
    project.sections[1].startBar = 5;
    assert.equal(projectSchema.safeParse(project).success, false);
  });
  it("starts with eight sections and a band that comes and goes", () => {
    const project = demoProject();
    assert.equal(project.sections.length, 8);
    assert.ok(project.sections.every((s) => s.endBar - s.startBar === 2));
    assert.ok(project.sections.some((s) => s.mutedIds.length > 0));
    assert.ok(project.sections.some((s) => s.mutedIds.length === 0));
    for (const s of project.sections)
      assert.ok(s.mutedIds.length < project.performers.length, s.label);
    assert.equal(projectSchema.safeParse(project).success, true);
    assert.ok(starterProject(7).sections.length === 8);
  });
  it("brings older four-section songs up to eight without losing edits", () => {
    const older = (sections) => ({
      ...demoProject(),
      schemaVersion: 2,
      sections,
    });
    const four = (mutedIds = []) =>
      ["A", "B", "C", "D"].map((label, index) => ({
        id: `old-${index}`,
        label,
        startBar: index * 4,
        endBar: index * 4 + 4,
        kind: "groove",
        leadId: null,
        mutedIds: index === 1 ? mutedIds : [],
      }));
    const untouched = projectSchema.parse(older(four()));
    assert.equal(untouched.schemaVersion, 3);
    assert.equal(untouched.sections.length, 8);
    assert.ok(untouched.sections.some((s) => s.mutedIds.length));
    const edited = projectSchema.parse(older(four(["p-1"])));
    assert.equal(edited.sections.length, 8);
    assert.deepEqual(
      edited.sections
        .filter((s) => s.mutedIds.includes("p-1"))
        .map((s) => [s.startBar, s.endBar, s.label]),
      [
        [4, 6, "B"],
        [6, 8, "B II"],
      ]
    );
    // Someone's own shape stays theirs.
    const three = demoProject();
    three.schemaVersion = 2;
    three.sections = [
      { ...four()[0], endBar: 8 },
      { ...four()[2], startBar: 8, endBar: 12 },
      { ...four()[3] },
    ];
    assert.equal(projectSchema.parse(three).sections.length, 3);
  });
  it("saves a character's spot outside the ring, but not on a clone", () => {
    const project = demoProject();
    project.performers[0].wing = { x: 500, y: -90 };
    assert.deepEqual(
      projectSchema.parse(JSON.parse(JSON.stringify(project))).performers[0]
        .wing,
      { x: 500, y: -90 }
    );
    assert.equal(clonePerformer(project.performers[0], 1).wing, undefined);
    assert.equal(demoProject().performers[0].wing, undefined);
  });
  it("sits a character out of one section and brings them back", () => {
    const project = demoProject();
    setPart(project, "section-3", "p-1", false);
    assert.equal(sectionGain(project, "p-1", 13), 1);
    assert.equal(sectionGain(project, "p-1", 25), 0);
    assert.ok(
      !compileEvents(project).some(
        (e) => e.performerId === "p-1" && e.step >= 96 && e.step < 128
      )
    );
    setPart(project, "section-3", "p-1", false);
    assert.equal(
      project.sections[3].mutedIds.filter((id) => id === "p-1").length,
      1
    );
    setPart(project, "section-3", "p-1", true);
    assert.equal(sectionGain(project, "p-1", 25), 1);
    assert.throws(() => setPart(project, "nope", "p-1", true));
  });
  it("keeps sustained sources available to reopen after a muted section", () => {
    const project = demoProject();
    project.performers[0].mode = "continuous_loop";
    setSectionKind(project, "section-0", "solo", "p-2");
    assert.ok(
      compileEvents(project).some(
        (e) => e.performerId === "p-0" && e.step === 0
      )
    );
    assert.equal(sectionGain(project, "p-0", 0), 0);
    assert.equal(sectionGain(project, "p-0", 18), 1);
  });
});

describe("fluid visuals", () => {
  /** A context whose render clock only moves once per 20 ms callback. */
  const fakeContext = (latency) => {
    const context = {
      state: "running",
      currentTime: 0,
      baseLatency: 0,
      outputLatency: latency,
      stamp: { contextTime: 0, performanceTime: 0 },
      getOutputTimestamp: () => context.stamp,
    };
    return context;
  };
  const engineAt = (context) => {
    const engine = new AudioEngine(
      async () => context,
      async () => undefined
    );
    Object.assign(engine, {
      context,
      playing: true,
      clock: [{ at: 0, beat: 0, bpm: 120 }],
    });
    return engine;
  };
  const withClock = (run) => {
    const real = globalThis.performance;
    let now = 1000;
    Object.defineProperty(globalThis, "performance", {
      value: { now: () => now },
      configurable: true,
    });
    try {
      run(
        (ms) => (now += ms),
        () => now
      );
    } finally {
      Object.defineProperty(globalThis, "performance", {
        value: real,
        configurable: true,
      });
    }
  };

  it("moves the drawn beat every frame, behind the render clock by the output latency", () => {
    withClock((advance, now) => {
      const context = fakeContext(0.04);
      const engine = engineAt(context);
      const beats = [];
      for (let frame = 0; frame < 60; frame++) {
        advance(1000 / 60);
        const rendered = Math.floor((now() - 1000) / 20) * 0.02;
        context.currentTime = rendered + 0.04;
        // The output stamp is refreshed per callback, like the render clock.
        context.stamp = {
          contextTime: rendered,
          performanceTime: 1000 + rendered * 1000,
        };
        beats.push(JSON.parse(engine.visualFrame()).beat);
      }
      const steps = beats.slice(1).map((beat, index) => beat - beats[index]);
      // 120 BPM at 60 fps is 1/30 beat per frame. The raw clock would alternate 0 and 0.04.
      for (const step of steps.slice(2))
        assert.ok(Math.abs(step - 1 / 30) < 0.002, String(step));
      assert.ok(
        beats.at(-1) < engine.beat(),
        "drawn beat trails the scheduler"
      );
    });
  });

  it("carries a coarse render clock forward when there is no output stamp", () => {
    withClock((advance, now) => {
      const context = fakeContext(0.03);
      delete context.getOutputTimestamp;
      const engine = engineAt(context);
      let previous = -1;
      for (let frame = 0; frame < 30; frame++) {
        advance(1000 / 60);
        context.currentTime = Math.floor((now() - 1000) / 25) * 0.025;
        const beat = JSON.parse(engine.visualFrame()).beat;
        assert.ok(beat >= previous, "never runs backwards");
        if (frame > 3) assert.ok(beat > previous, "moves every frame");
        previous = beat;
      }
    });
  });
});

describe("slider edits", () => {
  it("make one Undo step per drag, while other edits stay separate", async () => {
    globalThis.window ??= globalThis;
    const { StudioStore } = await import("../dist/modules/browser/store.js");
    // Autosave fails without IndexedDB; the store reports that as a notice.
    const store = new StudioStore();
    const id = store.state.project.performers[0].id;
    const { gainDb: start, pan } = store.state.project.performers[0];
    for (let value = -20; value <= -10; value++)
      store.update(id, { gainDb: value });
    store.update(id, { pan: pan === 0.5 ? 0.25 : 0.5 });
    assert.equal(store.state.project.performers[0].gainDb, -10);
    store.undo();
    assert.equal(store.state.project.performers[0].pan, pan);
    assert.equal(store.state.project.performers[0].gainDb, -10);
    store.undo();
    assert.equal(store.state.project.performers[0].gainDb, start);
  });
});
