import argparse
import logging
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.smoke_pipeline import run_smoke  # noqa: E402

logger = logging.getLogger("junk.smoke")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test audio or the full video-to-cardboard pipeline against the public gateway"
    )
    parser.add_argument("--api", default="http://127.0.0.1:5173/api")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--description", default="metal can clanking")
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--end", type=float, default=4)
    parser.add_argument("--output", type=Path, default=Path("data/smoke"))
    parser.add_argument("--require-live", action="store_true", help="Reject demo gateways/results")
    parser.add_argument(
        "--character",
        action="store_true",
        help="Also run paid Meta image generation and SAM; requires live video input",
    )
    parser.add_argument("--frame", type=float, default=0)
    parser.add_argument("--concept", help="Object to segment, e.g. the red tin can")
    parser.add_argument(
        "--details", default="Short hinged paper arms and boots; retain the object's markings."
    )
    parser.add_argument("--timeout", type=float, default=1000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with httpx.Client(base_url=args.api.rstrip("/") + "/", timeout=180) as client:
        report = run_smoke(
            client,
            args.source,
            args.output,
            args.description,
            args.start,
            args.end,
            character=args.character,
            require_live=args.require_live,
            frame=args.frame,
            concept=args.concept,
            details=args.details,
            timeout=args.timeout,
        )
    logger.info(
        "Smoke complete mode=%s artifacts=%s; human review required", report["mode"], args.output
    )


if __name__ == "__main__":
    main()
