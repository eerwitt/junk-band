import { audio } from "../../audio/browser";
import { gateway, type Health, type Media } from "../../services/gateway";
import { saveBlob } from "../../storage/database";
import { button, element, field } from "../dom";
import type { StudioStore } from "../store";
import { ClipPhase, type KeptMoment } from "./clip-phase";
import { FinishPhase, type FinishSource } from "./finish-phase";
import { ObjectsPhase, type Chosen } from "./objects-phase";

type Phase = "bring" | "moment" | "object" | "finish";
const PHASES: readonly { id: Phase; label: string }[] = [
  { id: "bring", label: "Bring it in" },
  { id: "moment", label: "Pick the moment" },
  { id: "object", label: "Choose the object" },
  { id: "finish", label: "Finish" },
];

/** Add takes over the stage: bring a clip in, pick a moment, choose an object, finish. */
export class AddStudio {
  private root = element("aside", "add-studio");
  private steps = element("ol", "add-steps");
  private stepButtons = new Map<Phase, HTMLButtonElement>();
  private bring = element("section", "bring-phase");
  private rights = element("input");
  private input = element("input");
  private status = element("p", "feedback");
  private serviceNote = element("p", "fine", "Checking available tools…");
  private pending = element("div");
  private pendingFile?: File;
  private clip: ClipPhase;
  private objects: ObjectsPhase;
  private finish: FinishPhase;
  private source?: FinishSource;
  private reached = new Set<Phase>(["bring"]);
  private busy = false;
  private healthEpoch = 0;

  constructor(store: StudioStore) {
    this.clip = new ClipPhase((moment) => this.momentKept(moment));
    this.objects = new ObjectsPhase((chosen, window) =>
      this.objectChosen(chosen, window)
    );
    this.finish = new FinishPhase(
      store,
      () => !this.root.hidden,
      () => this.close(true),
      () => this.setPhase("object")
    );
    this.root.hidden = true;
    this.root.tabIndex = -1;
    this.root.setAttribute("role", "dialog");
    this.root.setAttribute("aria-label", "Add to the band");
    const header = element("header", "add-header");
    const closeButton = button("Close", () => this.close());
    for (const { id, label } of PHASES) {
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
      this.finish.root
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
    this.bring.append(
      drop,
      this.input,
      field("I own this media or have permission to use it", this.rights),
      element(
        "p",
        "muted",
        "Use a clip of up to 1 minute and 200 MB, with a clearly audible object."
      ),
      this.pending,
      this.status,
      button(
        "Try the generated demo clip",
        () => void this.demo(),
        "text-button"
      ),
      element(
        "p",
        "fine",
        "Demo clip: generated artwork + synthesized audio. Not a real-object recording."
      ),
      this.serviceNote
    );
  }

  show(): void {
    this.root.hidden = false;
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
    this.objects.setService(health);
    this.finish.setService(health);
    if (!health) return;
    this.serviceNote.textContent =
      health.mode === "mock"
        ? "Demo tools: cutouts are rectangular crops; sound targets are raw copies."
        : [
            !health.sam
              ? "Finding by name is unavailable; a rough box or painted mask still works."
              : "",
            !health.image
              ? "Painting is unavailable; you can use it as is."
              : "",
            !health.audio
              ? "Sound separation is unavailable; raw audio still works."
              : "",
          ]
            .filter(Boolean)
            .join(" ");
  }

  close(finished = false): void {
    this.root.hidden = true;
    this.clip.pause();
    this.finish.pause();
    audio.setDucked(false);
    if (finished) {
      this.objects.reset();
      this.reached = new Set(["bring"]);
      this.setPhase("bring");
    }
    document.querySelector<HTMLCanvasElement>("#canvas")?.focus();
  }

  async demo(): Promise<void> {
    this.show();
    this.rights.checked = true;
    const response = await fetch("/demo-source.mp4");
    if (!response.ok) {
      this.status.textContent = "Demo clip unavailable. Import your own media.";
      return;
    }
    await this.ingest(
      new File([await response.blob()], "generated-demo.mp4", {
        type: "video/mp4",
      })
    );
  }

  private setPhase(phase: Phase): void {
    this.reached.add(phase);
    this.root.dataset.phase = phase;
    if (!this.root.hidden) this.root.focus({ preventScroll: true });
    this.bring.hidden = phase !== "bring";
    this.clip.root.hidden = phase !== "moment";
    this.objects.root.hidden = phase !== "object";
    this.finish.root.hidden = phase !== "finish";
    if (phase !== "moment") this.clip.pause();
    if (phase !== "finish") this.finish.pause();
    for (const { id } of PHASES) {
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

  private async ingest(file: File): Promise<void> {
    if (this.busy) return;
    this.status.classList.remove("error");
    if (!this.rights.checked) {
      this.pendingFile = file;
      this.setPhase("bring");
      this.pending.replaceChildren(
        button(`Open ${file.name}`, () => {
          if (this.pendingFile) void this.ingest(this.pendingFile);
        })
      );
      this.status.textContent =
        "Confirm your permission above, then open the dropped file.";
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
      this.pending.replaceChildren();
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
    this.objects.reset();
    this.finish.reset();
    if (this.source) URL.revokeObjectURL(this.source.url);
    this.source = { file, media, url: URL.createObjectURL(file) };
    this.reached = new Set(["bring", "moment"]);
    this.clip.open(media, this.source.url, file);
    this.setPhase("moment");
  }

  private momentKept(moment: KeptMoment): void {
    const source = this.source;
    if (!source) return;
    if (!source.media.width) {
      this.reached.add("finish");
      this.finish.open(source, undefined, moment.sound ?? "", {
        start: moment.start,
        end: Math.min(moment.end, moment.start + 8),
      });
      this.setPhase("finish");
      return;
    }
    this.reached.delete("finish");
    this.objects.open(source.media, moment.start, moment.end);
    this.setPhase("object");
  }

  private objectChosen(
    chosen: Chosen,
    window: { start: number; end: number }
  ): void {
    const source = this.source;
    if (!source) return;
    this.finish.open(source, chosen, chosen.sound, window);
    this.setPhase("finish");
  }
}
