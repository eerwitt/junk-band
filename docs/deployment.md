# Deployment

Run provider setup from your own shell after reviewing the source. Never paste tokens into browser forms or commit them; only `JUNK_API_BASE` reaches the browser build.

## Accounts and local setup

You need Modal with billing enabled, Meta Model API access to `sam-3.1`, `muse-image-1.0` (or your `META_IMAGE_MODEL`) and `muse-spark-1.3`, and an accepted Hugging Face gate for the SAM Audio checkpoint.

```bash
uv sync --extra dev
```

```bash
uv run modal setup
```

Copy `.env.example` to `.env` and keep `JUNK_MODE=auto`:

- `MODEL_API_KEY` enables Meta SAM, Muse Image and Muse Spark. `meta-sam-parser` must be installed in the server interpreter.
- `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` (or `JUNK_MODAL_ENABLED=true` with an existing CLI login) let a local gateway call the deployed separator. App and volume names default to `junk-living-sampler` and `junk-session-media`.
- `JUNK_MODE=mock` with credentials set is rejected at startup. Provider failures never switch back to mock output.
- On loopback origins a session secret is generated under the data directory; hosted live mode needs an explicit `JUNK_API_SESSION_SECRET` and an HTTPS origin.

Check setup without model calls with `uv run python scripts/preflight.py --offline`, or check Meta model access without generating an image with `--meta-only`. `GET /api/health` reports configured adapters; with the local Modal bridge it also checks (at most every 30 s) that the app and volume exist, reporting any problem in `configuration.modal_problem`. Health is configuration, not proof of entitlement or quality. The gateway labels a job `SAM Audio` only when the worker reports a `facebook/sam-audio*` model.

Create these Modal Secrets in the dashboard:

- `hf-sam-audio`: `HF_TOKEN` with gated model access.
- `meta-model-api`: `MODEL_API_KEY`.
- `junk-gateway`: a random 32+ character `JUNK_API_SESSION_SECRET`, and `CORS_ALLOWED_ORIGIN` set to the exact frontend origin.

## Worker build and weights

`SAM_AUDIO_REVISION` and `SAM_AUDIO_MODEL_REVISION` are pinned to verified commits; change the model revision together with `SAM_AUDIO_MODEL_ID`. `services/gpu/image_lock.py` pins every other package in the image (installed with `--no-deps`). The base is PyTorch 2.8.0 / CUDA 12.8. The deployment module reads `.env` with shell variables taking precedence, and passes only an allowlist of non-secret settings to the images; tokens stay in Modal Secrets.

```bash
uv run modal run -m services.gpu.modal_app --download
```

```bash
uv run modal deploy -m services.gpu.modal_app
```

Set `JUNK_MODAL_GATEWAY=false` for both commands to deploy only the worker for use with a local gateway; then only `hf-sam-audio` is required.

Weights download on Modal into `/weights/hf`, never locally. Defaults: `facebook/sam-audio-small-tv` on one L40S, `predict_spans` on and eight reranking candidates, chosen by listening. An 8 s window took about 4.7 s and reserved 37.9 GB; `large-tv` needs an A100-80GB. Rerun `--download` after changing the model.

The `Separator` uses a CPU memory snapshot so restored containers skip loading the model; `TORCHINDUCTOR_COMPILE_THREADS=1` is required for that. Making a selection warms the worker early, which can bill up to about 3 idle minutes if no sound job follows. A job fails after 10 minutes on the worker (`WORKER_LIMIT_S`) and the gateway cancels the call; the gateway's own limit is 13 minutes.

## Smoke test

```bash
uv run python scripts/smoke.py --api https://YOUR-GATEWAY.modal.run/api --source YOUR-OWN-tin.wav --description "metal can clanking" --start 0 --end 4 --require-live
```

This uploads your media, polls the job, downloads target and residual WAVs and logs metrics. Listen to both: a returned WAV does not prove correct attribution. Repeat with a silent source.

Add `--character --concept "the red tin can" --frame 1 --output data/smoke-tin-live` with a video source to run the full paid flow: SAM cutout, Muse Image painting, new matte, and audio separation. It writes `original-cutout.png`, `cardboard-character.png`, `target.wav`, `residual.wav` and `report.json`. `status: ready` means structural checks passed, not that it looks or sounds good. A failed rerun replaces the report with `status: failed`.

`scripts/rig_character.py --source <character.png>` separately extracts four SAM limb layers for review. The app no longer rigs new characters.

## Hosting for friends

The hosted gateway serves the page and API from one address; each browser gets its own signed anonymous session and keeps its band locally. Build with `JUNK_API_BASE` unset, then deploy:

```bash
uv run python scripts/build_web.py
```

```bash
uv run modal deploy -m services.gpu.modal_app
```

`CORS_ALLOWED_ORIGIN` must be the site's own `https://` address, which also marks the cookie secure.

**Limits.** `JUNK_DAILY_REQUEST_LIMIT` (default 90) caps paid requests across the site per UTC day, stored on the media volume. Cached results do not count. Sounds run one at a time and paintings two at a time, first come first served, with queue position shown.

**Budgets.** Before paid work the gateway reads the workspace's Modal bill (at most every five minutes) and stops if anything has been charged or this month's usage reaches `JUNK_MODAL_MONTHLY_LIMIT` (default $20). If the bill cannot be read the request proceeds, so also set a spend limit on the Modal account. Meta has no spend API: `JUNK_META_MONTHLY_LIMIT` (default $100) is checked against a running total the gateway adds up from published prices in `services/gateway/meta_costs.py`, counting only this site. A `402` from Meta pauses paid work for ten minutes. `GET /api/health` shows totals under `limits`.

This is enough for a few friends, not a public launch: one gateway container, in-memory jobs.

## Retention

Source retrieval expires after 24 hours. Locally, run `uv run python scripts/cleanup.py --root data --older-than-hours 24 --apply`; on Modal a daily scheduled function removes sessions untouched for 24 hours. `DELETE /api/session` removes a session's server media; accepted browser assets stay playable.
