"""Edits made during playback must be heard at once, not at the next bar."""

import argparse
import json

from playwright.sync_api import Page, sync_playwright

PROBE = """async () => {
  const { audio } = await import('/modules/audio/browser.js');
  await audio.unlock();
  const analyser = audio.context.createAnalyser();
  analyser.fftSize = 2048;
  audio.output.connect(analyser);
  const samples = new Float32Array(analyser.fftSize);
  // The loudest moment over a short window, sampled faster than the analyser's buffer turns over.
  window.loudest = async (ms) => {
    let peak = 0;
    const until = performance.now() + ms;
    while (performance.now() < until) {
      analyser.getFloatTimeDomainData(samples);
      for (const value of samples) peak = Math.max(peak, Math.abs(value));
      await new Promise((done) => setTimeout(done, 8));
    }
    return peak;
  };
  window.sendAll = (patch) => {
    for (const p of window.JUNK.snapshot().project.performers)
      window.JUNK.command(JSON.stringify({ kind: 'update_performer', payload: { id: p.id, patch } }));
  };
  window.dragAll = (x, y) => {
    for (const p of window.JUNK.snapshot().project.performers)
      window.JUNK.command(JSON.stringify({ kind: 'move_preview', payload: { id: p.id, x, y } }));
  };
}"""

# One bar is far longer than this, so passing cannot be the old wait for the next bar.
HEARD_WITHIN_MS = 60
LISTEN_MS = 110


def change_then_listen(page: Page, action: str) -> float:
    return page.evaluate(
        f"""async () => {{
          {action};
          await new Promise((done) => setTimeout(done, {HEARD_WITHIN_MS}));
          return window.loudest({LISTEN_MS});
        }}"""
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5182/")
    args = parser.parse_args()
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
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(args.url, wait_until="domcontentloaded")
        # The saved project loads after the API appears, so wait for the band to really be playing.
        page.wait_for_function("window.JUNK?.metrics?.().hits > 0", timeout=60000)
        page.evaluate(PROBE)
        # Nobody sits out for this check, so every sound can be heard whatever the section.
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
        page.evaluate(
            "() => { sendAll({ mode: 'continuous_loop', steps: [0], gainDb: -6, exit: 'fade', path: [], position: { x: 0, y: 0 } }); }"
        )
        page.wait_for_function(
            "window.JUNK.snapshot().project.performers.every(p => p.mode === 'continuous_loop')"
        )
        # The band starts by itself on load.
        page.wait_for_function("window.JUNK.snapshot().playing", timeout=20000)
        page.wait_for_timeout(300)

        loud = page.evaluate("window.loudest(250)")
        assert loud > 0.02, f"The band should be audible before any change, got {loud}"

        quiet = change_then_listen(page, "sendAll({ gainDb: -36 })")
        assert quiet < loud * 0.5, f"Volume down is heard at once: {loud} then {quiet}"
        back = change_then_listen(page, "sendAll({ gainDb: -6 })")
        assert back > quiet * 2, f"Volume up is heard at once: {quiet} then {back}"

        dragged_out = change_then_listen(page, "dragAll(900, 0)")
        assert dragged_out < 0.002, f"Dragging off the stage silences at once: {dragged_out}"
        dragged_in = change_then_listen(page, "dragAll(0, 0)")
        assert dragged_in > 0.02, f"Dragging back on is heard at once: {dragged_in}"

        muted = change_then_listen(page, "sendAll({ mute: true })")
        assert muted < 0.002, f"Mute is heard at once: {muted}"
        unmuted = change_then_listen(page, "sendAll({ mute: false })")
        assert unmuted > 0.02, f"A silent loop comes back at once: {unmuted}"

        # The punch card: one character stays clear while the rest of the band drops back.
        first = page.evaluate("window.JUNK.snapshot().project.performers[0].id")
        spotlight = "window.JUNK.command(JSON.stringify({ kind: 'spotlight', payload: %s }))"
        page.evaluate(
            "id => window.JUNK.command(JSON.stringify({ kind: 'update_performer', payload: { id, patch: { gainDb: -36 } } }))",
            first,
        )
        page.wait_for_timeout(100)
        band = page.evaluate("window.loudest(250)")
        dropped = change_then_listen(page, spotlight % json.dumps({"id": first}))
        assert dropped < band * 0.5, f"The band drops back at once: {band} then {dropped}"
        returned = change_then_listen(page, spotlight % "{}")
        assert returned > dropped * 2, f"Closing the card gives the song back: {dropped} then {returned}"
        # It is heard even when it would otherwise be silent.
        change_then_listen(page, "sendAll({ mute: true, gainDb: -6 })")
        silent = page.evaluate("window.loudest(150)")
        assert silent < 0.002, f"Everyone is muted first: {silent}"
        alone = change_then_listen(page, spotlight % json.dumps({"id": first}))
        assert alone > 0.01, f"The character on the card is heard even when muted: {alone}"
        change_then_listen(page, spotlight % "{}")
        gone = page.evaluate("window.loudest(150)")
        assert gone < 0.002, f"Muted again once the card closes: {gone}"
        browser.close()
    print("Audio response fixture passed: volume, drag out and in, mute and the punch card are heard at once")


if __name__ == "__main__":
    main()
