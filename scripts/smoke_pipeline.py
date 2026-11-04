"""Public-API smoke orchestration; no provider substitutes or private server imports."""

import hashlib
import io
import json
import math
import re
import sys
import time
import wave
from array import array
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, cast

import httpx
from PIL import Image


def fetch_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    files: dict[str, tuple[str, BinaryIO]] | None = None,
) -> dict[str, Any]:
    response = client.request(method, path.lstrip("/"), json=json, files=files)
    response.raise_for_status()
    return response.json()


def poll_job(
    client: httpx.Client, collection: str, job: dict[str, Any], timeout: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while job["status"] not in {"ready", "failed"}:
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"{collection} job {job['id']} did not finish; it may still be running"
            )
        time.sleep(1)
        job = fetch_json(client, "GET", f"{collection}/{job['id']}")
    if job["status"] != "ready":
        raise RuntimeError(f"{collection} job failed: {job.get('error') or 'no provider result'}")
    return job


def download(client: httpx.Client, asset: str, output: Path) -> bytes:
    # Keep the session on the gateway instead of following a provider URL.
    if not re.fullmatch(r"/assets/[a-f0-9]{32}[-a-z]*\.(png|wav)", asset):
        raise ValueError("Gateway returned an unsupported asset path")
    payload = bytearray()
    with client.stream("GET", asset.lstrip("/")) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            payload.extend(chunk)
            if len(payload) > 32 * 1024 * 1024:
                raise ValueError("Smoke artifact exceeded 32 MiB")
    output.write_bytes(payload)
    return bytes(payload)


def inspect_png(payload: bytes) -> dict[str, Any]:
    with Image.open(io.BytesIO(payload)) as image:
        if image.width * image.height > 16_000_000:
            raise ValueError("Character artifact is too large")
        low, high = cast("tuple[int, int]", image.convert("RGBA").getchannel("A").getextrema())
        if low >= 128 or high < 128:
            raise ValueError("Live character/cutout has no usable transparent silhouette")
        return {"width": image.width, "height": image.height, "alpha_range": [low, high]}


def inspect_wav(payload: bytes, expected_duration: float) -> dict[str, Any]:
    with wave.open(io.BytesIO(payload), "rb") as sound:
        if sound.getsampwidth() != 2 or sound.getnchannels() not in {1, 2}:
            raise ValueError("Expected mono/stereo PCM16 WAV")
        duration = sound.getnframes() / sound.getframerate()
        if abs(duration - expected_duration) > 0.1:
            raise ValueError("Separated audio duration does not match the requested window")
        samples = array("h", sound.readframes(sound.getnframes()))
        if sys.byteorder != "little":
            samples.byteswap()
        return {
            "sample_rate": sound.getframerate(),
            "channels": sound.getnchannels(),
            "duration_s": duration,
            "rms": math.sqrt(sum(float(v) ** 2 for v in samples) / max(1, len(samples))) / 32768,
            "peak": max((abs(v) for v in samples), default=0) / 32768,
        }


def run_smoke(
    client: httpx.Client,
    source: Path,
    output: Path,
    description: str,
    start: float = 0,
    end: float = 4,
    *,
    character: bool = False,
    require_live: bool = False,
    frame: float = 0,
    concept: str | None = None,
    details: str = "",
    timeout: float = 1000,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "report.json"
    manifest.write_text(json.dumps({"status": "running"}), encoding="utf-8")
    try:
        report = _run_smoke(
            client,
            source,
            output,
            description,
            start,
            end,
            character=character,
            require_live=require_live,
            frame=frame,
            concept=concept,
            details=details,
            timeout=timeout,
        )
    except Exception as error:
        manifest.write_text(
            json.dumps({"status": "failed", "error_type": type(error).__name__}), encoding="utf-8"
        )
        raise
    manifest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _run_smoke(
    client: httpx.Client,
    source: Path,
    output: Path,
    description: str,
    start: float,
    end: float,
    *,
    character: bool,
    require_live: bool,
    frame: float,
    concept: str | None,
    details: str,
    timeout: float,
) -> dict[str, Any]:
    if not 2 - 1e-7 <= end - start <= 8 + 1e-7 or not 0 <= start <= 58 or end > 60:
        raise ValueError("Choose a 2–8 second audio window inside the first minute")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Job timeout must be a positive finite number of seconds")
    health = fetch_json(client, "GET", "health")
    live = require_live or character or health.get("mode") == "live"
    if live and health.get("mode") != "live":
        raise RuntimeError("This smoke requires a live gateway; demo output is not accepted")
    required = ["audio"] + (["sam", "image"] if character else [])
    missing = [name for name in required if not health.get(name)]
    if missing:
        raise RuntimeError(f"Gateway is missing required adapters: {', '.join(missing)}")
    with source.open("rb") as handle:
        media = fetch_json(client, "POST", "media", files={"file": (source.name, handle)})
    if not media.get("audio_present") or end > media["duration_s"] + 0.01:
        raise ValueError("Source has no audio in the requested window")
    if character and (not media.get("width") or not 0 <= frame < media["duration_s"]):
        raise ValueError("Full character smoke needs a video and a frame inside its duration")
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "status": "ready",
        "mode": health["mode"],
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "description": description,
        "window": [start, end],
        "artifacts": {},
        "review_required": "Listen for attribution/leakage; inspect identity, style, limbs and matte. Automated checks do not establish model quality.",
    }
    if character:
        cutout = fetch_json(
            client,
            "POST",
            "segment",
            json={
                "media_id": media["id"],
                "frame_s": frame,
                "concept": concept or description[:100],
            },
        )
        if cutout.get("provenance") != "SAM 3.1 alpha mask":
            raise RuntimeError("Expected live SAM segmentation provenance")
        original = download(client, cutout["cutout_url"], output / "original-cutout.png")
        report["artifacts"]["original_cutout"] = {
            **inspect_png(original),
            "sha256": hashlib.sha256(original).hexdigest(),
            "provenance": cutout["provenance"],
        }
        job = fetch_json(
            client,
            "POST",
            "characters",
            json={
                "cutout_id": cutout["cutout_id"],
                "description": description,
                "details": details,
            },
        )
        job = poll_job(client, "characters", job, timeout)
        if not job.get("provenance", "").startswith("Meta "):
            raise RuntimeError("Expected live Meta image provenance")
        styled = download(client, job["character_url"], output / "cardboard-character.png")
        if styled == original:
            raise ValueError("Styled output is an unchanged copy of the source cutout")
        retained = download(client, cutout["cutout_url"], output / "original-cutout.png")
        if retained != original:
            raise ValueError("Character creation changed the original cutout")
        report["artifacts"]["character"] = {
            **inspect_png(styled),
            "sha256": hashlib.sha256(styled).hexdigest(),
            "provenance": job["provenance"],
            "details": details,
        }
    job = fetch_json(
        client,
        "POST",
        "separate",
        json={
            "media_id": media["id"],
            "start_s": start,
            "end_s": end,
            "description": description,
        },
    )
    job = poll_job(client, "jobs", job, timeout)
    if live and job.get("provenance") != "SAM Audio":
        raise RuntimeError("Expected live SAM Audio provenance; mock output is not accepted")
    for name in ("target", "residual"):
        payload = download(client, job[f"{name}_url"], output / f"{name}.wav")
        report["artifacts"][name] = {
            **inspect_wav(payload, end - start),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "provenance": job["provenance"],
        }
    report["provider_metrics"] = job.get("metrics", {})
    report["completed_at"] = datetime.now(UTC).isoformat()
    return report
