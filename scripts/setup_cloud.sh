#!/usr/bin/env bash
# Prepare a fresh Linux machine (such as a cloud session) to build and check JUNK.
# Needs Node 22+, Python 3.11+ with uv, and FFmpeg already installed. Safe to run again.
set -euo pipefail
cd "$(dirname "$0")/.."

npm ci --offline --cache .npm-cache --ignore-scripts --no-audit --no-fund
uv sync --extra dev
# Godot 4.6.3 and its single-threaded web templates; the editor is linked as ~/.local/bin/godot.
python3 scripts/install_godot.py
