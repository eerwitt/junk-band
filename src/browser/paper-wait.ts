import { element } from "./dom";

export type WaitScene = "sound" | "paint" | "cut";
export type WaitNote = readonly [afterSeconds: number, text: string];
export interface WaitView {
  scene: WaitScene | null;
  image?: string;
  line: string;
  steps?: readonly string[];
  step?: number;
  notes: readonly WaitNote[];
}

export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
export function noteFor(
  seconds: number,
  notes: readonly WaitNote[]
): string | undefined {
  let current: string | undefined;
  for (const [after, text] of notes) if (seconds >= after) current = text;
  return current;
}

/** One period of wave, repeated to cover `width` plus the distance it scrolls. */
function wave(
  values: readonly number[],
  period: number,
  width: number
): string {
  const spacing = period / values.length;
  const count = Math.ceil((width + period) / spacing);
  let path = "";
  for (let index = 0; index <= count; index++)
    path += `${index ? "L" : "M"}${(index * spacing).toFixed(1)} ${values[
      index % values.length
    ].toFixed(1)}`;
  return path;
}
const MIXED = [32, 25, 41, 18, 37, 12, 50, 26, 40, 22, 34, 29];
const TARGET = Array.from(
  { length: 16 },
  (_, index) => 22 + 13 * Math.sin((index / 16) * Math.PI * 2)
);
const REST = [22, 18, 26, 20, 16, 25, 21, 28, 19, 23];

const FLOOR = `<path class="wait-floor" d="M0 101 L132 99 L301 102 L456 100 V120 H0Z"/>`;
export const SCISSOR_BLADES = `
  <g class="wait-blade wait-blade-a">
    <path class="wait-ink" d="M7 2.5 L-40 -1 Q-20 -8 7 -3.5Z"/>
    <path class="wait-handle" d="M5 0 L18 6"/>
    <circle class="wait-grip" cx="25" cy="10" r="7.5"/>
  </g>
  <g class="wait-blade wait-blade-b">
    <path class="wait-ink" d="M7 -2.5 L-40 1 Q-20 8 7 3.5Z"/>
    <path class="wait-handle" d="M5 0 L18 -6"/>
    <circle class="wait-grip" cx="25" cy="-10" r="7.5"/>
  </g>
  <circle class="wait-rivet" r="2.4"/>`;
const TIN = `<svg class="wait-object" viewBox="0 0 70 84" aria-hidden="true">
  <path class="wait-tin-rim" d="M10 13 L60 11 L63 74 Q35 83 7 75Z"/>
  <path class="wait-tin" d="M14 16 L56 14 L58 71 Q35 78 12 72Z"/>
  <path class="wait-tin-rib" d="M13 30 Q35 35 57 29 M13 58 Q35 63 58 57"/>
  <path class="wait-tin-dent" d="M33 41 L43 45 L37 51"/>
  <ellipse class="wait-tin-top" cx="35" cy="14" rx="23" ry="6"/>
</svg>`;

function svg(markup: string): DocumentFragment {
  const template = document.createElement("template");
  template.innerHTML = markup;
  return template.content;
}

function object(image?: string): Element {
  if (!image) return svg(TIN).firstElementChild!;
  const node = element("img", "wait-object");
  node.alt = "";
  node.draggable = false;
  node.src = image;
  node.addEventListener("error", () => {
    if (node.isConnected) node.replaceWith(svg(TIN).firstElementChild!);
  });
  return node;
}

function bench(markup = ""): DocumentFragment {
  return svg(
    `<svg class="wait-bench" viewBox="0 0 456 120" aria-hidden="true">${FLOOR}${markup}</svg>`
  );
}

function soundScene(image?: string): DocumentFragment {
  const scene = document.createDocumentFragment();
  scene.append(
    bench(`
      <svg x="96" y="26" width="130" height="64" viewBox="0 0 130 64">
        <path class="wait-wave wait-wave-in" d="${wave(MIXED, 48, 130)}"/>
      </svg>
      <path class="wait-fork wait-fork-target" d="M226 58 Q240 36 252 36"/>
      <path class="wait-fork wait-fork-rest" d="M226 58 Q240 82 252 82"/>
      <svg x="252" y="14" width="204" height="44" viewBox="0 0 204 44">
        <path class="wait-wave wait-wave-target" d="${wave(TARGET, 64, 204)}"/>
      </svg>
      <svg x="252" y="60" width="204" height="44" viewBox="0 0 204 44">
        <path class="wait-wave wait-wave-rest" d="${wave(REST, 40, 204)}"/>
      </svg>
      <path class="wait-chip wait-chip-a" d="M222 72 l7 2 l-2 6 l-7 -3Z"/>
      <path class="wait-chip wait-chip-b" d="M230 74 l6 -1 l1 5 l-6 2Z"/>
      <path class="wait-chip wait-chip-c" d="M217 76 l5 1 l-1 5 l-5 -2Z"/>
      <g transform="translate(226 58) scale(1.2)">${SCISSOR_BLADES}</g>`)
  );
  const performer = element("div", "wait-performer");
  performer.append(object(image));
  scene.append(performer);
  return scene;
}

function figureScene(kind: "paint" | "cut", image?: string) {
  const scene = bench(
    kind === "paint"
      ? `<g class="wait-pots">
           <path class="wait-pot wait-pot-orange" d="M352 80 L382 79 L379 103 L355 103Z"/>
           <path class="wait-pot wait-pot-yellow" d="M388 84 L414 83 L411 103 L391 103Z"/>
           <path class="wait-pot wait-pot-mint" d="M322 87 L346 86 L344 103 L324 103Z"/>
         </g>`
      : ""
  );
  const fragment = document.createDocumentFragment();
  fragment.append(scene);
  const figure = element("div", `wait-figure wait-figure-${kind}`);
  figure.append(element("span", "wait-shadow"), object(image));
  if (kind === "paint") {
    const painted = element("div", "wait-painted");
    painted.append(object(image));
    const sweep = element("div", "wait-sweep");
    sweep.append(
      svg(`<svg class="wait-brush" viewBox="0 0 30 86" aria-hidden="true">
        <path class="wait-brush-handle" d="M13 0 L18 0 L19 44 L12 44Z"/>
        <path class="wait-brush-band" d="M10 44 L21 44 L22 54 L9 54Z"/>
        <path class="wait-brush-hair" d="M9 54 L22 54 Q25 72 16 86 Q6 72 9 54Z"/>
      </svg>`)
    );
    figure.append(painted, sweep);
  }
  if (kind === "cut") {
    figure.append(
      svg(`<svg class="wait-ring" viewBox="0 0 100 100" aria-hidden="true">
        <circle class="wait-ring-line" cx="50" cy="50" r="46"/>
      </svg>`)
    );
    const orbit = element("div", "wait-orbit");
    orbit.append(
      svg(`<svg class="wait-snips" viewBox="-44 -22 80 44" aria-hidden="true">
        ${SCISSOR_BLADES}
      </svg>`)
    );
    figure.append(orbit);
  }
  fragment.append(figure);
  return fragment;
}

/**
 * A stop-motion workbench shown during long jobs. It reports only what is known: real stages and
 * real elapsed time, never a percentage or an estimate. Keep it outside markup rebuilt on poll;
 * reinserting it would restart its animation.
 */
export class PaperWait {
  readonly root = element("div", "paper-wait");
  private scene = element("div", "wait-scene");
  private message = element("p", "wait-line");
  private meta = element("div", "wait-meta");
  private steps = element("ol", "wait-steps");
  private clock = element("span", "wait-clock");
  private note = element("p", "fine");
  private startedAt?: number;
  private timer?: number;
  private sceneKey = "";
  private stepsKey = "";
  private notes: readonly WaitNote[] = [];

  constructor() {
    this.root.hidden = true;
    this.scene.setAttribute("aria-hidden", "true");
    this.clock.setAttribute("aria-hidden", "true");
    this.message.setAttribute("role", "status");
    this.note.setAttribute("role", "status");
    this.meta.append(this.steps, this.clock);
    this.root.append(this.scene, this.message, this.meta, this.note);
  }

  show(view: WaitView): void {
    const entering = this.root.hidden;
    this.root.hidden = false;
    if (this.message.textContent !== view.line)
      this.message.textContent = view.line;
    this.renderScene(view);
    this.renderSteps(view);
    this.notes = view.notes;
    if (entering) {
      this.startedAt = Date.now();
      this.timer = window.setInterval(() => this.tick(), 1000);
      this.root.scrollIntoView({ block: "nearest" });
    }
    this.tick();
  }

  hide(): void {
    if (this.root.hidden) return;
    this.root.hidden = true;
    window.clearInterval(this.timer);
    this.startedAt = undefined;
    this.sceneKey = "";
    this.scene.replaceChildren();
  }

  private renderScene(view: WaitView): void {
    const key = `${view.scene}|${view.image ?? ""}`;
    if (key === this.sceneKey) return;
    this.sceneKey = key;
    this.scene.hidden = !view.scene;
    this.scene.replaceChildren(
      view.scene === "sound"
        ? soundScene(view.image)
        : view.scene
        ? figureScene(view.scene, view.image)
        : ""
    );
  }

  private renderSteps(view: WaitView): void {
    const key = `${view.steps?.join("|")}@${view.step}`;
    if (key === this.stepsKey) return;
    this.stepsKey = key;
    this.steps.replaceChildren(
      ...(view.steps ?? []).map((label, index) => {
        const step = element("li", "wait-step", label);
        const current = view.step ?? 0;
        step.dataset.state =
          index < current ? "done" : index === current ? "current" : "todo";
        if (index === current) step.setAttribute("aria-current", "step");
        return step;
      })
    );
  }

  private tick(): void {
    if (this.startedAt === undefined) return;
    const seconds = (Date.now() - this.startedAt) / 1000;
    this.clock.textContent = formatClock(seconds);
    const note = noteFor(seconds, this.notes) ?? "";
    if (this.note.textContent !== note) this.note.textContent = note;
    this.note.hidden = !note;
  }
}
