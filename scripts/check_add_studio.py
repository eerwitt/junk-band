"""Walk the full-screen Add studio against the no-credentials demo gateway.

Provider progress is scripted in the browser to exercise waiting and arrival. No model runs, so
this tests the interaction, not the quality of any cutout, picture or sound.
"""

import argparse
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any

from check_godot_browser import click_control
from playwright.sync_api import Locator, Page, Route, expect, sync_playwright


def _centre(locator: Locator) -> tuple[float, float]:
    box = locator.bounding_box()
    assert box is not None
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


LEVEL = """async () => (await import('/modules/audio/browser.js')).audio.output.gain.value"""
FITS = """() => {
  const body = document.querySelector('.add-body');
  return body.scrollHeight <= body.clientHeight + 1;
}"""
WASHED = """(x, y) => {
  const c = [...document.querySelectorAll('.mask-overlay')].find(n => n.isConnected);
  return c.getContext('2d').getImageData(c.width * x, c.height * y, 1, 1).data[3] > 0;
}"""
ANIMATION_KEPT = """() => {
  const node = document.querySelector('.finish-phase .wait-wave-in');
  if (!window.__waveNode) {
    window.__waveNode = node;
    window.__waveStart = node.getAnimations()[0].startTime;
    return true;
  }
  return node === window.__waveNode && node.getAnimations()[0].startTime === window.__waveStart;
}"""


def stroke(page: Page, x1: float, y1: float, x2: float, y2: float) -> None:
    preview = page.locator(".object-stage .source-preview")
    preview.scroll_into_view_if_needed()
    box = preview.bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + box["width"] * x1, box["y"] + box["height"] * y1)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * x2, box["y"] + box["height"] * y2, steps=10)
    page.mouse.up()


def no_sideways_scroll(page: Page) -> None:
    assert page.locator(".add-body").evaluate("e => e.scrollWidth <= e.clientWidth + 1"), (
        "Nothing should force sideways scrolling"
    )


def fixture_clips(output: Path) -> dict[str, Path]:
    wide = output / "wide.mp4"
    tall = output / "rotated-phone.mp4"
    silent = output / "no-sound.mp4"
    recording = output / "recording.wav"
    video = ["-f", "lavfi", "-i", "testsrc=size=640x360:rate=10:duration=6"]
    tone = ["-f", "lavfi", "-i", "sine=frequency=440:duration=6"]
    base = ["ffmpeg", "-v", "error", "-y"]
    subprocess.run(
        [*base, *video, *tone, "-pix_fmt", "yuv420p", "-shortest", str(wide)], check=True
    )
    subprocess.run(
        [*base, "-display_rotation", "90", "-i", str(wide), "-c", "copy", str(tall)], check=True
    )
    subprocess.run([*base, *video, "-pix_fmt", "yuv420p", str(silent)], check=True)
    subprocess.run([*base, *tone, str(recording)], check=True)
    return {"wide": wide, "tall": tall, "silent": silent, "recording": recording}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5182")
    parser.add_argument("--output", type=Path, default=Path("artifacts/add-studio-fixture"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    clips = fixture_clips(args.output)
    expect.set_options(timeout=20000)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
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
        flags: dict[str, Any] = {"sam": True, "image": True, "audio": True, "wonder": True}
        calls: dict[str, Any] = {"selections": 0}
        held: dict[str, Any] = {"selection": False, "pending": None}
        sound: dict[str, Any] = {"hold": True, "stage": "separating", "lose": False}
        art: dict[str, Any] = {"status": "processing", "stage": "painting", "cutout": ""}

        def health(route: Route) -> None:
            response = route.fetch()
            assert response.json()["mode"] == "mock", "Fixtures must never run against providers"
            route.fulfill(response=response, json={"mode": "live", **flags})

        def selection_route(route: Route) -> None:
            calls["selections"] += 1
            if held["selection"]:
                held["pending"] = route
                return
            response = route.fetch()
            if response.status != 200:
                route.fulfill(response=response)
                return
            # A section shorter than the clip, so the Finish preview has something to stay inside.
            route.fulfill(
                response=response,
                json={
                    **response.json(),
                    "name": "tin",
                    "sound": "tin clanks",
                    "sound_start_s": 1.0,
                    "sound_end_s": 3.0,
                },
            )

        def job_route(route: Route) -> None:
            if sound["lose"]:
                route.abort()
                return
            response = route.fetch()
            real = response.json()
            if sound["hold"]:
                route.fulfill(
                    json={
                        **real,
                        "status": "processing",
                        "stage": sound["stage"],
                        "queue_position": sound.get("ahead", 0),
                        "provenance": "SAM Audio",
                        "target_url": None,
                        "residual_url": None,
                    }
                )
            else:
                route.fulfill(response=response)

        def character_route(route: Route) -> None:
            if route.request.method == "POST":
                body = route.request.post_data_json
                assert body is not None
                art["cutout"] = body["cutout_id"]
            ready = art["status"] == "ready"
            route.fulfill(
                status=202 if route.request.method == "POST" else 200,
                json={
                    "id": "c" * 32,
                    "status": art["status"],
                    "stage": "ready" if ready else art["stage"],
                    "source_cutout_url": f"/assets/{art['cutout']}-cutout.png",
                    "character_url": f"/assets/{art['cutout']}-cutout.png" if ready else None,
                    "error": None,
                    "provenance": "Browser fixture · no Meta generation",
                },
            )

        page.route("**/api/health", health)
        page.route("**/api/selections", selection_route)
        page.route("**/api/jobs/*", job_route)
        page.route("**/api/characters", character_route)
        page.route("**/api/characters/*", character_route)
        page.goto(args.url, wait_until="domcontentloaded")
        page.wait_for_function(
            "window.JUNK?.layout?.controls?.play && document.querySelector('#loading').hidden",
            timeout=60000,
        )
        performers = page.evaluate("window.JUNK.snapshot().project.performers.length")

        # Bring it in: Add takes the whole window, and the band ducks.
        click_control(page, "source")
        studio = page.locator(".add-studio")
        expect(studio).to_be_visible()
        box = studio.bounding_box()
        assert box and box["width"] < 1440 and box["height"] < 900, "The stage shows around it"
        assert 900 < box["width"] <= 1040, "A contained work area, not the whole window"
        # The fade is real and gradual: partway down soon after opening, then nearly silent.
        page.evaluate(
            "async () => { const {audio} = await import('/modules/audio/browser.js'); await audio.unlock(); }"
        )
        page.wait_for_timeout(2500)
        assert page.evaluate(LEVEL) < 0.08, "The band fades right down"
        assert page.evaluate(
            "async () => (await import('/modules/audio/browser.js')).audio.ducked === true"
        )
        step = page.locator('.add-step[aria-current="step"]')
        expect(step).to_have_text("Bring it in")
        later = page.get_by_role("button", name="Finish", exact=True)
        expect(later).to_be_disabled()
        expect(later).to_have_attribute("title", "Finish the earlier steps first.")
        page.screenshot(path=str(args.output / "bring-desktop.png"))

        # A source with no sound cannot go further, and says so.
        page.get_by_label("I own this media or have permission to use it", exact=True).check()
        page.locator('.add-studio input[type="file"]').set_input_files(clips["silent"])
        page.get_by_text("This source has no audio.", exact=False).wait_for()
        expect(step).to_have_text("Bring it in")

        # Pick the moment: filmstrip, handles, keyboard.
        page.locator('.add-studio input[type="file"]').set_input_files(clips["wide"])
        expect(step).to_have_text("Pick the moment")
        strip = page.locator(".clip-strip")
        expect(page.locator(".film-kept .film-stock")).to_have_css(
            "background-image", re.compile("filmstrip")
        )
        with page.expect_response(
            lambda r: "/filmstrip" in r.url and r.status == 200, timeout=20000
        ):
            page.evaluate(
                "() => { const u = document.querySelector('.clip-strip').style.getPropertyValue('--frames'); const i = new Image(); i.src = u.slice(5, -2) + '&probe=1'; }"
            )
        # The picture is shown true, as a cardboard card with a kraft edge and a cast shadow.
        film_video = page.locator(".card-face video")
        assert film_video.evaluate("v => getComputedStyle(v).filter") == "none"
        assert not film_video.evaluate("v => v.controls")
        assert page.locator(".film-grain, .film-wear, .film-flicker, .rolling").count() == 0
        face_box = page.locator(".card-face").bounding_box()
        edge_box = page.locator(".card-edge").bounding_box()
        assert face_box and edge_box
        assert edge_box["x"] + edge_box["width"] > face_box["x"] + face_box["width"], "Edge shows"
        assert page.locator(".film-kept").evaluate(
            "n => !getComputedStyle(n).filter.includes('sepia')"
        ), "The kept frames keep their true colours too"
        page.get_by_role("button", name="Play", exact=True).click()
        page.get_by_role("button", name="Pause", exact=True).wait_for()
        page.wait_for_timeout(200)
        page.screenshot(path=str(args.output / "video-card.png"))
        page.get_by_role("button", name="Pause", exact=True).click()
        page.get_by_role("button", name="Play", exact=True).wait_for()
        page.get_by_role("button", name="Sound on", exact=True).click()
        assert film_video.evaluate("v => v.muted")
        page.get_by_role("button", name="Sound off", exact=True).click()
        part = page.get_by_role("button", name="Use this part", exact=True)
        expect(part).to_be_disabled()
        expect(part).to_have_attribute("title", re.compile("Drag the handles"))
        strip_box = strip.bounding_box()
        assert strip_box is not None
        assert strip_box["width"] > box["width"] * 0.9, "The strip spans the sheet"
        handle = page.get_by_role("slider", name="Start of the part to keep")
        handle_box = handle.bounding_box()
        assert handle_box is not None
        page.mouse.move(handle_box["x"] + 7, handle_box["y"] + 40)
        page.mouse.down()
        page.mouse.move(strip_box["x"] + strip_box["width"] * 0.25, handle_box["y"] + 40, steps=6)
        page.mouse.up()
        expect(page.locator(".clip-readout")).to_contain_text("0:01.")
        expect(part).to_be_enabled()
        # Letting go snips: the scissors come through, then the offcut drops behind, greyed.
        expect(page.locator(".film-snip.snipping")).to_have_count(1)
        page.wait_for_timeout(180)
        page.screenshot(path=str(args.output / "snip-during.png"))
        expect(strip).to_have_class(re.compile("cut-start"))
        assert "grayscale" in page.locator(".film-before").evaluate(
            "n => getComputedStyle(n).filter"
        )
        page.wait_for_timeout(450)
        expect(page.locator(".film-snip.snipping")).to_have_count(0)
        # The offcut is still there to re-edit: dragging over it heals, letting go at the end stays whole.
        cut_box = handle.bounding_box()
        assert cut_box is not None
        page.mouse.move(cut_box["x"] + 7, cut_box["y"] + 40)
        page.mouse.down()
        page.mouse.move(strip_box["x"] - 40, cut_box["y"] + 40, steps=6)
        expect(strip).not_to_have_class(re.compile("cut-start"))
        page.mouse.up()
        page.wait_for_timeout(400)
        expect(strip).not_to_have_class(re.compile("cut-start"))
        expect(part).to_be_disabled()
        # Trim both ends, then slide the kept piece along the film at the same length.
        page.mouse.move(strip_box["x"] + 7, cut_box["y"] + 40)
        page.mouse.down()
        page.mouse.move(strip_box["x"] + strip_box["width"] * 0.1, cut_box["y"] + 40, steps=6)
        page.mouse.up()
        end_handle = page.get_by_role("slider", name="End of the part to keep")
        end_box = end_handle.bounding_box()
        assert end_box is not None
        page.mouse.move(end_box["x"] + 7, end_box["y"] + 40)
        page.mouse.down()
        page.mouse.move(strip_box["x"] + strip_box["width"] * 0.6, end_box["y"] + 40, steps=6)
        page.mouse.up()
        page.wait_for_timeout(600)
        readout = page.locator(".clip-readout")
        length = (readout.text_content() or "").split("·")[1]
        slid_from = readout.text_content()
        window_box = page.get_by_role("slider", name="Part to keep", exact=True).bounding_box()
        assert window_box is not None
        middle = window_box["x"] + window_box["width"] / 2
        page.mouse.move(middle, window_box["y"] + 30)
        page.mouse.down()
        page.mouse.move(middle + strip_box["width"] * 0.2, window_box["y"] + 30, steps=8)
        page.wait_for_timeout(100)
        page.mouse.up()
        expect(readout).not_to_have_text(slid_from or "")
        assert (readout.text_content() or "").split("·")[1] == length, "Sliding keeps its length"
        page.wait_for_timeout(600)
        expect(strip).to_have_class(re.compile("cut-start"))
        expect(strip).to_have_class(re.compile("cut-end"))
        page.screenshot(path=str(args.output / "strip-cut.png"))
        # Sliding cannot run off the end of the film.
        window_box = page.get_by_role("slider", name="Part to keep", exact=True).bounding_box()
        assert window_box is not None
        middle = window_box["x"] + window_box["width"] / 2
        page.mouse.move(middle, window_box["y"] + 30)
        page.mouse.down()
        page.mouse.move(strip_box["x"] + strip_box["width"] + 300, window_box["y"] + 30, steps=8)
        page.mouse.up()
        assert (readout.text_content() or "").split("·")[1] == length
        assert "to 0:06" in (readout.text_content() or "") or "to 0:05.9" in (
            readout.text_content() or ""
        ), readout.text_content()
        # Back to a known place for the keyboard checks below.
        page.mouse.move(*_centre(page.get_by_role("slider", name="Part to keep", exact=True)))
        page.mouse.down()
        page.mouse.move(strip_box["x"] - 300, window_box["y"] + 30, steps=8)
        page.mouse.up()
        page.wait_for_timeout(600)
        before = page.locator(".clip-readout").text_content()
        handle.focus()
        page.keyboard.press("ArrowRight")
        expect(page.locator(".clip-readout")).not_to_have_text(before or "")
        # Handles cannot get closer than the shortest usable sound.
        page.mouse.move(handle_box["x"] + 7, handle_box["y"] + 40)
        end = page.get_by_role("slider", name="End of the part to keep")
        end.focus()
        for _ in range(60):
            page.keyboard.press("ArrowLeft")
        assert "2.0 s" in (page.locator(".clip-readout").text_content() or "")
        page.wait_for_timeout(300)
        page.screenshot(path=str(args.output / "moment-desktop.png"))
        page.set_viewport_size({"width": 1366, "height": 768})
        page.wait_for_timeout(300)
        assert page.evaluate(FITS), "Choosing a moment fits a laptop screen without scrolling"
        page.screenshot(path=str(args.output / "moment-laptop.png"))
        page.set_viewport_size({"width": 1440, "height": 900})
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(200)
        page.screenshot(path=str(args.output / "moment-mobile.png"))
        no_sideways_scroll(page)
        page.set_viewport_size({"width": 1440, "height": 900})

        # Choose the object: pick a frame on the film, paint, say what it is, cut it out.
        page.get_by_role("button", name="Use entire video", exact=True).click()
        expect(step).to_have_text("Choose the object")
        use = page.get_by_role("button", name="Use this one", exact=True, include_hidden=True)
        cut = page.get_by_role("button", name="Cut it out", exact=True, include_hidden=True)
        expect(use).to_be_disabled()
        expect(use).to_have_attribute("title", "Cut something out first.")
        expect(cut).to_have_attribute("title", "Paint over your thing first.")
        page.wait_for_function("document.querySelector('.object-stage img')?.naturalWidth > 0")
        tools = page.locator(".mask-tools")
        expect(tools.get_by_role("button", name="Select", exact=True)).to_have_count(0)
        expect(tools.get_by_role("button", name="Use this mask", exact=True)).to_be_hidden()
        expect(page.locator(".paint-hint")).to_be_visible()
        film = page.locator(".frame-strip")
        expect(film.locator(".frame-picked")).to_have_css(
            "background-image", re.compile("filmstrip.*start_s")
        )
        assert "grayscale" in film.locator(".frame-all").evaluate("n => getComputedStyle(n).filter")
        steps = page.locator(".make-step")
        expect(steps.nth(1)).to_have_attribute("data-state", "active")
        expect(steps.nth(2)).to_have_attribute("data-state", "todo")
        page.wait_for_timeout(500)
        assert calls["selections"] == 0, "No paid request before a selection"
        page.screenshot(path=str(args.output / "objects-empty-desktop.png"))

        # Painting makes the base mask, and costs nothing until it is cut.
        stroke(page, 0.15, 0.1, 0.85, 0.9)
        expect(page.locator(".paint-hint")).to_be_hidden()
        expect(steps.nth(1)).to_have_attribute("data-state", "done")
        expect(steps.nth(2)).to_have_attribute("data-state", "active")
        expect(cut).to_be_enabled()
        page.wait_for_timeout(300)
        assert calls["selections"] == 0, "Painting alone sends nothing"
        page.screenshot(path=str(args.output / "objects-painted-desktop.png"))

        held["selection"] = True
        cut.click()
        wait_line = page.locator(".objects-phase .wait-line")
        expect(wait_line).to_have_text("Working out what you painted…")
        page.wait_for_function(
            "document.querySelector('.objects-phase .wait-object')?.src?.startsWith('data:image/png')"
        )
        page.wait_for_timeout(350)
        page.screenshot(path=str(args.output / "looking-desktop.png"))
        held["selection"] = False
        pending = held["pending"]
        pending.fulfill(
            response=(answered := pending.fetch()),
            json={
                **answered.json(),
                "name": "tin",
                "sound": "tin clanks",
                "sound_start_s": 1.0,
                "sound_end_s": 3.0,
            },
        )
        cards = page.locator(".object-sprites .sprite-card")
        expect(cards).to_have_count(1)
        assert calls["selections"] == 1, "One cut is one selection"
        expect(wait_line).to_be_hidden()
        expect(cards.nth(0)).to_have_attribute("aria-pressed", "true")
        expect(page.get_by_label("Sound to pull", exact=True).first).to_have_value("tin clanks")
        expect(page.get_by_label("What is it?", exact=True).first).to_have_value("tin")
        expect(steps.nth(3).locator(".make-title")).to_have_text("Got it: tin!")
        expect(use).to_be_enabled()
        page.wait_for_function(f"({WASHED})(0.02, 0.02)")
        assert not page.evaluate(f"({WASHED})(0.5, 0.5)"), "Inside the selected mask stays clear"
        page.wait_for_timeout(350)
        page.screenshot(path=str(args.output / "objects-desktop.png"))
        page.set_viewport_size({"width": 1366, "height": 768})
        page.wait_for_timeout(300)
        assert page.evaluate(FITS), "Choosing an object fits a laptop screen without scrolling"
        page.screenshot(path=str(args.output / "objects-laptop.png"))
        page.set_viewport_size({"width": 1440, "height": 900})

        # Another frame on the film starts a new painting; choosing between results costs nothing.
        finder = page.get_by_role("slider", name="Picture moment", exact=True)
        before_frame = finder.get_attribute("aria-valuenow")
        film_box = film.bounding_box()
        assert film_box is not None
        page.mouse.click(film_box["x"] + film_box["width"] * 0.2, film_box["y"] + 30)
        expect(finder).not_to_have_attribute("aria-valuenow", before_frame or "")
        expect(use).to_be_disabled()
        page.wait_for_timeout(600)
        page.wait_for_function(
            "document.querySelector('.object-stage img').complete && document.querySelector('.object-stage img').naturalWidth > 0"
        )
        stroke(page, 0.2, 0.2, 0.7, 0.7)
        page.get_by_label("What is it?", exact=True).first.fill("red tin")
        cut.click()
        expect(cards).to_have_count(2)
        made = calls["selections"]
        cards.nth(0).click()
        expect(cards.nth(0)).to_have_attribute("aria-pressed", "true")
        page.wait_for_timeout(300)
        assert calls["selections"] == made

        # Editing the mask blocks moving on until it is applied or undone.
        apply = tools.get_by_role("button", name="Use this mask", exact=True)
        undo = tools.get_by_role("button", name="Undo", exact=True)
        expect(apply).to_be_visible()
        expect(apply).to_have_attribute("title", "Paint or erase something first.")
        expect(undo).to_have_attribute("title", "Nothing to undo yet.")
        tools.get_by_role("button", name="Erase", exact=True).click()
        stroke(page, 0.35, 0.5, 0.65, 0.5)
        assert page.evaluate(f"({WASHED})(0.5, 0.5)"), "Erasing washes that area back"
        expect(use).to_be_disabled()
        expect(use).to_have_attribute("title", re.compile("Use this mask"))
        page.get_by_text("Changed. Choose Use this mask to keep it.", exact=True).wait_for()
        undo.click()
        assert not page.evaluate(f"({WASHED})(0.5, 0.5)"), "Undo restores it"
        expect(use).to_be_enabled()
        tools.get_by_role("button", name="Paint", exact=True).click()
        stroke(page, 0.02, 0.05, 0.1, 0.05)
        assert not page.evaluate(f"({WASHED})(0.05, 0.05)"), "Painting reveals the object"
        apply.click()
        expect(cards).to_have_count(2)
        expect(apply).to_have_attribute("title", "Paint or erase something first.")
        expect(use).to_be_enabled()

        # Different words on the same painting cut again.
        made = calls["selections"]
        page.get_by_label("What is it?", exact=True).first.fill("blue tin")
        cut.click()
        expect(page.locator(".objects-phase .wait-line")).to_be_hidden()
        expect(use).to_be_enabled()
        assert calls["selections"] == made + 1
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(200)
        page.locator(".object-sprites").scroll_into_view_if_needed()
        page.screenshot(path=str(args.output / "objects-mobile.png"))
        no_sideways_scroll(page)
        page.set_viewport_size({"width": 1440, "height": 900})

        # Finish: sound and painting run at the same time.
        page.get_by_label("Sound to pull", exact=True).first.fill("tin clanks")
        use.click()
        expect(step).to_have_text("Finish")
        finish = page.locator(".finish-phase")
        add = finish.get_by_role("button", name=re.compile("Add "))
        sound_wait = finish.locator(".finish-column").nth(0).locator(".wait-line")
        look_wait = finish.locator(".finish-column").nth(1).locator(".wait-line")
        expect(sound_wait).to_contain_text("Snipping “tin clanks”")
        # Waiting behind other people's requests says so.
        sound["ahead"] = 2
        expect(sound_wait).to_have_text("2 requests ahead of you in the queue…")
        sound["ahead"] = 1
        expect(sound_wait).to_have_text("One request ahead of you in the queue…")
        sound["ahead"] = 0
        expect(sound_wait).to_contain_text("Snipping “tin clanks”")
        expect(look_wait).to_have_text("Painting your object in cut paper…")
        expect(add).to_be_disabled()
        expect(add).to_have_attribute("title", "Its sound is still being separated.")
        expect(add).to_have_text("Add as is")
        assert finish.locator(".finish-preview video").count() == 1
        # The preview is only the section in use: no way to reach the rest, and it loops inside it.
        preview = finish.locator(".finish-preview video")
        assert not preview.evaluate("v => v.controls"), "No timeline onto the whole video"
        assert finish.locator(".finish-preview .card-edge").count() == 1
        expect(finish.locator(".preview-time")).to_have_text(re.compile(r"^0\.0 / [\d.]+ s$"))
        section = float(
            (finish.locator(".preview-time").text_content() or "").split("/")[1].split()[0]
        )
        start = float(preview.evaluate("v => v.src.split('#t=')[1]"))
        page.wait_for_function(
            "document.querySelector('.finish-preview video').readyState >= 1", timeout=15000
        )
        whole = preview.evaluate("v => v.duration")
        assert section < whole, f"The section should be shorter: {section} of {whole}"
        page.evaluate("v => v.muted = true", preview.element_handle())
        finish.locator(".preview-controls button").click()
        expect(finish.locator(".preview-controls button")).to_have_text("Pause")
        seen = page.evaluate(
            """async () => {
              const v = document.querySelector('.finish-preview video');
              const times = [];
              const until = performance.now() + (v.duration + 1) * 1000;
              while (performance.now() < until) {
                times.push(v.currentTime);
                await new Promise((done) => setTimeout(done, 40));
              }
              return times;
            }"""
        )
        assert min(seen) >= start - 0.05, (start, min(seen))
        assert max(seen) <= start + section + 0.1, (start, section, max(seen))
        assert any(b < a for a, b in zip(seen, seen[1:], strict=False)), (
            "It loops back to the start"
        )
        finish.locator(".preview-controls button").click()
        expect(finish.locator(".preview-controls button")).to_have_text("Play")
        page.wait_for_function("document.querySelector('.finish-phase .wait-wave-in')")
        page.wait_for_timeout(350)
        assert page.evaluate(ANIMATION_KEPT)
        page.wait_for_timeout(1800)
        assert page.evaluate(ANIMATION_KEPT), "Polling must not restart the animation"
        page.screenshot(path=str(args.output / "finish-waiting-desktop.png"))

        # A missed check does not end a long job.
        sound["lose"] = True
        page.wait_for_timeout(1500)
        expect(sound_wait).to_be_visible()
        assert finish.get_by_text("Status check failed", exact=False).count() == 0
        sound["lose"] = False

        art["stage"] = "cutting"
        expect(look_wait).to_have_text("Cutting around the new picture…")

        # Sound ready first: only one audio player, and it can be added before painting ends.
        sound["hold"] = False
        finish.get_by_label("Target", exact=True).wait_for()
        assert finish.locator("audio").count() == 1, "Only the target; the video is the reference"
        expect(add).to_be_enabled()
        expect(add).to_have_text("Add as is")
        expect(look_wait).to_be_visible()

        # Painting arrives: the painted look is chosen, and either look can be picked.
        art["status"] = "ready"
        painted = finish.get_by_role("button", name="Use painted", exact=True)
        original = finish.get_by_role("button", name="Use as is", exact=True)
        painted.wait_for()
        expect(painted).to_have_attribute("aria-pressed", "true")
        expect(add).to_have_text("Add to band")
        expect(look_wait).to_be_hidden()
        page.wait_for_timeout(350)
        page.screenshot(path=str(args.output / "finish-ready-desktop.png"))
        page.set_viewport_size({"width": 1366, "height": 768})
        page.wait_for_timeout(300)
        assert page.evaluate(FITS), "Finishing fits a laptop screen without scrolling"
        page.screenshot(path=str(args.output / "finish-laptop.png"))
        page.set_viewport_size({"width": 1440, "height": 900})
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(200)
        page.screenshot(path=str(args.output / "finish-ready-mobile.png"))
        no_sideways_scroll(page)
        page.set_viewport_size({"width": 1440, "height": 900})
        original.click()
        expect(original).to_have_attribute("aria-pressed", "true")
        painted.click()

        # Adding closes the studio, restores the band and adds the performer.
        add.click()
        expect(studio).to_be_hidden()
        page.wait_for_function(
            "n => window.JUNK.snapshot().project.performers.length === n", arg=performers + 1
        )
        assert page.evaluate(
            "async () => (await import('/modules/audio/browser.js')).audio.ducked === false"
        )
        page.wait_for_timeout(2500)
        assert page.evaluate(LEVEL) > 0.9, "The band comes back up"
        # The fade's shape, timed on the audio clock, because the page can be too busy to watch it.
        fade = page.evaluate(
            """async () => {
              const { audio } = await import('/modules/audio/browser.js');
              audio.setDucked(true);
              await new Promise((done) => setTimeout(done, 2500));
              const start = audio.context.currentTime;
              const from = audio.output.gain.value;
              audio.setDucked(false);
              const samples = [];
              while (audio.context.currentTime - start < 1.5) {
                samples.push([audio.context.currentTime - start, audio.output.gain.value]);
                await new Promise((done) => setTimeout(done, 20));
              }
              return { from, samples };
            }"""
        )
        assert fade["from"] < 0.1, ("The band was right down", fade["from"])
        for elapsed, level in fade["samples"]:
            expected = 1 - (1 - fade["from"]) * math.exp(-elapsed / 0.3)
            assert abs(level - expected) < 0.12, ("It fades, not jumps", elapsed, level, expected)
        assert any(s[0] < 0.6 and s[1] < 0.9 for s in fade["samples"]), fade["samples"][:10]
        asset = page.evaluate("window.JUNK.snapshot().project.assets.at(-1)")
        assert asset["label"] == "tin"
        assert "fixture" in asset["visualProvenance"]

        # A job that ends after closing leaves a note on the stage.
        click_control(page, "source")
        art.update(status="processing", stage="painting")
        sound["hold"] = True
        page.locator('.add-studio input[type="file"]').set_input_files(clips["tall"])
        expect(step).to_have_text("Pick the moment")
        # Rotated phone video: a tall picture and a round brush.
        page.get_by_role("button", name="Use entire video", exact=True).click()
        page.wait_for_function(
            "(() => { const c = document.querySelector('.object-stage .mask-overlay'); return c.height > c.width; })()"
        )
        shape = page.evaluate(
            """() => {
              const c = document.querySelector('.object-stage .mask-overlay');
              const r = c.getBoundingClientRect();
              return {shown: r.width / r.height, internal: c.width / c.height};
            }"""
        )
        assert abs(shape["shown"] - shape["internal"]) < 0.02, shape
        tools_box = page.locator(".mask-tools").bounding_box()
        assert tools_box and tools_box["y"] + tools_box["height"] <= 900, (
            "The tools stay on screen beside a tall video"
        )
        stroke(page, 0.2, 0.2, 0.8, 0.8)
        cut.click()
        expect(page.locator(".object-sprites .sprite-card")).to_have_count(1)
        page.screenshot(path=str(args.output / "tall-desktop.png"))
        use.click()
        expect(step).to_have_text("Finish")
        page.get_by_role("button", name="Close", exact=True).first.click()
        expect(studio).to_be_hidden()
        sound["hold"] = False
        page.wait_for_function(
            "window.JUNK.snapshot().notice === 'Its sound is ready to hear. Open Add.'"
        )
        click_control(page, "source")
        expect(step).to_have_text("Finish"), "Reopening returns to where it was"
        finish.get_by_label("Target", exact=True).wait_for()

        # Repeated missed checks stop the wait and leave a retry.
        back = finish.get_by_role("button", name="Choose another object", exact=True)
        sound_name = finish.get_by_label("Sound to pull", exact=True)
        sound_name.fill("another sound")
        sound.update(hold=True, lose=False)
        pull = finish.get_by_role("button", name="Pull this sound", exact=True)
        pull.click()
        sound_wait.wait_for()
        sound["lose"] = True
        finish.get_by_text("Status check failed", exact=False).wait_for(timeout=15000)
        expect(pull).to_be_enabled()
        sound.update(lose=False, hold=False)
        art["status"] = "ready"
        back.click()
        expect(step).to_have_text("Choose the object")

        # A recording with no picture skips objects and needs its sound named.
        page.get_by_role("button", name="Bring it in", exact=True).click()
        page.locator('.add-studio input[type="file"]').set_input_files(clips["recording"])
        expect(step).to_have_text("Pick the moment")
        whole = page.get_by_role("button", name="Use entire recording", exact=True)
        expect(whole).to_be_disabled()
        expect(whole).to_have_attribute("title", "Say what the sound is first.")
        page.get_by_label("What sound is this?", exact=True).fill("a long tone")
        whole.click()
        expect(step).to_have_text("Finish")
        finish.get_by_label("Target", exact=True).wait_for()
        expect(finish.locator(".finish-column").nth(1)).to_be_hidden()
        page.keyboard.press("Escape")
        expect(studio).to_be_hidden()

        # Providers unavailable: paint the object, and use raw audio.
        flags.update(sam=False, image=False, audio=False, wonder=False)
        click_control(page, "source")
        page.get_by_role("button", name="Bring it in", exact=True).click()
        page.locator('.add-studio input[type="file"]').set_input_files(clips["wide"])
        expect(step).to_have_text("Pick the moment")
        page.get_by_role("button", name="Use entire video", exact=True).click()
        expect(step).to_have_text("Choose the object")
        page.wait_for_function("document.querySelector('.object-stage img')?.naturalWidth > 0")
        stroke(page, 0.3, 0.3, 0.7, 0.7)
        made = calls["selections"]
        cut.click()
        page.get_by_role("button", name="Choose my object", exact=True).wait_for()
        assert calls["selections"] == made, "With no AI, the painted mask is used directly"
        page.get_by_label("Sound to pull", exact=True).first.fill("my sound")
        use.click()
        expect(step).to_have_text("Finish")
        raw = finish.get_by_role("button", name="Use raw audio", exact=True)
        raw.wait_for()
        finish.get_by_text("Sound separation is unavailable", exact=False).wait_for()
        raw.click()
        expect(studio).to_be_hidden()
        page.wait_for_function(
            "n => window.JUNK.snapshot().project.performers.length === n", arg=performers + 2
        )
        asset = page.evaluate("window.JUNK.snapshot().project.assets.at(-1)")
        assert asset["provenance"] == "raw import"
        assert "Hand-drawn mask" in asset["visualProvenance"]

        assert not errors, errors
        (args.output / "summary.json").write_text(
            json.dumps(
                {
                    "provider_fixture": True,
                    "live_inference": False,
                    "sheet_over_stage_and_fades": True,
                    "filmstrip_handles_and_keyboard": True,
                    "painted_mask_then_one_cut": True,
                    "mask_edit_blocks_moving_on": True,
                    "sound_and_painting_run_together": True,
                    "add_before_painting_finishes": True,
                    "rotated_video": True,
                    "provider_unavailable_paths": True,
                    "errors": errors,
                },
                indent=2,
            )
        )
        browser.close()
    print(
        "Add studio fixtures passed: every phase, both layouts, recovery and unavailable providers"
    )


if __name__ == "__main__":
    main()
