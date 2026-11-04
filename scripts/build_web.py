import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("junk.build")


def run(arguments: list[str], environment: dict[str, str]) -> str:
    result = subprocess.run(
        arguments,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    output = result.stdout + result.stderr
    if "SCRIPT ERROR:" in output or "Parse Error:" in output or "Failed to load script" in output:
        raise RuntimeError(output)
    logger.info("%s", output[-6000:].strip())
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the Godot stage and native browser services without React or Vite"
    )
    parser.add_argument(
        "--godot", default=shutil.which("godot_console") or shutil.which("godot") or "godot"
    )
    parser.add_argument("--typescript", type=Path)
    parser.add_argument("--zod", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    from services.gateway.environment import load_environment

    load_environment(root / ".env")
    environment = dict(os.environ)
    node = shutil.which("node") or "node"
    command = [node, "scripts/build_browser.cjs"]
    if args.typescript:
        command.extend(["--typescript", str(args.typescript.resolve())])
    if args.zod:
        command.extend(["--zod", str(args.zod.resolve())])
    run(command, environment)
    version = run([args.godot, "--version"], environment).strip().splitlines()[0]
    match = re.match(r"(\d+\.\d+\.\d+)\.(stable)", version)
    if not match:
        raise ValueError("Use a stable Godot build with matching web export templates")
    template_version = f"{match[1]}.{match[2]}"
    template_root = (
        Path(os.environ.get("APPDATA", "")) / "Godot/export_templates" / template_version
    )
    profile = root / ".build/godot-profile"
    local_templates = profile / "Godot/export_templates" / template_version
    local_templates.mkdir(parents=True, exist_ok=True)
    for name in ("web_nothreads_release.zip", "web_nothreads_debug.zip"):
        if not (local_templates / name).exists():
            shutil.copyfile(template_root / name, local_templates / name)
    environment["APPDATA"] = str(profile)
    environment["LOCALAPPDATA"] = str(profile / "Local")
    (root / "dist/engine").mkdir(parents=True, exist_ok=True)
    run(
        [args.godot, "--headless", "--path", "godot", "--editor", "--import", "--quit"], environment
    )
    run([args.godot, "--headless", "--path", "godot", "--quit-after", "3"], environment)
    pickup_check = run(
        [
            args.godot,
            "--headless",
            "--path",
            "godot",
            "--script",
            "res://tests/pickup_test.gd",
            "--quit-after",
            "240",
        ],
        environment,
    )
    if "Pickup regression passed" not in pickup_check:
        raise RuntimeError("Godot pickup regression did not complete")
    cardboard_check = run(
        [
            args.godot,
            "--headless",
            "--path",
            "godot",
            "--script",
            "res://tests/cardboard_test.gd",
            "--quit-after",
            "180",
        ],
        environment,
    )
    if "Cardboard regression passed" not in cardboard_check:
        raise RuntimeError("Godot cardboard regression did not complete")
    rig_check = run(
        [
            args.godot,
            "--headless",
            "--path",
            "godot",
            "--script",
            "res://tests/rig_test.gd",
            "--quit-after",
            "240",
        ],
        environment,
    )
    if "Rig regression passed" not in rig_check:
        raise RuntimeError("Godot rigid limb regression did not complete")
    arrival_check = run(
        [
            args.godot,
            "--headless",
            "--path",
            "godot",
            "--script",
            "res://tests/arrival_test.gd",
            "--quit-after",
            "240",
        ],
        environment,
    )
    if "Arrival regression passed" not in arrival_check:
        raise RuntimeError("Godot character arrival regression did not complete")
    groove_check = run(
        [
            args.godot,
            "--headless",
            "--path",
            "godot",
            "--script",
            "res://tests/groove_test.gd",
            "--quit-after",
            "300",
        ],
        environment,
    )
    if "Groove regression passed" not in groove_check:
        raise RuntimeError("Godot dance and band-moment regression did not complete")
    run(
        [
            args.godot,
            "--headless",
            "--path",
            "godot",
            "--export-release",
            "Web",
            str(root / "dist/engine/junk.html"),
        ],
        environment,
    )
    html = (root / "dist/engine/junk.html").read_text(encoding="utf-8")
    config_match = re.search(r"const GODOT_CONFIG\s*=\s*(\{[^\n]+\});", html)
    if not config_match:
        raise ValueError("Could not read the generated Godot loader configuration")
    config = json.loads(config_match[1])
    (root / "dist/engine/config.json").write_text(json.dumps(config), encoding="utf-8")
    logger.info("Built Godot %s + native browser services in %s", version, root / "dist")


if __name__ == "__main__":
    main()
