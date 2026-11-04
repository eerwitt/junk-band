import { startRuntime } from "./runtime";

async function boot(): Promise<void> {
  const status = document.querySelector<HTMLElement>("#loading-status")!;
  await startRuntime();
  const configResponse = await fetch("/engine/config.json");
  if (!configResponse.ok)
    throw new Error(
      "Godot web export is missing. Run the web build script first."
    );
  const config = (await configResponse.json()) as Record<string, unknown>;
  await new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/engine/junk.js";
    script.onload = () => resolve();
    script.onerror = () =>
      reject(new Error("Could not load the Godot web engine."));
    document.head.append(script);
  });
  const engine = new window.Engine({
    ...config,
    executable: "engine/junk",
    mainPack: "engine/junk.pck",
    canvasResizePolicy: 2,
    focusCanvas: false,
  });
  await engine.startGame({
    canvas: document.querySelector("#canvas"),
    onProgress: (current: number, total: number) => {
      status.textContent = total
        ? `Opening your little world… ${Math.round((current / total) * 100)}%`
        : "Opening your little world…";
    },
    onPrintError: (...args: unknown[]) => console.error(...args),
  });
  document.querySelector<HTMLElement>("#loading")!.hidden = true;
  document.querySelector<HTMLCanvasElement>("#canvas")!.focus();
}
void boot().catch((error) => {
  const status = document.querySelector<HTMLElement>("#loading-status")!;
  status.textContent = String(error);
  document.querySelector<HTMLElement>("#loading")!.classList.add("failed");
  console.error(error);
});
