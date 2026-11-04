import argparse
import functools
import json
import logging
import math
import struct
import threading
import wave
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

logger = logging.getLogger("junk.audio-check")


class TestRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        logger.debug(format, *args)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify the real audio engine in Chromium without the studio's UI dependencies"
    )
    parser.add_argument("--root", type=Path, default=Path(".verification/audio"))
    parser.add_argument("--browser", type=Path, help="Optional installed Chromium executable")
    parser.add_argument("--port", type=int, default=8019)
    parser.add_argument("--output", type=Path, default=Path("artifacts/audio-check"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args.output.mkdir(parents=True, exist_ok=True)
    root = args.root.resolve(strict=True)
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), functools.partial(TestRequestHandler, directory=str(root))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=str(args.browser) if args.browser else None,
            args=["--autoplay-policy=no-user-gesture-required"],
        )
        page = browser.new_page(accept_downloads=True)
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"http://127.0.0.1:{args.port}/")
        page.wait_for_function("document.querySelector('#status').textContent === 'Ready'")
        page.locator("#play").click()
        page.wait_for_function("window.testStudio.audio.scheduledHits >= 8")
        assert page.evaluate("window.testStudio.audio.playing")
        page.wait_for_function(
            "Object.values(JSON.parse(window.testStudio.audio.visualFrame()).pulses).some(pulse=>pulse>0.2)"
        )
        # Drawn straight from currentTime, the beat stepped with each audio callback and showed
        # no lag, so bounces landed before they were heard.
        visual_clock = page.evaluate("""() => new Promise(done => {
            const { audio, context } = window.testStudio, lags = [], rates = [];
            let last, backwards = 0;
            const tick = () => {
                const now = performance.now();
                const drawn = JSON.parse(audio.visualFrame()).beat, scheduled = audio.beat();
                if (last && drawn < last.drawn && last.drawn - drawn < 32) backwards++;
                // Callbacks closer together than a frame (catching up) present nothing new.
                if (last && drawn >= last.drawn && now - last.now >= 4)
                    rates.push((drawn - last.drawn) / (now - last.now));
                last = { now, drawn };
                if (scheduled >= drawn) lags.push(scheduled - drawn);
                if (rates.length < 120) requestAnimationFrame(tick);
                else {
                    // Share of frames off the median rate: robust to one headless hiccup.
                    const median = [...rates].sort((a, b) => a - b)[rates.length >> 1];
                    const uneven = rates.filter(r => Math.abs(r - median) > median * 0.25).length;
                    lags.sort((a, b) => a - b);
                    done({ uneven_pct: uneven / rates.length * 100, backwards,
                           lag_s: lags[lags.length >> 1] * 60 / audio.current.bpm,
                           latency_s: (context.outputLatency || 0) + (context.baseLatency || 0) });
                }
            };
            requestAnimationFrame(tick);
        })""")
        assert visual_clock["backwards"] == 0, visual_clock
        assert visual_clock["uneven_pct"] < 10, visual_clock
        assert 0.005 < visual_clock["lag_s"] < visual_clock["latency_s"] + 0.05, visual_clock
        page.locator("#pause").click()
        paused = page.evaluate("window.testStudio.audio.beat()")
        page.wait_for_timeout(100)
        assert page.evaluate("window.testStudio.audio.beat()") == paused
        page.evaluate("window.testStudio.audio.seek(7.25)")
        assert page.evaluate("window.testStudio.audio.beat()") == 7.25
        page.locator("#play").click()
        page.wait_for_function("window.testStudio.audio.beat() > 7.3")
        page.locator("#pause").click()
        resumed_hits = page.evaluate("""async () => {
            const { audio, demoProject } = window.testStudio;
            const project = demoProject();
            project.performers = [{ ...project.performers[0], mode: 'continuous_loop' }];
            audio.seek(7.25);
            const before = audio.scheduledHits;
            await audio.play(project);
            const resumed = audio.scheduledHits - before;
            audio.pause();
            return resumed;
        }""")
        assert resumed_hits == 1, "A continuous sample must resume immediately at the seek phase"
        canceled_start = page.evaluate("""async () => {
            const { AudioEngine, context, demoProject } = window.testStudio;
            let release;
            const unlocked = new Promise(resolve => { release = resolve; });
            const delayed = new AudioEngine(async () => { await unlocked; return context; }, async () => undefined);
            const starting = delayed.play(demoProject());
            delayed.pause();
            release();
            await starting;
            return !delayed.playing && delayed.scheduledHits === 0;
        }""")
        assert canceled_start, "Pausing while autoplay is blocked must cancel the pending start"
        section_levels = page.evaluate("""async () => {
            const { audio, demoProject, setSectionKind } = window.testStudio;
            const project = demoProject();
            project.performers = [{ ...project.performers[0], mode: 'continuous_loop' }, { ...project.performers[2], mute: true }];
            for (const section of project.sections) section.mutedIds = [];
            setSectionKind(project, 'section-2', 'solo', 'p-2');
            const data = new DataView(await (await audio.export(project)).arrayBuffer());
            const sampleRate = data.getUint32(24, true);
            const rms = (start, end) => {
                let sum = 0, count = 0;
                for (let i = Math.floor(start * sampleRate) * 2; i < Math.floor(end * sampleRate) * 2; i++) {
                    const value = data.getInt16(44 + i * 2, true) / 32768;
                    sum += value * value; count++;
                }
                return Math.sqrt(sum / count);
            };
            return { before: rms(2,6), solo: rms(9.2,12.4), after: rms(14,18) };
        }""")
        assert section_levels["before"] > 0.005 and section_levels["after"] > 0.005
        assert section_levels["solo"] < 0.0002, (
            "Sustained backing must be silent inside a solo and reopen afterwards"
        )
        (args.output / "section-gating.json").write_text(
            json.dumps(section_levels), encoding="utf-8"
        )
        with page.expect_download() as download:
            page.locator("#export").click()
        target = args.output / "junk-starter.wav"
        download.value.save_as(target)
        assert not errors, errors
        browser.close()
    server.shutdown()
    server.server_close()
    with wave.open(str(target), "rb") as audio_file:
        assert audio_file.getnchannels() == 2
        assert audio_file.getsampwidth() == 2
        duration = audio_file.getnframes() / audio_file.getframerate()
        assert abs(duration - 64 * 60 / 112) < 0.001
        samples = struct.unpack(
            f"<{audio_file.getnframes() * 2}h", audio_file.readframes(audio_file.getnframes())
        )
    rms = math.sqrt(sum((sample / 32768) ** 2 for sample in samples) / len(samples))
    peak = max(abs(sample / 32768) for sample in samples)
    assert rms > 0.005, rms
    assert peak < 0.99, peak
    metrics = {
        "duration_s": duration,
        "rms": rms,
        "peak": peak,
        "visual_clock": visual_clock,
        "browser_errors": errors,
        "adapter": "native AudioContext; Godot bridge is covered by the full studio check",
    }
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    logger.info("Production audio engine passed Chromium checks: %s", metrics)


if __name__ == "__main__":
    main()
