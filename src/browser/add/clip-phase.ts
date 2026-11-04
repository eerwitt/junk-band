import { gateway, type Media } from "../../services/gateway";
import { button, element, setBlocked, textInput } from "../dom";
import { SCISSOR_BLADES } from "../paper-wait";
import { cardFibre, videoCard } from "./video-card";

const MIN_STRETCH_S = 2;
const KEY_STEP_S = 0.1;
const DRAG_THRESHOLD_PX = 4;
/** The film parts as the blades close, and the scissors are gone soon after. */
const SNIP_CLOSES_MS = 250;
const SNIP_ENDS_MS = 500;
const CUT_SLANT = "3px";

type Side = "start" | "end";

const clock = (seconds: number): string => {
  const whole = Math.max(0, seconds);
  const minutes = Math.floor(whole / 60);
  return `${minutes}:${(whole - minutes * 60).toFixed(1).padStart(4, "0")}`;
};

export interface KeptMoment {
  start: number;
  end: number;
  /** Only for a recording with no picture, which skips choosing an object. */
  sound?: string;
}

function filmPiece(part: string): { root: HTMLElement; stock: HTMLElement } {
  const root = element("span", `film-piece film-${part}`);
  const stock = element("span", "film-stock");
  root.setAttribute("aria-hidden", "true");
  root.append(stock);
  return { root, stock };
}

function scissors(): Element {
  const template = document.createElement("template");
  template.innerHTML = `<svg class="film-snip" viewBox="-44 -22 80 44" aria-hidden="true">${SCISSOR_BLADES}</svg>`;
  return template.content.firstElementChild!;
}

/**
 * Pick a stretch of time as if editing film: drag the ends, or slide the whole piece. Letting go
 * snips the strip. The offcuts stay behind, grey, and dragging an end back over them restores them.
 */
export class ClipPhase {
  readonly root = element("section", "clip-phase");
  private stage = element("div", "clip-stage");
  private frame = element("div");
  private strip = element("div", "clip-strip");
  private before = filmPiece("before");
  private kept = filmPiece("kept");
  private after = filmPiece("after");
  private window = element("span", "clip-window");
  private playhead = element("span", "clip-playhead");
  private startHandle = element("span", "clip-handle");
  private endHandle = element("span", "clip-handle");
  private snips: Record<Side, Element> = {
    start: scissors(),
    end: scissors(),
  };
  private cuts: Record<Side, boolean> = { start: false, end: false };
  private snipTimers: Record<Side, number[]> = { start: [], end: [] };
  private readout = element("p", "clip-readout");
  private playButton = button("Play", () => this.togglePlay());
  private soundButton = button("Sound on", () => this.toggleSound());
  private keepPart = button("Use this part", () => this.keep(), "primary");
  private keepAll = button("Use entire video", () => {
    this.start = 0;
    this.end = this.duration;
    this.heal("start");
    this.heal("end");
    this.draw();
    this.keep();
  });
  private soundName = textInput("What sound is this?");
  private soundRow = element("label", "field clip-sound");
  private video?: HTMLVideoElement;
  private fallback?: HTMLImageElement;
  private fallbackTimer?: number;
  private duration = 0;
  private start = 0;
  private end = 0;
  private media?: Media;

  constructor(private readonly onKeep: (moment: KeptMoment) => void) {
    this.stage.append(videoCard(this.frame));
    this.strip.append(
      this.before.root,
      this.after.root,
      this.kept.root,
      this.window,
      this.playhead,
      this.startHandle,
      this.endHandle,
      this.snips.start,
      this.snips.end
    );
    this.soundRow.append(
      element("span", "", "What sound is this?"),
      this.soundName
    );
    this.soundName.addEventListener("input", () => this.draw());
    this.soundButton.setAttribute("aria-pressed", "true");
    const actions = element("div", "phase-actions");
    actions.append(
      this.playButton,
      this.soundButton,
      this.readout,
      this.keepAll,
      this.keepPart
    );
    this.root.append(this.stage, this.strip, this.soundRow, actions);
    this.bindHandle(this.startHandle, "start");
    this.bindHandle(this.endHandle, "end");
    this.bindWindow();
    this.strip.addEventListener("pointerdown", (event) => {
      if (event.target !== this.strip) return;
      this.strip.setPointerCapture(event.pointerId);
      this.seek(this.timeAt(event));
      const move = (next: PointerEvent): void => this.seek(this.timeAt(next));
      const up = (): void => {
        this.strip.removeEventListener("pointermove", move);
        this.strip.removeEventListener("pointerup", up);
        this.strip.removeEventListener("pointercancel", up);
      };
      this.strip.addEventListener("pointermove", move);
      this.strip.addEventListener("pointerup", up);
      this.strip.addEventListener("pointercancel", up);
    });
  }

  open(media: Media, url: string, file: File): void {
    this.media = media;
    this.duration = media.duration_s;
    this.start = 0;
    this.end = media.duration_s;
    this.heal("start");
    this.heal("end");
    this.fallback = undefined;
    const hasPicture = media.width > 0;
    this.frame.replaceChildren();
    this.soundRow.hidden = hasPicture;
    this.keepAll.textContent = hasPicture
      ? "Use entire video"
      : "Use entire recording";
    this.stage.classList.toggle("no-picture", !hasPicture);
    this.strip.classList.toggle("no-picture", !hasPicture);
    if (hasPicture)
      this.strip.style.setProperty(
        "--frames",
        `url("${gateway.assetUrl(
          `/media/${encodeURIComponent(media.id)}/filmstrip?count=16`
        )}")`
      );
    else this.strip.style.removeProperty("--frames");
    const video = element("video");
    video.src = url;
    video.playsInline = true;
    video.preload = "auto";
    video.setAttribute("aria-label", `Preview of ${file.name}`);
    video.addEventListener("click", () => this.togglePlay());
    video.addEventListener("timeupdate", () => {
      if (video.currentTime >= this.end && !video.paused) {
        video.currentTime = this.start;
      }
      this.drawPlayhead(video.currentTime);
    });
    video.addEventListener("ended", () => {
      video.currentTime = this.start;
      void video.play().catch(() => undefined);
    });
    video.addEventListener("play", () => this.showPlaying(true));
    video.addEventListener("pause", () => this.showPlaying(video.ended));
    video.addEventListener("error", () => this.useServerFrames());
    this.video = video;
    this.frame.append(video, cardFibre());
    video.muted = false;
    this.soundButton.textContent = "Sound on";
    this.soundButton.setAttribute("aria-pressed", "true");
    setBlocked(this.playButton, "");
    setBlocked(this.soundButton, "");
    this.showPlaying(false);
    this.draw();
  }

  /** Stop any sound before leaving this phase. */
  pause(): void {
    this.video?.pause();
  }

  private togglePlay(): void {
    const video = this.video;
    if (!video) return;
    if (!video.paused) {
      video.pause();
      return;
    }
    if (video.currentTime < this.start || video.currentTime >= this.end)
      video.currentTime = this.start;
    void video.play().catch(() => this.showPlaying(false));
  }

  private toggleSound(): void {
    if (!this.video) return;
    this.video.muted = !this.video.muted;
    this.soundButton.textContent = this.video.muted ? "Sound off" : "Sound on";
    this.soundButton.setAttribute("aria-pressed", String(!this.video.muted));
  }

  private showPlaying(playing: boolean): void {
    this.playButton.textContent = playing ? "Pause" : "Play";
  }

  private useServerFrames(): void {
    if (!this.media?.width || this.fallback) return;
    const image = element("img");
    image.alt = "Selected frame";
    this.fallback = image;
    this.video?.replaceWith(image);
    this.video = undefined;
    this.showPlaying(false);
    const reason =
      "This browser can't play this video, but you can still cut it.";
    setBlocked(this.playButton, reason);
    setBlocked(this.soundButton, reason);
    this.showServerFrame(this.start);
  }

  private showServerFrame(seconds: number): void {
    window.clearTimeout(this.fallbackTimer);
    this.fallbackTimer = window.setTimeout(() => {
      if (!this.fallback || !this.media) return;
      this.fallback.src = gateway.assetUrl(
        `/media/${this.media.id}/frame?frame_s=${seconds.toFixed(2)}`
      );
    }, 120);
  }

  private timeAt(event: PointerEvent): number {
    const bounds = this.strip.getBoundingClientRect();
    return (
      Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)) *
      this.duration
    );
  }

  private seek(seconds: number): void {
    if (this.video) this.video.currentTime = seconds;
    else this.showServerFrame(seconds);
    this.drawPlayhead(seconds);
  }

  private isWhole(): boolean {
    return this.start <= 0.001 && this.end >= this.duration - 0.001;
  }

  private atEdge(side: Side): boolean {
    return side === "start"
      ? this.start <= 0.001
      : this.end >= this.duration - 0.001;
  }

  /** Close up a cut so that side can be dragged over the film again. */
  private heal(side: Side): void {
    for (const timer of this.snipTimers[side]) window.clearTimeout(timer);
    this.snipTimers[side] = [];
    this.snips[side].classList.remove("snipping");
    this.cuts[side] = false;
  }

  private snip(side: Side): void {
    if (this.cuts[side]) return;
    this.heal(side);
    if (this.atEdge(side)) {
      this.draw();
      return;
    }
    const blades = this.snips[side] as SVGElement;
    blades.style.left = `${
      ((side === "start" ? this.start : this.end) / (this.duration || 1)) * 100
    }%`;
    blades.classList.add("snipping");
    this.snipTimers[side] = [
      window.setTimeout(() => {
        this.cuts[side] = true;
        this.draw();
      }, SNIP_CLOSES_MS),
      window.setTimeout(
        () => blades.classList.remove("snipping"),
        SNIP_ENDS_MS
      ),
    ];
  }

  private bindHandle(handle: HTMLElement, side: Side): void {
    const label =
      side === "start"
        ? "Start of the part to keep"
        : "End of the part to keep";
    handle.setAttribute("role", "slider");
    handle.setAttribute("aria-label", label);
    handle.title = `${label}. Drag, or use the arrow keys.`;
    handle.tabIndex = 0;
    const apply = (seconds: number): void => {
      this.heal(side);
      if (side === "start")
        this.start = Math.max(0, Math.min(seconds, this.end - MIN_STRETCH_S));
      else
        this.end = Math.min(
          this.duration,
          Math.max(seconds, this.start + MIN_STRETCH_S)
        );
      this.seek(side === "start" ? this.start : this.end);
      this.draw();
    };
    handle.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
      handle.setPointerCapture(event.pointerId);
      this.video?.pause();
      const move = (next: PointerEvent): void => apply(this.timeAt(next));
      const up = (): void => {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
        handle.removeEventListener("pointercancel", up);
        this.snip(side);
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
      handle.addEventListener("pointercancel", up);
    });
    handle.addEventListener("keydown", (event) => {
      const direction =
        event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (!direction) return;
      event.preventDefault();
      apply(
        (side === "start" ? this.start : this.end) + direction * KEY_STEP_S
      );
    });
    handle.addEventListener("keyup", (event) => {
      if (event.key === "ArrowRight" || event.key === "ArrowLeft")
        this.snip(side);
    });
  }

  /** Slide the kept piece along the film, keeping its length. */
  private slideTo(start: number): void {
    const length = this.end - this.start;
    this.heal("start");
    this.heal("end");
    this.start = Math.max(0, Math.min(start, this.duration - length));
    this.end = this.start + length;
    this.seek(this.start);
    this.draw();
  }

  private bindWindow(): void {
    const area = this.window;
    area.setAttribute("role", "slider");
    area.setAttribute("aria-label", "Part to keep");
    area.tabIndex = 0;
    area.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
      area.setPointerCapture(event.pointerId);
      this.video?.pause();
      const whole = this.isWhole();
      const anchor = this.start;
      const originX = event.clientX;
      const secondsPerPixel =
        this.duration / (this.strip.getBoundingClientRect().width || 1);
      let moved = false;
      area.classList.add("sliding");
      const move = (next: PointerEvent): void => {
        const distance = next.clientX - originX;
        moved = moved || Math.abs(distance) >= DRAG_THRESHOLD_PX;
        if (!moved) return;
        // With nothing trimmed there is nothing to slide, so dragging scrubs instead.
        if (whole) this.seek(this.timeAt(next));
        else this.slideTo(anchor + distance * secondsPerPixel);
      };
      const up = (next: PointerEvent): void => {
        area.removeEventListener("pointermove", move);
        area.removeEventListener("pointerup", up);
        area.removeEventListener("pointercancel", up);
        area.classList.remove("sliding");
        if (!moved) {
          this.seek(this.timeAt(next));
          return;
        }
        this.snip("start");
        this.snip("end");
      };
      area.addEventListener("pointermove", move);
      area.addEventListener("pointerup", up);
      area.addEventListener("pointercancel", up);
    });
    area.addEventListener("keydown", (event) => {
      const direction =
        event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (!direction || this.isWhole()) return;
      event.preventDefault();
      this.slideTo(this.start + direction * KEY_STEP_S);
    });
    area.addEventListener("keyup", (event) => {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
      if (this.isWhole()) return;
      this.snip("start");
      this.snip("end");
    });
  }

  private drawPlayhead(seconds: number): void {
    this.playhead.style.left = `${(seconds / (this.duration || 1)) * 100}%`;
  }

  private drawFilm(): void {
    const share = (seconds: number): string =>
      `${(seconds / (this.duration || 1)) * 100}%`;
    const from = share(this.start);
    const to = share(this.end);
    // Each cut leans a little, the way a hand with scissors does.
    const a = this.cuts.start ? CUT_SLANT : "0px";
    const b = this.cuts.end ? CUT_SLANT : "0px";
    this.before.stock.style.clipPath = `polygon(0 0, calc(${from} + ${a}) 0, calc(${from} - ${a}) 100%, 0 100%)`;
    this.kept.stock.style.clipPath = `polygon(calc(${from} + ${a}) 0, calc(${to} - ${b}) 0, calc(${to} + ${b}) 100%, calc(${from} - ${a}) 100%)`;
    this.after.stock.style.clipPath = `polygon(calc(${to} - ${b}) 0, 100% 0, 100% 100%, calc(${to} + ${b}) 100%)`;
    this.before.root.style.transformOrigin = `${from} 50%`;
    this.after.root.style.transformOrigin = `${to} 50%`;
    this.strip.classList.toggle("cut-start", this.cuts.start);
    this.strip.classList.toggle("cut-end", this.cuts.end);
    this.window.style.left = from;
    this.window.style.width = share(this.end - this.start);
    this.startHandle.style.left = from;
    this.endHandle.style.left = to;
  }

  private draw(): void {
    this.drawFilm();
    const whole = this.isWhole();
    const span = `${clock(this.start)} to ${clock(this.end)}`;
    this.window.classList.toggle("whole", whole);
    this.window.title = whole
      ? "Drag to look through the video."
      : "Drag to move this part along the film.";
    this.window.setAttribute("aria-valuetext", span);
    this.window.setAttribute("aria-valuemin", "0");
    this.window.setAttribute(
      "aria-valuemax",
      (this.duration - (this.end - this.start)).toFixed(1)
    );
    this.window.setAttribute("aria-valuenow", this.start.toFixed(1));
    for (const [handle, seconds] of [
      [this.startHandle, this.start],
      [this.endHandle, this.end],
    ] as const) {
      handle.setAttribute("aria-valuemin", "0");
      handle.setAttribute("aria-valuemax", this.duration.toFixed(1));
      handle.setAttribute("aria-valuenow", seconds.toFixed(1));
      handle.setAttribute("aria-valuetext", clock(seconds));
    }
    this.readout.textContent = `${span} · ${(this.end - this.start).toFixed(
      1
    )} s`;
    const unnamed =
      !this.media?.width && !this.soundName.value.trim()
        ? "Say what the sound is first."
        : "";
    setBlocked(
      this.keepPart,
      unnamed ||
        (whole
          ? "Drag the handles to choose a part first, or use all of it."
          : "")
    );
    setBlocked(this.keepAll, unnamed);
  }

  private keep(): void {
    this.pause();
    const sound = this.soundName.value.trim();
    this.onKeep({
      start: this.start,
      end: this.end,
      ...(this.media?.width ? {} : { sound }),
    });
  }
}
