import type { Asset, Performer, Project } from "../domain/project";
import {
  compileEvents,
  stepSeconds,
  wrap,
  type NoteEvent,
} from "../domain/music";
import { stageGain } from "../domain/motion";
import { noteRow, playbackRate } from "../domain/pitch";
import { createDemoBuffer } from "./demo";
import { encodeWav } from "./wav";
import { loopBeats, loopSteps, pulseAtAge } from "../domain/timing";
import {
  sectionGain,
  sectionMixKey,
  sectionShapeKey,
} from "../domain/arrangement";

interface MusicalTime {
  beat: number;
  bpm: number;
  project: Project;
}

interface Voice {
  source: AudioBufferSourceNode;
  gain: GainNode;
  pan: StereoPannerNode;
  performerId?: string;
  time: number;
  length: number;
  velocity: number;
  musical?: MusicalTime;
}

const DUCKED_LEVEL = 0.04;
const DUCK_FADE_S = 0.3;
/** Fast enough to feel instant, slow enough not to click. */
const LIVE_RAMP_S = 0.012;
const MAX_VOICES = 64;
/** Low enough to hear one character clearly, high enough to still feel where the beat is. */
const SPOTLIGHT_BAND_LEVEL = 0.12;
/** A tap this close to a hit already in the pattern would only double it. */
const TAP_ALREADY_SOUNDING_S = 0.08;
/** The drawn clock jumps rather than eases when it is this far from the speakers. */
const VISUAL_SNAP_S = 0.05;
/** Share of the drawn clock's error taken out each frame: smooth, and settled within ~20. */
const VISUAL_EASE = 0.1;
export class AudioEngine {
  constructor(
    private readonly getAudioContext: () => Promise<AudioContext>,
    private readonly loadSample: (id: string) => Promise<Blob | undefined>
  ) {}
  private context?: AudioContext;
  private master?: DynamicsCompressorNode;
  private output?: GainNode;
  private ducked = false;
  private buffers = new Map<string, AudioBuffer>();
  private voices = new Set<Voice>();
  private timer?: number;
  private epoch = 0;
  private origin = 0;
  private cursor = 0;
  private nextStep = 0;
  private current?: Project;
  private pending?: Project;
  private eventsByStep: NoteEvent[][] = Array.from(
    { length: loopSteps },
    () => []
  );
  private visualHits: {
    id: string;
    time: number;
    duration: number;
    velocity: number;
  }[] = [];
  private clock: { at: number; beat: number; bpm: number }[] = [];
  /** Visual clock state: the last drawn audible time, and when `currentTime` last moved. */
  private audible = { time: 0, frame: 0 };
  private renderedAt = { context: -1, frame: 0 };
  playing = false;
  private playRequest = 0;
  private updateRequest = 0;
  private draggedRow?: { id: string; row: number };
  /** The one character being worked on, heard clearly over a quiet band. */
  spotlight: string | null = null;
  /** A section being looped, in steps. Unset plays the whole song. */
  private range?: { start: number; end: number };
  scheduledHits = 0;
  get activeVoices(): number {
    return this.voices.size;
  }

  /** Bring the band right down while something else needs to be heard, or restore it. */
  setDucked(ducked: boolean): void {
    this.ducked = ducked;
    if (!this.output || !this.context) return;
    // Start from wherever a previous fade reached, so reopening quickly cannot jump.
    const now = this.context.currentTime;
    this.output.gain.cancelScheduledValues(now);
    this.output.gain.setValueAtTime(this.output.gain.value, now);
    this.output.gain.setTargetAtTime(
      ducked ? DUCKED_LEVEL : 1,
      now,
      DUCK_FADE_S
    );
  }
  async unlock(): Promise<void> {
    if (!this.context) {
      this.context = await this.getAudioContext();
      this.master = this.context.createDynamicsCompressor();
      this.master.threshold.value = -8;
      this.master.knee.value = 12;
      this.master.ratio.value = 12;
      this.master.attack.value = 0.003;
      this.master.release.value = 0.15;
      this.output = this.context.createGain();
      this.output.gain.value = this.ducked ? DUCKED_LEVEL : 1;
      this.master.connect(this.output);
      this.output.connect(this.context.destination);
    }
    await this.context.resume();
  }
  async prepare(assets: Asset[]): Promise<void> {
    if (!this.context) throw new Error("Unlock audio first.");
    for (const asset of assets) {
      if (this.buffers.has(asset.audioId)) continue;
      if (asset.audioId.startsWith("demo-"))
        this.buffers.set(
          asset.audioId,
          createDemoBuffer(this.context, Number(asset.audioId.slice(-1)))
        );
      else {
        const blob = await this.loadSample(asset.audioId);
        if (!blob)
          throw new Error(
            `The saved sound for ${asset.label} is missing. Import its project bundle again.`
          );
        this.buffers.set(
          asset.audioId,
          await this.context.decodeAudioData(await blob.arrayBuffer())
        );
      }
    }
  }
  private voice(
    context: BaseAudioContext,
    destination: AudioNode,
    buffer: AudioBuffer,
    p: Performer,
    time: number,
    velocity: number,
    duration?: number,
    offsetS = 0,
    musicalTime?: MusicalTime
  ): void {
    if (context === this.context && this.voices.size >= MAX_VOICES) return;
    const source = context.createBufferSource(),
      gain = context.createGain(),
      pan = context.createStereoPanner();
    source.buffer = buffer;
    const rate = playbackRate(p, musicalTime?.beat ?? 0);
    source.playbackRate.value = rate;
    const length = duration ?? buffer.duration / rate;
    source.loop = duration !== undefined;
    const voice: Voice = {
      source,
      gain,
      pan,
      performerId: musicalTime ? p.id : undefined,
      time,
      length,
      velocity,
      musical: musicalTime,
    };
    this.shape(voice, p, time);
    pan.pan.value = p.pan;
    source.connect(gain);
    gain.connect(pan);
    pan.connect(destination);
    if (context === this.context) this.voices.add(voice);
    if (
      context === this.context &&
      musicalTime &&
      (p.id === this.spotlight || this.gate(p, musicalTime, 0) > 0)
    ) {
      this.visualHits = [
        ...this.visualHits.filter((hit) => hit.time > context.currentTime - 1),
        {
          id: p.id,
          time,
          duration: (0.45 * 60) / musicalTime.bpm,
          velocity,
        },
      ];
    }
    source.onended = () => {
      this.voices.delete(voice);
      source.disconnect();
      gain.disconnect();
      pan.disconnect();
    };
    source.start(time, offsetS);
    source.stop(time + length + 0.001);
  }
  private gate(p: Performer, musical: MusicalTime, elapsed: number): number {
    const beat = musical.beat + (elapsed * musical.bpm) / 60;
    return stageGain(p, beat) * sectionGain(musical.project, p.id, beat);
  }
  /** Write a voice's level from `from` onward, either at its start or while it is sounding. */
  private shape(voice: Voice, p: Performer, from: number): void {
    const { time, length, velocity, musical } = voice;
    const param = voice.gain.gain;
    // A song being exported is never affected by what is being worked on in the room.
    const spotlight =
      voice.gain.context === this.context ? this.spotlight : null;
    const spotlit = spotlight === p.id;
    const silenced =
      musical &&
      !spotlit &&
      (p.mute ||
        (!p.solo && musical.project.performers.some((other) => other.solo)));
    const backing = musical && spotlight && !spotlit ? SPOTLIGHT_BAND_LEVEL : 1;
    const level = silenced
      ? 0
      : Math.pow(10, p.gainDb / 20) * velocity * 0.72 * backing;
    const gate = (elapsed: number): number =>
      musical && !spotlit ? this.gate(p, musical, elapsed) : 1;
    const end = Math.max(0, length - 0.015);
    let reached = 0.004;
    if (from <= time) {
      param.setValueAtTime(0, time);
      param.linearRampToValueAtTime(level * gate(0), time + reached);
    } else {
      reached = from - time + LIVE_RAMP_S;
      if (reached < end)
        param.linearRampToValueAtTime(level * gate(reached), time + reached);
    }
    if (
      musical &&
      ((p.path.length && p.exit !== "continue") ||
        musical.project.sections.some(
          (s) => s.mutedIds.length || s.kind === "solo"
        ))
    ) {
      const increment = 15 / musical.bpm;
      for (
        let elapsed = (Math.floor(reached / increment) + 1) * increment;
        elapsed < end;
        elapsed += increment
      )
        param.linearRampToValueAtTime(level * gate(elapsed), time + elapsed);
    }
    if (reached < end) param.setValueAtTime(level * gate(end), time + end);
    param.linearRampToValueAtTime(0, time + length);
  }
  /** Make a voice that is already scheduled or sounding follow new settings right now. */
  private retune(voice: Voice, p: Performer, project: Project): void {
    if (!voice.musical) return;
    const now = this.context!.currentTime;
    const param = voice.gain.gain;
    voice.musical = { ...voice.musical, project };
    if (now < voice.time) {
      param.cancelScheduledValues(now);
      this.shape(voice, p, voice.time);
    } else if (now < voice.time + voice.length) {
      if (typeof param.cancelAndHoldAtTime === "function")
        param.cancelAndHoldAtTime(now);
      else {
        const value = param.value;
        param.cancelScheduledValues(now);
        param.setValueAtTime(value, now);
      }
      this.shape(voice, p, now);
    }
    voice.pan.pan.setTargetAtTime(p.pan, now, LIVE_RAMP_S);
    voice.source.playbackRate.setTargetAtTime(
      playbackRate(p, this.beat()),
      now,
      LIVE_RAMP_S
    );
  }
  async audition(asset: Asset, performer?: Performer): Promise<void> {
    await this.unlock();
    await this.prepare([asset]);
    const p = performer ?? ({ gainDb: -8, pan: 0, rate: 1 } as Performer);
    const time = this.context!.currentTime + 0.005;
    this.voice(
      this.context!,
      this.master!,
      this.buffers.get(asset.audioId)!,
      p,
      time,
      1
    );
    if (performer?.id)
      this.visualHits = [
        ...this.visualHits.filter(
          (hit) => hit.time > this.context!.currentTime - 1
        ),
        { id: performer.id, time, duration: 0.28, velocity: 1 },
      ];
  }
  async play(project: Project): Promise<void> {
    const request = ++this.playRequest;
    await this.unlock();
    await this.prepare(project.assets);
    if (request !== this.playRequest) return;
    this.stopVoices();
    if (
      this.range &&
      (this.cursor * 4 < this.range.start || this.cursor * 4 >= this.range.end)
    )
      this.cursor = this.range.start / 4;
    this.current = structuredClone(project);
    this.compileSchedule(this.current);
    this.pending = undefined;
    this.origin =
      this.context!.currentTime + 0.05 - (this.cursor * 60) / project.bpm;
    this.clock = [
      {
        at: this.context!.currentTime + 0.05,
        beat: this.cursor,
        bpm: project.bpm,
      },
    ];
    this.nextStep = Math.ceil(this.cursor * 4 - 0.00001);
    this.playing = true;
    this.resumeContinuous(
      this.current,
      this.cursor,
      this.context!.currentTime + 0.05
    );
    const epoch = ++this.epoch;
    const schedule = (): void => {
      if (epoch !== this.epoch || !this.playing || !this.current) return;
      let snapshot = this.current;
      while (
        this.origin + stepSeconds(this.nextStep, snapshot.bpm, snapshot.swing) <
        this.context!.currentTime + 0.12
      ) {
        let step = wrap(this.nextStep);
        if (this.range && step === this.range.end % loopSteps) {
          const at =
            this.origin +
            stepSeconds(this.nextStep, snapshot.bpm, snapshot.swing);
          this.stopLoops(at);
          this.nextStep = this.range.start;
          this.origin =
            at - stepSeconds(this.nextStep, snapshot.bpm, snapshot.swing);
          const beat = this.range.start / 4;
          this.clock = [
            ...this.clock.slice(-3),
            { at, beat, bpm: snapshot.bpm },
          ];
          this.resumeContinuous(snapshot, beat, at);
          step = wrap(this.nextStep);
        }
        // Tempo lands on the next beat. Reshaping sections waits for the bar.
        if (
          this.pending &&
          (step % 16 === 0 ||
            (step % 4 === 0 &&
              sectionShapeKey(snapshot) === sectionShapeKey(this.pending)))
        ) {
          const oldTime = this.origin + (this.nextStep * 15) / snapshot.bpm;
          const arrangementChanged =
            sectionMixKey(snapshot) !== sectionMixKey(this.pending);
          const tempoChanged = snapshot.bpm !== this.pending.bpm;
          this.current = this.pending;
          this.pending = undefined;
          snapshot = this.current;
          this.origin = oldTime - (this.nextStep * 15) / snapshot.bpm;
          this.compileSchedule(snapshot);
          if (arrangementChanged) {
            this.stopVoices(oldTime);
            this.visualHits = this.visualHits.filter(
              (hit) => hit.time < oldTime
            );
            this.resumeContinuous(
              snapshot,
              (this.nextStep / 4) % loopBeats,
              oldTime
            );
          } else if (tempoChanged) {
            // A loop's length was worked out from the old tempo.
            this.stopLoops(oldTime);
            this.resumeContinuous(
              snapshot,
              (this.nextStep / 4) % loopBeats,
              oldTime
            );
          }
          this.clock = [
            ...this.clock.slice(-3),
            { at: oldTime, beat: this.nextStep / 4, bpm: snapshot.bpm },
          ];
        }
        const time =
          this.origin +
          stepSeconds(this.nextStep, snapshot.bpm, snapshot.swing);
        for (const event of this.eventsByStep[step]) {
          const p = snapshot.performers.find(
            (p) => p.id === event.performerId
          )!;
          const asset = snapshot.assets.find((a) => a.id === p.assetId)!;
          const buffer = this.buffers.get(asset.audioId);
          if (buffer && time >= this.context!.currentTime) {
            const length =
              p.mode === "continuous_loop"
                ? ((loopBeats - step / 4) * 60) / snapshot.bpm
                : undefined;
            this.voice(
              this.context!,
              this.master!,
              buffer,
              p,
              time,
              event.velocity,
              length,
              0,
              { beat: step / 4, bpm: snapshot.bpm, project: snapshot }
            );
            this.scheduledHits++;
          }
        }
        this.nextStep++;
      }
    };
    window.clearInterval(this.timer);
    schedule();
    this.timer = window.setInterval(schedule, 25);
  }
  private compileSchedule(project: Project): void {
    this.eventsByStep = Array.from({ length: loopSteps }, () => []);
    const spotlit = project.performers.find((p) => p.id === this.spotlight);
    const events = spotlit
      ? [
          ...compileEvents(project).filter(
            (event) => event.performerId !== spotlit.id
          ),
          // Its whole card plays, even if it would be sitting out or muted right now.
          ...compileEvents({
            ...project,
            performers: [{ ...spotlit, mute: false, solo: false }],
            sections: project.sections.map((section) => ({
              ...section,
              kind: "groove" as const,
              leadId: null,
              mutedIds: [],
            })),
          }),
        ]
      : compileEvents(project);
    for (const event of events) this.eventsByStep[event.step].push(event);
  }
  visualFrame(): string {
    const heard = this.context ? this.audibleTime() : 0;
    const beat = this.beatAt(heard);
    const pulses: Record<string, number> = {};
    // The newest hit that has sounded, per character: [age in seconds, velocity].
    // Overlapping fast hits merge in `pulses`, so onsets are read from here.
    const onsets: Record<string, [number, number]> = {};
    if (this.context) {
      for (const hit of this.visualHits) {
        const age = heard - hit.time;
        const pulse = pulseAtAge(age, hit.duration) * hit.velocity;
        pulses[hit.id] = Math.max(pulses[hit.id] ?? 0, pulse);
        const newest = onsets[hit.id];
        if (age >= 0 && age < 1 && (!newest || age < newest[0]))
          onsets[hit.id] = [age, hit.velocity];
      }
    }
    return JSON.stringify({
      beat,
      pulses,
      onsets,
      playing: this.playing,
      masterPulse: this.playing
        ? pulseAtAge(beat % 1, 0.55) * (Math.floor(beat) % 4 === 0 ? 1 : 0.7)
        : 0,
    });
  }
  async impact(strength: number): Promise<void> {
    await this.unlock();
    const context = this.context!;
    const time = context.currentTime + 0.003;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.frequency.setValueAtTime(105, time);
    oscillator.frequency.exponentialRampToValueAtTime(42, time + 0.075);
    gain.gain.setValueAtTime(0.025 * strength, time);
    gain.gain.exponentialRampToValueAtTime(0.0001, time + 0.1);
    oscillator.connect(gain);
    gain.connect(this.master!);
    oscillator.onended = () => {
      oscillator.disconnect();
      gain.disconnect();
    };
    oscillator.start(time);
    oscillator.stop(time + 0.11);
  }
  private resumeContinuous(
    project: Project,
    beat: number,
    time: number,
    skip: ReadonlySet<string> = new Set(),
    scheduledBeat = beat
  ): void {
    const solo = project.performers.some((p) => p.solo);
    for (const p of project.performers) {
      const firstBeat = (p.steps[0] ?? loopSteps) / 4;
      if (
        skip.has(p.id) ||
        p.mode !== "continuous_loop" ||
        (p.id !== this.spotlight && (p.mute || (solo && !p.solo))) ||
        // Anything from here on will still be started by the scheduler.
        firstBeat >= scheduledBeat
      )
        continue;
      const asset = project.assets.find((a) => a.id === p.assetId)!;
      const buffer = this.buffers.get(asset.audioId);
      if (!buffer) continue;
      const elapsedS = (Math.max(0, beat - firstBeat) * 60) / project.bpm;
      this.voice(
        this.context!,
        this.master!,
        buffer,
        p,
        time,
        1,
        ((loopBeats - beat) * 60) / project.bpm,
        (elapsedS * p.rate) % buffer.duration,
        { beat, bpm: project.bpm, project }
      );
      this.scheduledHits++;
    }
  }
  /**
   * The mix answers at once: volume, pan, speed, position, mute, pattern, who sits out. Tempo and
   * swing land on the next beat, and reshaping song sections on the next bar, to stay in time.
   */
  async update(project: Project): Promise<void> {
    if (!this.context) return;
    const request = ++this.updateRequest;
    await this.prepare(project.assets);
    if (request !== this.updateRequest || !this.playing || !this.current)
      return;
    const next = structuredClone(project);
    const now = this.current;
    this.pending =
      next.bpm !== now.bpm ||
      next.swing !== now.swing ||
      sectionShapeKey(next) !== sectionShapeKey(now)
        ? next
        : undefined;
    this.current = {
      ...next,
      bpm: now.bpm,
      swing: now.swing,
      sections:
        sectionShapeKey(next) === sectionShapeKey(now)
          ? next.sections
          : now.sections,
    };
    this.compileSchedule(this.current);
    const sounding = new Set<string>();
    for (const voice of this.voices) {
      if (!voice.performerId) continue;
      const p = this.current.performers.find((p) => p.id === voice.performerId);
      if (!p || (voice.source.loop && p.mode !== "continuous_loop")) {
        this.silence(voice, this.context.currentTime);
        continue;
      }
      // A short hit still ringing out must not stop a performer's new loop from starting.
      if (voice.source.loop) sounding.add(p.id);
      this.retune(voice, p, this.current);
    }
    // A loop that was silent, or just arrived, should not wait for the loop to come around.
    const startsIn = 0.02;
    this.resumeContinuous(
      this.current,
      this.beat() + (startsIn * this.current.bpm) / 60,
      this.context.currentTime + startsIn,
      sounding,
      wrap(this.nextStep) / 4
    );
  }
  /** Hear one character clearly over a quiet band, or with null give the song back. */
  setSpotlight(id: string | null): void {
    if (id === this.spotlight) return;
    this.spotlight = id;
    if (!this.playing || !this.current || !this.context) return;
    this.compileSchedule(this.current);
    const sounding = new Set<string>();
    for (const voice of this.voices) {
      if (!voice.performerId) continue;
      const p = this.current.performers.find((p) => p.id === voice.performerId);
      if (!p) continue;
      if (voice.source.loop) sounding.add(p.id);
      this.retune(voice, p, this.current);
    }
    const startsIn = 0.02;
    this.resumeContinuous(
      this.current,
      this.beat() + (startsIn * this.current.bpm) / 60,
      this.context.currentTime + startsIn,
      sounding,
      wrap(this.nextStep) / 4
    );
  }
  /** Sound a tap straight away, unless the pattern is already playing that hit. */
  async tapNote(p: Performer, project: Project): Promise<void> {
    await this.unlock();
    const asset = project.assets.find((a) => a.id === p.assetId);
    if (!asset) return;
    await this.prepare([asset]);
    const now = this.context!.currentTime;
    for (const voice of this.voices)
      if (
        voice.performerId === p.id &&
        Math.abs(voice.time - now) < TAP_ALREADY_SOUNDING_S
      )
        return;
    const song = this.current ?? project;
    this.voice(
      this.context!,
      this.master!,
      this.buffers.get(asset.audioId)!,
      p,
      now + 0.003,
      1,
      undefined,
      0,
      { beat: this.beat(), bpm: song.bpm, project: song }
    );
  }
  /** Loop one section, jumping there now if playing. With null, play on into the whole song. */
  focusSection(range: { startBeat: number; endBeat: number } | null): void {
    if (!range) {
      this.range = undefined;
      return;
    }
    this.range = { start: range.startBeat * 4, end: range.endBeat * 4 };
    this.cursor = range.startBeat;
    if (this.playing && this.current)
      void this.play(this.pending ?? this.current);
  }
  /** Hear a performer where it is being dragged, before the drop commits the move. */
  previewPosition(
    id: string,
    position: { x: number; y: number },
    project: Project
  ): void {
    this.playDraggedNote(id, position, project);
    if (!this.playing || !this.current || !this.context) return;
    const p = this.current.performers.find((p) => p.id === id);
    if (!p) return;
    const beat = this.beat();
    const before = stageGain(p, beat);
    const hadPath = p.path.length > 0;
    p.position = position;
    p.path = [];
    if (this.pending) {
      const later = this.pending.performers.find((p) => p.id === id);
      if (later) Object.assign(later, { position, path: [] });
    }
    if (!p.tuned && !hadPath && stageGain(p, beat) === before) return;
    for (const voice of this.voices)
      if (voice.performerId === id) this.retune(voice, p, this.current);
  }
  /** A tuned character sounds its new note as it is dragged across each row. */
  private playDraggedNote(
    id: string,
    position: { x: number; y: number },
    project: Project
  ): void {
    const p = project.performers.find((p) => p.id === id);
    if (!p?.tuned || !this.context || !this.master) return;
    const row = noteRow(position.y);
    if (this.draggedRow?.id === id && this.draggedRow.row === row) return;
    const moved = this.draggedRow?.id === id;
    this.draggedRow = { id, row };
    if (!moved) return;
    const asset = project.assets.find((a) => a.id === p.assetId);
    const buffer = asset && this.buffers.get(asset.audioId);
    if (buffer)
      this.voice(
        this.context,
        this.master,
        buffer,
        { ...p, position, path: [] },
        this.context.currentTime + 0.005,
        0.8
      );
  }
  /** Where the scheduler is: the render clock, which runs ahead of what can be heard. */
  beat(): number {
    return this.beatAt(this.context?.currentTime ?? 0);
  }
  private beatAt(time: number): number {
    if (!this.playing || !this.context || !this.clock.length)
      return this.cursor;
    let segment = this.clock[0];
    for (const s of this.clock) if (s.at <= time) segment = s;
    return wrap(
      segment.beat + (Math.max(0, time - segment.at) * segment.bpm) / 60,
      loopBeats
    );
  }
  /**
   * The moment of the song leaving the speakers, for drawing. `currentTime` only moves once per
   * audio callback (often 10-40 ms) and leads the speakers by the output latency, so the stage
   * would step and bounce early. The drawn clock runs on frame time and eases toward the output
   * timestamp, so neither a late stamp nor a correction can make it stall or jump.
   */
  private audibleTime(): number {
    const context = this.context!;
    const now = performance.now();
    const running = context.state === "running";
    const target = this.measuredAudibleTime(context, now, running);
    const predicted =
      this.audible.time +
      (running ? Math.max(0, now - this.audible.frame) / 1000 : 0);
    const error = target - predicted;
    let time =
      Math.abs(error) > VISUAL_SNAP_S
        ? target
        : predicted + error * VISUAL_EASE;
    // Never backwards, and never well past what has been rendered.
    time = Math.min(
      Math.max(time, this.audible.time),
      context.currentTime + VISUAL_SNAP_S
    );
    this.audible = { time, frame: now };
    return time;
  }
  private measuredAudibleTime(
    context: AudioContext,
    now: number,
    running: boolean
  ): number {
    const stamp =
      typeof context.getOutputTimestamp === "function"
        ? context.getOutputTimestamp()
        : undefined;
    if (
      running &&
      stamp?.contextTime !== undefined &&
      stamp.performanceTime !== undefined &&
      stamp.performanceTime > 0
    )
      return (
        stamp.contextTime +
        Math.min(Math.max(0, now - stamp.performanceTime), 100) / 1000
      );
    if (context.currentTime !== this.renderedAt.context)
      this.renderedAt = { context: context.currentTime, frame: now };
    return (
      this.renderedAt.context +
      (running ? Math.min(now - this.renderedAt.frame, 50) / 1000 : 0) -
      (context.outputLatency || context.baseLatency || 0)
    );
  }
  pause(): void {
    this.playRequest++;
    this.cursor = this.beat();
    this.playing = false;
    this.visualHits = [];
    this.epoch++;
    window.clearInterval(this.timer);
    this.stopVoices();
  }
  seek(beat: number): void {
    this.pause();
    this.cursor = wrap(beat, loopBeats);
  }
  private stopVoices(at?: number): void {
    if (!this.context) return;
    const time = at ?? this.context.currentTime;
    for (const v of this.voices) this.silence(v, time);
  }
  private stopLoops(at: number): void {
    for (const voice of this.voices)
      if (voice.source.loop) this.silence(voice, at);
  }
  private silence(voice: Voice, time: number): void {
    voice.gain.gain.cancelScheduledValues(time);
    voice.gain.gain.setTargetAtTime(0, time, 0.004);
    voice.source.stop(time + 0.025);
    this.voices.delete(voice);
  }
  async export(project: Project): Promise<Blob> {
    await this.unlock();
    await this.prepare(project.assets);
    const duration = (loopBeats * 60) / project.bpm;
    const context = new OfflineAudioContext(
      2,
      Math.ceil(duration * 44100),
      44100
    );
    const compressor = context.createDynamicsCompressor();
    compressor.threshold.value = -8;
    compressor.ratio.value = 12;
    compressor.connect(context.destination);
    for (const event of compileEvents(project)) {
      const p = project.performers.find((p) => p.id === event.performerId)!,
        asset = project.assets.find((a) => a.id === p.assetId)!;
      const time = stepSeconds(event.step, project.bpm, project.swing);
      this.voice(
        context,
        compressor,
        this.buffers.get(asset.audioId)!,
        p,
        time,
        event.velocity,
        p.mode === "continuous_loop" ? duration - time : undefined,
        0,
        { beat: event.step / 4, bpm: project.bpm, project }
      );
    }
    return encodeWav(await context.startRendering());
  }
}
