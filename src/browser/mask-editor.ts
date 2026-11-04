import { button, element, field, setBlocked } from "./dom";

export type MaskTool = "paint" | "erase";
const MAX_CANVAS_WIDTH = 1280;
const HISTORY_LIMIT = 12;
const WASH = "rgba(247, 245, 236, 0.76)";
const INK = "#29271f";

/**
 * A brush mask painted directly over the source picture. Outside the mask washes back to paper, so
 * the object stays in full colour and what will be cut is visible while painting.
 */
export class MaskEditor {
  readonly overlay = element("canvas", "mask-overlay");
  readonly cursor = element("span", "mask-brush");
  readonly tools = element("div", "mask-tools");
  tool: MaskTool = "paint";
  /** Counts every change, so a caller can tell whether this is still the mask it last used. */
  revision = 0;
  private mask = element("canvas");
  private edge = element("canvas");
  private history: ImageData[] = [];
  private empty = true;
  private enabled = true;
  private brushShare = 0.02;
  private drawing = false;
  private last?: { x: number; y: number };
  private frame?: number;
  private toolButtons = new Map<MaskTool, HTMLButtonElement>();
  private undoButton: HTMLButtonElement;
  private brush = element("input");

  constructor(
    private readonly preview: HTMLElement,
    width: number,
    height: number,
    private readonly onChange: () => void
  ) {
    const scale = Math.min(1, MAX_CANVAS_WIDTH / width);
    for (const canvas of [this.overlay, this.mask, this.edge]) {
      canvas.width = Math.round(width * scale);
      canvas.height = Math.round(height * scale);
    }
    this.overlay.setAttribute("aria-hidden", "true");
    this.cursor.setAttribute("aria-hidden", "true");
    this.cursor.hidden = true;
    const choices = element("div", "mask-choices");
    choices.setAttribute("role", "group");
    choices.setAttribute("aria-label", "Selection tool");
    for (const [tool, label] of [
      ["paint", "Paint"],
      ["erase", "Erase"],
    ] as const) {
      const choice = button(label, () => this.setTool(tool));
      this.toolButtons.set(tool, choice);
      choices.append(choice);
    }
    this.brush.type = "range";
    this.brush.min = "0.5";
    this.brush.max = "12";
    this.brush.step = "0.5";
    this.brush.value = String(this.brushShare * 100);
    this.brush.addEventListener("input", () => {
      this.brushShare = Number(this.brush.value) / 100;
    });
    const size = field("Brush size", this.brush);
    size.classList.add("mask-size");
    this.undoButton = button("Undo", () => this.undo());
    this.tools.append(choices, size, this.undoButton);
    preview.addEventListener("pointerdown", (event) => this.begin(event));
    preview.addEventListener("pointermove", (event) => this.move(event));
    preview.addEventListener("pointerup", () => this.end());
    preview.addEventListener("pointercancel", () => this.end());
    preview.addEventListener("pointerleave", () => {
      this.cursor.hidden = true;
    });
    this.setTool("paint");
  }

  private get context(): CanvasRenderingContext2D {
    return this.mask.getContext("2d", { willReadFrequently: true })!;
  }

  /**
   * Paint on the picture's real shape. Stored video can differ from what displays, and a canvas of
   * another shape would stretch the brush and make a mask that does not fit the frame.
   */
  matchFrame(width: number, height: number): void {
    const scale = Math.min(1, MAX_CANVAS_WIDTH / Math.max(width, height));
    const fitted = {
      width: Math.round(width * scale),
      height: Math.round(height * scale),
    };
    if (fitted.width === this.mask.width && fitted.height === this.mask.height)
      return;
    const previous = element("canvas");
    previous.width = this.mask.width;
    previous.height = this.mask.height;
    previous.getContext("2d")!.drawImage(this.mask, 0, 0);
    for (const canvas of [this.overlay, this.mask, this.edge]) {
      canvas.width = fitted.width;
      canvas.height = fitted.height;
    }
    this.context.drawImage(previous, 0, 0, fitted.width, fitted.height);
    this.history = [];
    this.render();
    this.setEnabled(this.enabled);
  }

  setEnabled(enabled: boolean): void {
    this.enabled = enabled;
    const wait = enabled ? "" : "Wait for the current step to finish.";
    for (const choice of this.toolButtons.values()) setBlocked(choice, wait);
    this.brush.disabled = !enabled;
    setBlocked(
      this.undoButton,
      wait || (this.history.length ? "" : "Nothing to undo yet.")
    );
  }

  get isEmpty(): boolean {
    return this.empty;
  }

  private paintedBounds(): [number, number, number, number] | null {
    if (this.empty) return null;
    const { width, height } = this.mask;
    const { data } = this.context.getImageData(0, 0, width, height);
    let [left, top, right, bottom] = [width, height, -1, -1];
    for (let y = 0; y < height; y++)
      for (let x = 0; x < width; x++)
        if (data[(y * width + x) * 4 + 3] > 0) {
          left = Math.min(left, x);
          right = Math.max(right, x);
          top = Math.min(top, y);
          bottom = Math.max(bottom, y);
        }
    return right < 0 ? null : [left, top, right + 1, bottom + 1];
  }

  /** The painted area as a box from 0 to 1, for telling the model where to look. */
  paintedBox(): number[] | null {
    const bounds = this.paintedBounds();
    if (!bounds) return null;
    const { width, height } = this.mask;
    return [
      bounds[0] / width,
      bounds[1] / height,
      bounds[2] / width,
      bounds[3] / height,
    ];
  }

  /** Just what was painted, cropped from the picture, to show it being cut out. */
  paintedPicture(picture: HTMLImageElement): string | undefined {
    const bounds = this.paintedBounds();
    if (!bounds) return undefined;
    const [left, top, right, bottom] = bounds;
    const canvas = element("canvas");
    canvas.width = right - left;
    canvas.height = bottom - top;
    const context = canvas.getContext("2d")!;
    context.drawImage(picture, -left, -top, this.mask.width, this.mask.height);
    context.globalCompositeOperation = "destination-in";
    context.drawImage(this.mask, -left, -top);
    try {
      return canvas.toDataURL("image/png");
    } catch {
      return undefined;
    }
  }

  setTool(tool: MaskTool): void {
    this.tool = tool;
    this.preview.dataset.tool = tool;
    for (const [name, choice] of this.toolButtons)
      choice.setAttribute("aria-pressed", String(name === tool));
    this.render();
  }

  /** Forget the mask, as when the picture under it changes. */
  clear(): void {
    this.context.clearRect(0, 0, this.mask.width, this.mask.height);
    this.history = [];
    this.empty = true;
    this.revision++;
    this.render();
    this.setEnabled(this.enabled);
  }

  toBlob(): Promise<Blob> {
    return new Promise((resolve, reject) => {
      this.mask.toBlob(
        (blob) =>
          blob ? resolve(blob) : reject(new Error("Could not read the mask.")),
        "image/png"
      );
    });
  }

  private remember(): void {
    this.history.push(
      this.context.getImageData(0, 0, this.mask.width, this.mask.height)
    );
    if (this.history.length > HISTORY_LIMIT) this.history.shift();
  }

  private undo(): void {
    const previous = this.history.pop();
    if (!previous) return;
    this.context.putImageData(previous, 0, 0);
    this.changed();
  }

  private changed(): void {
    this.revision++;
    this.refreshEmpty();
    this.render();
    this.setEnabled(this.enabled);
    this.onChange();
  }

  private refreshEmpty(): void {
    const { data } = this.context.getImageData(
      0,
      0,
      this.mask.width,
      this.mask.height
    );
    this.empty = true;
    for (let index = 3; index < data.length; index += 4)
      if (data[index] > 0) {
        this.empty = false;
        return;
      }
  }

  private point(event: PointerEvent): { x: number; y: number } {
    const bounds = this.preview.getBoundingClientRect();
    return {
      x: ((event.clientX - bounds.left) / bounds.width) * this.mask.width,
      y: ((event.clientY - bounds.top) / bounds.height) * this.mask.height,
    };
  }

  private stroke(to: { x: number; y: number }): void {
    const context = this.context;
    const from = this.last ?? to;
    context.globalCompositeOperation =
      this.tool === "erase" ? "destination-out" : "source-over";
    context.strokeStyle = context.fillStyle = "#fff";
    context.lineCap = context.lineJoin = "round";
    context.lineWidth = this.brushShare * this.mask.width * 2;
    context.beginPath();
    context.moveTo(from.x, from.y);
    context.lineTo(to.x + 0.01, to.y);
    context.stroke();
    context.globalCompositeOperation = "source-over";
    this.last = to;
    if (this.frame === undefined)
      this.frame = requestAnimationFrame(() => {
        this.frame = undefined;
        this.render();
      });
  }

  private begin(event: PointerEvent): void {
    if (!this.enabled) return;
    this.preview.setPointerCapture(event.pointerId);
    this.remember();
    this.drawing = true;
    this.last = undefined;
    this.stroke(this.point(event));
  }

  private move(event: PointerEvent): void {
    if (!this.enabled) return;
    const bounds = this.preview.getBoundingClientRect();
    const diameter = this.brushShare * bounds.width * 2;
    this.cursor.hidden = false;
    this.cursor.style.width = this.cursor.style.height = `${diameter}px`;
    this.cursor.style.transform = `translate(${
      event.clientX - bounds.left - diameter / 2
    }px, ${event.clientY - bounds.top - diameter / 2}px)`;
    if (this.drawing) this.stroke(this.point(event));
  }

  private end(): void {
    if (!this.drawing) return;
    this.drawing = false;
    this.last = undefined;
    this.changed();
  }

  private render(): void {
    const context = this.overlay.getContext("2d")!;
    context.clearRect(0, 0, this.overlay.width, this.overlay.height);
    if (this.empty && !this.drawing) return;
    context.globalCompositeOperation = "source-over";
    context.fillStyle = WASH;
    context.fillRect(0, 0, this.overlay.width, this.overlay.height);
    context.globalCompositeOperation = "destination-out";
    context.drawImage(this.mask, 0, 0);
    context.globalCompositeOperation = "source-over";
    if (!this.empty || this.drawing) context.drawImage(this.inkLine(), 0, 0);
  }

  /** The cut line: the mask nudged outward in each direction, minus the mask itself. */
  private inkLine(): HTMLCanvasElement {
    const context = this.edge.getContext("2d")!;
    const reach = Math.max(1, Math.round(this.edge.width / 640));
    context.globalCompositeOperation = "source-over";
    context.clearRect(0, 0, this.edge.width, this.edge.height);
    for (const [x, y] of [
      [reach, 0],
      [-reach, 0],
      [0, reach],
      [0, -reach],
    ])
      context.drawImage(this.mask, x, y);
    context.globalCompositeOperation = "source-in";
    context.fillStyle = INK;
    context.fillRect(0, 0, this.edge.width, this.edge.height);
    context.globalCompositeOperation = "destination-out";
    context.drawImage(this.mask, 0, 0);
    return this.edge;
  }
}
