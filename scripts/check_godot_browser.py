import argparse
import atexit
import json
import logging
import math
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, sync_playwright

logger = logging.getLogger("junk.godot-check")


def click_control(page: Page, name: str, fraction: float = 0.5) -> None:
    layout = page.evaluate("window.JUNK.layout")
    rect = layout["controls"][name]
    canvas = page.locator("#canvas").bounding_box()
    assert canvas is not None and rect["visible"], f"Godot control not visible: {name}"
    page.mouse.click(
        canvas["x"]
        + (rect["x"] + rect["w"] * fraction) * canvas["width"] / layout["viewport"]["x"],
        canvas["y"] + (rect["y"] + rect["h"] * 0.5) * canvas["height"] / layout["viewport"]["y"],
    )


def performer_point(page: Page, performer_id: str) -> tuple[float, float, float, float]:
    layout = page.evaluate("window.JUNK.layout")
    performer = page.evaluate(
        "id => window.JUNK.snapshot().project.performers.find(p => p.id === id)", performer_id
    )
    canvas = page.locator("#canvas").bounding_box()
    assert canvas is not None
    stage = layout["stage"]
    zoom = stage["zoom"]
    ratio_x = canvas["width"] / layout["viewport"]["x"]
    ratio_y = canvas["height"] / layout["viewport"]["y"]
    x = canvas["x"] + (stage["x"] + stage["originX"] + performer["position"]["x"] * zoom) * ratio_x
    y = (
        canvas["y"]
        + (stage["y"] + stage["originY"] + (performer["position"]["y"] - 60) * zoom) * ratio_y
    )
    return x, y, zoom * ratio_x, zoom * ratio_y


def click_performer(page: Page, performer_id: str) -> None:
    x, y, _, _ = performer_point(page, performer_id)
    page.mouse.click(x, y)
    page.wait_for_function("window.JUNK.layout.inspector")


def drag_performer(
    page: Page, performer_id: str, dx: float, dy: float, output: Path | None = None
) -> None:
    performer = page.evaluate(
        "id => window.JUNK.snapshot().project.performers.find(p => p.id === id)", performer_id
    )
    x, y, scale_x, scale_y = performer_point(page, performer_id)
    # Count what reaches the audio engine, because the sound must follow before the drop.
    page.evaluate(
        """async () => {
          const { audio } = await import('/modules/audio/browser.js');
          window.previewCount = 0;
          if (window.previewSpy) return;
          window.previewSpy = true;
          const original = audio.previewPosition.bind(audio);
          audio.previewPosition = (...args) => {
            window.previewCount += 1;
            original(...args);
          };
        }"""
    )
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx * scale_x, y + dy * scale_y, steps=10)
    page.wait_for_function("window.previewCount > 0", timeout=5000)
    page.mouse.up()
    if output is not None:
        page.wait_for_timeout(330)
        page.screenshot(path=str(output / "landing-effect.png"), full_page=True)
    page.wait_for_function(
        "data => Math.abs(window.JUNK.snapshot().project.performers.find(p => p.id === data.id).position.x - data.x) < 3",
        arg={"id": performer_id, "x": performer["position"]["x"] + dx},
    )


def ring_point(page: Page, fraction: float, outward: float = 0.0) -> tuple[float, float]:
    """A point on the ring, or that many screen units outside it, in page coordinates."""
    layout = page.evaluate("window.JUNK.layout")
    stage = layout["stage"]
    canvas = page.locator("#canvas").bounding_box()
    assert canvas is not None
    zoom = stage["zoom"]
    angle = fraction * math.tau
    x = -math.sin(angle) * (380 * zoom + outward)
    y = -math.cos(angle) * (230 * zoom + outward)
    return (
        canvas["x"]
        + (stage["x"] + stage["originX"] + x) * canvas["width"] / layout["viewport"]["x"],
        canvas["y"]
        + (stage["y"] + stage["originY"] + y) * canvas["height"] / layout["viewport"]["y"],
    )


def bring_everyone_on(page: Page) -> None:
    page.evaluate(
        """() => {
          const { project } = window.JUNK.snapshot();
          for (const section of project.sections)
            for (const id of section.mutedIds)
              window.JUNK.command(JSON.stringify({
                kind: 'set_part',
                payload: { sectionId: section.id, id, present: true },
              }));
        }"""
    )
    page.wait_for_function(
        "window.JUNK.snapshot().project.sections.every(s => s.mutedIds.length === 0)"
    )
    page.wait_for_function(
        "Object.values(window.JUNK.layout.puppets).every(p => p.presence === 1)", timeout=30000
    )


def check_ring_sections(page: Page, output: Path) -> None:
    project = page.evaluate("window.JUNK.snapshot().project")
    sections = project["sections"]
    assert len(sections) == 8, "A new song has eight sections"
    middle = lambda index: (sections[index]["startBar"] + sections[index]["endBar"]) / 32  # noqa: E731
    ids = [p["id"] for p in project["performers"]]

    # Hovering opens out a shaded area with that section's name. Nothing changes yet.
    page.mouse.move(*ring_point(page, middle(3)))
    page.wait_for_function("window.JUNK.layout.hoverSection === 3")
    page.wait_for_function("window.JUNK.layout.sectionReveal > 0.9", timeout=15000)
    assert page.evaluate("window.JUNK.layout.focusSection") == ""
    page.screenshot(path=str(output / "ring-hover.png"), full_page=True)

    # Clicking zooms in a little, keeps playing, and loops just that section.
    was_playing = page.evaluate("window.JUNK.snapshot().playing")
    page.mouse.down()
    page.mouse.up()
    page.wait_for_function("id => window.JUNK.layout.focusSection === id", arg=sections[3]["id"])
    page.wait_for_function("window.JUNK.layout.sectionZoom > 1.09", timeout=30000)
    assert page.evaluate("window.JUNK.snapshot().playing") == was_playing, "It keeps playing"
    start, end = sections[3]["startBar"] * 4, sections[3]["endBar"] * 4
    page.wait_for_timeout(300)
    beats = page.evaluate(
        """async () => {
          const seen = [];
          const until = performance.now() + 7000;
          while (performance.now() < until) {
            seen.push(window.JUNK.beat());
            await new Promise((done) => setTimeout(done, 60));
          }
          return seen;
        }"""
    )
    assert min(beats) >= start - 0.05 and max(beats) <= end + 0.05, (
        start,
        end,
        min(beats),
        max(beats),
    )
    assert any(b < a for a, b in zip(beats, beats[1:], strict=False)), "It comes back round"
    page.mouse.move(10, 10)
    page.wait_for_timeout(400)
    page.screenshot(path=str(output / "ring-focus.png"), full_page=True)

    # Clicking another section moves there: those sitting out walk off beyond the ring.
    page.mouse.move(*ring_point(page, middle(0)))
    page.mouse.down()
    page.mouse.up()
    page.wait_for_function("id => window.JUNK.layout.focusSection === id", arg=sections[0]["id"])
    absent = [i for i in ids if i in sections[0]["mutedIds"]]
    assert absent, "The intro leaves someone out"
    page.wait_for_function(
        """ids => ids.every((id) => {
          const p = window.JUNK.layout.puppets[id];
          return p.presence === 0 && Math.hypot(p.x / 380, p.y / 230) > 1.06;
        })""",
        arg=absent,
        timeout=30000,
    )
    stayed = [i for i in ids if i not in sections[0]["mutedIds"]]
    assert all(
        page.evaluate("id => window.JUNK.layout.puppets[id].presence", i) == 1 for i in stayed
    )
    waiting = page.evaluate("window.JUNK.layout.puppets")
    assert all(waiting[i]["alpha"] == 1 for i in absent), "Waiting their turn is not greyed out"
    spots = [(waiting[i]["wingX"], waiting[i]["wingY"]) for i in ids]
    assert len({abs(round(x)) for x, _ in spots}) > 1, ("They do not line up", spots)
    assert all(math.dist(a, b) >= 100 for i, a in enumerate(spots) for b in spots[i + 1 :]), spots
    assert {waiting[i]["style"] for i in ids} == {0, 1, 2}, "Three ways of getting about"
    page.mouse.move(10, 10)
    page.wait_for_timeout(400)
    page.screenshot(path=str(output / "ring-intro.png"), full_page=True)

    # In a section, dragging someone off the stage sits them out, and back brings them in.
    page.mouse.move(*ring_point(page, middle(3)))
    page.mouse.down()
    page.mouse.up()
    page.wait_for_function("id => window.JUNK.layout.focusSection === id", arg=sections[3]["id"])
    page.wait_for_function(
        "window.JUNK.layout.puppets[window.JUNK.snapshot().project.performers[1].id].presence === 1",
        timeout=30000,
    )
    extra = ids[1]
    x, y, scale_x, scale_y = performer_point(page, extra)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x - 620 * scale_x, y + 10 * scale_y, steps=10)
    page.mouse.up()
    page.wait_for_function(
        "id => window.JUNK.snapshot().project.sections[3].mutedIds.includes(id)", arg=extra
    )
    page.wait_for_function(
        "id => window.JUNK.layout.puppets[id].presence === 0", arg=extra, timeout=30000
    )
    page.wait_for_function(
        "id => Math.hypot(window.JUNK.layout.puppets[id].x / 380, window.JUNK.layout.puppets[id].y / 230) > 1.06",
        arg=extra,
        timeout=30000,
    )
    position = page.evaluate(
        "id => window.JUNK.snapshot().project.performers.find(p => p.id === id).position", extra
    )
    assert position == next(p["position"] for p in project["performers"] if p["id"] == extra), (
        "Sitting out does not lose their spot"
    )
    page.wait_for_function(
        "id => window.JUNK.snapshot().project.performers.find(p => p.id === id).wing", arg=extra
    )

    # Moving someone around outside the ring makes that their spot, and it is saved.
    def grab_waiting() -> tuple[float, float]:
        layout = page.evaluate("window.JUNK.layout")
        wing = layout["puppets"][extra]
        stage = layout["stage"]
        canvas = page.locator("#canvas").bounding_box()
        assert canvas is not None
        return (
            canvas["x"]
            + (stage["x"] + stage["originX"] + wing["x"] * stage["zoom"])
            * canvas["width"]
            / layout["viewport"]["x"],
            canvas["y"]
            + (stage["y"] + stage["originY"] + (wing["y"] - 50) * stage["zoom"])
            * canvas["height"]
            / layout["viewport"]["y"],
        )

    page.wait_for_function(
        """id => {
          const p = window.JUNK.layout.puppets[id];
          return Math.hypot(p.x - p.wingX, p.y - p.wingY) < 3;
        }""",
        arg=extra,
        timeout=30000,
    )
    page.wait_for_timeout(1200)
    wing_before = page.evaluate(
        "id => window.JUNK.snapshot().project.performers.find(p => p.id === id).wing", extra
    )
    from_x, from_y = grab_waiting()
    page.mouse.move(from_x, from_y)
    page.mouse.down()
    page.mouse.move(from_x + 8, from_y + 90, steps=8)
    page.mouse.up()
    page.wait_for_function(
        """data => {
          const wing = window.JUNK.snapshot().project.performers.find(p => p.id === data.id).wing;
          return wing && Math.abs(wing.y - data.y) > 40;
        }""",
        arg={"id": extra, "y": wing_before["y"]},
    )
    assert page.evaluate(
        "id => window.JUNK.snapshot().project.sections[3].mutedIds.includes(id)", extra
    ), "Moving them around outside does not bring them in"
    page.wait_for_function(
        """id => {
          const p = window.JUNK.layout.puppets[id];
          return Math.hypot(p.x - p.wingX, p.y - p.wingY) < 3;
        }""",
        arg=extra,
        timeout=30000,
    )
    page.wait_for_timeout(1200)
    page.screenshot(path=str(output / "ring-moved-wing.png"), full_page=True)
    from_x, from_y = grab_waiting()
    page.mouse.move(from_x, from_y)
    page.mouse.down()
    box_x, box_y = ring_point(page, 0.5, -90)
    page.mouse.move(box_x, box_y, steps=10)
    page.mouse.up()
    page.wait_for_function(
        "id => !window.JUNK.snapshot().project.sections[3].mutedIds.includes(id)", arg=extra
    )

    # The outer band zooms back out to the whole song, without stopping the music.
    page.wait_for_timeout(500)
    page.mouse.move(*ring_point(page, 0.14, 26))
    page.mouse.down()
    page.mouse.up()
    page.wait_for_function("window.JUNK.layout.focusSection === ''")
    page.wait_for_function("window.JUNK.layout.sectionZoom < 1.01", timeout=30000)
    assert page.evaluate("window.JUNK.snapshot().playing") == was_playing
    page.wait_for_function("b => window.JUNK.beat() > b", arg=end + 0.5, timeout=20000)
    page.screenshot(path=str(output / "ring-whole.png"), full_page=True)


def check_tempo_dial(page: Page, output: Path) -> None:
    layout = page.evaluate("window.JUNK.layout")
    rect = layout["controls"]["bpm"]
    canvas = page.locator("#canvas").bounding_box()
    assert canvas is not None
    ratio_x = canvas["width"] / layout["viewport"]["x"]
    ratio_y = canvas["height"] / layout["viewport"]["y"]
    x = canvas["x"] + (rect["x"] + rect["w"] / 2) * ratio_x
    y = canvas["y"] + (rect["y"] + rect["h"] / 2) * ratio_y
    bpm = page.evaluate("window.JUNK.snapshot().project.bpm")
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 25 * ratio_x, y, steps=5)
    page.wait_for_function("b => window.JUNK.snapshot().project.bpm === b + 10", arg=bpm)
    page.screenshot(path=str(output / "tempo-dragging.png"), full_page=True)
    page.mouse.up()
    # Tempo reaches the band within a beat, not at the end of a bar.
    page.wait_for_function(
        "b => { const f = window.JUNK.snapshot().project.bpm; return f === b + 10; }", arg=bpm
    )
    # A plain click is only a tap, and one tap changes nothing.
    page.mouse.click(x, y)
    page.wait_for_timeout(200)
    assert page.evaluate("window.JUNK.snapshot().project.bpm") == bpm + 10
    # Three even taps set the tempo from their spacing.
    for _ in range(3):
        page.mouse.click(x, y)
        page.wait_for_timeout(450)
    tapped = page.evaluate("window.JUNK.snapshot().project.bpm")
    assert 80 <= tapped <= 160 and tapped != bpm + 10, tapped


def performer(page: Page, performer_id: str) -> dict:
    return page.evaluate(
        "id => window.JUNK.snapshot().project.performers.find(p => p.id === id)", performer_id
    )


def spotlit(page: Page) -> str | None:
    return page.evaluate("import('/modules/audio/browser.js').then(({ audio }) => audio.spotlight)")


def check_rhythm_card_and_notes(page: Page, output: Path) -> None:
    project = page.evaluate("window.JUNK.snapshot().project")
    assert len(project["performers"]) >= 11, "The base band is on stage in a new session"
    assert page.evaluate("Object.keys(window.JUNK.layout.puppets).length") >= 11
    click_performer(page, "p-0")
    click_control(page, "punch")
    page.wait_for_function("window.JUNK.layout.controls.card_gallop.visible")
    # Opening the card brings the band down around this character.
    page.wait_for_timeout(200)
    assert spotlit(page) == "p-0"
    page.wait_for_timeout(1000)
    page.screenshot(path=str(output / "rhythm-card.png"), full_page=True)
    # A ready-made card sets one bar, repeated through the whole song.
    click_control(page, "card_gallop")
    page.wait_for_function(
        """() => {
          const p = window.JUNK.snapshot().project.performers.find(p => p.id === 'p-0');
          return p.steps.length === 8 * 16 && p.steps.slice(0, 8).join() === '0,3,4,7,8,11,12,15';
        }"""
    )
    # Tapping a hole changes it.
    holes = page.evaluate("window.JUNK.layout.controls.holes")
    layout = page.evaluate("window.JUNK.layout")
    canvas = page.locator("#canvas").bounding_box()
    assert canvas is not None
    ratio_x, ratio_y = (
        canvas["width"] / layout["viewport"]["x"],
        canvas["height"] / layout["viewport"]["y"],
    )
    slot = (holes["w"] - 24) / 16
    page.mouse.click(
        canvas["x"] + (holes["x"] + slot * 1.5) * ratio_x,
        canvas["y"] + (holes["y"] + holes["h"] / 2) * ratio_y,
    )
    page.wait_for_function(
        "window.JUNK.snapshot().project.performers.find(p => p.id === 'p-0').steps.includes(1)"
    )
    # Tapping in time teaches a new pattern, and a pause starts over.
    before = performer(page, "p-0")["steps"]
    click_control(page, "tap")
    page.wait_for_function(
        "n => window.JUNK.snapshot().project.performers.find(p => p.id === 'p-0').steps.length !== n",
        arg=len(before),
    )
    assert len(performer(page, "p-0")["steps"]) == 16, "One tap is one hit a bar"
    # Closing the card gives the song back.
    click_control(page, "punch")
    page.wait_for_function("!window.JUNK.layout.controls.card_gallop.visible")
    page.wait_for_timeout(200)
    assert spotlit(page) is None
    click_control(page, "punch")
    page.wait_for_function("window.JUNK.layout.controls.card_gallop.visible")
    page.wait_for_timeout(200)
    assert spotlit(page) == "p-0"
    click_control(page, "card_steady")
    page.wait_for_function(
        "window.JUNK.snapshot().project.performers.find(p => p.id === 'p-0').steps.length === 64"
    )
    # Switching on "height sets its note" is saved on the character.
    assert not performer(page, "p-0").get("tuned")
    click_control(page, "tuned")
    page.wait_for_function(
        "window.JUNK.snapshot().project.performers.find(p => p.id === 'p-0').tuned === true"
    )
    click_control(page, "tuned")
    page.wait_for_function(
        "!window.JUNK.snapshot().project.performers.find(p => p.id === 'p-0').tuned"
    )
    page.keyboard.press("Escape")
    page.wait_for_function("!window.JUNK.layout.inspector")
    # Dragging a tuned character shows the note rows, and its note sounds as it crosses them.
    page.evaluate(
        """async () => {
          const { audio } = await import('/modules/audio/browser.js');
          window.draggedNotes = 0;
          const original = audio.voice.bind(audio);
          audio.voice = (...args) => {
            if (args[6] === undefined && args[8] === undefined) window.draggedNotes += 1;
            return original(...args);
          };
        }"""
    )
    tuned = "p-4"
    assert performer(page, tuned)["tuned"], "The keys start tuned"
    x, y, scale_x, scale_y = performer_point(page, tuned)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x, y - 100 * scale_y, steps=10)
    page.wait_for_timeout(1200)
    page.screenshot(path=str(output / "note-rows.png"), full_page=True)
    page.wait_for_function("window.draggedNotes >= 1", timeout=8000)
    page.mouse.up()
    page.wait_for_timeout(800)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exercise the actual Godot web export and native browser bridge"
    )
    parser.add_argument("--url", default="http://127.0.0.1:5173")
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/godot-browser"))
    parser.add_argument(
        "--autoplay-gesture-only",
        action="store_true",
        help="Check startup under browser gesture restrictions",
    )
    parser.add_argument(
        "--start-server", action="store_true", help="Start and stop an owned mock gateway"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args.output.mkdir(parents=True, exist_ok=True)
    owned_server: subprocess.Popen[bytes] | None = None
    if args.start_server:
        port = urlparse(args.url).port or 5173
        owned_server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "services.gateway.dev_server:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )

        def stop_owned_server() -> None:
            if owned_server is not None and owned_server.poll() is None:
                owned_server.terminate()
                owned_server.wait(timeout=10)

        atexit.register(stop_owned_server)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            check = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys,urllib.request; urllib.request.urlopen(sys.argv[1],timeout=1).close()",
                    f"{args.url}/api/health",
                ],
                capture_output=True,
                check=False,
            )
            if check.returncode == 0:
                break
            if owned_server.poll() is not None:
                raise RuntimeError("The owned mock gateway exited before becoming ready")
            time.sleep(0.1)
        else:
            raise TimeoutError("Mock gateway did not become ready")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=str(args.browser) if args.browser else None,
            args=[
                "--autoplay-policy=document-user-activation-required"
                if args.autoplay_gesture_only
                else "--autoplay-policy=no-user-gesture-required",
                "--use-gl=angle",
                "--use-angle=swiftshader",
                "--enable-webgl",
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            accept_downloads=True,
        )
        page = context.new_page()
        errors: list[str] = []
        messages: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: messages.append(f"{message.type}: {message.text}"))
        page.goto(args.url, wait_until="domcontentloaded")
        page.wait_for_function(
            "window.JUNK?.layout?.controls?.play && document.querySelector('#loading').hidden",
            timeout=60000,
        )
        page.wait_for_timeout(700)
        initial_count = page.evaluate("window.JUNK.snapshot().project.performers.length")
        assert initial_count == 11, initial_count
        if args.autoplay_gesture_only:
            assert page.evaluate("window.JUNK.snapshot().playing"), (
                "The default transport intent must be playing"
            )
            assert page.evaluate("window.JUNK.metrics().hits") == 0, (
                "Restricted audio must wait for a gesture"
            )
            page.mouse.click(12, 12)
            page.wait_for_function(
                "window.JUNK.metrics().hits > 4 && window.JUNK.metrics().voices > 0"
            )
            assert not errors, errors
            logger.info(
                "Autoplay policy check passed: default playing; first gesture unlocks actual audio"
            )
            context.close()
            browser.close()
            return
        page.screenshot(path=str(args.output / "desktop.png"), full_page=True)
        (args.output / "desktop-layout.json").write_text(
            json.dumps(page.evaluate("window.JUNK.layout"), indent=2), encoding="utf-8"
        )
        page.wait_for_function("window.JUNK.snapshot().playing && window.JUNK.metrics().hits > 4")
        assert page.evaluate("window.JUNK.metrics().voices") > 0
        assert page.evaluate("window.JUNK.layout.loopBeats") == 64
        page.wait_for_function(
            "Object.values(JSON.parse(window.JUNK.frame()).pulses).some(pulse=>pulse>0.2)"
        )
        click_control(page, "play")
        page.wait_for_function("!window.JUNK.snapshot().playing")
        click_control(page, "play")
        page.wait_for_function("window.JUNK.snapshot().playing")
        check_ring_sections(page, args.output)
        check_tempo_dial(page, args.output)
        bring_everyone_on(page)
        drag_performer(page, "p-0", 35, 5, args.output)
        page.wait_for_function("!window.JUNK.layout.inspector")
        page.wait_for_function("window.JUNK.layout.landingCount >= 1")
        check_rhythm_card_and_notes(page, args.output)
        click_performer(page, "p-0")
        click_control(page, "duplicate")
        page.wait_for_function(
            "n => window.JUNK.snapshot().project.performers.length === n", arg=initial_count + 1
        )
        page.wait_for_function("!window.JUNK.layout.inspector")
        click_performer(page, "p-0")
        page.screenshot(path=str(args.output / "desktop-inspector.png"), full_page=True)
        click_control(page, "gain", 0.4)
        page.wait_for_function(
            "window.JUNK.snapshot().project.performers.find(p=>p.id===window.JUNK.snapshot().selected).gainDb <= -15"
        )
        drag_performer(page, "p-0", -10, 0)
        page.wait_for_function("!window.JUNK.layout.inspector")
        layout = page.evaluate("window.JUNK.layout")
        orbit = layout["stage"]
        canvas = page.locator("#canvas").bounding_box()
        assert canvas is not None
        ratio_x = canvas["width"] / layout["viewport"]["x"]
        ratio_y = canvas["height"] / layout["viewport"]["y"]
        for index in range(7):
            fraction = 0.25 + index / 16
            angle = fraction * math.tau
            page.mouse.move(
                canvas["x"]
                + (orbit["x"] + orbit["w"] / 2 - math.sin(angle) * 380 * orbit["zoom"]) * ratio_x,
                canvas["y"]
                + (orbit["y"] + orbit["h"] / 2 + (34 - math.cos(angle) * 230) * orbit["zoom"])
                * ratio_y,
            )
            if index == 0:
                page.wait_for_function(
                    "getComputedStyle(document.querySelector('#canvas')).cursor === 'grab'"
                )
                page.mouse.down()
                page.wait_for_function(
                    "getComputedStyle(document.querySelector('#canvas')).cursor === 'grabbing'"
                )
        page.mouse.up()
        page.wait_for_function("!window.JUNK.snapshot().playing")
        page.wait_for_function("Math.abs(window.JUNK.beat() - 40) < 0.1")
        page.keyboard.press("ArrowRight")
        page.wait_for_function("Math.abs(window.JUNK.beat() - 40.25) < 0.1")
        click_performer(page, "p-0")
        click_control(page, "draw_path")
        page.wait_for_function("window.JUNK.layout.pathDrawing")
        x, y, scale_x, scale_y = performer_point(page, "p-0")
        page.mouse.move(x, y)
        page.mouse.down()
        for index in range(1, 25):
            page.mouse.move(x + index * 4 * scale_x, y + math.sin(index / 5) * 40 * scale_y)
        page.mouse.up()
        page.wait_for_function(
            "window.JUNK.snapshot().project.performers.find(p=>p.id==='p-0').path.length > 8 && !window.JUNK.layout.pathDrawing"
        )
        page.keyboard.press("End")
        page.wait_for_function("Math.abs(window.JUNK.beat() - 63.75) < 0.1")
        page.wait_for_timeout(450)
        page.screenshot(path=str(args.output / "motion-return.png"), full_page=True)
        click_performer(page, "p-0")
        click_control(page, "clear_path")
        page.wait_for_function(
            "window.JUNK.snapshot().project.performers.find(p=>p.id==='p-0').path.length === 0"
        )
        click_control(page, "source")
        page.locator(".add-studio").get_by_role("checkbox").check()
        page.evaluate("""async () => {
            const data = new DataTransfer();
            const response = await fetch('/demo-source.mp4');
            data.items.add(new File([await response.blob()], 'owned-tin.mp4', { type: 'video/mp4' }));
            document.querySelector('#canvas').dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: data }));
        }""")
        page.get_by_role("button", name="Next", exact=True).click()
        page.wait_for_function("document.querySelector('.object-stage img')?.naturalWidth > 0")
        area = page.locator(".object-stage .source-preview").bounding_box()
        assert area is not None
        page.mouse.move(area["x"] + area["width"] * 0.2, area["y"] + area["height"] * 0.2)
        page.mouse.down()
        page.mouse.move(area["x"] + area["width"] * 0.7, area["y"] + area["height"] * 0.8, steps=6)
        page.mouse.up()
        page.get_by_label("What do you want to hear?", exact=True).fill("tin clanking")
        page.get_by_role("button", name="Make it", exact=True).click()
        add_to_band = page.get_by_role("button", name="Add to band", exact=True)
        page.wait_for_function(
            "!document.querySelector('.review-phase .primary').disabled", timeout=30000
        )
        add_to_band.click()
        page.wait_for_function(
            "n => window.JUNK.snapshot().project.performers.length === n", arg=initial_count + 2
        )
        page.wait_for_function("window.JUNK.snapshot().saved")
        with page.expect_download() as download:
            click_control(page, "export")
        download.value.save_as(args.output / "godot-mix.wav")
        with page.expect_download() as download:
            click_control(page, "help")
            page.get_by_role("button", name="Save project", exact=True).click()
        download.value.save_as(args.output / "scene.junk.json")
        page.get_by_role("complementary", name="A sampler with a pulse.").get_by_role(
            "button", name="Close", exact=True
        ).click()
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function(
            "window.JUNK?.layout?.controls?.play && document.querySelector('#loading').hidden",
            timeout=60000,
        )
        assert (
            page.evaluate("window.JUNK.snapshot().project.performers.length") == initial_count + 2
        )
        assert any(
            a["provenance"] == "mock candidate"
            for a in page.evaluate("window.JUNK.snapshot().project.assets")
        ), [a["provenance"] for a in page.evaluate("window.JUNK.snapshot().project.assets")]
        page.wait_for_timeout(400)
        page.screenshot(path=str(args.output / "accepted-source.png"), full_page=True)
        metrics = page.evaluate("window.JUNK.metrics()")
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(700)
        mobile = page.evaluate("window.JUNK.layout")
        for name in ("play", "bpm", "export", "scrub", "source", "help"):
            rect = mobile["controls"][name]
            assert rect["x"] >= 0 and rect["x"] + rect["w"] <= mobile["viewport"]["x"] + 1, (
                name,
                rect,
            )
            assert rect["y"] + rect["h"] <= mobile["viewport"]["y"] + 1, (name, rect)
        page.screenshot(path=str(args.output / "mobile.png"), full_page=True)
        click_performer(page, "p-0")
        page.screenshot(path=str(args.output / "mobile-inspector.png"), full_page=True)
        for name in ("gain", "rate", "pan", "delete_performer"):
            rect = page.evaluate("window.JUNK.layout.controls")[name]
            assert rect["visible"] and rect["x"] >= 0 and rect["x"] + rect["w"] <= 391, (
                name,
                rect,
            )
        page.keyboard.press("Escape")
        (args.output / "mobile-layout.json").write_text(
            json.dumps(page.evaluate("window.JUNK.layout"), indent=2), encoding="utf-8"
        )
        (args.output / "browser-log.json").write_text(
            json.dumps({"errors": errors, "console": messages, "metrics": metrics}, indent=2),
            encoding="utf-8",
        )
        assert not errors, errors
        assert not any("SCRIPT ERROR" in message for message in messages), messages
        assert not any("SHADER ERROR" in message for message in messages), messages
        logger.info("Godot browser check passed: %s", metrics)
        context.close()
        portable = browser.new_context(
            viewport={"width": 1440, "height": 1000}, accept_downloads=True
        )
        restored = portable.new_page()
        restored.goto(args.url, wait_until="domcontentloaded")
        restored.wait_for_function(
            "window.JUNK?.layout?.controls?.play && document.querySelector('#loading').hidden",
            timeout=60000,
        )
        assert restored.evaluate("window.JUNK.snapshot().project.performers.length") == 11
        click_control(restored, "help")
        with restored.expect_file_chooser() as chooser:
            restored.get_by_role("button", name="Open project", exact=True).click()
        chooser.value.set_files(args.output / "scene.junk.json")
        restored.wait_for_function(
            "n => window.JUNK.snapshot().project.performers.length === n", arg=initial_count + 2
        )
        restored.get_by_role("complementary", name="A sampler with a pulse.").get_by_role(
            "button", name="Close", exact=True
        ).click()
        if not restored.evaluate("window.JUNK.snapshot().playing"):
            click_control(restored, "play")
        restored.wait_for_function(
            "window.JUNK.snapshot().playing && window.JUNK.metrics().hits > 4"
        )
        click_control(restored, "play")
        restored.wait_for_function("!window.JUNK.snapshot().playing")
        click_control(restored, "help")
        restored.get_by_role("button", name="Check model catalogue").click()
        restored.get_by_text("mock:sam-3.1", exact=False).wait_for()
        restored.get_by_role("button", name="Remove server session media").click()
        restored.wait_for_function(
            "window.JUNK.snapshot().notice.includes('Server session media removed')"
        )
        await_close = restored.get_by_role(
            "complementary", name="A sampler with a pulse."
        ).get_by_role("button", name="Close")
        await_close.click()
        restored.route("**/api/**", lambda route: route.abort())
        click_control(restored, "play")
        restored.wait_for_function(
            "window.JUNK.snapshot().playing && window.JUNK.metrics().voices > 0"
        )
        click_performer(restored, "p-0")
        click_control(restored, "delete_performer")
        restored.wait_for_function(
            "n => window.JUNK.snapshot().project.performers.length === n && !window.JUNK.layout.inspector",
            arg=initial_count + 1,
        )
        portable.close()
        browser.close()
    with wave.open(str(args.output / "godot-mix.wav"), "rb") as wav:
        assert wav.getnchannels() == 2 and wav.getsampwidth() == 2
        duration = wav.getnframes() / wav.getframerate()
        samples = struct.unpack(f"<{wav.getnframes() * 2}h", wav.readframes(wav.getnframes()))
    rms = math.sqrt(sum((sample / 32768) ** 2 for sample in samples) / len(samples))
    peak = max(abs(sample / 32768) for sample in samples)
    assert rms > 0.005 and peak < 0.99
    (args.output / "audio-metrics.json").write_text(
        json.dumps({"duration_s": duration, "rms": rms, "peak": peak}, indent=2),
        encoding="utf-8",
    )
    logger.info("Integrated mix WAV passed: duration=%.4f RMS=%.5f peak=%.5f", duration, rms, peak)
    if owned_server is not None:
        stop_owned_server()


if __name__ == "__main__":
    main()
