# JUNK visual system

The stage is the primary artifact: a generous eggshell canvas holding a low, sunlit circular arena. Everything belongs to one cut-paper, stop-motion world. No dashboard card grids, no DAW track stacks, no selection rings (pickup itself is the feedback).

## Palette and type

- Eggshell paper ground, black ink lettering, burnt-orange transport, mint status and pressed states, yellow accents.
- Self-hosted Noto Sans for Godot and browser controls. Impact words use hand-drawn monoline glyph strokes.
- Browser drawers share the Godot palette and spacing.

## Stage and controls

- Default framing leaves generous empty paper around the band. The playing area is a faint feathered gradient, with no outline, rings or ticks.
- The loop cursor follows a quiet counterclockwise elliptical orbit. Hover thickens it and shows a grab cursor; dragging seeks the full sixteen bars.
- **The ring is the song**, in eight sections. Hover opens a shaded band with the section name in light curved lettering. Clicking zooms in 10% and loops the section; a pale outer band repeats the name and zooms back out.
- Characters sitting a section out wait at full colour outside the ring; where one is moved there becomes its spot. They travel there with long bounds, a waddle, or a teetering run.
- Below the ellipse sit only play/pause, the tempo metronome and Add: individually shadowed cardboard pieces with irregular ink edges, fixed to the viewport during camera navigation. A compact row beside the stage holds the help drawer and an icon-only WAV save.
- Tempo is a cardboard metronome whose arm swings on the beat and whose weight slides with the value.
- Camera: cursor-anchored wheel zoom 0.5×–4×, middle/right drag and trackpad gestures pan, Home resets. The world stays 2D orthographic.
- Height on the stage is pitch for tuned characters, snapped to one pentatonic scale; faint note rows appear only while one is carried.
- Rhythm lives on a card of sixteen holes: ready-made cards first, holes to fiddle with, tapping along to teach it. There is no note grid.

## Radial controls

A click opens cardboard controls in a circle around the character, over a local feathered blur; the character stays sharp above it. Dragging dismisses the menu and becomes a pickup. Empty stage or Escape also closes it. Remove is an authored ink skull. Every blocked control explains why on hover.

## Characters and material

- Characters fit within 150 × 144 world units, with a cream paper rim, a darker cut edge, subtle grain anchored to the object and a corrugated core (6.8–8% of art height) that keeps visible thickness through half-turns. A slight resting yaw (0.28 rad) shows the edge.
- Print keeps source resolution up to 2048 px; a separate ≤512 px mask drives the rim and edge mesh. Backing composites beneath opaque pixels without changing them; transparent texels carry paper colour to avoid dark fringes.
- Performer IDs seed stable grain and thickness variation. A bounded cache shares textures and edge meshes between clones. No screen reads or per-frame image/mesh generation.
- Path direction drives smooth facing turns. Both faces carry the print by default; a plain kraft reverse is available.
- Older projects may carry a rigged body plus four rigid limbs. Joints rotate before facing projection in face, edge and shadow; they respond to notes and travel, and freeze during pickup.
- New generated art is a single flat cutout that stays recognisably the object, with no added face or limbs unless asked. Art direction: bright, fun, musical, a little punk, matching the base band.

## Motion

Godot never schedules notes; it reads the audio clock. Characters bounce a few units on their actual note onsets; the orbit expands at most 0.5% on the main beat.

- **Pickup** is snappy and mostly rigid (spring damping 18, frequency 20): a 90 ms loaded dip with 1.2% compression, then a rise to thirty world units. Fast pulls give at most 1.8% stretch and 1.2% shear with limited recoil. Pickup preserves the exact grip and freezes yaw.
- **Shadows** stay on the floor layer behind all characters. Floor position and lift height are independent; height alone drives the fixed light offset (0.38, −0.16), softening, mask gathering and the late merge into an ellipse that widens from 24 to 34 units and lightens.
- **Stationary drops** fall under gravity and land at the committed destination: a held compression of up to ~10%, a small hop, an embossed pressure wave and dent, a dust skirt, tumbling chips, inked impact lines, a nearby-neighbour hop, a quiet plop and a hand-lettered impact word (0.72 s) placed clear of the body.
- **Slides** happen when a release is fast (over 260 units/s) or far from its floor point (over 18 units). The body leans back against the skid and pitches past upright as it brakes; a faint dry-brush trail with heel tracks follows the real route and erodes oldest-first. Particle records are capped (64 puffs, 48 chips, 14 lines).
- **Arrivals** of new or cloned characters drop from 25.5 units with the same landing. Imported characters stay hidden until their real art (and every rig layer) has loaded; they never borrow starter artwork. Loading, opening and Undo do not replay arrivals.
- **Paths**: the pencil records a freehand route, smoothed with cubic interpolation at distance-based timing, reserving the last two bars to return home with zero seam velocity. The eraser clears it.

The engine still supports a reduced-motion mode (no spatial effects, gentler follow), but the web build always plays full motion and exposes no setting.

## Add

Three steps, one decision each, and the waiting happens while you compare.

- A large sheet floats over the washed-out stage, sized so a laptop needs no scrolling; the band fades to near silence while it is open. Dropping a clip goes straight to trimming; the permission checkbox is asked once per browser.
- **Pick the sound** is a film edit: the video sits on a cardboard card, the strip below is perforated stock, and the kept stretch is snipped out with stop-motion scissors. The kept stretch is the sound, 2–8 s, and starts centred on the loudest part of the clip.
- **Choose the object** is three stamped steps: pick the frame on grey film, paint over the thing (Paint, Erase, brush size, Undo), and say what you want to hear. **Make it** needs both. Outside the mask washes back to paper with a thin ink line along the cut.
- **Listen and add** has two cream cards: the look and the sound. Each shows the option in hand, chosen with two paper tabs pressed in mint: Cutout | Painted and Separated | Original clip. The original clip plays at once; switching while playing keeps the place, so the two can be compared directly. A finished painting is picked automatically unless you chose otherwise. The as-is look is only the object on a torn scrap of white paper. The waveform is drawn in ink from the real file: orange for the separated sound, grey for the original.
- Unavailable tools stay disabled with a written reason: no AI cutout means the painted mask is used, no separation means the original clip.
- Long jobs wait on a small paper workbench in 8 fps stop-motion steps. The wait is honest: only stages the gateway reports, real elapsed time, never a percentage or fake bar. Demo mode shows no scene and says nothing is being separated. Jobs outlive the sheet and report back with a stage notice; going Back and changing nothing reruns nothing.
