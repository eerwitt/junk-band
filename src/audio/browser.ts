import { AudioEngine } from "./engine";
import { loadBlob } from "../storage/database";

let context: AudioContext | undefined;
export const audio = new AudioEngine(
  async () => {
    context ??= new AudioContext({ latencyHint: "interactive" });
    return context;
  },
  async (id) => {
    if (!id.startsWith("band-")) return loadBlob(id);
    const response = await fetch(`sounds/${id.slice(5)}.wav`);
    return response.ok ? response.blob() : undefined;
  }
);
