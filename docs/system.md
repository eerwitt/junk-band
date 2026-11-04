# Godot and browser service boundary

Godot 4.6.3 / GDScript owns the interface, 2D stage, puppet scene nodes, shadows, selection, dragging, path drawing, inspector, mixer controls and compact timeline. It exports with the Compatibility renderer and no threads. The browser owns native media and audio; the Python gateway owns source preparation and model requests.

`JunkPerformerMenu` owns the radial inspector independently of the studio shell. Stage clicks open it, the drag threshold closes it, and typed signals carry edits and skull deletion. `JunkCardboardStyle` draws irregular ink-edged paper controls and layered ground shadows. The focus effect copies only the local region via `BackBufferCopy` and evaluates a continuous 5×5 Gaussian with nine bilinear texture reads, avoiding full-screen mipmap generation. The inspected puppet draws above the blur and below the menu cards. Only play/pause and BPM remain in the world transport.

## JavaScriptBridge protocol

`window.JUNK.version` is `1`. Godot obtains the object with `JavaScriptBridge.get_interface("JUNK")`, retains a callback created with `JavaScriptBridge.create_callback()`, and subscribes once. It unsubscribes on exit. Callback arguments are handled as the required single Godot Array.

- `subscribe(callback)` returns a numeric subscription ID and sends an initial `state` packet. Later state edits are coalesced to one notification per browser animation frame.
- `command(json)` accepts a schema-validated allowlisted command: transport, selection, audition, settings, bounded performer patch, clone/add/remove/Undo, save/open/export, source/director/help or starter scene selection. Unknown kinds and invalid values are rejected. No model-generated code is executed.
- `frame()` returns one small JSON packet per frame: authoritative Web Audio beat, playback state, master pulse and per-performer note envelopes. Envelopes use actual scheduled voice onset timestamps, including swing and bar-committed edits. The bridge caches the packet before other Godot nodes run. `beat()` remains available for transport clients. Audio scheduling is independent of rendering.
- `state` packets carry small project metadata, selection, playing/saved status, service mode and notices. They do not contain media bytes.
- `texture` packets transfer an accepted PNG as base64 once per asset/subscription. Godot decodes it into a cached `ImageTexture`. Clones share that texture. No video frames or project JSON are streamed every render frame.
- `publishLayout(json)` exposes control rectangles and FPS for browser integration checks. Tests map these rectangles to canvas pixels and click actual Godot controls. `metrics()` exposes scheduled-hit and voice counters without driving the scheduler.

## Audio

`AudioEngine` receives a context factory and sample loader. The production adapter uses a native `AudioContext` and IndexedDB. Project changes compile one 256-step event table for sixteen bars, then commit on a bar boundary. A 25 ms lookahead task schedules source nodes against the audio clock 120 ms ahead. Seeking invalidates the transport epoch and fades active voices; continuous samples resume at their proper offset. Tempo segments prevent visual cursor jumps when a future bar has already been scheduled.

Buffers are cached by immutable audio ID. Each voice has gain attack/release, independent rate and pan, plus path-dependent stage gating, before a master compressor. Demo sounds are original deterministic synthesis. WAV export uses the same event compiler and mix parameters in `OfflineAudioContext`, then encodes stereo PCM16. Sample speed changes pitch; no time stretch is claimed.

Godot never schedules musical notes from `_process()` or a Timer. Note-on envelopes drive subtle character bounce; the main beat gently expands the orbit and moves the world controls. A frame-rate-independent critically damped spring controls weighted pickup and settling, retaining the dropped destination until scene data acknowledges it. A single landing creates a short-lived ripple, dirt flecks, authored stroke lettering and a quiet browser-synthesized plop. Reduced motion suppresses spatial beat animation and particles.

`src/domain/timing.ts` defines 16 bars, 64 beats and 256 steps; the build generates matching `JunkLoopTiming` constants for Godot. Schema v2 upgrades old four-bar scenes by repeating notes and scaling path times while retaining media. Pencil drawing records distance-timed points. Cubic Hermite interpolation closes the route at home, reserving two bars for return and zero seam velocity. The matching browser evaluator drives offstage audio gating.

`SongDrawer` is a browser-native, opt-in bottom sheet. Validated contiguous sections cover all sixteen bars. `arrangement.ts` controls boundaries, splitting/joining, local part participation, bridge density and solo/backing gain. The original note patterns remain intact. The same event compiler and section gain are used in live playback and offline export, including sustained voices across section boundaries. Mix changes and who sits out apply at once, tempo and swing on the next beat, and reshaping a section on the next bar.

Weighted carry uses an analytic underdamped spring for visible recoil, with movement-dependent stretch and shear. Path handoffs retain critical damping. Reduced motion uses the gentler critically damped follow and no deformation. A dropped object retains its committed destination until acknowledged, independently of the spring’s settling time.

## Media, persistence and models

Browser drawers use native file inputs, drag/drop, video, audio, microphone recording and downloads, with the same warm paper visual system as the Godot controls. Source seconds and composition beats remain distinct. Native IndexedDB stores source and accepted blobs and autosaves validated project metadata. Portable bundles include accepted assets; a fresh browser can restore and play them without server-side media. Undo retains at most 30 metadata snapshots.

FastAPI accepts bounded local uploads, uses FFprobe / FFmpeg to inspect media and extract aligned windows, isolates files under opaque IDs and HMAC-signed HTTP-only sessions, and expires retrieval after 24 hours. Mock image output is a rectangle, target audio is a raw copy and residual is silence. Mock director/transcription results are labeled explicitly. Failure leaves raw audio and local music available.

Live adapters use Meta's official SDK and SAM parser. Wonder first inspects performers through a tool, then proposes bounded preview actions. Server validation and browser schedule dry run precede explicit user Apply. Python serves SAM 3.1, Spark interpretation, Wonder and Voice; independently hosted SAM Audio runs on Modal. Sleeve/image generation was removed.

Modal has separate CPU/GPU images, persistent media and weight volumes, a capped scale-to-zero L40S worker, and timing/VRAM output. Gateway dependencies are imported only in the CPU function so the GPU image does not require the UI gateway stack. The worker loads authorized weights remotely and writes target/residual WAVs. The worker has run real separations on an L40S; output quality still needs listening on each recording.

The gateway uses in-process async supervision and persisted completed jobs, capped to one CPU container. Restarts fail unfinished jobs explicitly and allow retry. This is a single-gateway demonstration deployment, not a distributed queue or a public billing boundary.
