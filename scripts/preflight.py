import argparse
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path
from urllib.parse import quote

logger = logging.getLogger("junk.preflight")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check live Meta model entitlements and HF checkpoint gate without downloading weights"
    )
    parser.add_argument(
        "--model", help="Override the configured SAM_AUDIO_MODEL_ID for the HF gate check"
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Report configuration and installed adapters without contacting providers",
    )
    parser.add_argument(
        "--meta-only",
        action="store_true",
        help="Check Meta model access without a Hugging Face gate request",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from services.gateway.config import Settings
    from services.gateway.environment import load_environment
    from services.gpu.config import WorkerSettings

    load_environment(Path(__file__).resolve().parents[1] / ".env")
    settings = Settings()
    settings.validate()
    worker = WorkerSettings.from_environment()
    gate_model = args.model or worker.model
    dependencies = {
        name: importlib.util.find_spec(name) is not None
        for name in ("fastapi", "uvicorn", "PIL", "httpx", "openai", "meta_sam_parser", "modal")
    }
    report = {
        "mode": settings.mode,
        "meta_key_configured": bool(settings.meta_key),
        "modal_configured": settings.modal_enabled,
        "image_model": settings.image_model,
        "hf_gate_model": gate_model,
        "worker": {
            "app": worker.app,
            "media_volume": worker.media_volume,
            "model": worker.model,
            "source_revision": worker.source_revision,
            "model_revision": worker.model_revision,
            "gpu": worker.gpu,
            "uses_floating_main": worker.source_revision == "main"
            or worker.model_revision == "main",
        },
        "dependencies": dependencies,
    }
    if args.offline:
        print(json.dumps(report, indent=2))
        return
    if not settings.meta_key:
        raise SystemExit("Set MODEL_API_KEY in .env, or use --offline to inspect setup first.")
    if not dependencies["openai"] or not dependencies["meta_sam_parser"]:
        raise SystemExit("Install the project server dependencies first: uv sync --extra dev")
    import httpx
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["MODEL_API_KEY"], base_url="https://api.meta.ai/v1")
    enabled = {model.id for model in client.models.list().data}
    expected = {"sam-3.1", settings.image_model, "muse-spark-1.3"}
    logger.info("Meta models enabled=%s missing=%s", sorted(enabled), sorted(expected - enabled))
    if expected - enabled:
        raise SystemExit("The required Meta models are not enabled for this account.")
    if args.meta_only:
        return
    if not os.environ.get("HF_TOKEN"):
        raise SystemExit("Set HF_TOKEN for the deployed SAM Audio checkpoint, or use --meta-only.")
    response = httpx.head(
        f"https://huggingface.co/{gate_model}/resolve/{quote(worker.model_revision, safe='')}/config.json",
        headers={"Authorization": f"Bearer {os.environ['HF_TOKEN']}"},
        follow_redirects=True,
        timeout=30,
    )
    response.raise_for_status()
    logger.info(
        "HF model gate accessible model=%s status=%s; no weights downloaded",
        gate_model,
        response.status_code,
    )


if __name__ == "__main__":
    main()
