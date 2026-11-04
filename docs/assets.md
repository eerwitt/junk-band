# Asset provenance

**Base band.** The eleven sounds in `public/sounds/` are CC0 recordings from VCSL and Kenney, trimmed and levelled by `scripts/prepare_band.py`; sources are listed in `public/sounds/CREDITS.md`. Their pictures in `public/band/` were painted with Meta Muse Image for this project.

**Demo band.** `src/audio/demo.ts` synthesizes four original, deterministic samples (low thump, noisy snare, tuned glass tone, high tick) for the demo scene. `public/sprites.png` (also `godot/assets/sprites.png`) is the matching generated four-tile atlas: tin can, rubber duck, bottle and matchbox. These are labelled as synthesized demo sounds and never represent real segmentation.

**Demo clip.** `public/demo-source.mp4` is a synthetic fixture made by `scripts/make_fixture.py` for the demo import flow.

**Icons and lettering.** The play/pause, add, save, duplicate, pencil, eraser, rhythm-card and skull icons in `godot/assets/` are original SVG. Impact words are original monoline glyph strokes in `godot/scripts/landing_effect.gd`. The landing plop is a browser-synthesized oscillator, separate from the exported mix.

**Font.** Noto Sans (Copyright 2015–2021 Google LLC) under the SIL Open Font License 1.1; the license is at `godot/assets/OFL.txt`.

**JavaScript packages.** Three unmodified npm archives in `vendor/` for offline installation, each with its upstream license; see `vendor/README.md`.

**Models.** SAM and SAM Audio weights are never bundled. Review the upstream SAM License and Hugging Face conditions before deploying.
