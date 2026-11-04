import argparse
import logging
import math
import struct
import subprocess
import wave
from pathlib import Path

logger = logging.getLogger("junk.fixture")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a clearly synthetic, project-owned media fixture for the mock pipeline"
    )
    parser.add_argument("--output", type=Path, default=Path("public/demo-source.mp4"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    audio = args.output.with_suffix(".wav")
    rate = 48000
    frames = bytearray()
    for i in range(rate * 6):
        t = i / rate
        local = t % 0.75
        signal = (
            math.sin(2 * math.pi * (180 * local + 70 * local * local))
            * math.exp(-local * 17)
            * 0.55
        )
        background = math.sin(2 * math.pi * 87 * t) * 0.04
        frames.extend(struct.pack("<h", int((signal + background) * 28000)))
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(frames)
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-loop",
            "1",
            "-i",
            "public/sprites.png",
            "-i",
            str(audio),
            "-f",
            "lavfi",
            "-i",
            "color=c=0xf7f5ec:s=720x720:r=24",
            "-filter_complex",
            "[0:v]scale=620:620[art];[2:v][art]overlay=50:50:shortest=1,format=yuv420p[v]",
            "-map",
            "[v]",
            "-map",
            "1:a",
            "-t",
            "6",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(args.output),
        ],
        check=True,
        capture_output=True,
        timeout=90,
    )
    logger.info(
        "Created %s: generated artwork + synthesized audio; not a real-object recording",
        args.output,
    )


if __name__ == "__main__":
    main()
