"""Render the stage's motion and effects to PNG frames, without a browser or audio.

Builds the browser modules, writes the base band and its compiled notes to JSON, then runs
godot/tests/vfx_preview.gd against a simulated audio clock. Needs a display; on a headless
Linux machine it uses xvfb-run when available.

    uv run python scripts/preview_vfx.py --scenario dance --start 24
    uv run python scripts/preview_vfx.py --scenario remove --every 3

Scenarios: dance, pause, remove, arrive, clone, menu, card, path, wrap, walk.
"""

import argparse
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("junk.preview")

DUMP = """
import { starterProject } from "./dist/modules/domain/project.js";
import { compileEvents } from "./dist/modules/domain/music.js";
const project = starterProject(42);
process.stdout.write(JSON.stringify({ project, events: compileEvents(project) }));
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--godot", default=shutil.which("godot") or shutil.which("godot_console") or "godot"
    )
    parser.add_argument("--scenario", default="dance")
    parser.add_argument("--start", type=float, default=0.0, help="Song beat to start from")
    parser.add_argument("--frames", type=int, default=180, help="Frames to run (dance only)")
    parser.add_argument("--every", type=int, default=3, help="Save every Nth frame")
    parser.add_argument(
        "--metrics", action="store_true", help="Print each character's motion range"
    )
    parser.add_argument("--out", type=Path, default=Path("artifacts/vfx-preview"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node") or "node"
    subprocess.run([node, "scripts/build_browser.cjs"], cwd=root, check=True)
    band = subprocess.run(
        [node, "--input-type=module", "-e", DUMP], cwd=root, check=True, capture_output=True
    ).stdout
    out = (root / args.out / args.scenario).resolve()
    out.mkdir(parents=True, exist_ok=True)
    band_file = out / "band.json"
    band_file.write_bytes(band)
    command = [
        args.godot,
        "--path",
        str(root / "godot"),
        "--rendering-driver",
        "opengl3",
        "--audio-driver",
        "Dummy",
        "--fixed-fps",
        "60",
        "--resolution",
        "1440x900",
        "--script",
        "res://tests/vfx_preview.gd",
        "--",
        f"--band={band_file}",
        f"--out={out}",
        f"--scenario={args.scenario}",
        f"--start={args.start}",
        f"--frames={args.frames}",
        f"--every={args.every}",
        f"--public={root / 'public'}",
    ]
    if args.metrics:
        command.append("--metrics")
    xvfb = shutil.which("xvfb-run")
    if xvfb:
        command = [xvfb, "-a", "-s", "-screen 0 1440x900x24", *command]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=600)
    output = result.stdout + result.stderr
    if "SCRIPT ERROR:" in output or "Parse Error:" in output:
        raise RuntimeError(output)
    for line in output.splitlines():
        if line.startswith("p-"):
            print(line)
    logger.info("Wrote %d frames to %s", len(list(out.glob("*.png"))), out)


if __name__ == "__main__":
    main()
