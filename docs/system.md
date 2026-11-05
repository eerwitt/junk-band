# System and bridge contract

Godot (`godot/`) owns the stage, puppets, shadows, pickup, path drawing, the radial performer menu, the ring and the world controls. It exports with the Compatibility renderer and no threads. The browser layer (`src/`) owns audio, media, storage and gateway calls. The Python gateway (`services/gateway`) owns source preparation and model requests; SAM Audio runs on Modal (`services/gpu`).

## Layout

| Path                      | Role                                                                                                                                                                                                     |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/domain/`             | Pure project schema, timing, music compilation, motion, pitch and song arrangement. Shared by live playback, export and tests.                                                                           |
| `src/audio/`              | `AudioEngine` scheduler, browser adapter, base-band loading, demo synthesis and WAV encoding.                                                                                                            |
| `src/browser/`            | Runtime, store and Undo, the `JUNK` bridge object, drawers and the Add studio (`add/`).                                                                                                                  |
| `src/storage/`            | IndexedDB persistence and portable `.junk.json` bundles.                                                                                                                                                 |
| `src/services/gateway.ts` | Typed gateway client.                                                                                                                                                                                    |
| `godot/scripts/`          | `studio.gd` (shell), `stage.gd`, `puppet.gd`, `cardboard_*.gd` (material and rig), `performer_menu.gd`, `orbit_scrubber.gd`, `tempo_dial.gd`, `punch_card.gd`, `landing_effect.gd`, `browser_bridge.gd`. |

`src/domain/timing.ts` defines 32 bars, 128 beats and 512 steps, and the rhythm card lengths (1, 2, 4, 8 bars or the whole song); the build generates the matching `JunkLoopTiming` constants for Godot.

## JavaScriptBridge protocol

`window.JUNK.version` is `1`. Godot gets the object with `JavaScriptBridge.get_interface("JUNK")`, keeps a callback from `JavaScriptBridge.create_callback()`, subscribes once and unsubscribes on exit.

- `subscribe(callback)` returns a subscription ID and sends an initial `state` packet. Later edits are coalesced to one notification per animation frame.
- `command(json)` accepts schema-validated, allowlisted commands (transport, selection, performer patches, clone/add/remove/Undo, save/open/export, drawers). Unknown kinds and invalid values are rejected.
- `frame()` returns one small JSON packet per frame: the beat, playback state, master pulse, per-performer note envelopes from actual scheduled onsets, and `onsets` (the age in seconds and velocity of each performer's newest sounded hit, so overlapping fast hits are still seen one by one). It is timed to what is leaving the speakers (`getOutputTimestamp()` carried forward on the frame clock), not `currentTime`, which steps once per audio callback and runs ahead by the output latency. The bridge caches it before other nodes run.
- `state` packets carry project metadata, selection, playing/saved status, service mode and notices, never media bytes. `project` is left out when it has not changed since the last packet, and Godot only rebuilds the stage when it or the selection did.
- `arrival` packets name a performer that just joined, with `kind` `new` (made in Add) or `clone` (with its `source`); `departure` packets name one being removed, sent before the state that drops it, so the stage can tell removal from unloading.
- `texture` packets send an accepted PNG as base64 once per asset per subscription; clones share the decoded `ImageTexture`.
- `publishLayout(json)` exposes control rectangles and FPS so browser checks can click real Godot controls. `metrics()` exposes scheduled-hit and voice counters.

## Audio

Project changes compile one 512-step event table, committed on a bar boundary (mix changes and sit-outs apply at once, tempo and swing on the next beat). A 25 ms lookahead task schedules source nodes 120 ms ahead on the audio clock. Seeking invalidates the transport epoch and fades active voices; continuous samples and phrases resume at their proper offset. Events from phrases and from imported sounds carry a `hold`, the steps until they are cut off (the next hit, or the card's end), so a long sound never stacks on itself, live or in export.

Buffers are cached by immutable audio ID. Each voice has attack/release, rate, pan and section gain before a master compressor. Sample speed changes pitch; there is no time stretch. WAV export runs the same compiler and mix in an `OfflineAudioContext` and encodes stereo PCM16.

Godot never schedules notes from `_process()` or a Timer; note envelopes and onsets from `frame()` drive each note's pop and marks, and the beat drives the groove. Drawn paths use cubic Hermite interpolation closed at home, and the same evaluator gates offstage audio.

## Persistence

IndexedDB stores source and accepted blobs and autosaves validated project metadata. Older schemas upgrade on load (four-bar scenes repeat to sixteen bars, four sections become eight, sixteen-bar songs become thirty-two with each section twice as long and every pattern and path played through twice, and pre-base-band songs gain the band once). Portable bundles include accepted assets, so a fresh browser can restore and play them without the server. Undo keeps at most 30 snapshots; a run of volume, pitch or pan slider changes to one performer is a single step.

## Gateway

FastAPI accepts bounded uploads, uses FFprobe/FFmpeg to inspect media and extract frames and audio windows, stores files under opaque IDs in HMAC-signed HTTP-only sessions, and expires retrieval after 24 hours.

| Route                                                                                                        | Purpose                                                                          |
| ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| `GET /api/health`, `GET /api/models`                                                                         | Configured providers, limits and model catalogue                                 |
| `POST /api/media`, `GET /api/media/{id}/frame`, `GET /api/media/{id}/filmstrip`, `GET /api/media/{id}/audio` | Upload and previews                                                              |
| `POST /api/selections`                                                                                       | Box on a frame → Muse Spark names it, SAM cuts it, plus a suggested sound window |
| `POST /api/media/{id}/mask`                                                                                  | Cutout from a hand-painted mask (no model)                                       |
| `POST /api/segment`                                                                                          | Direct SAM segmentation by concept or box                                        |
| `POST /api/characters`, `GET /api/characters/{id}`                                                           | Muse Image painting of a cutout, then a new matte                                |
| `POST /api/separate`, `GET /api/jobs/{id}`                                                                   | SAM Audio separation on Modal                                                    |
| `GET /api/assets/{file}`, `DELETE /api/session`                                                              | Session assets and removal                                                       |

In demo mode the cutout is a rectangle, the target audio is a raw copy and the residual is silence, all labelled. Jobs run under in-process supervision with completed jobs persisted; a restart fails unfinished jobs explicitly and allows retry. This is a single-container deployment, not a distributed queue.
