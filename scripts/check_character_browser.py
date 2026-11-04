"""Exercise character review/persistence with explicit browser-side provider fixtures.

This does not claim a live Meta generation: a labelled geometric rig fixture tests mechanics.
Run against the no-credentials demo gateway, never a live provider deployment.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

from check_godot_browser import click_control
from PIL import Image, ImageDraw
from playwright.sync_api import Route, sync_playwright


def rig_fixture(output: Path) -> tuple[dict, Path]:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from services.gateway.rigging import assemble_rig

    output.mkdir(parents=True, exist_ok=True)
    identifier = "e" * 32
    source = Image.new("RGBA", (200, 240))
    ImageDraw.Draw(source).rectangle((60, 25, 140, 150), fill="#cf6034")
    masks = {}
    for name, bounds in {
        "left_arm": (35, 65, 65, 100),
        "right_arm": (135, 65, 165, 100),
        "left_leg": (70, 145, 85, 218),
        "right_leg": (115, 145, 130, 218),
    }.items():
        ImageDraw.Draw(source).rectangle(bounds, fill="#d6ae75")
        mask = Image.new("RGBA", source.size)
        ImageDraw.Draw(mask).rectangle(bounds, fill="white")
        masks[name] = output / f"{name}.png"
        mask.save(masks[name])
    poster = output / f"{identifier}-character.png"
    source.save(poster)
    rig = assemble_rig(poster, cast("dict[Any, Path]", masks), output, identifier)
    return {
        "width": rig.width,
        "height": rig.height,
        "body_url": f"/assets/{rig.body_file}",
        "parts": [
            {
                "name": part.name,
                "url": f"/assets/{part.file}",
                "pivot": part.pivot,
                "max_angle": part.max_angle,
            }
            for part in rig.parts
        ],
    }, poster


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5181")
    parser.add_argument("--output", type=Path, default=Path("artifacts/character-browser-fixture"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rig, poster = rig_fixture(args.output / "fixture-layers")
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
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            reduced_motion="no-preference",
            accept_downloads=True,
        )
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: (
                errors.append(message.text)
                if "SHADER ERROR" in message.text or "SCRIPT ERROR" in message.text
                else None
            ),
        )
        fixture: dict = {"attempt": 0, "poll": 0}

        def health(route: Route) -> None:
            response = route.fetch()
            data = response.json()
            assert data["mode"] == "mock", "This check requires the no-credentials demo gateway"
            route.fulfill(response=response, json={**data, "image": True, "test_fixture": True})

        def character(route: Route) -> None:
            if route.request.method == "POST":
                request = route.request.post_data_json
                assert request is not None
                fixture.update(attempt=fixture["attempt"] + 1, poll=0, cutout=request["cutout_id"])
                fixture["job"] = {
                    "id": "f" * 32,
                    "status": "queued",
                    "stage": "painting",
                    "source_cutout_url": f"/assets/{request['cutout_id']}-cutout.png",
                    "character_url": None,
                    "error": None,
                    "provenance": "Browser fixture · no Meta generation",
                }
                route.fulfill(status=202, json=fixture["job"])
                return
            fixture["poll"] += 1
            job = {**fixture["job"]}
            if fixture["attempt"] == 1:
                job.update(
                    status="failed",
                    error="Fixture transient failure. Your source cutout is retained.",
                )
            elif fixture["poll"] < 2:
                job.update(status="processing", stage="cutting")
            elif fixture["poll"] < 3:
                job.update(status="processing", stage="rigging")
            else:
                job.update(
                    status="ready", stage="ready", character_url=f"/assets/{poster.name}", rig=rig
                )
            route.fulfill(json=job)

        page.route("**/api/health", health)
        page.route("**/api/characters", character)
        page.route("**/api/characters/*", character)
        page.route(
            "**/api/assets/" + "e" * 32 + "*",
            lambda route: route.fulfill(
                path=str(poster.parent / route.request.url.rsplit("/", 1)[1]),
                content_type="image/png",
            ),
        )
        page.goto(args.url, wait_until="domcontentloaded")
        page.wait_for_function(
            "window.JUNK?.layout?.controls?.play && document.querySelector('#loading').hidden",
            timeout=60000,
        )
        initial = page.evaluate("window.JUNK.snapshot().project.performers.length")
        click_control(page, "source")
        page.get_by_role("button", name="Try the generated demo clip", exact=True).click()
        page.get_by_role("button", name="Use entire video", exact=True).click()
        use = page.get_by_role("button", name="Use this one", exact=True)
        page.wait_for_function("document.querySelector('.object-stage img')?.naturalWidth > 0")
        area = page.locator(".object-stage .source-preview").bounding_box()
        assert area is not None
        page.mouse.move(area["x"] + area["width"] * 0.2, area["y"] + area["height"] * 0.2)
        page.mouse.down()
        page.mouse.move(area["x"] + area["width"] * 0.7, area["y"] + area["height"] * 0.8, steps=6)
        page.mouse.up()
        page.get_by_role("button", name="Cut it out", exact=True).click()
        page.locator(".object-sprites .sprite-card").first.wait_for()
        page.get_by_label("Sound to pull", exact=True).first.fill("tin clanking")
        use.click()
        finish = page.locator(".finish-phase")
        # The first attempt fails: the original stays usable, and painting can be retried.
        page.get_by_text("Fixture transient failure.", exact=False).wait_for()
        original = finish.get_by_role("button", name="Use as is", exact=True)
        assert original.get_attribute("aria-pressed") == "true"
        finish.get_by_label("Target", exact=True).wait_for()
        finish.get_by_label("Character details (optional)", exact=True).fill(
            "Small paper boots and hinged arms"
        )
        finish.get_by_role("button", name="Paint it again", exact=True).click()
        finish.get_by_text("Cutting around the new picture…", exact=True).wait_for()
        painted = finish.get_by_role("button", name="Use painted", exact=True)
        painted.wait_for()
        assert painted.get_attribute("aria-pressed") == "true"
        original.click()
        assert original.get_attribute("aria-pressed") == "true"
        painted.click()
        page.screenshot(path=str(args.output / "review-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(200)
        page.screenshot(path=str(args.output / "review-mobile.png"), full_page=True)
        assert page.locator(".add-body").evaluate("e => e.scrollWidth <= e.clientWidth + 1")
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.wait_for_function("window.JUNK.layout.viewport.x === 1440")
        before_arrival = page.evaluate("window.JUNK.layout.landingCount")
        finish.get_by_role("button", name="Add to band", exact=True).click()
        page.wait_for_function(
            "n => window.JUNK.snapshot().project.performers.length === n && window.JUNK.snapshot().saved",
            arg=initial + 1,
        )
        asset = page.evaluate("window.JUNK.snapshot().project.assets.at(-1)")
        assert asset["provenance"] == "mock candidate" and "fixture" in asset["visualProvenance"]
        assert asset["sprite"] != asset["sourceSprite"]
        assert len(asset["rig"]["parts"]) == 4
        page.wait_for_function("window.JUNK.layout.rigs?.[0]?.pieces === 5", timeout=15000)
        page.wait_for_function("n => window.JUNK.layout.landingCount === n", arg=before_arrival + 1)
        page.evaluate(
            "window.__rigAudition = setInterval(() => window.JUNK.command(JSON.stringify({kind:'audition',payload:{id:window.JUNK.snapshot().project.performers.at(-1).id}})), 400)"
        )
        page.wait_for_function(
            "Object.values(window.JUNK.layout.rigs[0].joints).some(angle => Math.abs(angle) > .005)",
            timeout=15000,
        )
        page.evaluate("clearInterval(window.__rigAudition)")
        page.screenshot(path=str(args.output / "rig-desktop.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(500)
        page.screenshot(path=str(args.output / "rig-mobile.png"))
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.wait_for_function("window.JUNK.layout.viewport.x === 1440")
        click_control(page, "help")
        with page.expect_download() as download:
            page.get_by_role("button", name="Save project", exact=True).click()
        download.value.save_as(args.output / "character-fixture.junk.json")
        bundle = json.loads((args.output / "character-fixture.junk.json").read_text())
        media_ids = {item["id"] for item in bundle["media"]}
        assert {asset["audioId"], asset["sprite"][11:], asset["sourceSprite"][11:]} <= media_ids
        assert {
            asset["rig"]["body"][11:],
            *(part["sprite"][11:] for part in asset["rig"]["parts"]),
        } <= media_ids
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function(
            "n => window.JUNK?.layout?.controls?.play && document.querySelector('#loading').hidden && window.JUNK.snapshot().project.performers.length === n",
            arg=initial + 1,
            timeout=60000,
        )
        restored = page.evaluate("window.JUNK.snapshot().project.assets.at(-1)")
        assert restored == asset
        page.wait_for_function("window.JUNK.layout.rigs?.[0]?.pieces === 5", timeout=15000)
        assert page.evaluate("window.JUNK.layout.landingCount") == 0, (
            "Reload must not replay arrival VFX or sound"
        )
        page.evaluate("window.JUNK.command(JSON.stringify({kind:'clone'}))")
        page.wait_for_function(
            "n => window.JUNK.snapshot().project.performers.length === n && window.JUNK.layout.landingCount === 1",
            arg=initial + 2,
        )
        page.keyboard.press("Delete")
        page.wait_for_function(
            "n => window.JUNK.snapshot().project.performers.length === n", arg=initial + 1
        )
        assert not errors, errors
        (args.output / "summary.json").write_text(
            json.dumps(
                {
                    "provider_fixture": True,
                    "live_meta_generation": False,
                    "retry_and_selection": True,
                    "original_cutout_exported": True,
                    "hydration_preserved": True,
                    "rig_layers_exported_and_restored": True,
                    "character_details_invalidate_style_keep_sound": True,
                    "one_arrival_per_add_and_clone": True,
                    "quiet_hydration": True,
                    "errors": errors,
                },
                indent=2,
            )
        )
        context.close()
        browser.close()
    print(
        "Character browser fixture passed: retry, original/style choice, acceptance, portable media and hydration"
    )


if __name__ == "__main__":
    main()
