import { gateway, type Media } from "../../services/gateway";
import { button, element, setBlocked, textInput } from "../dom";
import { MaskEditor } from "../mask-editor";

/** What Make it hands on: the words, and for a picture, where the thing is. */
export interface Made {
  description: string;
  picture?: {
    frameS: number;
    /** The painted area as a 0–1 box. */
    box: number[];
    mask: Blob;
    /** Just the painted part of the frame, to show while it is being cut. */
    preview?: string;
    /** Changes whenever the frame or the painting does. */
    key: string;
  };
}

type StepState = "todo" | "active" | "done";
interface Step {
  root: HTMLElement;
  tab: HTMLElement;
  number: string;
}

const FRAME_DELAY_MS = 120;
const KEY_STEP_S = 0.1;
/** About how wide the strip shows, to choose how many whole frames fit along it. */
const STRIP_WIDTH_PX = 640;
const FRAME_HEIGHT_PX = 46;
const MIN_FRAMES = 4;
const MAX_FRAMES = 24;
const MAX_DESCRIPTION = 100;

function makeStep(number: string, title: string, hint: string): Step {
  const root = element("li", "make-step");
  const tab = element("span", "make-tab", number);
  tab.setAttribute("aria-hidden", "true");
  root.append(
    tab,
    element("strong", "make-title", title),
    element("p", "fine make-hint", hint)
  );
  return { root, tab, number };
}

/** Pick a frame, paint over the thing, and say what you want to hear from it. */
export class ObjectsPhase {
  readonly root = element("section", "objects-phase");
  private stage = element("div", "object-stage");
  private preview = element("div", "source-preview");
  private picture = element("img");
  private paintHint = element("span", "paint-hint", "Paint over your thing");
  private strip = element("div", "frame-strip");
  private stripAll = element("span", "film-stock frame-all");
  private stripPicked = element("span", "film-stock frame-picked");
  private viewfinder = element("span", "frame-viewfinder");
  private frameStep = makeStep(
    "1",
    "Pick the frame",
    "Slide along the film to where your thing shows best."
  );
  private paintStep = makeStep(
    "2",
    "Paint over it",
    "Scribble right across it. Messy is fine, we tidy it up."
  );
  private describeStep = makeStep(
    "3",
    "Say what you want to hear",
    "We pull that sound out and cut your thing out at the same time."
  );
  private describe = textInput("What do you want to hear?");
  private makeButton = button("Make it", () => void this.make(), "primary");
  private status = element("p", "feedback");
  private mask: MaskEditor;
  private media?: Media;
  private keptStart = 0;
  private keptEnd = 0;
  private frameReady = false;
  private currentFrame = 0;
  private frameShare = 1 / MIN_FRAMES;
  private frameTimer?: number;
  private busy = false;

  constructor(private readonly onMake: (made: Made) => void) {
    this.picture.alt = "Frame of the video to paint on";
    this.picture.draggable = false;
    // Painted frames are read back to show them being cut.
    this.picture.crossOrigin = "anonymous";
    this.picture.addEventListener("load", () => {
      const { naturalWidth: width, naturalHeight: height } = this.picture;
      this.preview.style.aspectRatio = `${width}/${height}`;
      this.preview.style.setProperty("--shape", String(width / height));
      this.mask.matchFrame(width, height);
      this.frameReady = true;
      this.update();
    });
    this.mask = new MaskEditor(this.preview, 16, 9, () => this.update());
    this.paintHint.setAttribute("aria-hidden", "true");
    this.preview.append(
      this.picture,
      this.mask.overlay,
      this.paintHint,
      this.mask.cursor
    );
    this.strip.append(this.stripAll, this.stripPicked, this.viewfinder);
    this.bindStrip();
    this.stage.append(this.preview, this.strip, this.mask.tools);

    this.describe.maxLength = MAX_DESCRIPTION;
    this.describe.placeholder = "the tin can clanking";
    this.describe.addEventListener("input", () => this.update());
    this.describe.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !this.makeButton.disabled) void this.make();
    });
    const describeBody = element("div", "make-body");
    describeBody.append(this.describe);
    this.describeStep.root.append(describeBody);
    const steps = element("ol", "make-steps");
    steps.append(
      this.frameStep.root,
      this.paintStep.root,
      this.describeStep.root
    );
    this.status.setAttribute("role", "status");
    const rail = element("div", "object-rail");
    rail.append(steps, this.makeButton, this.status);
    this.root.append(this.stage, rail);
  }

  /** A new source starts clean; a new stretch of the same one keeps the words. */
  open(media: Media, start: number, end: number): void {
    window.clearTimeout(this.frameTimer);
    const sameSource = media.id === this.media?.id;
    this.media = media;
    this.keptStart = start;
    this.keptEnd = end;
    this.busy = false;
    this.status.textContent = "";
    this.status.classList.remove("error");
    if (!sameSource) this.describe.value = "";
    const hasPicture = media.width > 0;
    this.root.classList.toggle("no-picture", !hasPicture);
    this.stage.hidden = !hasPicture;
    this.frameStep.root.hidden = !hasPicture;
    this.paintStep.root.hidden = !hasPicture;
    this.describeStep.tab.textContent = this.describeStep.number = hasPicture
      ? "3"
      : "1";
    if (hasPicture) {
      this.loadStrip(media, start, end);
      const inside = this.currentFrame >= start && this.currentFrame <= end;
      if (!sameSource) this.picture.removeAttribute("src");
      if (!sameSource || !inside) {
        this.mask.clear();
        this.mask.setTool("paint");
        this.showFrame(start + (end - start) / 2);
      } else this.drawStrip();
    }
    this.update();
    window.setTimeout(() => {
      if (!hasPicture) this.describe.focus();
    });
  }

  /** As many whole frames as fit, so each one on the strip looks like the frame it is. */
  private loadStrip(media: Media, start: number, end: number): void {
    const shape = media.width / (media.height || 1);
    const count = Math.max(
      MIN_FRAMES,
      Math.min(
        MAX_FRAMES,
        Math.round(STRIP_WIDTH_PX / (FRAME_HEIGHT_PX * shape))
      )
    );
    this.frameShare = 1 / count;
    this.strip.style.setProperty(
      "--frames",
      `url("${gateway.assetUrl(
        `/media/${encodeURIComponent(
          media.id
        )}/filmstrip?count=${count}&start_s=${start.toFixed(
          2
        )}&end_s=${end.toFixed(2)}`
      )}")`
    );
  }

  private bindStrip(): void {
    const area = this.viewfinder;
    area.setAttribute("role", "slider");
    area.setAttribute("aria-label", "Picture moment");
    area.title = "The frame you are painting on. Drag along the film.";
    area.tabIndex = 0;
    const seekTo = (event: PointerEvent): void => {
      const bounds = this.strip.getBoundingClientRect();
      const share = Math.max(
        0,
        Math.min(1, (event.clientX - bounds.left) / (bounds.width || 1))
      );
      this.chooseFrame(
        this.keptStart + share * (this.keptEnd - this.keptStart)
      );
    };
    this.strip.addEventListener("pointerdown", (event) => {
      if (this.busy) return;
      this.strip.setPointerCapture(event.pointerId);
      seekTo(event);
      const up = (): void => {
        this.strip.removeEventListener("pointermove", seekTo);
        this.strip.removeEventListener("pointerup", up);
        this.strip.removeEventListener("pointercancel", up);
      };
      this.strip.addEventListener("pointermove", seekTo);
      this.strip.addEventListener("pointerup", up);
      this.strip.addEventListener("pointercancel", up);
    });
    area.addEventListener("keydown", (event) => {
      const direction =
        event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (!direction || this.busy) return;
      event.preventDefault();
      this.chooseFrame(this.currentFrame + direction * KEY_STEP_S);
    });
  }

  /** A new picture means a new painting, so the old one is cleared with it. */
  private chooseFrame(seconds: number): void {
    const frame = Math.max(
      this.keptStart,
      Math.min(Math.max(this.keptStart, this.keptEnd - 0.05), seconds)
    );
    if (Math.abs(frame - this.currentFrame) < 0.01) return;
    this.mask.clear();
    this.mask.setTool("paint");
    this.showFrame(frame, FRAME_DELAY_MS);
  }

  private showFrame(seconds: number, delay = 0): void {
    if (!this.media) return;
    const media = this.media;
    this.currentFrame = seconds;
    this.drawStrip();
    this.frameReady = false;
    window.clearTimeout(this.frameTimer);
    this.frameTimer = window.setTimeout(() => {
      this.picture.src = gateway.assetUrl(
        `/media/${media.id}/frame?frame_s=${seconds.toFixed(2)}`
      );
    }, delay);
    this.update();
  }

  private drawStrip(): void {
    const length = this.keptEnd - this.keptStart || 1;
    const share = (this.currentFrame - this.keptStart) / length;
    const left = Math.max(
      0,
      Math.min(1 - this.frameShare, share - this.frameShare / 2)
    );
    const right = 1 - left - this.frameShare;
    this.stripPicked.style.clipPath = `inset(0 ${right * 100}% 0 ${
      left * 100
    }%)`;
    this.viewfinder.style.left = `${left * 100}%`;
    this.viewfinder.style.width = `${this.frameShare * 100}%`;
    this.viewfinder.setAttribute("aria-valuemin", this.keptStart.toFixed(1));
    this.viewfinder.setAttribute("aria-valuemax", this.keptEnd.toFixed(1));
    this.viewfinder.setAttribute("aria-valuenow", this.currentFrame.toFixed(1));
    this.viewfinder.setAttribute(
      "aria-valuetext",
      `${this.currentFrame.toFixed(1)} seconds`
    );
  }

  private async make(): Promise<void> {
    const media = this.media;
    const description = this.describe.value.trim();
    if (!media || !description || this.busy) return;
    if (!media.width) {
      this.onMake({ description });
      return;
    }
    const box = this.mask.paintedBox();
    if (!box) return;
    this.busy = true;
    this.update();
    try {
      this.onMake({
        description,
        picture: {
          frameS: this.currentFrame,
          box,
          mask: await this.mask.toBlob(),
          preview: this.mask.paintedPicture(this.picture),
          key: `${this.currentFrame.toFixed(2)}:${this.mask.revision}`,
        },
      });
    } catch (error) {
      this.status.textContent =
        error instanceof Error ? error.message : String(error);
      this.status.classList.add("error");
    } finally {
      this.busy = false;
      this.update();
    }
  }

  private setStep(step: Step, state: StepState): void {
    if (step.root.dataset.state === state) return;
    step.root.dataset.state = state;
    step.tab.textContent = state === "done" ? "✓" : step.number;
  }

  private update(): void {
    const hasPicture = Boolean(this.media?.width);
    const painted = !this.mask.isEmpty;
    const described = Boolean(this.describe.value.trim());
    this.mask.setEnabled(!this.busy && this.frameReady);
    this.paintHint.hidden = painted || !this.frameReady;
    this.setStep(this.frameStep, painted ? "done" : "active");
    this.setStep(this.paintStep, painted ? "done" : "active");
    this.setStep(
      this.describeStep,
      described && (painted || !hasPicture) ? "done" : "active"
    );
    setBlocked(
      this.makeButton,
      this.busy
        ? "Getting it ready…"
        : hasPicture && !painted
        ? "Paint over your thing first."
        : !described
        ? "Say what you want to hear first."
        : ""
    );
  }
}
