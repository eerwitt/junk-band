import { z } from "zod";
import { audio } from "../audio/browser";
import { download } from "../audio/wav";
import {
  demoProject,
  performerSchema,
  starterProject,
} from "../domain/project";
import { loadBlob } from "../storage/database";
import { importBundle, exportBundle } from "../storage/bundle";
import { gateway } from "../services/gateway";
import { StudioStore } from "./store";
import { AddStudio } from "./add/add-studio";
import { button, drawer, element } from "./dom";
import type { JunkBridgeAPI, GodotLayout } from "./types";
import { setPart } from "../domain/arrangement";
import { loopBeats } from "../domain/timing";

const commandSchema = z
  .object({
    kind: z.enum([
      "toggle",
      "seek",
      "select",
      "audition",
      "settings",
      "update_performer",
      "clone",
      "add",
      "remove",
      "undo",
      "save",
      "open_project",
      "export",
      "source",
      "demo",
      "help",
      "impact",
      "move_preview",
      "focus_section",
      "set_part",
      "spotlight",
      "tap_note",
    ]),
    payload: z.record(z.string(), z.unknown()).default({}),
  })
  .strict();
const patchSchema = performerSchema
  .omit({ id: true, assetId: true })
  .partial()
  .strict();
const settingsSchema = z
  .object({
    title: z.string().trim().min(1).max(80).optional(),
    bpm: z.number().min(80).max(160).optional(),
    swing: z.number().min(0).max(0.6).optional(),
  })
  .strict();

export async function startRuntime(): Promise<JunkBridgeAPI> {
  const store = new StudioStore((id) => emit({ type: "arrival", id }));
  const media = new AddStudio(store);
  const callbacks = new Map<number, (message: string) => void>();
  const textures = new Map<string, string>(),
    pendingTextures = new Set<string>();
  // The project last sent to Godot. Edits always replace the object, so identity means unchanged.
  let sentProject: unknown;
  let nextId = 0,
    animationFrame = 0,
    transportBusy = false,
    exporting = false;
  const help = drawer("A sampler with a pulse.");
  help.content.append(
    element(
      "p",
      "",
      "Tap a character for its controls. Drag to pick it up. Clone adds a new rhythm. Scroll to zoom at the pointer; drag with the middle or right mouse button to pan. Home resets the camera. Drag the orbit to travel through the loop."
    ),
    element(
      "p",
      "",
      "Space: play / pause. Ctrl/⌘ Z: Undo. Delete: remove. R: export WAV. Escape: close character controls or a browser drawer."
    )
  );
  const serviceInfo = element("p", "fine");
  help.content.append(
    button("Check model catalogue", () => {
      void fetch(`${window.JUNK_CONFIG?.apiBase ?? "/api"}/models`, {
        credentials: "include",
      })
        .then((response) => {
          if (!response.ok) throw new Error("Catalogue unavailable");
          return response.json();
        })
        .then((data) => {
          serviceInfo.textContent = JSON.stringify(data);
        })
        .catch((error) => {
          serviceInfo.textContent = String(error);
        });
    }),
    serviceInfo
  );
  help.content.append(
    button("Remove server session media", () => {
      void fetch(`${window.JUNK_CONFIG?.apiBase ?? "/api"}/session`, {
        method: "DELETE",
        credentials: "include",
      })
        .then((response) => {
          if (!response.ok)
            throw new Error(
              "Server media could not be removed. Wait for running jobs."
            );
          store.notice(
            "Server session media removed. Accepted local samples remain playable."
          );
        })
        .catch((error) => store.notice(String(error)));
    })
  );
  const projectInput = element("input");
  projectInput.type = "file";
  projectInput.accept = ".json";
  projectInput.hidden = true;
  document.body.append(projectInput);
  help.content.append(
    button("Save project", () => {
      void exportBundle(store.state.project)
        .then((blob) =>
          download(blob, `${store.state.project.title}.junk.json`)
        )
        .catch((error) => store.notice(String(error)));
    }),
    button("Open project", () => projectInput.click()),
    button("New song", () => {
      store.replace(starterProject());
      store.notice("A fresh band. Undo brings your last song back.");
    })
  );
  projectInput.addEventListener("change", () => {
    const file = projectInput.files?.[0];
    if (file) {
      void importBundle(file)
        .then((project) => {
          audio.seek(0);
          store.set({ playing: false });
          store.replace(project);
        })
        .catch((error) => store.notice(String(error)));
    }
    projectInput.value = "";
  });

  const emit = (packet: unknown): void => {
    const message = JSON.stringify(packet);
    for (const callback of callbacks.values()) callback(message);
  };
  const texture = async (assetId: string, sprite: string): Promise<void> => {
    if (
      textures.has(assetId) ||
      pendingTextures.has(assetId) ||
      !(sprite.startsWith("blob:asset:") || sprite.startsWith("/band/"))
    )
      return;
    pendingTextures.add(assetId);
    const blob = sprite.startsWith("/band/")
      ? await fetch(sprite.slice(1)).then((reply) =>
          reply.ok ? reply.blob() : undefined
        )
      : await loadBlob(sprite.slice(11));
    if (!blob)
      throw new Error("An accepted cutout is missing from local storage.");
    const data = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1]);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
    textures.set(assetId, data);
    pendingTextures.delete(assetId);
    emit({ type: "texture", assetId, data });
  };
  const notify = (): void => {
    if (animationFrame) return;
    animationFrame = requestAnimationFrame(() => {
      animationFrame = 0;
      // Notices, saving and transport flips leave the stage as it is: no project to re-read.
      const { project, ...status } = store.state;
      emit(
        project === sentProject
          ? { type: "state", ...status }
          : { type: "state", ...status, project }
      );
      sentProject = project;
      for (const asset of store.state.project.assets) {
        void texture(asset.id, asset.sprite).catch((error) =>
          store.notice(String(error))
        );
        if (asset.rig)
          for (const ref of [
            asset.rig.body,
            ...asset.rig.parts.map((part) => part.sprite),
          ])
            void texture(ref, ref).catch((error) =>
              store.notice(String(error))
            );
      }
      document.querySelector<HTMLElement>("#accessible-status")!.textContent =
        store.state.notice;
      const debug = document.querySelector<HTMLElement>("#debug");
      if (debug)
        debug.textContent = `${store.state.mode} · ${store.state.project.performers.length} performers`;
    });
  };
  store.subscribe(notify);

  async function execute(message: string): Promise<void> {
    const { kind, payload } = commandSchema.parse(JSON.parse(message));
    switch (kind) {
      case "toggle":
        if (transportBusy) return;
        transportBusy = true;
        try {
          if (store.state.playing) {
            audio.pause();
            store.set({ playing: false });
          } else {
            await audio.play(store.state.project);
            store.set({
              playing: audio.playing,
              notice:
                "The stage is yours. Tap a character. Make a little trouble.",
            });
          }
        } finally {
          transportBusy = false;
        }
        break;
      case "seek":
        audio.seek(z.number().min(0).max(loopBeats).parse(payload.beat));
        store.set({ playing: false });
        break;
      case "select":
        store.select(z.string().parse(payload.id));
        break;
      case "audition": {
        const p = store.state.project.performers.find(
          (p) => p.id === payload.id
        );
        if (p)
          await audio.audition(
            store.state.project.assets.find((a) => a.id === p.assetId)!,
            p
          );
        break;
      }
      case "settings": {
        const patch = settingsSchema.parse(payload);
        store.edit((project) => Object.assign(project, patch));
        break;
      }
      case "update_performer":
        store.update(
          z.string().parse(payload.id),
          patchSchema.parse(payload.patch)
        );
        break;
      case "move_preview":
        audio.previewPosition(
          z.string().parse(payload.id),
          {
            x: z.number().parse(payload.x),
            y: z.number().parse(payload.y),
          },
          store.state.project
        );
        break;
      case "focus_section":
        audio.focusSection(
          payload.start === undefined
            ? null
            : {
                startBeat: z
                  .number()
                  .min(0)
                  .max(loopBeats)
                  .parse(payload.start),
                endBeat: z.number().min(0).max(loopBeats).parse(payload.end),
              }
        );
        break;
      case "spotlight":
        audio.setSpotlight(
          payload.id === undefined ? null : z.string().parse(payload.id)
        );
        break;
      case "tap_note": {
        const p = store.state.project.performers.find(
          (p) => p.id === payload.id
        );
        if (p) await audio.tapNote(p, store.state.project);
        break;
      }
      case "set_part":
        store.edit((project) =>
          setPart(
            project,
            z.string().parse(payload.sectionId),
            z.string().parse(payload.id),
            z.boolean().parse(payload.present)
          )
        );
        break;
      case "clone":
        store.clone();
        break;
      case "add": {
        const asset = store.state.project.assets.find(
          (a) => a.id === payload.assetId
        );
        if (asset) store.add(asset);
        break;
      }
      case "remove":
        store.remove();
        break;
      case "impact":
        await audio.impact(z.number().min(0.2).max(1).parse(payload.strength));
        break;
      case "undo":
        store.undo();
        break;
      case "save":
        download(
          await exportBundle(store.state.project),
          `${store.state.project.title}.junk.json`
        );
        break;
      case "open_project":
        projectInput.click();
        break;
      case "export":
        if (exporting) return;
        exporting = true;
        store.notice("Rendering one complete loop…");
        try {
          download(
            await audio.export(store.state.project),
            `${store.state.project.title}.wav`
          );
          store.notice("One complete sixteen-bar loop, bounced to stereo WAV.");
        } finally {
          exporting = false;
        }
        break;
      case "source":
        if (payload.demo === true) await media.demo();
        else media.show();
        break;
      case "demo":
        audio.seek(0);
        store.set({ playing: false });
        store.replace(demoProject(store.state.project.bpm !== 104));
        break;
      case "help":
        help.show();
        break;
    }
  }
  const api: JunkBridgeAPI = {
    version: 1,
    subscribe: (callback) => {
      if (typeof callback !== "function")
        throw new Error("Bridge subscription requires a callback.");
      const id = ++nextId;
      callbacks.set(id, callback);
      queueMicrotask(() => {
        if (!callbacks.has(id)) return;
        callback(JSON.stringify({ type: "state", ...store.state }));
        for (const [assetId, data] of textures)
          callback(JSON.stringify({ type: "texture", assetId, data }));
      });
      return id;
    },
    unsubscribe: (id) => {
      callbacks.delete(id);
    },
    command: (message) => {
      void execute(message).catch((error) =>
        store.notice(error instanceof Error ? error.message : String(error))
      );
    },
    beat: () => audio.beat(),
    frame: () => audio.visualFrame(),
    setCursor: (cursor) => {
      document.querySelector<HTMLCanvasElement>(
        "#canvas"
      )!.dataset.stageCursor = z
        .enum(["default", "grab", "grabbing"])
        .parse(cursor);
    },
    snapshot: () => structuredClone(store.state),
    publishLayout: (message) => {
      const parsed = JSON.parse(message) as GodotLayout;
      if (parsed.viewport && parsed.controls) api.layout = parsed;
    },
    metrics: () => ({
      beat: audio.beat(),
      voices: audio.activeVoices,
      hits: audio.scheduledHits,
      fps: api.layout?.fps ?? 0,
    }),
  };
  window.JUNK = api;
  document
    .querySelector<HTMLCanvasElement>("#canvas")!
    .addEventListener("contextmenu", (event) => event.preventDefault());
  document.addEventListener(
    "pointerdown",
    () => {
      void audio.unlock().catch((error) => store.notice(String(error)));
    },
    { once: true, capture: true }
  );
  document.addEventListener(
    "keydown",
    () => {
      void audio.unlock().catch((error) => store.notice(String(error)));
    },
    { once: true, capture: true }
  );
  document.addEventListener(
    "keydown",
    (event) => {
      if (event.code === "Space" && event.target instanceof HTMLCanvasElement)
        event.preventDefault();
    },
    { capture: true }
  );
  const accessible = document.querySelector<HTMLElement>(
    "#accessible-controls"
  )!;
  accessible.append(
    button("Play or pause", () =>
      api.command(JSON.stringify({ kind: "toggle" }))
    ),
    button("Import media", () =>
      api.command(JSON.stringify({ kind: "source" }))
    ),
    button("Duplicate performer", () =>
      api.command(JSON.stringify({ kind: "clone" }))
    ),
    button("Undo", () => api.command(JSON.stringify({ kind: "undo" }))),
    button("Export WAV", () => api.command(JSON.stringify({ kind: "export" })))
  );
  await store
    .hydrate()
    .catch((error) =>
      store.notice(`Local project could not be restored: ${String(error)}`)
    );
  store.set({ playing: true });
  void audio.play(store.state.project).catch((error) => {
    store.set({ playing: false });
    store.notice(String(error));
  });
  void gateway
    .health()
    .then((health) => store.set({ mode: health.mode }))
    .catch(() =>
      store.set({
        mode: "offline",
        notice:
          "Music is ready. Start the Python gateway to import and process media.",
      })
    );
  notify();
  return api;
}
