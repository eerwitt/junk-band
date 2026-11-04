import {
  gateway,
  type CharacterJob,
  type Health,
  type Job,
  type Media,
} from "../../services/gateway";
import { saveBlob } from "../../storage/database";
import type { Rig } from "../../domain/project";
import { button, element, setBlocked } from "../dom";
import { PaperWait, type WaitNote, type WaitView } from "../paper-wait";
import type { StudioStore } from "../store";
import type { Made } from "./objects-phase";

const SOUND_STEPS = ["Send", "Snip", "Bring back"] as const;
const SOUND_STAGE_STEP = { sending: 0, separating: 1, collecting: 2 } as const;
const LOOK_STEPS = ["Cut out", "Paint", "Cut again"] as const;
const SOUND_NOTES: readonly WaitNote[] = [
  [0, "Listen to the original clip while you wait."],
  [
    20,
    "Still snipping. A worker that has been asleep has to wake up first, so the first sound can take a couple of minutes.",
  ],
  [
    240,
    "This is a long one, but nothing is lost. The original clip still works if you'd rather not wait.",
  ],
];
const CUT_NOTES: readonly WaitNote[] = [
  [15, "Still cutting carefully. This can take up to a minute."],
];
const PAINT_NOTES: readonly WaitNote[] = [
  [45, "Still painting. You can add the cutout right now."],
];
const MISSED_POLLS_ALLOWED = 4;
const WAVE_BARS = 96;

export interface ReviewSource {
  file: File;
  url: string;
  media: Media;
}

type Look = "cutout" | "painted";
type Sound = "separated" | "original";
interface Cutout {
  id: string;
  url: string;
  cardUrl: string;
  name: string;
  provenance: string;
}

const queueLine = (ahead: number): string =>
  ahead === 1
    ? "One request ahead of you in the queue…"
    : `${ahead} requests ahead of you in the queue…`;
const message = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

/** Two A/B choices, look and sound, made while the work arrives. */
function choice(
  label: string,
  options: readonly [string, string],
  pick: (index: number) => void
): { root: HTMLElement; buttons: HTMLButtonElement[] } {
  const root = element("div", "review-choice");
  root.setAttribute("role", "group");
  root.setAttribute("aria-label", label);
  const buttons = options.map((text, index) => button(text, () => pick(index)));
  root.append(...buttons);
  return { root, buttons };
}

/**
 * Everything starts at once: the sound, the cutout, and its painting once the cutout is ready.
 * You compare as they arrive, then add.
 */
export class ReviewPhase {
  readonly root = element("section", "review-phase");
  private lookPanel = element("div", "review-panel review-look");
  private lookStage = element("div", "review-stage");
  private lookImage = element("img", "review-art");
  private lookWait = new PaperWait();
  private paintWait = new PaperWait();
  private lookNote = element("p", "fine");
  private lookRetry = button(
    "Try again",
    () => this.retryLook(),
    "text-button"
  );
  private looks = choice("Look", ["Cutout", "Painted"], (index) => {
    this.look = index ? "painted" : "cutout";
    this.pickedLook = true;
    this.render();
  });
  private soundStage = element("div", "review-stage review-sound-stage");
  private soundWait = new PaperWait();
  private wave = element("canvas", "review-wave");
  private play = button("Play", () => this.togglePlay());
  private time = element("span", "preview-time");
  private soundNote = element("p", "fine");
  private soundRetry = button(
    "Try again",
    () => this.startSound(),
    "text-button"
  );
  private sounds = choice("Sound", ["Separated", "Original clip"], (index) =>
    this.chooseSound(index ? "original" : "separated", true)
  );
  private status = element("p", "feedback");
  private addButton = button("Add to band", () => void this.add(), "primary");
  private source?: ReviewSource;
  private made?: Made;
  private start = 0;
  private end = 0;
  private soundKey = "";
  private cutKey = "";
  private job?: Job;
  private soundProblem = "";
  private soundLost = false;
  private cutout?: Cutout;
  private cutting = false;
  private cutProblem = "";
  private character?: CharacterJob;
  private painting = false;
  private paintProblem = "";
  private look: Look = "cutout";
  private pickedLook = false;
  private sound: Sound = "separated";
  private pickedSound = false;
  private players: Partial<Record<Sound, HTMLAudioElement>> = {};
  private waves: Partial<Record<Sound, Float32Array>> = {};
  private playing = false;
  private adding = false;
  private soundEpoch = 0;
  private cutEpoch = 0;
  private soundPoll?: AbortController;
  private paintPoll?: AbortController;
  private service?: Health;

  constructor(
    private readonly store: StudioStore,
    private readonly isOpen: () => boolean,
    private readonly onDone: () => void,
    onBack: () => void
  ) {
    this.lookImage.alt = "";
    this.lookImage.draggable = false;
    this.lookStage.append(this.lookImage, this.lookWait.root);
    this.paintWait.root.classList.add("review-progress");
    const lookNotes = element("div", "review-notes");
    lookNotes.append(this.lookNote, this.lookRetry);
    this.lookPanel.append(
      element("h3", "", "Its look"),
      this.lookStage,
      this.looks.root,
      this.paintWait.root,
      lookNotes
    );
    this.wave.setAttribute("aria-hidden", "true");
    this.wave.addEventListener("pointerdown", (event) => this.scrub(event));
    const transport = element("div", "review-transport");
    transport.append(this.play, this.time);
    this.soundStage.append(this.wave, transport, this.soundWait.root);
    const soundNotes = element("div", "review-notes");
    soundNotes.append(this.soundNote, this.soundRetry);
    const soundPanel = element("div", "review-panel review-sound");
    soundPanel.append(
      element("h3", "", "Its sound"),
      this.soundStage,
      this.sounds.root,
      soundNotes
    );
    const panels = element("div", "review-panels");
    panels.append(this.lookPanel, soundPanel);
    this.status.setAttribute("role", "status");
    const actions = element("div", "phase-actions");
    actions.append(
      button("Back", onBack, "text-button"),
      this.status,
      this.addButton
    );
    this.root.append(panels, actions);
  }

  setService(service?: Health): void {
    this.service = service;
    this.render();
  }

  /** Forget every job, as for a new source. */
  reset(): void {
    this.soundEpoch++;
    this.cutEpoch++;
    this.soundPoll?.abort();
    this.paintPoll?.abort();
    this.soundKey = this.cutKey = "";
    this.job = undefined;
    this.cutout = undefined;
    this.character = undefined;
    this.cutting = this.painting = false;
    this.soundWait.hide();
    this.lookWait.hide();
    this.paintWait.hide();
    this.pause();
  }

  pause(): void {
    for (const player of Object.values(this.players)) player?.pause();
    this.playing = false;
    this.renderTransport();
  }

  /** Only the work whose inputs changed runs again. */
  open(
    source: ReviewSource,
    made: Made,
    window: { start: number; end: number }
  ): void {
    if (source.media.id !== this.source?.media.id) this.reset();
    this.source = source;
    this.made = made;
    this.start = window.start;
    this.end = window.end;
    this.status.textContent = "";
    this.lookPanel.hidden = !made.picture;
    this.root.classList.toggle("no-picture", !made.picture);
    const soundKey = `${window.start}:${window.end}:${made.description}`;
    if (soundKey !== this.soundKey) {
      this.soundKey = soundKey;
      this.setPlayer(
        "original",
        gateway.assetUrl(
          `/media/${encodeURIComponent(source.media.id)}/audio?start_s=${
            window.start
          }&end_s=${window.end}`
        )
      );
      this.startSound();
    }
    const cutKey = made.picture?.key ?? "";
    if (cutKey !== this.cutKey) {
      this.cutKey = cutKey;
      if (made.picture) this.startCut();
    }
    this.render();
  }

  // ---- Sound -------------------------------------------------------------------------------

  private startSound(): void {
    const source = this.source;
    const made = this.made;
    if (!source || !made) return;
    const epoch = ++this.soundEpoch;
    this.soundPoll?.abort();
    this.soundProblem = "";
    this.soundLost = false;
    this.job = undefined;
    this.setPlayer("separated");
    if (!this.pickedSound) this.chooseSound("separated");
    if (this.service && !this.service.audio) {
      this.soundProblem =
        "Sound separation is unavailable on this server. The original clip still works.";
      this.chooseSound("original");
      this.render();
      return;
    }
    this.soundWait.show({
      scene: "sound",
      image: made.picture?.preview,
      steps: SOUND_STEPS,
      step: 0,
      line: "Handing the clip to the sound worker…",
      notes: SOUND_NOTES,
    });
    this.render();
    void (async () => {
      try {
        const job = await gateway.separate(
          source.media.id,
          this.start,
          this.end,
          made.description
        );
        if (epoch !== this.soundEpoch) return;
        this.job = job;
        await this.pollSound(job.id, epoch);
      } catch (error) {
        if (epoch !== this.soundEpoch) return;
        this.soundProblem = message(error);
        this.soundWait.hide();
        this.soundFailed();
      }
    })();
  }

  private soundRunning(): boolean {
    return (
      !this.soundLost &&
      (this.job?.status === "queued" || this.job?.status === "processing")
    );
  }

  private soundView(job: Job): WaitView {
    if (job.provenance !== "SAM Audio")
      return {
        scene: null,
        line: "Demo tools: copying the raw clip. No separation is happening.",
        notes: [],
      };
    const stage = job.stage ?? "sending";
    return {
      scene: "sound",
      image: this.cutout ? gateway.assetUrl(this.cutout.url) : undefined,
      steps: SOUND_STEPS,
      step: SOUND_STAGE_STEP[stage],
      line: job.queue_position
        ? queueLine(job.queue_position)
        : stage === "sending"
        ? "Handing the clip to the sound worker…"
        : stage === "collecting"
        ? "Bringing it back to the bench…"
        : `Snipping “${this.made?.description}” away from everything around it…`,
      notes: SOUND_NOTES,
    };
  }

  private async pollSound(id: string, epoch: number): Promise<void> {
    const controller = new AbortController();
    this.soundPoll = controller;
    let missed = 0;
    while (epoch === this.soundEpoch && this.job && this.soundRunning()) {
      this.soundWait.show(this.soundView(this.job));
      this.render();
      await new Promise((resolve) => window.setTimeout(resolve, 700));
      if (epoch !== this.soundEpoch) return;
      try {
        const result = await gateway.job(id, controller.signal);
        if (epoch !== this.soundEpoch) return;
        this.job = result;
        missed = 0;
      } catch (error) {
        // One lost status check says nothing about a job that runs for minutes.
        if (controller.signal.aborted) return;
        if (++missed > MISSED_POLLS_ALLOWED) {
          this.soundLost = true;
          this.soundProblem = `Status check failed: ${String(error)}.`;
        }
      }
    }
    if (epoch !== this.soundEpoch) return;
    this.soundWait.hide();
    if (this.job?.status === "ready" && this.job.target_url) {
      this.setPlayer("separated", gateway.assetUrl(this.job.target_url));
      this.noticeIfClosed("Its sound is ready to hear. Open Add.");
    } else {
      if (this.job?.status === "failed")
        this.soundProblem = this.job.error ?? "That sound failed.";
      this.soundFailed();
      this.noticeIfClosed("That sound did not come through. Open Add.");
    }
    this.render();
  }

  private soundFailed(): void {
    if (!this.pickedSound) this.chooseSound("original");
    this.render();
  }

  private separatedReady(): boolean {
    return this.job?.status === "ready" && Boolean(this.players.separated);
  }

  private setPlayer(which: Sound, url?: string): void {
    const old = this.players[which];
    old?.pause();
    if (old && this.sound === which) this.playing = false;
    delete this.players[which];
    delete this.waves[which];
    if (!url) return;
    const player = element("audio");
    player.preload = "auto";
    player.loop = true;
    player.src = url;
    player.addEventListener("ended", () => this.renderTransport());
    this.players[which] = player;
    void this.loadWave(which, url, player);
  }

  /** The waveform is drawn once from the real file, like the workbench's ink strand. */
  private async loadWave(
    which: Sound,
    url: string,
    player: HTMLAudioElement
  ): Promise<void> {
    try {
      const response = await fetch(url, { credentials: "include" });
      const decoded = await new OfflineAudioContext(1, 1, 8000).decodeAudioData(
        await response.arrayBuffer()
      );
      if (this.players[which] !== player) return;
      const samples = decoded.getChannelData(0);
      const bars = new Float32Array(WAVE_BARS);
      const size = Math.max(1, Math.floor(samples.length / WAVE_BARS));
      for (let bar = 0; bar < WAVE_BARS; bar++) {
        let peak = 0;
        for (let index = bar * size; index < (bar + 1) * size; index++)
          peak = Math.max(peak, Math.abs(samples[index] ?? 0));
        bars[bar] = peak;
      }
      this.waves[which] = bars;
      this.drawWave();
    } catch {
      // The sound still plays without its picture.
    }
  }

  private chooseSound(which: Sound, picked = false): void {
    if (picked) this.pickedSound = true;
    if (which === this.sound) {
      this.render();
      return;
    }
    const from = this.players[this.sound];
    const to = this.players[which];
    this.sound = which;
    // Switching while it plays keeps the place, so the two can be compared directly.
    if (this.playing && from && to) {
      to.currentTime = from.currentTime;
      from.pause();
      void to.play().catch(() => undefined);
    } else {
      from?.pause();
      this.playing = false;
    }
    this.render();
  }

  private togglePlay(): void {
    const player = this.players[this.sound];
    if (!player) return;
    if (this.playing) {
      this.pause();
      return;
    }
    this.playing = true;
    void player.play().catch(() => {
      this.playing = false;
      this.renderTransport();
    });
    const tick = (): void => {
      if (!this.playing || this.players[this.sound] !== player) {
        this.renderTransport();
        return;
      }
      this.renderTransport();
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  private scrub(event: PointerEvent): void {
    const player = this.players[this.sound];
    if (!player || !player.duration) return;
    const bounds = this.wave.getBoundingClientRect();
    player.currentTime =
      Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)) *
      player.duration;
    this.renderTransport();
  }

  private renderTransport(): void {
    const player = this.players[this.sound];
    const length = this.end - this.start;
    const into = Math.min(length, player?.currentTime ?? 0);
    this.time.textContent = `${into.toFixed(1)} / ${length.toFixed(1)} s`;
    this.play.textContent = this.playing ? "Pause" : "Play";
    setBlocked(this.play, player ? "" : "Its sound is still being separated.");
    this.drawWave();
  }

  private drawWave(): void {
    const canvas = this.wave;
    const width = Math.round(canvas.clientWidth * devicePixelRatio);
    const height = Math.round(canvas.clientHeight * devicePixelRatio);
    if (!width || !height) return;
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    const context = canvas.getContext("2d")!;
    context.clearRect(0, 0, width, height);
    const bars = this.waves[this.sound];
    const player = this.players[this.sound];
    const done = player?.duration ? player.currentTime / player.duration : 0;
    const step = width / WAVE_BARS;
    const loudest = bars ? Math.max(0.05, ...bars) : 1;
    for (let bar = 0; bar < WAVE_BARS; bar++) {
      const level = bars ? bars[bar] / loudest : 0.04;
      const tall = Math.max(2, level * height * 0.9);
      context.fillStyle =
        (bar + 0.5) / WAVE_BARS < done
          ? "#29271f"
          : this.sound === "separated"
          ? "#b86339"
          : "#a59c88";
      context.fillRect(
        bar * step + step * 0.2,
        (height - tall) / 2,
        step * 0.6,
        tall
      );
    }
  }

  // ---- Look --------------------------------------------------------------------------------

  private startCut(): void {
    const source = this.source;
    const picture = this.made?.picture;
    if (!source || !picture) return;
    const epoch = ++this.cutEpoch;
    this.paintPoll?.abort();
    this.paintWait.hide();
    this.cutout = undefined;
    this.character = undefined;
    this.cutProblem = this.paintProblem = "";
    this.cutting = true;
    this.painting = false;
    if (!this.pickedLook) this.look = "cutout";
    this.lookWait.show({
      scene: "cut",
      image: picture.preview,
      steps: LOOK_STEPS,
      step: 0,
      line: "Cutting around what you painted…",
      notes: CUT_NOTES,
    });
    this.render();
    void (async () => {
      try {
        const media = source.media;
        let found: Cutout | undefined;
        if (!this.service || this.service.sam) {
          const picked = await gateway.pick(
            media.id,
            picture.frameS,
            picture.box,
            null,
            this.start,
            this.end
          );
          if (!picked.provenance.startsWith("Rough selection"))
            found = {
              id: picked.cutout_id,
              url: picked.cutout_url,
              cardUrl: picked.card_url,
              name: picked.name,
              provenance: picked.provenance,
            };
        }
        // With nothing better found, the painted mask itself is the cutout.
        if (!found) {
          const own = await gateway.maskCutout(
            media.id,
            picture.frameS,
            picture.mask
          );
          found = {
            id: own.cutout_id,
            url: own.cutout_url,
            cardUrl: own.card_url ?? own.cutout_url,
            name: "",
            provenance: own.provenance,
          };
        }
        if (epoch !== this.cutEpoch) return;
        this.cutout = found;
        this.cutting = false;
        this.lookWait.hide();
        this.startPainting();
      } catch (error) {
        if (epoch !== this.cutEpoch) return;
        this.cutting = false;
        this.cutProblem = message(error);
        this.lookWait.hide();
        this.render();
      }
    })();
  }

  private startPainting(): void {
    const cutout = this.cutout;
    if (!cutout) return;
    const epoch = this.cutEpoch;
    this.paintPoll?.abort();
    this.character = undefined;
    this.paintProblem = "";
    if (this.service && !this.service.image) {
      this.paintProblem = "Painting is unavailable on this server.";
      this.render();
      return;
    }
    this.painting = true;
    this.showPaintWait();
    this.render();
    void (async () => {
      try {
        const job = await gateway.character(cutout.id, this.name(), "");
        if (epoch !== this.cutEpoch) return;
        this.character = job;
        await this.pollPainting(job.id, epoch);
      } catch (error) {
        if (epoch !== this.cutEpoch) return;
        this.painting = false;
        this.paintProblem = message(error);
        this.paintWait.hide();
        this.render();
      }
    })();
  }

  private showPaintWait(): void {
    const stage = this.character?.stage ?? "painting";
    this.paintWait.show({
      scene: null,
      steps: LOOK_STEPS,
      step: stage === "painting" ? 1 : 2,
      line: this.character?.queue_position
        ? queueLine(this.character.queue_position)
        : stage === "painting"
        ? "Painting it in cut paper…"
        : "Cutting around the new picture…",
      notes: PAINT_NOTES,
    });
  }

  private async pollPainting(id: string, epoch: number): Promise<void> {
    const controller = new AbortController();
    this.paintPoll = controller;
    let missed = 0;
    const running = (): boolean =>
      this.character?.status === "queued" ||
      this.character?.status === "processing";
    while (epoch === this.cutEpoch && running()) {
      this.showPaintWait();
      this.render();
      await new Promise((resolve) => window.setTimeout(resolve, 850));
      if (epoch !== this.cutEpoch) return;
      try {
        const result = await gateway.characterJob(id, controller.signal);
        if (epoch !== this.cutEpoch) return;
        this.character = result;
        missed = 0;
      } catch (error) {
        if (controller.signal.aborted) return;
        if (++missed > MISSED_POLLS_ALLOWED) {
          this.character = undefined;
          this.paintProblem = `Could not check the painting: ${String(error)}.`;
          break;
        }
      }
    }
    if (epoch !== this.cutEpoch) return;
    this.painting = false;
    this.paintWait.hide();
    if (this.character?.status === "ready") {
      if (!this.pickedLook) this.look = "painted";
      this.noticeIfClosed("Your band member is painted. Open Add.");
    } else if (this.character?.status === "failed") {
      this.paintProblem =
        this.character.error ?? "Painting could not finish. Try again.";
      this.noticeIfClosed("The painted version did not finish. Open Add.");
    }
    this.render();
  }

  private painted(): string | undefined {
    return this.character?.status === "ready"
      ? this.character.character_url ?? undefined
      : undefined;
  }

  private retryLook(): void {
    if (this.cutout) this.startPainting();
    else this.startCut();
  }

  private name(): string {
    return (this.cutout?.name || this.made?.description || "Found sound").slice(
      0,
      80
    );
  }

  // ---- Shared ------------------------------------------------------------------------------

  private noticeIfClosed(text: string): void {
    if (!this.isOpen()) this.store.notice(text);
  }

  private render(): void {
    const painted = this.painted();
    if (this.look === "painted" && !painted) this.look = "cutout";
    const shown =
      this.look === "painted" ? painted : this.cutout?.cardUrl ?? undefined;
    if (shown) {
      const url = gateway.assetUrl(shown);
      if (this.lookImage.getAttribute("src") !== url) this.lookImage.src = url;
    }
    this.lookImage.hidden = !shown;
    const [cutoutChoice, paintedChoice] = this.looks.buttons;
    cutoutChoice.setAttribute("aria-pressed", String(this.look === "cutout"));
    paintedChoice.setAttribute("aria-pressed", String(this.look === "painted"));
    setBlocked(cutoutChoice, this.cutout ? "" : "Still cutting it out.");
    setBlocked(
      paintedChoice,
      painted
        ? ""
        : this.painting || this.cutting
        ? "Still painting. It switches over by itself when it's done."
        : this.paintProblem || "Not painted."
    );
    this.looks.root.hidden = !this.cutout;
    this.lookNote.textContent =
      this.cutProblem ||
      this.paintProblem ||
      (this.look === "painted"
        ? this.character?.provenance ?? ""
        : this.cutout
        ? `Cut out from the frame · ${this.cutout.provenance}`
        : "");
    this.lookNote.classList.toggle(
      "error",
      Boolean(this.cutProblem || this.paintProblem)
    );
    this.lookRetry.hidden =
      !(this.cutProblem || this.paintProblem) ||
      Boolean(this.service && !this.service.image && this.cutout);

    const [separatedChoice, originalChoice] = this.sounds.buttons;
    separatedChoice.setAttribute(
      "aria-pressed",
      String(this.sound === "separated")
    );
    originalChoice.setAttribute(
      "aria-pressed",
      String(this.sound === "original")
    );
    const separating = !this.separatedReady() && !this.soundProblem;
    setBlocked(
      separatedChoice,
      separating || this.separatedReady()
        ? ""
        : this.soundProblem || "Not separated."
    );
    this.soundStage.classList.toggle(
      "waiting",
      this.sound === "separated" && separating
    );
    this.soundNote.textContent =
      this.soundProblem ||
      (this.sound === "original"
        ? "Exactly what you trimmed, nothing taken away."
        : this.job?.status === "ready"
        ? this.job.provenance === "SAM Audio"
          ? "SAM Audio pulled this out. Check it is the sound you meant."
          : "Demo tools: this is a raw copy. No separation happened."
        : "");
    this.soundNote.classList.toggle("error", Boolean(this.soundProblem));
    this.soundRetry.hidden =
      !this.soundProblem || Boolean(this.service && !this.service.audio);

    const wait = this.adding ? "Adding to the band…" : "";
    setBlocked(
      this.addButton,
      wait ||
        (this.made?.picture && !this.cutout
          ? this.cutProblem
            ? "Its cutout failed. Try again, or go back and paint it again."
            : "Wait for it to be cut out."
          : "") ||
        (this.sound === "separated" && !this.separatedReady()
          ? "Its sound is still being separated. Pick Original clip to add it now."
          : "")
    );
    this.renderTransport();
  }

  private async add(): Promise<void> {
    const source = this.source;
    if (!source || this.adding) return;
    this.adding = true;
    this.render();
    try {
      const id = crypto.randomUUID();
      const original = this.sound === "original";
      const path = original
        ? `/media/${source.media.id}/audio?start_s=${this.start}&end_s=${this.end}`
        : this.job?.target_url;
      if (!path) throw new Error("Its sound is not ready yet.");
      await saveBlob(id, await gateway.blob(path));
      const cutout = this.cutout;
      const styled = this.look === "painted" ? this.painted() : undefined;
      let sprite = "/sprites.png";
      let sourceSprite: string | undefined;
      let rig: Rig | undefined;
      if (cutout) {
        await saveBlob(
          `sprite-${id}`,
          await gateway.blob(styled ?? cutout.cardUrl)
        );
        sprite = sourceSprite = `blob:asset:sprite-${id}`;
        if (styled) {
          await saveBlob(
            `sprite-source-${id}`,
            await gateway.blob(cutout.cardUrl)
          );
          sourceSprite = `blob:asset:sprite-source-${id}`;
          rig = await this.saveRig(id);
        }
      }
      this.store.add({
        id,
        label: this.name(),
        color: "#b37850",
        sprite,
        ...(rig ? { rig } : {}),
        ...(cutout ? {} : { tile: 0 }),
        audioId: id,
        provenance: original
          ? "raw import"
          : this.job?.provenance === "SAM Audio"
          ? "SAM Audio"
          : "mock candidate",
        sourceId: source.media.id,
        startS: this.start,
        endS: this.end,
        ...(sourceSprite && cutout
          ? {
              sourceSprite,
              visualProvenance: styled
                ? this.character!.provenance
                : `Cut out from the source frame on white paper · ${cutout.provenance}`,
            }
          : {}),
      });
      // Anything still running was chosen against, so its later result is no longer news.
      this.reset();
      this.source = undefined;
      this.onDone();
    } catch (error) {
      this.status.textContent = message(error);
      this.status.classList.add("error");
    } finally {
      this.adding = false;
      this.render();
    }
  }

  /** Older painting jobs could return limb layers; keep them with the character. */
  private async saveRig(id: string): Promise<Rig | undefined> {
    const candidate = this.character?.rig;
    if (!candidate) return undefined;
    const body = `rig-body-${id}`;
    await saveBlob(body, await gateway.blob(candidate.body_url));
    const parts: Rig["parts"] = [];
    for (const part of candidate.parts) {
      const partId = `rig-${part.name}-${id}`;
      await saveBlob(partId, await gateway.blob(part.url));
      parts.push({
        name: part.name,
        sprite: `blob:asset:${partId}`,
        pivot: { x: part.pivot[0], y: part.pivot[1] },
        maxAngle: part.max_angle,
      });
    }
    return {
      width: candidate.width,
      height: candidate.height,
      body: `blob:asset:${body}`,
      parts,
    };
  }
}
