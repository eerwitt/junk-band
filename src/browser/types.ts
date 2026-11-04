import type { StudioState } from "./store";

export interface GodotLayout {
  inspector: boolean;
  viewport: { x: number; y: number };
  controls: Record<
    string,
    { x: number; y: number; w: number; h: number; visible: boolean }
  >;
  fps: number;
  stage: {
    x: number;
    y: number;
    w: number;
    h: number;
    zoom: number;
    originX: number;
    originY: number;
    cameraZoom: number;
  };
}
export interface JunkBridgeAPI {
  readonly version: 1;
  subscribe: (callback: (message: string) => void) => number;
  unsubscribe: (id: number) => void;
  command: (message: string) => void;
  beat: () => number;
  frame: () => string;
  setCursor: (cursor: "default" | "grab" | "grabbing") => void;
  snapshot: () => StudioState;
  publishLayout: (message: string) => void;
  layout?: GodotLayout;
  metrics: () => { beat: number; voices: number; hits: number; fps: number };
}
declare global {
  interface Window {
    JUNK_CONFIG?: { apiBase?: string };
    JUNK: JunkBridgeAPI;
    Engine: new (config: Record<string, unknown>) => {
      startGame: (options: Record<string, unknown>) => Promise<void>;
    };
  }
}
