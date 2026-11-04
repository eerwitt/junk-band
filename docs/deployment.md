# Secure-shell deployment

Run provider setup from your normal shell after reviewing the source. The application now uses environment-selected providers; live inference still needs account access and a deployed worker.

## Accounts and secrets

Accept the SAM Audio checkpoint gate and license on Hugging Face. Its PE-AV and other research dependencies may require additional access; inspect the first remote build's errors. Have Modal billing enabled and Meta Model API models enabled. Do not paste tokens into browser forms, commit them, or put them in `VITE_*` variables.

Configure `MODEL_API_KEY` and `HF_TOKEN` in the secure shell, then run:

```powershell
uv sync --extra dev
uv run python scripts/preflight.py
uv run modal setup
```

For local development, copy `.env.example` to `.env` and leave `JUNK_MODE=auto`. `MODEL_API_KEY` selects live Meta SAM/Muse Image/description requests. `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` select the deployed Modal separator; alternatively set `JUNK_MODAL_ENABLED=true` to use an existing Modal CLI login. The app and volume names default to `junk-living-sampler` and `junk-session-media`. The local bridge uploads source media plus its metadata into the volume before calling `Separator.separate`, then downloads and validates both WAVs. It does not run GPU models locally. This follows Modal's [deployed class invocation](https://modal.com/docs/guide/trigger-deployed-functions) and [volume transfer](https://modal.com/docs/guide/volumes) interfaces.

Do not leave `JUNK_MODE=mock` while credentials are set: startup rejects that conflicting configuration. Provider failures never switch back to mock output. The synthesized starter band remains playable without an account. For local loopback origins, a persistent session secret is generated under the ignored data directory; hosted live mode requires your explicit secret and HTTPS origin.

Check setup without model calls: `uv run python scripts/preflight.py --offline`. Check Meta account model access without generating an image: `uv run python scripts/preflight.py --meta-only`. Required Meta models are `sam-3.1`, `muse-image-1.0` (or your `META_IMAGE_MODEL`) and `muse-spark-1.3`. `meta-sam-parser` must be installed in the actual server interpreter, even if the API key is present. Health reports configuration and installed adapters; it does not establish model entitlement or output quality. With the local bridge, it also checks (at most every 30 seconds) that the Modal app and volume exist and the token is accepted: `audio` turns false and `configuration.modal_problem` says why. An inconclusive check, such as a network failure, leaves `audio` true because it says nothing about the deployment. The gateway labels a job `SAM Audio` only when the worker's metrics report a `facebook/sam-audio*` model, and otherwise discards its output. This catches a wrong app deployed under the configured name; it is a self-report, not proof of inference.

The SAM adapter checks the final stream outcome, rejects parser errors, resolves cumulative masks to their latest revision and uses the explicit object ID for a box prompt. A concept that matches multiple objects requires a tighter selection instead of choosing an arbitrary result. Bounds are half-open source-pixel coordinates; integral float values are converted before placing full-canvas limb masks. Image EXIF orientation is applied before segmentation so photo previews and mask coordinates agree. These rules follow the official [SAM protocol](https://github.com/meta-models/meta-sam/blob/main/protocol/sam3.md) and [Python parser contract](https://github.com/meta-models/meta-sam/blob/main/python/README.md). Contract fixtures test completed/incomplete streams, revisions, identity, cleanup, cancellation and oriented photos; they do not establish live parser/model behavior.

`POST /api/selections` takes a rough box on a frame. Muse Spark names what is in it, SAM searches for that name and the match overlapping the box wins, with SAM's own reading of the box as the fallback: one description and one or two SAM requests per selection, cached per box. It also saves the as-is look: only the selected object, on a torn scrap of white paper. A box with no match still gives a usable rough selection, labelled as one. Spark was chosen after testing: `muse-wonder-1.0` took up to 78 s or timed out on images and misnamed a drum as sandy ground, and SAM from a loose box alone cut out the ground. `GET /api/media/{id}/filmstrip` returns the frames for scrubbing.

The character route is `POST /api/characters` after `POST /api/segment`, followed by polling `GET /api/characters/{id}`. It sends the original cutout to Meta's [Muse Image edit API](https://dev.meta.ai/docs/image-generation), stores the painted image, then calls SAM again for a new full-character alpha mask. A cached painted image survives a failed mask retry. Original cutout, styled artwork and accepted audio remain distinct. No paid image request has been made or claimed as validated by the browser fixtures in this workspace.

The import drawer honors individual capabilities: Meta-only setup can cut/style objects and keep raw audio; Modal-only setup can separate audio-only recordings. Video acceptance requires an actual object cutout. Controls are recomputed after asynchronous work, and prompt changes invalidate their previous candidates. Late poll replies are discarded; lost status checks and failed retries remain recoverable. `scripts/check_media_capabilities.py` verifies these cases using explicitly labelled fixtures against a demo gateway, without contacting live providers.

`GET /api/media/{id}/frame?frame_s=0.5` supplies a session-private PNG preview when browser video decoding fails. It uses the same source orientation and frame extraction as segmentation, requires no model credentials, caches decoded frames server-side and returns `Cache-Control: private, no-store`. The client debounces fallback seeks, ignores old frame loads and keeps selection disabled until the requested frame is visible. The route validates timestamps and source access; actual FFmpeg decode, orientation, cache and isolation are covered by server tests.

Create Modal Secrets through the Modal dashboard:

- `hf-sam-audio`: `HF_TOKEN` with gated model access.
- `meta-model-api`: `MODEL_API_KEY`.
- `junk-gateway`: a random 32+ character `JUNK_API_SESSION_SECRET`, and `CORS_ALLOWED_ORIGIN` set to the exact frontend origin.

## Remote build and weights

`SAM_AUDIO_REVISION` and `SAM_AUDIO_MODEL_REVISION` are pinned to the commits verified by ear, and `services/gpu/image_lock.py` pins every other package from that image, installed with `--no-deps` because some research packages declare conflicting requirements. Change the model revision together with `SAM_AUDIO_MODEL_ID`, because a revision belongs to one model. The base is PyTorch 2.8.0 / CUDA 12.8.

The deployment module reads the local `.env` with shell variables taking precedence. Custom `JUNK_MODAL_APP` and `JUNK_MODAL_VOLUME` names are shared with the local bridge. Both remote images receive an explicit allowlist of non-secret worker settings, including the source and checkpoint revisions; account tokens remain in Modal Secrets. Preflight reports those settings and flags use of floating `main`. Its HF gate check uses the configured model and checkpoint revision rather than hard-coded defaults. A configured revision is not evidence that a remote download or inference has succeeded.

```powershell
uv run modal run -m services.gpu.modal_app --download
uv run modal deploy -m services.gpu.modal_app
```

To use only the local gateway with the deployed worker, set `JUNK_MODAL_GATEWAY=false` in the shell for both commands. Only `hf-sam-audio` is then required; the hosted gateway and its secrets are left out.

A job fails after 10 minutes on the worker (`WORKER_LIMIT_S`), and the gateway cancels the call and its containers. A worker that crashes at startup never fails its call, so this limit is what ends the job and stops the billing. A 13-minute gateway limit also covers moving media each way, and the `Separator` allows 10 minutes to start and 5 to run.

Making a selection starts the worker early, so a cold start is usually under way before the sound is requested. That can bill up to about 3 idle minutes if no sound job follows. Metrics report `waited_for_gpu_s`, the time a job waited for its container. The `Separator` uses a CPU memory snapshot, so a restored container skips reading the model from the volume: the first cold start builds the snapshot, and Modal occasionally rebuilds it, which costs a normal slow start. `TORCHINDUCTOR_COMPILE_THREADS=1` is required, because `torch.compile` worker processes started during a snapshot have no GPU after a restore.

Weight download runs on Modal, never on Windows/WSL. The model's auxiliary downloads also use `/weights/hf`. The GPU runtime loads the cached local checkpoint, starts no minimum containers, and caps the L40S worker at one container. The defaults are `facebook/sam-audio-small-tv` with `predict_spans` on and eight reranking candidates (`SAM_AUDIO_PREDICT_SPANS`, `SAM_AUDIO_RERANKING_CANDIDATES`), chosen by listening to real recordings. An 8-second window measured about 4.7 seconds of inference and 37.9 GB reserved of the L40S's 48 GB. `large-tv` reserved 47.8 GB, so it needs an A100-80GB. The download step also caches the ranking models on the weights volume; rerun it after changing the model.

The gateway is a separate CPU function, capped at one container with concurrent inputs, sharing `/session-media`. CPU writes commit before GPU requests; GPU reloads before reads and commits before returning. Readiness reflects configured adapters, not verified model entitlement; use preflight plus the real smoke below.

## Real inference smoke

```powershell
uv run python scripts/smoke.py --api https://YOUR-GATEWAY.modal.run/api --source YOUR-OWN-tin.wav --description "metal can clanking" --start 0 --end 4 --require-live
```

This uploads permissioned media, polls the job, downloads target/residual WAVs and logs measured metrics. Listen to both. Record checkpoint/source revisions, CUDA dependency freeze, GPU name, load time, warm/cold inference time, peak allocated/reserved memory, sample rate, duration and subjective leakage/faithfulness. A returned WAV alone does not prove correct object attribution. Repeat with a silent-negative source. Do not present mock artifacts as live evidence.

For the complete video workflow, use a recording with both the object and its sound:

```powershell
uv run python scripts/smoke.py --api https://YOUR-GATEWAY.modal.run/api --source YOUR-OWN-tin.mp4 --description "metal can clanking" --concept "the red tin can" --frame 1 --start 0 --end 4 --character --output data/smoke-tin-live
```

`--character` requires live mode and configured image, segmentation and audio adapters before uploading. It runs paid Meta image generation: source video → SAM cutout → reference-guided Muse Image edit → new SAM matte, followed by audio separation from the same uploaded recording. This command retains `original-cutout.png`, `cardboard-character.png`, `target.wav`, `residual.wav` and `report.json`. The report records provenance, source/output hashes, image dimensions and alpha range, WAV duration/rate/channels/RMS/peak and provider metrics. It checks that generation preserved the original cutout and produced a distinct transparent character, and rejects mock audio provenance in any live run. A failed rerun replaces the prior success report with `status: failed`; leftover artifacts are not evidence of a completed run.

The character job paints one image of the object and cuts it out with SAM. There is no limb rigging: the prompt asks Muse Image to keep the object recognizable, with no face or limbs unless the details ask for them. Its plain paper is removed directly, which costs nothing and keeps every part of the object; SAM is only the fallback when the paper is not plain, because it has returned a few scattered pieces of a painted object while passing every structural check. Provenance says which method cut the image. Look at the results: structural checks cannot tell a good cutout from a broken one. Accepted images are single flat cutouts; rigged characters in older projects still play. Report `status: ready` means structural checks passed; it does not rate visual or audio quality. Without `--character` or `--require-live`, audio-only smoke also supports labelled demo testing; the default API is `http://127.0.0.1:5173/api`.

### Separate limb review

The same limb extractor is available separately for reviewing a saved character:

```powershell
uv run python scripts/rig_character.py --source data/smoke-tin-live/cardboard-character.png --output data/rig-review
```

This requires `MODEL_API_KEY` and the SAM parser in the actual interpreter. It makes up to four real SAM requests to isolate the arms and legs on their original shared canvas. It writes a body layer, four limb layers, cached masks and a `*-rig.json` manifest with normalized pivots, bounds and rotation limits. All print colors come from the input character. Wrong-side, oversized, overlapping, empty or misaligned masks fail explicitly. Successful masks survive retries; a mask rejected by validation is discarded so that retry can request a replacement. The completion manifest is published only after validation, and the source image is preserved. Input must have a usable alpha matte and fit within 2048 pixels on its longest side.

This standalone command is not part of the app, which no longer rigs new images. It remains for reviewing limb extraction by hand.

## Hosting for friends

The hosted gateway serves the built page and the API from one address, so each browser gets its own signed anonymous session cookie and its own band in local storage, with no accounts. Build with `JUNK_API_BASE` unset, then deploy. The image gzips the engine files and serves them revalidated, so a deploy cannot mix old and new files.

```powershell
uv run python scripts/build_web.py
uv run modal deploy -m services.gpu.modal_app
```

`CORS_ALLOWED_ORIGIN` in the `junk-gateway` secret must be the site's own `https://` address, which also marks the cookie secure.

**Limits.** `JUNK_DAILY_REQUEST_LIMIT` (default 90) caps requests that cost money across the whole site per UTC day, kept on the media volume so a restart does not reset it. Cached results do not count. Sounds run one at a time and paintings two at a time, in first-come order with the place in line shown, and a full queue refuses new requests.

**Budgets.** Before paid work the gateway reads the workspace's real Modal bill, at most every five minutes, and stops if anything has actually been charged or this month's usage reaches `JUNK_MODAL_MONTHLY_LIMIT` (default $20). This covers everything in the workspace. If the bill cannot be read the request goes ahead, because Modal's own account limit and the daily limit still apply; set a spend limit on the Modal account as well.

Meta has no balance or spend API, so `JUNK_META_MONTHLY_LIMIT` (default $100) is checked against a running total the gateway adds up itself, per call, at the published prices in `services/gateway/meta_costs.py`, using the token counts each reply reports. It only knows about this site: calls from a local gateway or another app on the same Meta account are not included, and the total starts at zero when first deployed. Check the real figure on Meta's dashboard. A `402 billing_error` from Meta, its documented answer for a low balance, also pauses paid work for ten minutes. `GET /api/health` shows the totals under `limits`.

This is enough for a few friends, not a public launch. There is one gateway container, so jobs in memory fail with a retry if it restarts.

## Retention and operations

Source retrieval expires after 24 hours. Run `uv run python scripts/cleanup.py --root data --older-than-hours 24 --apply` locally. On Modal, a scheduled function removes sessions untouched for 24 hours from the media volume every day. Deleting a session uses `DELETE /api/session`; accepted browser assets remain playable. Stopping the gateway during a job causes an explicit failed state with retry/raw fallback. Use a durable queue/object storage for multi-container production use.

No hosted repository, public website or hackathon submission is created by these scripts.
