import { audio } from "../../audio/browser";
import { boostFor } from "../../audio/tighten";
import {
  Microphone,
  cutTake,
  finishTake,
  peakOf,
  rotate,
} from "../../audio/take";
import { encodeWav } from "../../audio/wav";
import { loopBars } from "../../domain/timing";
import { saveBlob } from "../../storage/database";
import { button, element, field, setBlocked, textInput } from "../dom";
import type { StudioStore } from "../store";

/** The four paper characters on the sprite sheet, in its order. */
const SINGERS = [
  { name: "Tin", color: "#bd7046" },
  { name: "Duck", color: "#d7b34e" },
  { name: "Bottle", color: "#6d9990" },
  { name: "Matchbox", color: "#8b849d" },
] as const;
const LENGTHS = [1, 2, 4] as const;
/** Loud enough to sing along to, quiet enough to hear yourself. */
const BAND_WHILE_SINGING = 0.7;
/** Quieter than this, the take is probably a microphone that is off. */
const QUIET_PEAK = 0.01;
/** Room after the last bar for late samples to arrive before the take is cut. */
const SETTLE_S = 0.15;

type State = "idle" | "opening" | "counting" | "recording" | "done";

interface Plan {
  countAt: number;
  startAt: number;
  endAt: number;
  startBar: number;
  bars: number;
  barS: number;
  latency: number;
}

/**
 * Sing, beatbox or bang a pot along with the band. A bar of count-in, then exactly the bars
 * chosen are kept, lined up with the song, so the take comes round as a phrase with no gap and
 * nothing to trim. It needs no server, so it works anywhere.
 */
export class SingAlong {
  readonly root = element("section", "sing-phase");
  private singers: HTMLButtonElement[] = [];
  private lengths: HTMLButtonElement[] = [];
  private count = element("p", "sing-count", "Ready");
  private progress = element("div", "sing-bars");
  private level = element("span", "sing-level-fill");
  private wave = element("canvas", "sing-wave");
  private recordButton = button(
    "Record",
    () => void this.record(),
    "sing-record"
  );
  private status = element("p", "feedback");
  private nameInput = textInput("Its name", "Singer");
  private hear = button("Hear it with the band", () => this.preview());
  private addButton = button("Add to band", () => void this.add(), "primary");
  private kept = element("div", "sing-kept");
  private tile = 1;
  private bars: number = 2;
  private state: State = "idle";
  private mic?: Microphone;
  private plan?: Plan;
  private take?: { buffer: AudioBuffer; quiet: boolean };
  private frame = 0;
  private stopPreview?: () => void;
  private previewTimer?: number;
  private epoch = 0;
  private raised = false;

  constructor(
    private readonly store: StudioStore,
    private readonly onDone: () => void,
    onBack: () => void
  ) {
    const singers = element("div", "singer-picker");
    singers.setAttribute("role", "group");
    singers.setAttribute("aria-label", "Who's singing?");
    SINGERS.forEach((singer, index) => {
      const choice = button(
        "",
        () => {
          this.tile = index;
          this.render();
        },
        "singer"
      );
      choice.setAttribute("aria-label", singer.name);
      choice.title = singer.name;
      choice.style.backgroundPosition = `${(index % 2) * 100}% ${
        Math.floor(index / 2) * 100
      }%`;
      this.singers.push(choice);
      singers.append(choice);
    });
    const lengths = element("div", "review-choice sing-lengths");
    lengths.setAttribute("role", "group");
    lengths.setAttribute("aria-label", "How long");
    for (const bars of LENGTHS) {
      const choice = button(bars === 1 ? "1 bar" : `${bars} bars`, () => {
        this.bars = bars;
        this.render();
      });
      this.lengths.push(choice);
      lengths.append(choice);
    }
    for (let bar = 0; bar < 4; bar++)
      this.progress.append(element("span", "sing-bar"));
    const meter = element("span", "sing-level");
    meter.setAttribute("aria-hidden", "true");
    meter.append(this.level);
    this.wave.setAttribute("aria-hidden", "true");
    const stage = element("div", "sing-stage");
    stage.append(this.count, this.progress, meter, this.wave);
    this.count.setAttribute("aria-live", "assertive");
    this.status.setAttribute("role", "status");
    this.kept.append(field("Its name", this.nameInput), this.hear);
    const choices = element("div", "sing-choices");
    choices.append(
      element("h4", "review-style-head", "Who's singing?"),
      singers,
      element("h4", "review-style-head", "How long"),
      lengths,
      element(
        "p",
        "fine",
        "One bar of clicks counts you in, then it records exactly that long, in time with the band. Headphones help: then only you are recorded."
      )
    );
    const body = element("div", "sing-body");
    body.append(choices, stage);
    const actions = element("div", "phase-actions");
    actions.append(
      button(
        "Back",
        () => {
          this.leave();
          onBack();
        },
        "text-button"
      ),
      this.status,
      this.recordButton,
      this.addButton
    );
    this.root.append(
      element(
        "p",
        "sing-lead",
        "Sing it, beatbox it, or bang along. Your sound joins the band right where you played it."
      ),
      body,
      this.kept,
      actions
    );
    this.render();
  }

  open(): void {
    this.status.textContent = "";
    this.status.classList.remove("error");
    this.render();
  }

  /** Stop everything and give the microphone back, as when leaving this page. */
  leave(): void {
    this.epoch++;
    cancelAnimationFrame(this.frame);
    this.endPreview();
    this.mic?.close();
    this.mic = undefined;
    this.plan = undefined;
    if (this.state !== "done") this.state = "idle";
    // Back to the quiet band the rest of Add has, if this page brought it up.
    if (this.raised) audio.setDucked(true);
    this.raised = false;
    this.render();
  }

  /** Forget the take, as for starting over. */
  reset(): void {
    this.leave();
    this.take = undefined;
    this.state = "idle";
    this.nameInput.value = "Singer";
    this.render();
  }

  private busy(): boolean {
    return (
      this.state === "opening" ||
      this.state === "counting" ||
      this.state === "recording"
    );
  }

  private fail(text: string): void {
    this.state = this.take ? "done" : "idle";
    this.status.textContent = text;
    this.status.classList.add("error");
    this.render();
  }

  private async record(): Promise<void> {
    if (this.busy()) {
      // Pressed again while counting or recording: stop, keeping any earlier take.
      this.epoch++;
      cancelAnimationFrame(this.frame);
      this.mic?.heard();
      this.plan = undefined;
      this.state = this.take ? "done" : "idle";
      this.render();
      return;
    }
    const epoch = ++this.epoch;
    this.endPreview();
    this.state = "opening";
    this.status.textContent = "";
    this.status.classList.remove("error");
    this.render();
    try {
      await audio.unlock();
      if (!audio.playing) {
        await audio.play(this.store.state.project);
        this.store.set({ playing: audio.playing });
      }
      this.raiseBand();
      this.mic ??= await Microphone.open(audio.liveContext!);
    } catch {
      if (epoch === this.epoch)
        this.fail(
          "The microphone isn't available. Let this page use it, then press Record again."
        );
      return;
    }
    if (epoch !== this.epoch) return;
    const context = audio.liveContext!;
    const bar = audio.barAfter(context.currentTime + 0.3);
    if (!bar) {
      this.fail("Press play on the band first, then record along with it.");
      return;
    }
    const barS = 240 / audio.tempo;
    const plan: Plan = {
      countAt: bar.time,
      startAt: bar.time + barS,
      endAt: bar.time + barS * (1 + this.bars),
      startBar: (bar.bar + 1) % loopBars,
      bars: this.bars,
      barS,
      latency: audio.outputLatency + this.mic.inputLatency,
    };
    for (let beat = 0; beat < 4; beat++)
      audio.tick(plan.countAt + (beat * barS) / 4, beat === 0);
    this.mic.listen();
    this.plan = plan;
    this.state = "counting";
    this.render();
    this.animate(epoch);
  }

  private animate(epoch: number): void {
    const step = (): void => {
      if (epoch !== this.epoch || !this.plan) return;
      const plan = this.plan;
      const now = audio.liveContext!.currentTime - audio.outputLatency;
      if (this.state === "counting" && now >= plan.startAt) {
        this.state = "recording";
        this.render();
      }
      if (now >= plan.endAt + plan.latency + SETTLE_S) {
        this.finish(plan);
        return;
      }
      this.drawLive(plan, now);
      this.frame = requestAnimationFrame(step);
    };
    this.frame = requestAnimationFrame(step);
  }

  private drawLive(plan: Plan, now: number): void {
    const beatS = plan.barS / 4;
    if (this.state === "counting") {
      const beat = Math.floor((now - plan.countAt) / beatS);
      this.count.textContent = beat < 0 ? "Get ready" : String(4 - beat);
      // A knock on each beat, landing with the click.
      const phase = (now - plan.countAt) / beatS - beat;
      this.count.style.transform =
        beat < 0 || matchMedia("(prefers-reduced-motion: reduce)").matches
          ? ""
          : `scale(${1 + 0.22 * Math.exp(-phase * 7)})`;
    } else {
      this.count.style.transform = "";
      const bar = Math.min(
        plan.bars,
        Math.floor((now - plan.startAt) / plan.barS) + 1
      );
      this.count.textContent =
        plan.bars === 1 ? "Go!" : `Go! Bar ${bar} of ${plan.bars}`;
    }
    const done = (now - plan.startAt) / plan.barS;
    [...this.progress.children].forEach((node, index) => {
      const fill = Math.min(1, Math.max(0, done - index));
      (node as HTMLElement).style.setProperty("--fill", String(fill));
    });
    this.level.style.transform = `scaleX(${Math.min(
      1,
      (this.mic?.level ?? 0) * 2.5
    )})`;
  }

  private finish(plan: Plan): void {
    const mic = this.mic!;
    const rate = mic.sampleRate;
    const lengthS = plan.bars * plan.barS;
    const samples = cutTake(
      mic.heard(),
      rate,
      plan.startAt + plan.latency,
      lengthS
    );
    const peak = peakOf(samples);
    finishTake(samples, rate, boostFor(peak));
    const shift = Math.round(
      ((plan.startBar % plan.bars) * samples.length) / plan.bars
    );
    const buffer = new AudioBuffer({
      length: samples.length,
      numberOfChannels: 1,
      sampleRate: rate,
    });
    buffer.getChannelData(0).set(rotate(samples, shift));
    this.take = { buffer, quiet: peak < QUIET_PEAK };
    this.plan = undefined;
    this.state = "done";
    this.status.textContent = this.take.quiet
      ? "That was very quiet. Is the microphone on? You can record again."
      : "";
    this.status.classList.toggle("error", this.take.quiet);
    this.render();
    this.drawWave();
  }

  /** The take, from its card's next start, with the band: exactly how it will play. */
  private preview(): void {
    if (this.stopPreview) {
      this.endPreview();
      this.render();
      return;
    }
    const take = this.take;
    const context = audio.liveContext;
    if (!take || !context) return;
    const bars = Math.round(take.buffer.duration / (240 / audio.tempo)) || 1;
    const bar = audio.barAfter(context.currentTime + 0.1);
    if (!bar) {
      this.fail("Press play on the band first, then listen.");
      return;
    }
    this.raiseBand();
    const wait = (bars - (bar.bar % bars)) % bars;
    const at = bar.time + (wait * 240) / audio.tempo;
    this.stopPreview = audio.playTake(take.buffer, at);
    this.previewTimer = window.setTimeout(() => {
      this.stopPreview = undefined;
      this.render();
    }, (at - context.currentTime + take.buffer.duration) * 1000 + 100);
    this.render();
  }

  private raiseBand(): void {
    audio.setDucked(true, BAND_WHILE_SINGING);
    this.raised = true;
  }

  private endPreview(): void {
    window.clearTimeout(this.previewTimer);
    this.stopPreview?.();
    this.stopPreview = undefined;
  }

  private async add(): Promise<void> {
    const take = this.take;
    if (!take || this.busy()) return;
    try {
      const id = crypto.randomUUID();
      await saveBlob(id, encodeWav(take.buffer));
      const singer = SINGERS[this.tile];
      this.store.add(
        {
          id,
          label: this.nameInput.value.trim().slice(0, 80) || singer.name,
          color: singer.color,
          sprite: "/sprites.png",
          tile: this.tile,
          audioId: id,
          provenance: "microphone",
          lengthS: take.buffer.duration,
        },
        "phrase"
      );
      this.reset();
      this.onDone();
    } catch (error) {
      this.fail(error instanceof Error ? error.message : String(error));
    }
  }

  private drawWave(): void {
    const canvas = this.wave;
    const take = this.take;
    const width = (canvas.width = canvas.clientWidth * devicePixelRatio || 600);
    const height = (canvas.height =
      canvas.clientHeight * devicePixelRatio || 120);
    const draw = canvas.getContext("2d");
    if (!draw || !take) return;
    draw.clearRect(0, 0, width, height);
    const samples = take.buffer.getChannelData(0);
    const columns = Math.max(1, Math.floor(width / (3 * devicePixelRatio)));
    const size = Math.max(1, Math.floor(samples.length / columns));
    draw.fillStyle = "#b86339";
    for (let column = 0; column < columns; column++) {
      let peak = 0;
      for (let i = column * size; i < (column + 1) * size; i++)
        peak = Math.max(peak, Math.abs(samples[i] ?? 0));
      const bar = Math.max(1, peak * height * 0.9);
      draw.fillRect(
        (column * width) / columns,
        (height - bar) / 2,
        Math.max(1, width / columns - devicePixelRatio),
        bar
      );
    }
    // Where each bar of the card begins.
    const bars = Math.round(take.buffer.duration / (240 / audio.tempo)) || 1;
    draw.fillStyle = "rgba(41, 39, 31, 0.35)";
    for (let bar = 1; bar < bars; bar++)
      draw.fillRect((bar * width) / bars, 0, devicePixelRatio, height);
  }

  private render(): void {
    const busy = this.busy();
    this.root.dataset.state = this.state;
    this.singers.forEach((choice, index) => {
      choice.setAttribute("aria-pressed", String(index === this.tile));
      choice.disabled = busy;
    });
    this.lengths.forEach((choice, index) => {
      choice.setAttribute("aria-pressed", String(LENGTHS[index] === this.bars));
      choice.disabled = busy;
    });
    [...this.progress.children].forEach((node, index) => {
      (node as HTMLElement).hidden = index >= (this.plan?.bars ?? this.bars);
      if (!busy) (node as HTMLElement).style.setProperty("--fill", "0");
    });
    if (this.state === "idle") this.count.textContent = "Ready";
    if (this.state === "opening") this.count.textContent = "Listening…";
    if (this.state === "done")
      this.count.textContent = this.take?.quiet ? "Hmm, quiet" : "Got it!";
    this.recordButton.textContent =
      this.state === "opening"
        ? "Opening the microphone…"
        : busy
        ? "Stop"
        : this.take
        ? "Record again"
        : "Record";
    this.recordButton.classList.toggle("recording", busy);
    this.recordButton.disabled = this.state === "opening";
    this.kept.hidden = !this.take || busy;
    this.wave.hidden = !this.take || busy;
    this.hear.textContent = this.stopPreview
      ? "Stop listening"
      : "Hear it with the band";
    setBlocked(
      this.addButton,
      !this.take ? "Record something first." : busy ? "Still recording." : ""
    );
  }
}
