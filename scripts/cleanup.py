import argparse
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.gateway.retention import expired_sessions  # noqa: E402

logger = logging.getLogger("junk.cleanup")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove expired JUNK server session media; dry run by default"
    )
    parser.add_argument("--root", type=Path, default=Path("data"))
    parser.add_argument("--older-than-hours", type=float, default=24)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    root = args.root.resolve(strict=True)
    if root == Path(root.anchor) or args.older_than_hours < 1:
        parser.error("Use a specific media directory and a retention of at least one hour")
    for session in expired_sessions(root, args.older_than_hours):
        logger.info("%s %s", "Removing" if args.apply else "Would remove", session)
        if args.apply:
            shutil.rmtree(session)


if __name__ == "__main__":
    main()
