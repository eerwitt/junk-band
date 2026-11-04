import { audio } from "../../audio/browser";
import { gateway, type Health, type Media } from "../../services/gateway";
import { saveBlob } from "../../storage/database";
import { button, element, field } from "../dom";
import type { StudioStore } from "../store";
import { ClipPhase, MAX_STRETCH_S, type KeptMoment } from "./clip-phase";
import { ObjectsPhase, type Made } from "./objects-phase";
import { ReviewPhase, type ReviewSource } from "./review-phase";

type Phase = "bring" | "moment" | "object" | "review";
const STEPS: readonly { id: Phase; label: string }[] = [
  { id: "moment", label: "Pick the sound" },
  { id: "object", label: "Choose the object" },
  { id: "review", label: "Listen and add" },
];
const RIGHTS_KEY = "junk.mediaRights";

function rememberedRights(): boolean {
  try {
    return localStorage.getItem(RIGHTS_KEY) === "yes";
  } catch {
    return false;
  }
}

function rememberRights(): void {
  try {
    localStorage.setItem(RIGHTS_KEY, "yes");
  } catch {
    // Without storage it is simply asked again next time.
  }
}

/** Add takes over the stage: trim the sound, paint the thing, then listen and add. */
export class AddStudio {
  private root = element("aside", "add-studio");
  private steps = element("ol", "add-steps");
  private stepButtons = new Map<Phase, HTMLButtonElement>();
  private bring = element("section", "bring-phase");
  private rights = element("input");
  private rightsField: HTMLLabelElement;
  private input = element("input");
  private status = element("p", "feedback");
  private serviceNote = element("p", "fine", "Checking available tools…");
  private pendingFile?: File;
  private clip: ClipPhase;
  private objects: ObjectsPhase;
  private review: ReviewPhase;
  private source?: ReviewSource;
  private moment?: KeptMoment;
  private reached = new Set<Phase>(["bring"]);
  private busy = false;
  private healthEpoch = 0;

  constructor(store: StudioStore) {
    this.clip = new ClipPhase((moment) => this.momentKept(moment));
    this.objects = new ObjectsPhase((made) => this.made(made));
    this.review = new ReviewPhase(
      store,
      () => !this.root.hidden,
      () => this.close(true),
      () => this.setPhase("object")
    );
    this.rightsField = field(
      "I own this media or have permission to use it",
      this.rights
    );
    this.root.hidden = true;
    this.root.tabIndex = -1;
    this.root.setAttribute("role", "dialog");
    this.root.setAttribute("aria-label", "Add to the band");
    const header = element("header", "add-header");
    const closeButton = button("Close", () => this.close());
    for (const { id, label } of STEPS) {
      const item = element("li");
      const step = button(label, () => {
        if (this.reached.has(id)) this.setPhase(id);
      });
      step.className = "add-step";
      this.stepButtons.set(id, step);
      item.append(step);
      this.steps.append(item);
    }
    header.append(
      element("h2", "", "Find its voice."),
      this.steps,
      closeButton
    );
    this.buildBring();
    const body = element("div", "add-body");
    body.append(
      this.bring,
      this.clip.root,
      this.objects.root,
      this.review.root
    );
    this.root.append(header, body);
    document.body.append(this.root);
    // Caught at the document: focus falls back to the page when a focused button's phase hides,
    // and those keys must still reach this studio rather than the stage behind it.
    document.addEventListener(
      "keydown",
      (event) => {
        if (this.root.hidden) return;
        if (event.key === "Escape") this.close();
        const inside =
          event.target instanceof Node && this.root.contains(event.target);
        if (!inside) event.stopImmediatePropagation();
      },
      true
    );
    // Controls in here still get their keys; the stage's shortcuts do not.
    this.root.addEventListener("keydown", (event) => event.stopPropagation());
    document.addEventListener("dragover", (event) => {
      if (event.dataTransfer?.types.includes("Files")) event.preventDefault();
    });
    document.addEventListener("drop", (event) => {
      const file = event.dataTransfer?.files[0];
      if (file) {
        event.preventDefault();
        this.show();
        void this.ingest(file);
      }
    });
    this.setPhase("bring");
  }

  private buildBring(): void {
    this.rights.type = "checkbox";
    this.rights.addEventListener("change", () => {
      if (!this.rights.checked) return;
      rememberRights();
      if (this.pendingFile) void this.ingest(this.pendingFile);
    });
    this.input.type = "file";
    this.input.hidden = true;
    this.input.accept =
      "video/mp4,video/webm,audio/wav,audio/mpeg,audio/ogg,audio/flac,image/png,image/jpeg,image/webp";
    this.input.addEventListener("change", () => {
      const file = this.input.files?.[0];
      if (file) void this.ingest(file);
      this.input.value = "";
    });
    const drop = button(
      "Choose or drop a video",
      () => this.input.click(),
      "drop-target"
    );
    drop.addEventListener("dragover", (event) => event.preventDefault());
    drop.addEventListener("drop", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const file = event.dataTransfer?.files[0];
      if (file) void this.ingest(file);
    });
    this.status.setAttribute("role", "status");
    this.serviceNote.setAttribute("role", "status");
    const demo = button(
      "Try the demo clip",
      () => void this.demo(),
      "text-button"
    );
    demo.title =
      "Generated artwork and synthesized audio, not a real-object recording.";
    this.bring.append(
      drop,
      this.input,
      element(
        "p",
        "muted",
        `A clip of up to 1 minute and 200 MB. You'll keep ${MAX_STRETCH_S} seconds of its sound.`
      ),
      this.rightsField,
      this.status,
      demo,
      this.serviceNote
    );
  }

  show(): void {
    this.root.hidden = false;
    this.rights.checked = rememberedRights();
    this.rightsField.hidden = this.rights.checked;
    audio.setDucked(true);
    this.root.focus({ preventScroll: true });
    const epoch = ++this.healthEpoch;
    this.serviceNote.textContent = "Checking available tools…";
    void gateway
      .health()
      .then((health) => {
        if (epoch !== this.healthEpoch) return;
        this.applyService(health);
      })
      .catch(() => {
        if (epoch !== this.healthEpoch) return;
        this.applyService(undefined);
        this.serviceNote.textContent =
          "Service availability could not be checked. Reopen Add to retry.";
      });
  }

  private applyService(health?: Health): void {
    this.review.setService(health);
    if (!health) return;
    this.serviceNote.textContent =
      health.mode === "mock"
        ? "Demo tools: cutouts are rectangular crops; sounds are raw copies."
        : [
            !health.sam
              ? "AI cutouts are unavailable; your painting is used."
              : "",
            !health.image ? "Painting is unavailable." : "",
            !health.audio
              ? "Sound separation is unavailable; the original clip still works."
              : "",
          ]
            .filter(Boolean)
            .join(" ");
  }

  close(finished = false): void {
    this.root.hidden = true;
    this.clip.pause();
    this.review.pause();
    audio.setDucked(false);
    if (finished) {
      this.reached = new Set(["bring"]);
      this.setPhase("bring");
    }
    document.querySelector<HTMLCanvasElement>("#canvas")?.focus();
  }

  async demo(): Promise<void> {
    this.show();
    const response = await fetch("/demo-source.mp4");
    if (!response.ok) {
      this.status.textContent = "Demo clip unavailable. Import your own media.";
      return;
    }
    // The demo is the project's own generated clip, so no permission is needed for it.
    await this.ingest(
      new File([await response.blob()], "generated-demo.mp4", {
        type: "video/mp4",
      }),
      true
    );
  }

  private setPhase(phase: Phase): void {
    this.reached.add(phase);
    this.root.dataset.phase = phase;
    if (!this.root.hidden) this.root.focus({ preventScroll: true });
    this.bring.hidden = phase !== "bring";
    this.clip.root.hidden = phase !== "moment";
    this.objects.root.hidden = phase !== "object";
    this.review.root.hidden = phase !== "review";
    this.steps.hidden = phase === "bring";
    if (phase !== "moment") this.clip.pause();
    if (phase !== "review") this.review.pause();
    for (const { id } of STEPS) {
      const step = this.stepButtons.get(id)!;
      const available = this.reached.has(id);
      step.disabled = !available;
      step.title = available ? "" : "Finish the earlier steps first.";
      if (id === phase) step.setAttribute("aria-current", "step");
      else step.removeAttribute("aria-current");
    }
  }

  private fail(message: string): void {
    this.status.textContent = message;
    this.status.classList.add("error");
  }

  private async ingest(file: File, ownClip = false): Promise<void> {
    if (this.busy) return;
    this.status.classList.remove("error");
    if (!ownClip && !this.rights.checked) {
      this.pendingFile = file;
      this.setPhase("bring");
      this.rightsField.hidden = false;
      this.status.textContent = `Tick the box above to open ${file.name}.`;
      return;
    }
    if (file.size > 200 * 1024 * 1024) {
      this.setPhase("bring");
      this.fail("Keep media under 200 MB and 1 minute.");
      return;
    }
    this.busy = true;
    this.setPhase("bring");
    this.status.textContent = "Opening your source…";
    try {
      const media = await gateway.upload(file);
      if (!media.audio_present) {
        this.fail(
          "This source has no audio. Import a recording or video with an audible sound."
        );
        return;
      }
      this.pendingFile = undefined;
      await saveBlob(`source-${media.id}`, file);
      this.acceptSource(file, media);
      this.status.textContent = "";
    } catch (error) {
      this.fail(error instanceof Error ? error.message : String(error));
    } finally {
      this.busy = false;
    }
  }

  private acceptSource(file: File, media: Media): void {
    this.review.reset();
    if (this.source) URL.revokeObjectURL(this.source.url);
    this.source = { file, media, url: URL.createObjectURL(file) };
    this.reached = new Set(["bring", "moment"]);
    this.clip.open(media, this.source.url, file);
    this.setPhase("moment");
  }

  private momentKept(moment: KeptMoment): void {
    const source = this.source;
    if (!source) return;
    this.moment = moment;
    this.reached.delete("review");
    this.objects.open(source.media, moment.start, moment.end);
    this.setPhase("object");
  }

  private made(made: Made): void {
    const source = this.source;
    const moment = this.moment;
    if (!source || !moment) return;
    this.review.open(source, made, moment);
    this.setPhase("review");
  }
}
