import {
  starterProject,
  withBaseBand,
  makePerformer,
  projectSchema,
  type Asset,
  type Performer,
  type Project,
} from "../domain/project";
import { clonePerformer } from "../domain/music";
import { saveProject, loadProject } from "../storage/database";
import { audio } from "../audio/browser";

export interface StudioState {
  project: Project;
  selected: string;
  playing: boolean;
  saved: boolean;
  reducedMotion: boolean;
  mode: string;
  notice: string;
}
export class StudioStore {
  constructor(private readonly onJoin: (id: string) => void = () => {}) {}
  state: StudioState = {
    project: starterProject(),
    selected: "p-0",
    playing: false,
    saved: false,
    reducedMotion: false,
    mode: "connecting",
    notice: "A little band. A lot of possibilities.",
  };
  private history: Project[] = [];
  private listeners = new Set<() => void>();
  private saveTimer?: number;
  private revision = 0;

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
  private notify(): void {
    for (const listener of this.listeners) listener();
  }
  async hydrate(): Promise<void> {
    const saved = await loadProject();
    if (saved) {
      const project = withBaseBand(saved);
      if (project !== saved) await saveProject(project);
      this.state.project = project;
      this.state.selected = project.performers[0]?.id ?? "";
    }
    this.state.saved = true;
    this.notify();
  }
  notice(message: string): void {
    this.state.notice = message;
    this.notify();
  }
  set(patch: Partial<Omit<StudioState, "project">>): void {
    Object.assign(this.state, patch);
    this.notify();
  }
  edit(change: (project: Project) => void): void {
    const previous = this.state.project,
      next = structuredClone(previous);
    change(next);
    projectSchema.parse(next);
    if (JSON.stringify(previous) === JSON.stringify(next)) return;
    this.history = [...this.history.slice(-29), previous];
    this.state.project = next;
    this.changed();
  }
  private changed(): void {
    const revision = ++this.revision;
    if (
      !this.state.project.performers.some((p) => p.id === this.state.selected)
    )
      this.state.selected = this.state.project.performers[0]?.id ?? "";
    this.state.saved = false;
    window.clearTimeout(this.saveTimer);
    this.saveTimer = window.setTimeout(() => {
      void saveProject(this.state.project)
        .then(() => {
          if (this.revision === revision) {
            this.state.saved = true;
            this.notify();
          }
        })
        .catch((e) => this.notice(String(e)));
    }, 400);
    void audio.update(this.state.project).catch((e) => this.notice(String(e)));
    this.notify();
  }
  selected(): Performer | undefined {
    return this.state.project.performers.find(
      (p) => p.id === this.state.selected
    );
  }
  select(id: string): void {
    if (this.state.project.performers.some((p) => p.id === id)) {
      this.state.selected = id;
      this.notify();
    }
  }
  update(id: string, patch: Partial<Performer>): void {
    this.edit((project) => {
      const performer = project.performers.find((p) => p.id === id);
      if (performer) Object.assign(performer, patch);
    });
  }
  replace(project: Project): void {
    const parsed = projectSchema.parse(project);
    this.history = [...this.history.slice(-29), this.state.project];
    this.state.project = parsed;
    this.changed();
  }
  undo(): void {
    const project = this.history.pop();
    if (project) {
      this.state.project = project;
      this.state.notice = "Back one move.";
      this.changed();
    }
  }
  clone(): void {
    const p = this.selected();
    if (!p || this.state.project.performers.length >= 24) {
      this.notice("The circle holds 24 performers. Remove one to make room.");
      return;
    }
    const clone = clonePerformer(
      p,
      this.state.project.performers.filter((x) => x.assetId === p.assetId)
        .length
    );
    this.state.selected = clone.id;
    this.edit((project) => {
      project.performers.push(clone);
      for (const section of project.sections)
        if (section.kind === "solo") section.mutedIds.push(clone.id);
    });
    this.notice("A new friend. A different rhythm.");
    this.onJoin(clone.id);
  }
  add(asset: Asset): void {
    if (this.state.project.performers.length >= 24) {
      this.notice("The stage is full.");
      return;
    }
    const performer = makePerformer(
      asset,
      this.state.project.performers.length,
      this.state.project.performers
    );
    this.state.selected = performer.id;
    this.edit((project) => {
      if (!project.assets.some((a) => a.id === asset.id))
        project.assets.push(asset);
      project.performers.push(performer);
      for (const section of project.sections)
        if (section.kind === "solo") section.mutedIds.push(performer.id);
    });
    this.notice(`${asset.label} joined the band.`);
    this.onJoin(performer.id);
  }
  remove(): void {
    const id = this.state.selected;
    this.edit((project) => {
      project.performers = project.performers.filter((p) => p.id !== id);
      for (const section of project.sections) {
        section.mutedIds = section.mutedIds.filter((value) => value !== id);
        if (section.leadId === id) {
          section.leadId = null;
          section.kind = "groove";
          section.label = "Groove";
          section.mutedIds = [];
        }
      }
    });
  }
}
