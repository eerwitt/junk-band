import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("junk.dev")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve the Godot studio with environment-selected Meta and Modal providers"
    )
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    from services.gateway.environment import load_environment

    load_environment(root / ".env")
    if args.build:
        subprocess.run([sys.executable, "scripts/build_web.py"], check=True)
    if not (root / "dist/engine/junk.wasm").exists():
        parser.error("Build first: npm run build, or pass --build")
    environment = dict(os.environ)
    logger.info("JUNK: http://%s:%s · API docs: /docs", args.host, args.port)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "services.gateway.dev_server:app",
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
        check=True,
        env=environment,
    )


if __name__ == "__main__":
    main()
