import {
  gateway,
  type Health,
  type Media,
  type Picked,
} from "../../services/gateway";
import { button, element, field, setBlocked, textInput } from "../dom";
import { MaskEditor } from "../mask-editor";
import { PaperWait, type WaitNote } from "../paper-wait";

/** The object chosen to become a band member. */
export interface Chosen {
  cutoutId: string;
  cutoutUrl: string;
  maskUrl?: string;
  cardUrl: string;
  frameS: number;
  name: string;
  sound: string;
  provenance: string;
}

type StepState = "todo" | "active" | "done";
interface Step {
  root: HTMLElement;
  tab: HTMLElement;
  title: HTMLElement;
  number: string;
}

const LOOK_NOTES: readonly WaitNote[] = [
  [15, "Still cutting carefully. This can take up to a minute."],
];
const FRAME_DELAY_MS = 120;
const KEY_STEP_S = 0.1;
/** About how wide the strip shows, to choose how many whole frames fit along it. */
const STRIP_WIDTH_PX = 640;
const FRAME_HEIGHT_PX = 46;
const MIN_FRAMES = 4;
const MAX_FRAMES = 24;

function makeStep(number: string, title: string, hint: string): Step {
  const root = element("li", "make-step");
  const tab = element("span", "make-tab", number);
  tab.setAttribute("aria-hidden", "true");
  const heading = element("strong", "make-title", title);
  root.append(tab, heading, element("p", "fine make-hint", hint));
  return { root, tab, title: heading, number };
}

/** Pick a frame, paint a rough mask over the thing, say what it is, and let it be cut out. */
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
  private rail = element("div", "object-rail");
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
    "Say what it is",
    "A word or two helps. Leave it blank and we'll take a guess."
  );
  private keepStep = makeStep(
    "4",
    "Keep it",
    "Happy? Paint or erase to fix it, or say which sound to pull."
  );
  private sprites = element("div", "object-sprites");
  private wait = new PaperWait();
  private status = element("p", "feedback");
  private describe = textInput("What is it?");
  private cutButton = button("Cut it out", () => void this.cut(), "primary");
  private soundName = textInput("Sound to pull");
  private useButton = button("Use this one", () => this.use(), "primary");
  private mask: MaskEditor;
  private cards = new Map<string, HTMLButtonElement>();
  private found: Chosen[] = [];
  private selected?: Chosen;
  private media?: Media;
  private keptStart = 0;
  private keptEnd = 0;
  private soundStart = 0;
  private soundEnd = 0;
  private epoch = 0;
  private busy = false;
  private frameReady = false;
  private currentFrame = 0;
  private frameShare = 1 / MIN_FRAMES;
  private frameTimer?: number;
  private service?: Health;

  constructor(
    private readonly onUse: (
      chosen: Chosen,
      sound: { start: number; end: number }
    ) => void
  ) {
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
    this.mask = new MaskEditor(
      this.preview,
      16,
      9,
      () => this.update(),
      () => void this.applyMask()
    );
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

    this.status.setAttribute("role", "status");
    this.describe.addEventListener("input", () => this.update());
    this.describe.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !this.cutButton.disabled) void this.cut();
    });
    this.soundName.addEventListener("input", () => {
      if (this.selected) this.selected.sound = this.soundName.value;
      this.update();
    });
    const describeBody = element("div", "make-body object-describe");
    describeBody.append(field("What is it?", this.describe), this.cutButton);
    this.describeStep.root.append(describeBody, this.wait.root);
    const keepBody = element("div", "make-body");
    keepBody.append(
      this.sprites,
      field("Sound to pull", this.soundName),
      this.useButton
    );
    this.keepStep.root.append(keepBody);
    const steps = element("ol", "make-steps");
    steps.append(
      this.frameStep.root,
      this.paintStep.root,
      this.describeStep.root,
      this.keepStep.root
    );
    this.rail.append(steps, this.status);
    this.root.append(this.stage, this.rail);
  }

  setService(service?: Health): void {
    this.service = service;
    this.update();
  }

  /** Ignore replies to work that has been replaced by another source. */
  reset(): void {
    this.epoch++;
    this.busy = false;
    window.clearTimeout(this.frameTimer);
    this.wait.hide();
  }

  open(media: Media, start: number, end: number): void {
    this.reset();
    this.media = media;
    this.keptStart = start;
    this.keptEnd = end;
    this.soundStart = start;
    this.soundEnd = end;
    this.found = [];
    this.cards.clear();
    this.sprites.replaceChildren();
    this.selected = undefined;
    this.status.textContent = "";
    this.status.classList.remove("error");
    this.describe.value = "";
    this.soundName.value = "";
    this.mask.clear();
    this.mask.setTool("paint");
    const hasFilm = end > start && media.duration_s > 0;
    this.strip.hidden = !hasFilm;
    this.frameStep.root.hidden = !hasFilm;
    if (hasFilm) this.loadStrip(media, start, end);
    this.showFrame(start + (end - start) / 2);
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
    this.selected = undefined;
    this.mask.clear();
    this.mask.setTool("paint");
    this.markSelected();
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

  private canFind(): boolean {
    return !this.service || this.service.sam;
  }

  /** Cut along the painted mask, with the words to tell the model what it is. */
  private async cut(): Promise<void> {
    if (!this.canFind()) {
      await this.applyMask();
      return;
    }
    const media = this.media;
    const box = this.mask.paintedBox();
    if (!media || !box || this.busy) return;
    const epoch = this.epoch;
    const concept = this.describe.value.trim() || null;
    this.busy = true;
    this.status.textContent = "";
    this.status.classList.remove("error");
    this.wait.show({
      scene: "cut",
      image: this.mask.paintedPicture(this.picture),
      line: concept
        ? `Snipping out “${concept}”…`
        : "Working out what you painted…",
      notes: LOOK_NOTES,
    });
    this.update();
    try {
      const painted = await this.mask.toBlob();
      let picked = await gateway.pick(
        media.id,
        this.currentFrame,
        box,
        concept,
        this.keptStart,
        this.keptEnd
      );
      if (epoch !== this.epoch) return;
      // With nothing better found, the painted mask itself is the selection.
      if (picked.provenance.startsWith("Rough selection")) {
        const own = await gateway.maskCutout(
          media.id,
          this.currentFrame,
          painted
        );
        if (epoch !== this.epoch) return;
        picked = {
          ...picked,
          cutout_id: own.cutout_id,
          cutout_url: own.cutout_url,
          mask_url: own.mask_url ?? picked.mask_url,
          card_url: own.card_url ?? picked.card_url,
          provenance: own.provenance,
        };
      }
      this.soundStart = picked.sound_start_s;
      this.soundEnd = picked.sound_end_s;
      if (!concept) this.describe.value = picked.name;
      await this.arrive(picked, concept);
    } catch (error) {
      if (epoch === this.epoch)
        this.say(error instanceof Error ? error.message : String(error));
    } finally {
      if (epoch === this.epoch) {
        this.busy = false;
        this.wait.hide();
        this.update();
      }
    }
  }

  private async arrive(picked: Picked, concept: string | null): Promise<void> {
    const known = this.found.find((item) => item.cutoutId === picked.cutout_id);
    const chosen: Chosen = known ?? {
      cutoutId: picked.cutout_id,
      cutoutUrl: picked.cutout_url,
      maskUrl: picked.mask_url,
      cardUrl: picked.card_url,
      frameS: picked.frame_s,
      name: picked.name,
      sound: picked.sound || concept || "",
      provenance: picked.provenance,
    };
    if (!known) this.addSprite(chosen);
    await this.select(chosen);
  }

  private addSprite(chosen: Chosen): void {
    this.found.push(chosen);
    const card = button("", () => void this.select(chosen));
    card.className = "sprite-card";
    const image = element("img");
    image.src = gateway.assetUrl(chosen.cardUrl);
    image.alt = "";
    image.draggable = false;
    card.append(image, element("span", "sprite-name", chosen.name));
    card.setAttribute("aria-label", `Choose ${chosen.name}`);
    this.cards.set(chosen.cutoutId, card);
    this.sprites.append(card);
    this.markSelected();
  }

  private markSelected(): void {
    for (const [id, card] of this.cards)
      card.setAttribute("aria-pressed", String(id === this.selected?.cutoutId));
  }

  private async select(chosen: Chosen): Promise<void> {
    this.selected = chosen;
    this.soundName.value = chosen.sound;
    this.markSelected();
    if (Math.abs(chosen.frameS - this.currentFrame) > 0.01)
      this.showFrame(chosen.frameS);
    if (chosen.maskUrl) await this.mask.load(chosen.maskUrl);
    this.update();
  }

  private say(message: string): void {
    this.status.textContent = message;
    this.status.classList.add("error");
    this.status.scrollIntoView({ block: "nearest" });
  }

  private async applyMask(): Promise<void> {
    const media = this.media;
    if (!media || this.busy) return;
    const epoch = this.epoch;
    const base = this.selected;
    this.busy = true;
    this.status.textContent = "";
    this.status.classList.remove("error");
    this.update();
    try {
      const result = await gateway.maskCutout(
        media.id,
        this.currentFrame,
        await this.mask.toBlob(),
        base?.cutoutId
      );
      if (epoch !== this.epoch) return;
      this.mask.markApplied();
      const updated: Chosen = {
        cutoutId: result.cutout_id,
        cutoutUrl: result.cutout_url,
        maskUrl: result.mask_url,
        cardUrl: result.card_url ?? base?.cardUrl ?? result.cutout_url,
        frameS: this.currentFrame,
        name: base?.name ?? (this.describe.value.trim() || "my object"),
        sound: this.soundName.value.trim() || base?.sound || "",
        provenance: result.provenance,
      };
      if (base) {
        this.cards.get(base.cutoutId)?.remove();
        this.cards.delete(base.cutoutId);
        this.found = this.found.filter((item) => item !== base);
      }
      this.addSprite(updated);
      this.selected = updated;
      this.markSelected();
    } catch (error) {
      if (epoch === this.epoch)
        this.say(error instanceof Error ? error.message : String(error));
    } finally {
      if (epoch === this.epoch) {
        this.busy = false;
        this.update();
      }
    }
  }

  private use(): void {
    if (!this.selected) return;
    this.onUse(
      { ...this.selected, sound: this.soundName.value.trim() },
      { start: this.soundStart, end: this.soundEnd }
    );
  }

  private setStep(step: Step, state: StepState): void {
    if (step.root.dataset.state === state) return;
    step.root.dataset.state = state;
    step.tab.textContent = state === "done" ? "✓" : step.number;
  }

  private update(): void {
    const painted = !this.mask.isEmpty;
    const cutOut = Boolean(this.selected);
    const ready = !this.busy && this.frameReady;
    this.mask.setEnabled(ready);
    this.mask.setEditing(cutOut);
    this.paintHint.hidden = painted || !ready;
    this.setStep(this.frameStep, painted ? "done" : "active");
    this.setStep(this.paintStep, painted ? "done" : "active");
    this.setStep(
      this.describeStep,
      cutOut && !this.mask.dirty ? "done" : painted ? "active" : "todo"
    );
    this.setStep(this.keepStep, cutOut ? "active" : "todo");
    this.keepStep.title.textContent = this.selected
      ? `Got it: ${this.selected.name}!`
      : "Keep it";
    this.cutButton.classList.toggle("primary", !cutOut || this.mask.dirty);
    const wait = this.busy ? "Wait for the current step to finish." : "";
    setBlocked(
      this.cutButton,
      wait || (painted ? "" : "Paint over your thing first.")
    );
    setBlocked(
      this.useButton,
      wait ||
        (this.mask.dirty
          ? "Choose Use this mask to keep your painting, or undo it, first."
          : "") ||
        (this.selected ? "" : "Cut something out first.") ||
        (this.soundName.value.trim() ? "" : "Say which sound to pull first.")
    );
  }
}
