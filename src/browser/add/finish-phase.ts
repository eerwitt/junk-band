import {
  gateway,
  type CharacterJob,
  type Health,
  type Job,
  type Media,
} from "../../services/gateway";
import { saveBlob } from "../../storage/database";
import type { Rig } from "../../domain/project";
import {
  audioControl,
  button,
  element,
  field,
  setBlocked,
  textInput,
} from "../dom";
import { PaperWait, type WaitNote, type WaitView } from "../paper-wait";
import type { StudioStore } from "../store";
import type { Chosen } from "./objects-phase";
import { cardFibre, videoCard } from "./video-card";

const SOUND_STEPS = ["Send", "Snip", "Bring back"] as const;
const SOUND_STAGE_STEP = { sending: 0, separating: 1, collecting: 2 } as const;
const CHARACTER_STEPS = ["Paint", "Cut out"] as const;
const SOUND_NOTES: readonly WaitNote[] = [
  [
    0,
    "The band keeps playing. Close this if you like; we'll leave a note when this is done.",
  ],
  [
    20,
    "Still snipping. A worker that has been asleep has to wake up first, so the first sound can take a couple of minutes.",
  ],
  [
    240,
    "This is a long one, but nothing is lost. Raw audio still works if you'd rather not wait.",
  ],
];
const CHARACTER_NOTES: readonly WaitNote[] = [
  [60, "Still painting. You can add it as is right now."],
];
const MISSED_POLLS_ALLOWED = 4;

export interface FinishSource {
  file: File;
  url: string;
  media: Media;
}

/** Sound and character are made at the same time; the choice comes when they arrive. */
const queueLine = (ahead: number): string =>
  ahead === 1
    ? "One request ahead of you in the queue…"
    : `${ahead} requests ahead of you in the queue…`;

export class FinishPhase {
  readonly root = element("section", "finish-phase");
  private previewBox = element("div", "finish-preview");
  private previewPlay = button("Play", () => this.togglePreview());
  private previewTime = element("span", "preview-time");
  private video?: HTMLVideoElement;
  private soundColumn = element("div", "finish-column");
  private soundWait = new PaperWait();
  private soundResult = element("div", "finish-result");
  private soundName = textInput("Sound to pull");
  private soundRetry = button("Pull this sound", () => this.startSound());
  private lookColumn = element("div", "finish-column");
  private lookWait = new PaperWait();
  private looks = element("div", "finish-looks");
  private lookNote = element("p", "fine");
  private details = textInput("Character details (optional)");
  private paintAgain = button("Paint it again", () => this.startCharacter());
  private status = element("p", "feedback");
  private addButton = button(
    "Add to band",
    () => void this.add(false),
    "primary"
  );
  private rawButton = button(
    "Use raw audio",
    () => void this.add(true),
    "text-button"
  );
  private backButton: HTMLButtonElement;
  private source?: FinishSource;
  private chosen?: Chosen;
  private start = 0;
  private end = 0;
  private job?: Job;
  private character?: CharacterJob;
  private characterProblem = "";
  private soundProblem = "";
  private soundLost = false;
  private useStyled = false;
  private pickedLook = false;
  private adding = false;
  private soundEpoch = 0;
  private artEpoch = 0;
  private soundPoll?: AbortController;
  private artPoll?: AbortController;
  private service?: Health;
  private usedDirection = "";

  constructor(
    private readonly store: StudioStore,
    private readonly isOpen: () => boolean,
    private readonly onDone: () => void,
    onBack: () => void
  ) {
    this.backButton = button("Choose another object", onBack, "text-button");
    this.status.setAttribute("role", "status");
    this.soundName.addEventListener("input", () => this.update());
    this.details.addEventListener("input", () => this.update());
    const soundHeading = element("h3", "", "Its sound");
    const soundRow = element("div", "finish-retry");
    soundRow.append(field("Sound to pull", this.soundName), this.soundRetry);
    this.soundColumn.append(
      soundHeading,
      this.soundWait.root,
      this.soundResult,
      soundRow
    );
    const lookHeading = element("h3", "", "Its look");
    const lookRow = element("div", "finish-retry");
    lookRow.append(
      field("Character details (optional)", this.details),
      this.paintAgain
    );
    this.lookColumn.append(
      lookHeading,
      this.lookWait.root,
      this.looks,
      this.lookNote,
      lookRow
    );
    const actions = element("div", "phase-actions");
    actions.append(
      this.backButton,
      this.status,
      this.rawButton,
      this.addButton
    );
    const columns = element("div", "finish-columns");
    columns.append(this.previewBox, this.soundColumn, this.lookColumn);
    this.root.append(columns, actions);
  }

  setService(service?: Health): void {
    this.service = service;
    this.update();
  }

  reset(): void {
    this.soundEpoch++;
    this.artEpoch++;
    this.soundPoll?.abort();
    this.artPoll?.abort();
    this.job = undefined;
    this.character = undefined;
    this.soundWait.hide();
    this.lookWait.hide();
    this.video?.pause();
  }

  pause(): void {
    this.video?.pause();
  }

  /** Begin both jobs together. */
  open(
    source: FinishSource,
    chosen: Chosen | undefined,
    sound: string,
    window: { start: number; end: number }
  ): void {
    this.reset();
    this.source = source;
    this.chosen = chosen;
    this.start = window.start;
    this.end = window.end;
    this.useStyled = false;
    this.pickedLook = false;
    this.soundProblem = "";
    this.characterProblem = "";
    this.soundLost = false;
    this.status.textContent = "";
    this.status.classList.remove("error");
    this.soundName.value = sound;
    this.details.value = "";
    this.lookColumn.hidden = !chosen;
    this.showPreview();
    this.startSound();
    if (chosen) this.startCharacter();
    this.update();
  }

  private showPreview(): void {
    const source = this.source;
    if (!source) return;
    const video = element("video");
    video.src = `${source.url}#t=${this.start}`;
    video.playsInline = true;
    video.setAttribute("aria-label", "The section of video being used");
    video.addEventListener("click", () => this.togglePreview());
    video.addEventListener("loadedmetadata", () => {
      video.currentTime = this.start;
    });
    video.addEventListener("play", () => {
      this.previewPlay.textContent = "Pause";
      this.holdPreview(video);
    });
    video.addEventListener("pause", () => {
      if (!video.ended) this.previewPlay.textContent = "Play";
    });
    video.addEventListener("ended", () => {
      video.currentTime = this.start;
      void video.play().catch(() => undefined);
    });
    video.addEventListener("timeupdate", () => this.drawPreviewTime());
    video.addEventListener("error", () =>
      setBlocked(
        this.previewPlay,
        "This browser can't play this video, but its sound is below."
      )
    );
    this.video = video;
    const face = element("div");
    face.append(video, cardFibre());
    const controls = element("div", "preview-controls");
    controls.append(this.previewPlay, this.previewTime);
    this.previewBox.replaceChildren(videoCard(face), controls);
    this.previewPlay.textContent = "Play";
    setBlocked(this.previewPlay, "");
    this.drawPreviewTime();
  }

  private togglePreview(): void {
    const video = this.video;
    if (!video) return;
    if (!video.paused) {
      video.pause();
      return;
    }
    if (video.currentTime < this.start || video.currentTime >= this.end)
      video.currentTime = this.start;
    void video.play().catch(() => undefined);
  }

  /** Checked every frame, because the video's own time updates can run a quarter second late. */
  private holdPreview(video: HTMLVideoElement): void {
    const check = (): void => {
      if (video !== this.video || video.paused) return;
      if (video.currentTime >= this.end) video.currentTime = this.start;
      this.drawPreviewTime();
      requestAnimationFrame(check);
    };
    requestAnimationFrame(check);
  }

  private drawPreviewTime(): void {
    const length = this.end - this.start;
    const into = Math.min(
      length,
      Math.max(0, (this.video?.currentTime ?? this.start) - this.start)
    );
    this.previewTime.textContent = `${into.toFixed(1)} / ${length.toFixed(
      1
    )} s`;
  }

  private soundRunning(): boolean {
    return (
      !this.soundLost &&
      (this.job?.status === "queued" || this.job?.status === "processing")
    );
  }

  private artRunning(): boolean {
    return (
      this.character?.status === "queued" ||
      this.character?.status === "processing"
    );
  }

  /** Also true from the click, before the first reply says what the job is doing. */
  private soundPending(): boolean {
    return this.soundRunning() || !this.soundWait.root.hidden;
  }

  private artPending(): boolean {
    return this.artRunning() || !this.lookWait.root.hidden;
  }

  private startSound(): void {
    const source = this.source;
    const wanted = this.soundName.value.trim();
    if (!source || !wanted) return;
    const epoch = ++this.soundEpoch;
    this.soundPoll?.abort();
    this.soundProblem = "";
    this.soundLost = false;
    this.job = undefined;
    this.soundResult.replaceChildren();
    if (this.service && !this.service.audio) {
      this.soundProblem =
        "Sound separation is unavailable on this server. Raw audio still works.";
      this.update();
      return;
    }
    this.soundWait.show({
      scene: "sound",
      image: this.performerImage(),
      steps: SOUND_STEPS,
      step: 0,
      line: "Handing the clip to the sound worker…",
      notes: SOUND_NOTES,
    });
    this.update();
    void (async () => {
      try {
        const job = await gateway.separate(
          source.media.id,
          this.start,
          this.end,
          wanted
        );
        if (epoch !== this.soundEpoch) return;
        this.job = job;
        await this.pollSound(job.id, epoch);
      } catch (error) {
        if (epoch !== this.soundEpoch) return;
        this.soundProblem =
          error instanceof Error ? error.message : String(error);
        this.soundWait.hide();
        this.update();
      }
    })();
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
      image: this.performerImage(),
      steps: SOUND_STEPS,
      step: SOUND_STAGE_STEP[stage],
      line: job.queue_position
        ? queueLine(job.queue_position)
        : stage === "sending"
        ? "Handing the clip to the sound worker…"
        : stage === "collecting"
        ? "Bringing it back to the bench…"
        : `Snipping “${this.soundName.value.trim()}” away from everything around it…`,
      notes: SOUND_NOTES,
    };
  }

  private async pollSound(id: string, epoch: number): Promise<void> {
    this.update();
    const controller = new AbortController();
    this.soundPoll = controller;
    let missed = 0;
    while (epoch === this.soundEpoch && this.job && this.soundRunning()) {
      this.soundWait.show(this.soundView(this.job));
      this.update();
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
          this.soundProblem = `Status check failed: ${String(
            error
          )}. Pull the sound again, or use raw audio.`;
        }
      }
    }
    if (epoch !== this.soundEpoch) return;
    this.soundWait.hide();
    this.renderSound();
    if (this.job?.status === "ready")
      this.noticeIfClosed("Its sound is ready to hear. Open Add.");
    else if (this.job?.status === "failed")
      this.noticeIfClosed("That sound did not come through. Open Add.");
    this.update();
  }

  private renderSound(): void {
    const job = this.job;
    if (job?.status === "failed")
      this.soundProblem = job.error ?? "That sound failed.";
    if (job?.status !== "ready") {
      this.soundResult.replaceChildren();
      return;
    }
    this.soundResult.replaceChildren(
      audioControl(gateway.assetUrl(job.target_url!), "Target"),
      element(
        "p",
        "fine",
        job.provenance === "SAM Audio"
          ? "SAM Audio candidate. Check that it matches the intended sound."
          : "Mock service: target is a raw copy; residual is silence. No separation performed."
      )
    );
    this.soundResult.classList.add("arrived");
  }

  private performerImage(): string | undefined {
    const look =
      this.useStyled && this.character?.character_url
        ? this.character.character_url
        : this.chosen?.cutoutUrl;
    return look ? gateway.assetUrl(look) : undefined;
  }

  private startCharacter(): void {
    const chosen = this.chosen;
    if (!chosen) return;
    const epoch = ++this.artEpoch;
    this.artPoll?.abort();
    this.character = undefined;
    this.characterProblem = "";
    this.useStyled = false;
    this.pickedLook = false;
    this.usedDirection = this.details.value.trim();
    this.renderLooks();
    if (this.service && !this.service.image) {
      this.characterProblem =
        "Painting is unavailable on this server. You can use it as is.";
      this.update();
      return;
    }
    this.showArtWait("painting");
    this.update();
    void (async () => {
      try {
        const job = await gateway.character(
          chosen.cutoutId,
          chosen.name,
          this.usedDirection
        );
        if (epoch !== this.artEpoch) return;
        this.character = job;
        await this.pollCharacter(job.id, epoch);
      } catch (error) {
        if (epoch !== this.artEpoch) return;
        this.characterProblem =
          error instanceof Error ? error.message : String(error);
        this.lookWait.hide();
        this.update();
      }
    })();
  }

  private showArtWait(stage: string): void {
    const chosen = this.chosen;
    if (!chosen) return;
    this.lookWait.show({
      scene: stage === "painting" ? "paint" : "cut",
      image: gateway.assetUrl(chosen.cutoutUrl),
      steps: CHARACTER_STEPS,
      step: stage === "painting" ? 0 : 1,
      line: this.character?.queue_position
        ? queueLine(this.character.queue_position)
        : stage === "painting"
        ? "Painting your object in cut paper…"
        : "Cutting around the new picture…",
      notes: CHARACTER_NOTES,
    });
  }

  private async pollCharacter(id: string, epoch: number): Promise<void> {
    const controller = new AbortController();
    this.artPoll = controller;
    let missed = 0;
    while (epoch === this.artEpoch && this.artRunning() && this.character) {
      this.showArtWait(this.character.stage);
      this.update();
      await new Promise((resolve) => window.setTimeout(resolve, 850));
      if (epoch !== this.artEpoch) return;
      try {
        const result = await gateway.characterJob(id, controller.signal);
        if (epoch !== this.artEpoch) return;
        this.character = result;
        missed = 0;
      } catch (error) {
        if (controller.signal.aborted) return;
        if (++missed > MISSED_POLLS_ALLOWED) {
          this.characterProblem = `Could not check the character: ${String(
            error
          )}.`;
          this.lookWait.hide();
          this.update();
          return;
        }
      }
    }
    if (epoch !== this.artEpoch) return;
    this.lookWait.hide();
    if (this.character?.status === "ready") {
      if (!this.pickedLook) this.useStyled = true;
      this.noticeIfClosed("Your band member is painted. Open Add.");
    } else if (this.character?.status === "failed") {
      this.characterProblem =
        this.character.error ??
        "Painting could not finish. Retry, or keep the original.";
      this.noticeIfClosed("The painted version did not finish. Open Add.");
    }
    this.renderLooks();
    this.update();
  }

  private renderLooks(): void {
    const chosen = this.chosen;
    if (!chosen) {
      this.looks.replaceChildren();
      return;
    }
    const card = (
      label: string,
      url: string,
      styled: boolean
    ): HTMLButtonElement => {
      const choice = button("", () => {
        this.useStyled = styled;
        this.pickedLook = true;
        this.renderLooks();
      });
      choice.className = "sprite-card";
      choice.setAttribute("aria-pressed", String(this.useStyled === styled));
      choice.setAttribute("aria-label", `Use ${label.toLowerCase()}`);
      const image = element("img");
      image.src = gateway.assetUrl(url);
      image.alt = "";
      image.draggable = false;
      choice.append(image, element("span", "sprite-name", label));
      return choice;
    };
    const cards = [card("As is", chosen.cardUrl, false)];
    if (this.character?.status === "ready" && this.character.character_url)
      cards.push(card("Painted", this.character.character_url, true));
    this.looks.replaceChildren(...cards);
    this.lookNote.textContent =
      this.useStyled && this.character
        ? this.character.provenance
        : `Cut out from the source frame on white paper · ${chosen.provenance}`;
  }

  private noticeIfClosed(message: string): void {
    if (!this.isOpen()) this.store.notice(message);
  }

  private update(): void {
    const wait = this.adding ? "Adding to the band…" : "";
    const pendingSound = this.soundPending()
      ? "Its sound is still being separated."
      : "";
    setBlocked(
      this.soundRetry,
      wait ||
        pendingSound ||
        (this.service && !this.service.audio
          ? "Sound separation is unavailable on this server."
          : "") ||
        (this.soundName.value.trim() ? "" : "Say which sound to pull first.")
    );
    setBlocked(
      this.paintAgain,
      wait ||
        (this.artPending() ? "Wait for the painting to finish." : "") ||
        (this.service && !this.service.image
          ? "Painting is unavailable on this server."
          : "")
    );
    const soundReady = this.job?.status === "ready";
    setBlocked(
      this.addButton,
      wait ||
        pendingSound ||
        (soundReady ? "" : "Pull a sound first, or use raw audio.")
    );
    this.addButton.textContent =
      this.chosen && this.artPending() ? "Add as is" : "Add to band";
    setBlocked(this.rawButton, wait);
    this.rawButton.hidden = soundReady;
    this.status.textContent = this.soundProblem || this.characterProblem;
    this.status.classList.toggle("error", !!this.status.textContent);
  }

  private async add(raw: boolean): Promise<void> {
    const source = this.source;
    if (!source || this.adding) return;
    this.adding = true;
    this.update();
    try {
      const id = crypto.randomUUID();
      const path = raw
        ? `/media/${source.media.id}/audio?start_s=${this.start}&end_s=${this.end}`
        : this.job?.target_url;
      if (!path) throw new Error("Pull a sound first, or use raw audio.");
      await saveBlob(id, await gateway.blob(path));
      const chosen = this.chosen;
      let sprite = "/sprites.png";
      let sourceSprite: string | undefined;
      let rig: Rig | undefined;
      const styled =
        this.useStyled &&
        this.character?.status === "ready" &&
        this.character.character_url;
      if (chosen) {
        await saveBlob(
          `sprite-${id}`,
          await gateway.blob(styled || chosen.cardUrl)
        );
        sprite = `blob:asset:sprite-${id}`;
        sourceSprite = sprite;
        if (styled) {
          await saveBlob(
            `sprite-source-${id}`,
            await gateway.blob(chosen.cardUrl)
          );
          sourceSprite = `blob:asset:sprite-source-${id}`;
          const candidateRig = this.character!.rig;
          if (candidateRig) {
            const bodyId = `rig-body-${id}`;
            await saveBlob(bodyId, await gateway.blob(candidateRig.body_url));
            const parts: Rig["parts"] = [];
            for (const part of candidateRig.parts) {
              const partId = `rig-${part.name}-${id}`;
              await saveBlob(partId, await gateway.blob(part.url));
              parts.push({
                name: part.name,
                sprite: `blob:asset:${partId}`,
                pivot: { x: part.pivot[0], y: part.pivot[1] },
                maxAngle: part.max_angle,
              });
            }
            rig = {
              width: candidateRig.width,
              height: candidateRig.height,
              body: `blob:asset:${bodyId}`,
              parts,
            };
          }
        }
      }
      const label = chosen?.name ?? this.soundName.value.trim();
      this.store.add({
        id,
        label: label.slice(0, 80) || "Found sound",
        color: "#b37850",
        sprite,
        ...(rig ? { rig } : {}),
        ...(chosen ? {} : { tile: 0 }),
        audioId: id,
        provenance: raw
          ? "raw import"
          : this.job?.provenance === "SAM Audio"
          ? "SAM Audio"
          : "mock candidate",
        sourceId: source.media.id,
        startS: this.start,
        endS: this.end,
        ...(sourceSprite && chosen
          ? {
              sourceSprite,
              visualProvenance: styled
                ? this.character!.provenance
                : `Cut out from the source frame on white paper · ${chosen.provenance}`,
              ...(styled ? { characterPrompt: this.usedDirection } : {}),
            }
          : {}),
      });
      // Anything still running was chosen against, so its later result is no longer news.
      this.reset();
      this.onDone();
    } catch (error) {
      this.soundProblem =
        error instanceof Error ? error.message : String(error);
    } finally {
      this.adding = false;
      this.update();
    }
  }
}
