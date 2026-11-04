"""Extract real SAM limb layers from an already generated transparent character."""

import argparse
import asyncio
import hashlib
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logger = logging.getLogger("junk.rig")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract four rigid paper limbs with real Meta SAM masks"
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="The generated character PNG, including its alpha matte",
    )
    parser.add_argument("--output", type=Path, default=Path("data/rig-review"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from services.gateway.environment import load_environment

    load_environment(Path(__file__).resolve().parents[1] / ".env")
    from services.gateway.config import Settings
    from services.gateway.meta import MetaAdapter
    from services.gateway.rigging import segment_rig

    settings = Settings()
    settings.validate()
    if settings.mode != "live" or not settings.meta_key:
        raise SystemExit(
            "Set MODEL_API_KEY in .env. Limb extraction requires real Meta SAM; there is no mock rig."
        )
    if not MetaAdapter.segmentation_available():
        raise SystemExit("Install meta-sam-parser in this interpreter first: uv sync --extra dev")
    identifier = hashlib.sha256(b"rig-v1:" + args.source.read_bytes()).hexdigest()[:32]
    rig = asyncio.run(
        segment_rig(MetaAdapter(settings.meta_key), args.source, args.output, identifier)
    )
    logger.info(
        "Extracted %s validated rigid limbs; manifest=%s",
        len(rig.parts),
        args.output / f"{identifier}-rig.json",
    )
    logger.info(
        "Review body/limb masks and joint pivots before animation. This does not yet install the rig into the browser project."
    )


if __name__ == "__main__":
    main()
