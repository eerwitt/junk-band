# JUNK — The Living Sampler

A paper-puppet instrument for the browser. Find a sound in a video, cut out the object that made it, and drop it onto a circular stage where it plays in the band.

- **Godot 4.6.3 / GDScript** (Compatibility renderer, single-threaded web export) draws the stage, characters, controls and animation.
- **TypeScript** in `src/` owns Web Audio, media import, IndexedDB and gateway calls, talking to Godot through `JavaScriptBridge`. Its only runtime dependency is Zod; TypeScript and Prettier are the dev tools. All three are vendored in `vendor/` and install offline.
- **Python FastAPI gateway** in `services/gateway` handles uploads, FFmpeg and model requests (Meta SAM 3.1, Muse Image, Muse Spark). **SAM Audio** runs on a Modal GPU worker in `services/gpu`.

Without credentials the gateway runs in demo mode: music, editing, persistence and export all work, while cutouts and separation are clearly labelled stand-ins (a rectangular crop and a raw audio copy). Configured providers never fall back to mock output after an error.

## Run it

Needs Node 22+, Python 3.11+ with `uv`, FFmpeg/FFprobe, and Godot 4.6.3 with matching web export templates (`--godot` selects another executable).

```bash
npm ci --offline --cache .npm-cache --ignore-scripts --no-audit --no-fund
```

```bash
uv sync --extra dev
```

```bash
uv run python scripts/build_web.py
```

```bash
uv run python scripts/dev.py
```

Open http://127.0.0.1:5173 (API docs at `/docs`). On Windows, `./scripts/setup.ps1 -Check -Start` does all of the above plus the checks. Build output goes to `dist/`; the build uses an isolated Godot profile under `.build/`.

To use real models, copy `.env.example` to `.env`, set `MODEL_API_KEY` and/or Modal credentials, keep `JUNK_MODE=auto` and restart the gateway. Shell variables override `.env`. `uv run python scripts/preflight.py --offline` reports what is configured without calling any model. See [deployment](docs/deployment.md) for Modal, secrets and hosting.

## Playing

- New sessions start with the base band: eleven painted characters with CC0 sounds (see `public/sounds/CREDITS.md`). Playback starts automatically, or on the first click if the browser blocks autoplay.
- **The ring is the song**: sixteen bars in eight sections. Drag along it to scrub; click a section to loop it, click the outer strip (or Escape) to return to the whole song. Drag a character off the stage to sit it out of a section.
- **Tap a character** for its radial controls: volume, pitch/speed, pan, playback mode, rhythm card, duplicate, pencil (draw a motion path), eraser and skull (remove). Click empty stage or press Escape to close.
- **Height sets the note** for tuned characters, snapped to one scale.
- **Tempo** is the cardboard metronome: drag, scroll, arrow keys, or tap it in time.
- **Add** takes a clip (up to 1 min and 200 MB) in three steps: trim the 2–8 s you want to hear, paint over the object on a frame and say what you want to hear, then **Make it**. The sound, the cutout and its painting all start at once; compare Cutout | Painted and Separated | Original clip, then **Add to band**. The permission checkbox is asked once per browser.
- **Save** exports a sixteen-bar stereo WAV. The help drawer saves and opens portable `.junk.json` projects, including accepted media.

Keys: Space play/pause · Ctrl/⌘ Z undo · Delete remove · R export WAV · Home reset camera · Escape close. Scroll zooms at the cursor; middle/right drag pans.

## Checks

```bash
npm run check
```

```bash
uv run ruff check services scripts && uv run ruff format --check services scripts && uv run mypy && uv run pytest
```

```bash
uv run python scripts/check_godot_browser.py --start-server
```

To look at motion and effects without a browser, `uv run python scripts/preview_vfx.py --scenario dance --start 24` renders the base band against a simulated audio clock to PNG frames in `artifacts/vfx-preview/` (scenarios: dance, pause, remove, arrive, clone, menu, card, path, wrap, walk; `--metrics` prints each character's motion range). It needs a display, and uses `xvfb-run` when one is installed.

`npm run check` type-checks, runs the Node core tests in `tests/` and checks formatting. `build_web.py` also runs the headless Godot regressions in `godot/tests/` before exporting. The browser check drives the real web export in Chromium and writes screenshots and a mix WAV to `artifacts/godot-browser/`. Focused browser checks: `check_add_studio.py` (Add flow, runs against the demo gateway with or without the Godot build), `check_audio_response.py` (live edits) and `check_audio_browser.py` (isolated audio engine, after `node scripts/build_audio_check.cjs`).

## More

- [System and bridge contract](docs/system.md)
- [Deployment](docs/deployment.md)
- [Asset provenance](docs/assets.md)
- [Visual design](DESIGN.md) and [product brief](PRODUCT.md)
