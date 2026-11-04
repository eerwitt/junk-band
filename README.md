# JUNK — The Living Sampler

A Godot paper-puppet instrument with a native browser audio engine. Find a sound, give it a body, drop it into the circle and make a beat.

Godot owns the stage, controls, animation and pointer interaction. A small TypeScript service layer owns Web Audio, uploads, video, IndexedDB, model requests and downloads through `JavaScriptBridge`. **No React, PixiJS, Tone, Zustand or Vite.** There is one runtime JavaScript dependency: Zod for validation. The two development packages are TypeScript and Prettier. All three are pinned, vendored with their upstream licenses, and install offline.

The gateway selects providers from server configuration. With no credentials, the starter band and local music tools work, while demo segmentation/separation are explicitly labelled as a rectangular crop and raw audio copy. Set `MODEL_API_KEY` for Meta SAM, Muse Image and descriptions, and Modal credentials for the deployed SAM Audio worker. Configured providers never silently substitute mock results after an error. Music, sample editing, uploaded-byte processing, mixing, animation, persistence and export are real in either mode.

## Open the studio

Requires Node 22+, Python 3.11+, FFmpeg / FFprobe, and Godot 4.6.3 with matching web export templates. The project uses GDScript and the Compatibility renderer. Godot's installed CLI is supported; `--godot` can select another executable with matching templates.

```powershell
npm ci --offline --cache .npm-cache --ignore-scripts --no-audit --no-fund
uv sync --extra dev
uv run python scripts/build_web.py
uv run python scripts/dev.py
```

Copy `.env.example` to `.env`, fill in the server keys you need, and restart the gateway. Keep `JUNK_MODE=auto`. Shell variables override `.env`; only the public `JUNK_API_BASE` is written into the browser build. A local session secret is generated automatically; hosted live mode needs an explicit `JUNK_API_SESSION_SECRET`.

`uv run python scripts/preflight.py --offline` reports configured providers and missing server packages without contacting any model. `uv run python scripts/preflight.py --meta-only` checks actual Meta model access without generating an image. See [deployment setup](docs/deployment.md) for Modal app, volume, checkpoint and credential details. The current installed Python 3.12 environment can run the gateway tests; live cutout support also requires the `meta-sam-parser` project dependency.

Open **http://127.0.0.1:5173**. The studio and mock gateway use the same origin; API documentation is at **http://127.0.0.1:5173/docs**. On Windows, `./scripts/setup.ps1 -Check -Start` installs, builds, checks and starts the studio. Python dependencies need registry access on first installation. Godot export and JavaScript installation do not require network when the templates are installed.

You can also open [godot/project.godot](godot/project.godot) in the editor. Native editor playback previews the stage; browser media and audio require the web export. Generated output is in `dist/`. The build uses an isolated local Godot profile under `.build/` so it does not modify editor preferences elsewhere on the machine.

## Cardboard characters

New browser projects start with a small randomized band of three or four synthesized demo instruments. The low rhythm stays anchored while the other members, tempo, swing, pitch and stereo placement vary within musical bounds. A saved project always restores unchanged.

Every character uses a warm paper rim, fine material grain and a corrugated cut edge. The edge is silhouette geometry projected with the face shader, so a half-turn retains thickness even when the printed face is edge-on. Path direction drives smooth turns; `JunkPuppet.set_facing(-1)` and `set_facing(1)` also control direction. Both sides carry the print by default. Set the face material's `back_print` uniform to `0.0` for a plain kraft reverse, and adjust `grain_strength` for cleaner or rougher stock.

`cardboard_cutout.gd` preserves the print at source resolution up to 2048 pixels on its longest side. A separate mask of at most 512 pixels prepares the paper rim and edge mesh; it does not downsample the print. The backing is composited under the original opaque pixels, with paper-colored transparent texels and bounded edge antialiasing to avoid dark, fuzzy fringes. Mipmaps keep distant artwork stable; the edge shader filters unresolved corrugation along the contour while retaining distinct liners through the thickness. A bounded cache shares these resources between clones. Performer IDs seed stable grain and thickness differences. Each character adds one edge draw; the face takes one texture sample, the edge uses procedural corrugation, and the shadow follows the turn. There are no screen reads, ray marching or per-frame image/mesh generation in these materials. Pickup freezes yaw and preserves the material under the grip. Reduced motion changes facing immediately.

Characters are up to 150 world units tall, with a thicker corrugated core and a slight resting turn that exposes the side. The camera supports cursor-centered wheel zoom from 0.5× to 4×, middle- or right-button drag to pan, trackpad magnify/pan gestures where supported, and Home to reset. Transport and buttons stay fixed to the viewport. This is a 2D orthographic material system for Godot's Compatibility renderer; arbitrary 3D camera movement would need an extruded 3D mesh. Transparent source art is required to follow an object's silhouette; opaque images receive a rectangular backing.

Inspect front, side and reverse views with `godot --path godot --script res://tests/cardboard_preview.gd`. The contact sheet is saved to `artifacts/cardboard-material.png`. Optionally append `-- --reference=C:/path/to/cutout.png`. The web build runs the cardboard and pickup regressions before exporting.

For imported video, cut out the object first, then choose **Make cardboard character** when the image service is available. Meta Muse Image receives that cutout and the character direction as references, preserves the object's identity, and is prompted to add short paper boots and hinged arms in the board's visual style. Muse Image returns opaque artwork, so SAM makes a new alpha mask around the complete character, including the added limbs. The source mask is never reused as a substitute. See [Meta's documented image editing interface](https://dev.meta.ai/docs/image-generation).

Compare **Original cutout** and **Cardboard character**, select a look, audition the sound, then accept. Visual and audio provenance are separate. After painting and cutting, four real SAM limb masks produce body/arm/leg layers with normalized pivots and bounded joint angles. Acceptance preserves the original cutout, complete styled image, five rig layers and audio in IndexedDB and portable project bundles. Rigged characters respond to notes, auditions, floor travel and landing; their joints freeze during pickup to keep the grip solid. Reduced motion returns joints to rest. Existing unrigged projects keep their complete cutout. Failed masks retry from cached artwork and successful limb masks without another image-generation request. Jobs are session-isolated and report painting/cutting/rigging progress. Browser and native fixtures verify the mechanics; real generated limb quality remains unverified without live provider access.

New additions and clones arrive with a short rigid fall onto their actual floor shadow, then one compression/rebound and landing effect. Imported characters wait for their real artwork (and complete rig, when present); they never briefly impersonate a starter sprite. Pickup can interrupt the entrance. Reduced motion retains the floor acknowledgement without a fall. Loading saved projects stays quiet and does not replay entrances.

Add reflects which image and sound tools the server has configured. Unavailable model actions stay disabled, with raw trimming available when the source is usable. Changing the description clears candidates made for the previous prompt; delayed replies cannot restore them. Polling failures leave a retry path. If the browser cannot decode a video's preview, the server supplies an actual PNG frame from the recording. Frame changes clear the previous box and selection waits for the new frame to load.

## Make a little trouble

1. The studio starts playing automatically. If the browser restricts autoplay, your first click, tap or key press unlocks sound. Only play/pause and BPM sit below the circle, as individually shadowed cardboard controls. Characters bounce subtly when their own scheduled notes sound; the orbit and world buttons pulse on the main beat. Tap a performer for its controls. Pickup separates the spring-driven floor position from a thirty-world-unit lift height. A short loaded dip and small rigid compression precede the rise. Carry retains a little weighted swing and at most 1.8% stretch. The shadow stays on the floor and follows the character’s ground movement, including spring lag. Actual lift height controls its fixed light-direction offset, softening, progressive mask gathering and late circle merge. The ellipse broadens from 24 to 34 world units in radius and lightens as the character rises. Both shadow layers remain behind all characters and aligned after zoom and pan. Release falls under gravity; landing feedback occurs at floor contact rather than on a timer. Dropping gives a quick compression/rebound, stronger ripple, warm dust, six flecks and a clearly readable hand-lettered impact word. Reduced motion retains the landing acknowledgment without spatial effects.
2. **Duplicate**, the two-cards icon in a character's circle of controls, adds a performer sharing its sample, with a different quantized rhythm, bounded speed and lower gain. The loop is **16 bars / 64 beats**, four times longer than the original. Old four-bar projects upgrade by repeating their groove and preserving accepted media. Scrub the counterclockwise orbit; hover reveals its depth and a grab cursor. Arrow keys move a quarter beat and End seeks the last quarter beat. The bottom numbered step editor and bar pager have been removed.
3. The radial controls adjust volume, pan, sample speed/pitch, repeat spacing, one-shot/continuous playback and offstage behavior. A soft circular blur separates them from the background while the performer stays sharp. The skull removes the performer. Click empty stage, drag the character or press Escape to dismiss. There is no right sidebar, duplicate portrait, audition, mute/solo, motion-preset or duplicate control in this menu.

   The **pencil** arms freehand motion drawing. Press and draw across the stage; the stroke keeps a consistent travel speed, becomes a smooth curve and reserves the last two bars to return to its starting spot without a jump at the loop seam. The **eraser** clears the path. The same curve drives visual motion and offstage audio gating.

   **The ring is the song.** It holds eight sections. Hover over it and a shaded area opens out with that section's name; drag along it to scrub. Click to zoom in a little and loop that section: the band walks to their spots or along their paths, and anyone sitting it out heads off to their own spot beyond the ring, by bounding, waddling or a teetering run. Dragging a character off the stage in a section sits them out of it, and dragging them back brings them in. Move someone around while they wait outside and that becomes their spot. The strip around the outside carries the section's name; click it, or press Escape, to zoom back out and play on through the whole song, where the band keeps coming and going between sections. Enter does the same from the keyboard.

   **The base band** is on stage in every new session: drums, a bass that walks a little line, keys, marimba, glockenspiel and three arcade sound effects, all CC0 (see `public/sounds/CREDITS.md`). Remove any of them with the skull; Undo brings them back.

   **Notes.** A tuned character's height on the stage sets its note, always within one scale, so nothing sounds wrong. Drag it up to play higher and you hear each new note on the way; faint lines show the notes while you carry it. Drawing it a motion path makes it play a line as it walks. Any character can use this with **Height sets its note** in its controls.

   **Rhythm.** The card icon in a character's controls opens a strip of 16 holes for one repeating bar. Pick a ready-made card, tap holes to change them, roll a surprise, or tap along in time to teach it a rhythm.

   **Tempo** is a cardboard metronome whose arm swings on the beat. Drag it sideways, scroll on it, use the arrow keys, or tap it three or more times in time. Changes land on the next beat.

4. Drop a clip of 2 seconds to 1 minute and up to 200 MB, MP4/WebM or recording onto the page, or use **Add**, confirm your media rights and open it. Scrub a frame, draw a box, choose **Cut out object**, select a 2–8 second audio window and **Take its sound**.
5. Audition **Original**, **Target** and **Residual** before **Accept sample**. Raw trimmed audio is a separate fallback. Accepted cutouts and samples persist locally and remain playable independently of the gateway.
6. The **save icon** renders one sixteen-bar stereo PCM16 WAV loop—about 34.29 seconds at 112 BPM. In **Keys**, **Save project** downloads a portable `.junk.json` bundle containing accepted audio and cutouts; **Open project** restores it, including in a fresh browser profile. Twist and Band direction have been removed, along with the collection sidebar, project header and bottom status strip.

Scroll: zoom at cursor. Middle/right drag: pan. Home: reset camera. Space: play/pause. Ctrl/⌘ Z: Undo. Delete: remove. R: export WAV. Escape: cancel path drawing or close a browser drawer. Browser-native accessible transport controls appear when keyboard focused.

## Verify

```powershell
npm run check
uv run ruff check services scripts
uv run ruff format --check services scripts
uv run mypy
uv run pytest
uv run playwright install chromium
# With the studio already running:
uv run python scripts/check_godot_browser.py
# Or let the check own its server on a free port:
uv run python scripts/check_godot_browser.py --start-server --url http://127.0.0.1:5181
```

`npm run check` runs strict TypeScript checking, sixteen Node core tests and formatting. `build_web.py` checks and emits browser modules, imports and tests Godot headlessly, then exports a single-threaded web build. Browser checks exercise native controls, elastic drop/landing, note pulses, all sixteen bars, pencil/eraser, orbit seeking, song sections, bridges/solos, media processing, persistence, model flows and portable bundles. Desktop/mobile screenshots and an actual mix WAV are written to `artifacts/godot-browser/`. A focused `--elastic-only` check records visible elastic motion. The local static server sends `Cache-Control: no-store` so refreshes load current browser and Godot assets.

The focused audio harness remains available via `node scripts/build_audio_check.cjs` and `uv run python scripts/check_audio_browser.py`. Objective duration, RMS and peak checks establish signal properties. Musical taste still needs human listening.

## Architecture and deployment

See [system and bridge contract](docs/system.md), [verified progress](docs/progress.md), [acceptance audit](docs/acceptance.md), [secure-shell deployment](docs/deployment.md) and [asset provenance](docs/assets.md).

For a deployed gateway, set the public `JUNK_API_BASE` before building, or edit `dist/config.js` with its `/api` URL. Keep all model credentials in Modal Secrets. The current backend supports still-frame SAM 3.1 segmentation and text-prompted SAM Audio; visual conditioning, video tracking, arbitrary anatomy, pitch-preserving stretching and video export are outside this first version. Live model inference and deployment remain deliberately unverified until your secure-shell smoke test.
