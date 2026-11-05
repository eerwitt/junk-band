"""Walk the Add studio against the no-credentials demo gateway.

Provider progress is scripted in the browser to exercise waiting and arrival. No model runs, so
this tests the interaction, not the quality of any cutout, picture or sound.
"""

import argparse
import json
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, Route, expect, sync_playwright

LEVEL = (
    """async () => (await import('/modules/audio/browser.js')).audio.output?.gain.value ?? null"""
)
FITS = """() => {
  const body = document.querySelector('.add-body');
  return body.scrollHeight <= body.clientHeight + 1;
}"""
PAINTED = Path(__file__).resolve().parents[1] / "public/band/kick.png"


def stroke(page: Page, x1: float, y1: float, x2: float, y2: float) -> None:
    preview = page.locator(".object-stage .source-preview")
    preview.scroll_into_view_if_needed()
    box = preview.bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + box["width"] * x1, box["y"] + box["height"] * y1)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * x2, box["y"] + box["height"] * y2, steps=10)
    page.mouse.up()


def open_add(page: Page) -> None:
    """Through the same command the stage's Add button sends, so this runs with or without Godot."""
    page.evaluate("window.JUNK.command(JSON.stringify({ kind: 'source' }))")


def wait_until(page: Page, check: Callable[[], bool], what: str) -> None:
    deadline = time.monotonic() + 10
    while not check():
        assert time.monotonic() < deadline, what
        page.wait_for_timeout(50)


def frame_ready(page: Page) -> None:
    """The brush is enabled only once the new frame has loaded, so painting can start."""
    page.wait_for_function(
        "!document.querySelector('.mask-tools button').disabled"
        " && document.querySelector('.object-stage img').complete"
    )


def no_sideways_scroll(page: Page) -> None:
    assert page.locator(".add-body").evaluate("e => e.scrollWidth <= e.clientWidth + 1"), (
        "Nothing should force sideways scrolling"
    )


def fixture_clips(output: Path) -> dict[str, Path]:
    """A short clip, a long one with a loud burst at 9–11 s, a phone clip, and two odd sources."""
    wide = output / "wide.mp4"
    long = output / "long.mp4"
    tall = output / "rotated-phone.mp4"
    silent = output / "no-sound.mp4"
    recording = output / "recording.wav"
    base = ["ffmpeg", "-v", "error", "-y"]
    video = ["-f", "lavfi", "-i", "testsrc=size=640x360:rate=10:duration=6"]
    tone = ["-f", "lavfi", "-i", "sine=frequency=440:duration=6"]
    subprocess.run(
        [*base, *video, *tone, "-pix_fmt", "yuv420p", "-shortest", str(wide)], check=True
    )
    burst = "sine=frequency=330:duration=16,volume='if(between(t,9,11),1,0.02)':eval=frame"
    subprocess.run(
        [
            *base,
            *["-f", "lavfi", "-i", "testsrc=size=640x360:rate=10:duration=16"],
            *["-f", "lavfi", "-i", burst],
            *["-pix_fmt", "yuv420p", "-shortest", str(long)],
        ],
        check=True,
    )
    subprocess.run(
        [*base, "-display_rotation", "90", "-i", str(wide), "-c", "copy", str(tall)], check=True
    )
    subprocess.run([*base, *video, "-pix_fmt", "yuv420p", str(silent)], check=True)
    subprocess.run([*base, *tone, str(recording)], check=True)
    return {"wide": wide, "long": long, "tall": tall, "silent": silent, "recording": recording}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5182")
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/add-studio-fixture"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    clips = fixture_clips(args.output)
    expect.set_options(timeout=20000)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=str(args.browser) if args.browser else None,
            args=[
                "--use-gl=angle",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        flags: dict[str, Any] = {"sam": True, "image": True, "audio": True}
        calls = {"selections": 0, "separate": 0, "masks": 0, "characters": 0}
        held: dict[str, Any] = {"selection": None, "hold_selection": False}
        sound: dict[str, Any] = {"hold": True}
        art: dict[str, Any] = {"status": "processing"}

        def health(route: Route) -> None:
            response = route.fetch()
            assert response.json()["mode"] == "mock", "Fixtures must never run against providers"
            route.fulfill(response=response, json={**response.json(), "mode": "live", **flags})

        def selection(route: Route) -> None:
            calls["selections"] += 1
            if held["hold_selection"]:
                held["selection"] = route
                return
            answer(route)

        def answer(route: Route) -> None:
            response = route.fetch()
            if response.status != 200:
                route.fulfill(response=response)
                return
            route.fulfill(
                response=response,
                json={**response.json(), "name": "tin", "provenance": "Fixture SAM cutout"},
            )

        def separate(route: Route) -> None:
            calls["separate"] += 1
            route.continue_()

        def job(route: Route) -> None:
            response = route.fetch()
            real = response.json()
            if sound["hold"]:
                real = {
                    **real,
                    "status": "processing",
                    "stage": "separating",
                    "provenance": "SAM Audio",
                    "target_url": None,
                }
            route.fulfill(response=response, json=real)

        def mask(route: Route) -> None:
            calls["masks"] += 1
            route.continue_()

        def character(route: Route) -> None:
            calls["characters"] += 1
            route.fulfill(status=202, json=character_job())

        def character_job() -> dict[str, Any]:
            ready = art["status"] == "ready"
            return {
                "id": "c" * 32,
                "status": art["status"],
                "stage": "ready" if ready else "painting",
                "source_cutout_url": "",
                "character_url": "/assets/painted-fixture.png" if ready else None,
                "error": None,
                "provenance": "Fixture painting, not a model result",
            }

        page.route("**/api/health", health)
        page.route("**/api/selections", selection)
        page.route("**/api/separate", separate)
        page.route("**/api/jobs/*", job)
        page.route("**/api/media/*/mask", mask)
        page.route("**/api/characters", character)
        page.route("**/api/characters/*", lambda route: route.fulfill(json=character_job()))
        page.route(
            "**/api/assets/painted-fixture.png",
            lambda route: route.fulfill(body=PAINTED.read_bytes(), content_type="image/png"),
        )
        page.goto(args.url, wait_until="domcontentloaded")
        page.wait_for_function("window.JUNK?.snapshot", timeout=60000)
        studio = page.locator(".add-studio")
        review = page.locator(".review-phase")
        performers = page.evaluate("window.JUNK.snapshot().project.performers.length")
        level_before = page.evaluate(LEVEL)

        # Rights are asked once: a file chosen before ticking waits, then opens on the tick.
        open_add(page)
        page.wait_for_timeout(1200)
        level_open = page.evaluate(LEVEL)
        if level_before is not None and level_open is not None:
            assert level_open < level_before, "The band fades down while Add is open"
        rights = studio.get_by_role("checkbox")
        expect(rights).to_be_visible()
        studio.locator('input[type="file"]').set_input_files(clips["long"])
        studio.get_by_text("Tick the box above", exact=False).wait_for()
        rights.check()
        clip = page.locator(".clip-phase")
        expect(clip).to_be_visible()

        # The trim is the sound: at most 8 s, starting on the loud part of a long clip.
        handles = clip.locator(".clip-handle")
        page.wait_for_function(
            "Number(document.querySelectorAll('.clip-handle')[0].getAttribute('aria-valuenow')) > 2"
        )
        start = float(handles.nth(0).get_attribute("aria-valuenow") or 0)
        end = float(handles.nth(1).get_attribute("aria-valuenow") or 0)
        assert end - start <= 8.01 and start <= 9.2 and end >= 10.8, (start, end)
        handles.nth(1).focus()
        for _ in range(30):
            page.keyboard.press("ArrowRight")
        end = float(handles.nth(1).get_attribute("aria-valuenow") or 0)
        start = float(handles.nth(0).get_attribute("aria-valuenow") or 0)
        assert end - start <= 8.01, "The end cannot pull the sound past 8 s"
        page.screenshot(path=str(args.output / "clip-desktop.png"))
        clip.get_by_role("button", name="Next", exact=True).click()

        # Make it needs paint and words, and nothing else.
        objects = page.locator(".objects-phase")
        make = objects.get_by_role("button", name="Make it", exact=True)
        frame_ready(page)
        expect(make).to_be_disabled()
        stroke(page, 0.3, 0.3, 0.7, 0.7)
        expect(make).to_be_disabled()
        describe = objects.get_by_label("What do you want to hear?", exact=True)
        describe.fill("the tin clanking")
        expect(make).to_be_enabled()
        page.set_viewport_size({"width": 1366, "height": 768})
        page.wait_for_timeout(200)
        assert page.evaluate(FITS), "Choosing the object fits a laptop screen"
        page.screenshot(path=str(args.output / "object-laptop.png"))
        page.set_viewport_size({"width": 1440, "height": 900})

        # Everything starts at once: the sound does not wait for the cutout.
        held["hold_selection"] = True
        make.click()
        expect(review).to_be_visible()
        page.wait_for_function("() => document.querySelector('.review-sound-stage.waiting')")
        wait_until(
            page,
            lambda: calls["separate"] == 1 and held["selection"] is not None,
            "The sound starts while the cutout is still being made",
        )
        add = review.get_by_role("button", name="Add to band", exact=True)
        expect(add).to_be_disabled()
        original = review.get_by_role("button", name="Original clip", exact=True)
        original.click()
        play = review.get_by_role("button", name="Play", exact=True)
        play.click()
        review.get_by_role("button", name="Pause", exact=True).wait_for()
        expect(add).to_be_disabled()  # Still cutting.
        held["hold_selection"] = False
        answer(held["selection"])
        review.locator(".review-art").wait_for()
        expect(add).to_be_enabled()
        painted = review.get_by_role("button", name="Painted", exact=True)
        expect(painted).to_be_disabled()
        wait_until(page, lambda: calls["characters"] == 1, "Painting starts with the cutout")
        page.screenshot(path=str(args.output / "review-waiting.png"))

        # Back with nothing changed reruns nothing.
        review.get_by_role("button", name="Back", exact=True).click()
        expect(describe).to_have_value("the tin clanking")
        make.click()
        expect(review).to_be_visible()
        assert calls["separate"] == 1 and calls["selections"] == 1, calls

        # Results arrive while the sheet is closed, and leave a note on the stage.
        page.keyboard.press("Escape")
        expect(studio).to_be_hidden()
        art["status"] = "ready"
        page.wait_for_function(
            "window.JUNK.snapshot().notice === 'Your band member is painted. Open Add.'"
        )
        sound["hold"] = False
        open_add(page)
        expect(painted).to_have_attribute("aria-pressed", "true")
        separated = review.get_by_role("button", name="Separated", exact=True)
        expect(separated).to_be_enabled()
        separated.click()
        expect(review.locator(".review-sound-stage")).not_to_have_class(re.compile(r"\bwaiting\b"))
        page.set_viewport_size({"width": 1366, "height": 768})
        page.wait_for_timeout(200)
        assert page.evaluate(FITS), "Listening fits a laptop screen"
        page.screenshot(path=str(args.output / "review-laptop.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(200)
        no_sideways_scroll(page)
        page.screenshot(path=str(args.output / "review-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 900})
        # How it plays is chosen from the sound's length, and explained in a line.
        styles = review.get_by_role("group", name="How it plays")
        expect(styles).to_be_visible()
        expect(review.locator(".review-style-note")).not_to_contain_text("Listening")
        phrase = styles.get_by_role("button", name="Phrase", exact=True)
        phrase.click()
        expect(phrase).to_have_attribute("aria-pressed", "true")
        expect(review.locator(".review-style-note")).to_contain_text("A phrase")
        page.screenshot(path=str(args.output / "review-how-it-plays.png"))
        add.click()
        expect(studio).to_be_hidden()
        page.wait_for_function(
            "n => window.JUNK.snapshot().project.performers.length === n", arg=performers + 1
        )
        asset = page.evaluate("window.JUNK.snapshot().project.assets.at(-1)")
        assert asset["label"] == "tin", asset["label"]
        assert asset["provenance"] == "mock candidate", asset["provenance"]
        assert asset["visualProvenance"] == "Fixture painting, not a model result"
        assert asset["sourceSprite"] != asset["sprite"], "The plain cutout is kept too"
        # The quiet ends are trimmed, and what is left is measured.
        assert 0 < asset["lengthS"] <= 8.01, asset.get("lengthS")
        assert abs(asset["endS"] - asset["startS"] - asset["lengthS"]) < 0.01
        joined = page.evaluate("window.JUNK.snapshot().project.performers.at(-1)")
        assert joined["mode"] == "phrase" and joined["cardBars"] in (1, 2, 4, 8), joined

        # Rights are remembered; a phone video keeps its upright shape.
        open_add(page)
        expect(rights).to_be_hidden()
        studio.locator('input[type="file"]').set_input_files(clips["tall"])
        expect(clip).to_be_visible()
        clip.get_by_role("button", name="Next", exact=True).click()
        page.wait_for_function(
            "(img => img.naturalHeight > img.naturalWidth)(document.querySelector('.object-stage img'))"
        )
        shape = page.locator(".object-stage .source-preview").bounding_box()
        assert shape and shape["height"] > shape["width"], shape
        page.keyboard.press("Escape")

        # A source with no sound is refused before anything else.
        open_add(page)
        studio.locator('input[type="file"]').set_input_files(clips["silent"])
        studio.get_by_text("This source has no audio", exact=False).wait_for()

        # A recording has no picture: only words, then only its sound.
        sound["hold"] = False
        studio.locator('input[type="file"]').set_input_files(clips["recording"])
        expect(clip).to_be_visible()
        clip.get_by_role("button", name="Next", exact=True).click()
        expect(page.locator(".object-stage")).to_be_hidden()
        describe.fill("a steady hum")
        make.click()
        expect(review.locator(".review-look")).to_be_hidden()
        review.get_by_role("button", name="Separated", exact=True).wait_for()
        expect(add).to_be_enabled()
        add.click()
        page.wait_for_function(
            "n => window.JUNK.snapshot().project.performers.length === n", arg=performers + 2
        )
        asset = page.evaluate("window.JUNK.snapshot().project.assets.at(-1)")
        assert asset["label"] == "a steady hum" and "sourceSprite" not in asset, asset

        # No providers: the painting is the cutout and the original clip is the sound.
        flags.update(sam=False, image=False, audio=False)
        before = dict(calls)
        open_add(page)
        studio.locator('input[type="file"]').set_input_files(clips["wide"])
        expect(clip).to_be_visible()
        clip.get_by_role("button", name="Next", exact=True).click()
        frame_ready(page)
        stroke(page, 0.3, 0.3, 0.7, 0.7)
        describe.fill("tin")
        make.click()
        review.locator(".review-art").wait_for()
        assert calls["selections"] == before["selections"], "With no AI, no selection request"
        assert calls["masks"] == before["masks"] + 1, "The painted mask makes the cutout"
        assert calls["separate"] == before["separate"], "No separation request"
        expect(original).to_have_attribute("aria-pressed", "true")
        expect(review.get_by_role("button", name="Separated", exact=True)).to_be_disabled()
        review.get_by_text("Sound separation is unavailable", exact=False).wait_for()
        add.click()
        page.wait_for_function(
            "n => window.JUNK.snapshot().project.performers.length === n", arg=performers + 3
        )
        asset = page.evaluate("window.JUNK.snapshot().project.assets.at(-1)")
        assert asset["provenance"] == "raw import"
        assert "Hand-drawn mask" in asset["visualProvenance"], asset["visualProvenance"]

        assert not errors, errors
        (args.output / "summary.json").write_text(
            json.dumps(
                {
                    "provider_fixture": True,
                    "live_inference": False,
                    "rights_asked_once": True,
                    "trim_is_the_sound": True,
                    "sound_starts_with_make_it": True,
                    "back_reruns_nothing_unchanged": True,
                    "results_reach_a_closed_sheet": True,
                    "rotated_video": True,
                    "recording_without_picture": True,
                    "provider_unavailable_paths": True,
                    "errors": errors,
                },
                indent=2,
            )
        )
        browser.close()
    print("Add studio fixtures passed: trim, paint, describe, review and every fallback")


if __name__ == "__main__":
    main()
