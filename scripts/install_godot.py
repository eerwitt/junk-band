"""Install the Godot editor and the web export templates the build needs, on Linux.

Fetches the headless-capable Linux editor and only the two single-threaded web templates. The
official template bundle is over a gigabyte, so they are read out of it with HTTP range requests
instead of downloading the whole archive. Safe to run again: anything present is kept.
"""

import argparse
import io
import logging
import os
import stat
import struct
import time
import urllib.request
import zipfile
import zlib
from pathlib import Path

logger = logging.getLogger("junk.install-godot")

VERSION = "4.6.3"
RELEASES = f"https://github.com/godotengine/godot/releases/download/{VERSION}-stable"
EDITOR = f"Godot_v{VERSION}-stable_linux.x86_64"
TEMPLATES = f"Godot_v{VERSION}-stable_export_templates.tpz"
WEB_TEMPLATES = ("web_nothreads_release.zip", "web_nothreads_debug.zip")
CHUNK = 8 * 1024 * 1024


def fetch(url: str, start: int | None = None, end: int | None = None) -> bytes:
    """GET a URL, or an inclusive byte range of it, retrying dropped connections."""
    headers = {"User-Agent": "junk-build"}
    if start is not None:
        headers["Range"] = f"bytes={start}-" if end is None else f"bytes={start}-{end}"
    for attempt in range(5):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=60
            ) as reply:
                return reply.read()
        except OSError as error:
            if attempt == 4:
                raise
            logger.warning("Retrying %s after %s", url.rsplit("/", 1)[-1], error)
            time.sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


def size_of(url: str) -> int:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "junk-build"})
    with urllib.request.urlopen(request, timeout=60) as reply:
        return int(reply.headers["Content-Length"])


def download(url: str, target: Path) -> None:
    """Whole-file download in ranged chunks, so one reset connection costs one chunk."""
    total = size_of(url)
    with target.open("wb") as file:
        for start in range(0, total, CHUNK):
            file.write(fetch(url, start, min(start + CHUNK, total) - 1))
    if target.stat().st_size != total:
        raise RuntimeError(f"{target.name}: expected {total} bytes, got {target.stat().st_size}")


def remote_members(url: str, names: tuple[str, ...]) -> dict[str, bytes]:
    """Read named files out of a remote zip using only its central directory and their data."""
    total = size_of(url)
    tail = fetch(url, max(0, total - 66000), total - 1)
    end = tail.rfind(b"PK\x05\x06")
    if end < 0:
        raise RuntimeError("No zip directory found at the end of the template bundle")
    entries, directory_size, directory_offset = struct.unpack_from("<HII", tail, end + 10)
    locator = tail.rfind(b"PK\x06\x07", 0, end)
    if locator >= 0:
        (zip64_end,) = struct.unpack_from("<Q", tail, locator + 8)
        record = fetch(url, zip64_end, zip64_end + 55)
        entries, directory_size, directory_offset = struct.unpack_from("<QQQ", record, 32)
    directory = fetch(url, directory_offset, directory_offset + directory_size - 1)
    found: dict[str, bytes] = {}
    position = 0
    for _ in range(entries):
        (
            method,
            _time,
            _date,
            _crc,
            packed,
            unpacked,
            name_length,
            extra_length,
            comment_length,
        ) = struct.unpack_from("<HHHIIIHHH", directory, position + 10)
        (offset,) = struct.unpack_from("<I", directory, position + 42)
        name = directory[position + 46 : position + 46 + name_length].decode()
        extra = directory[position + 46 + name_length : position + 46 + name_length + extra_length]
        position += 46 + name_length + extra_length + comment_length
        member = name.rsplit("/", 1)[-1]
        if member not in names:
            continue
        # Zip64 keeps the real sizes and offset in an extra field when the 32-bit ones overflow.
        cursor = 0
        while cursor + 4 <= len(extra):
            tag, length = struct.unpack_from("<HH", extra, cursor)
            if tag == 1:
                values = iter(struct.unpack_from(f"<{length // 8}Q", extra, cursor + 4))
                if unpacked == 0xFFFFFFFF:
                    unpacked = next(values)
                if packed == 0xFFFFFFFF:
                    packed = next(values)
                if offset == 0xFFFFFFFF:
                    offset = next(values)
            cursor += 4 + length
        header = fetch(url, offset, offset + 29)
        name_size, extra_size = struct.unpack_from("<HH", header, 26)
        start = offset + 30 + name_size + extra_size
        data = b"".join(
            fetch(url, chunk, min(chunk + CHUNK, start + packed) - 1)
            for chunk in range(start, start + packed, CHUNK)
        )
        if method == 8:
            data = zlib.decompress(data, -15)
        elif method != 0:
            raise RuntimeError(f"{member}: unsupported zip method {method}")
        if len(data) != unpacked:
            raise RuntimeError(f"{member}: expected {unpacked} bytes, got {len(data)}")
        found[member] = data
    missing = set(names) - set(found)
    if missing:
        raise RuntimeError(f"Template bundle has no {', '.join(sorted(missing))}")
    return found


def main() -> None:
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prefix", type=Path, default=data_home / "junk/godot")
    parser.add_argument("--bin", type=Path, default=Path.home() / ".local/bin")
    parser.add_argument(
        "--templates",
        type=Path,
        default=data_home / f"godot/export_templates/{VERSION}.stable",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    editor = args.prefix / EDITOR
    if editor.exists():
        logger.info("Godot %s already at %s", VERSION, editor)
    else:
        args.prefix.mkdir(parents=True, exist_ok=True)
        archive = args.prefix / f"{EDITOR}.zip"
        logger.info("Downloading Godot %s editor", VERSION)
        download(f"{RELEASES}/{EDITOR}.zip", archive)
        with zipfile.ZipFile(archive) as bundle:
            editor.write_bytes(bundle.read(EDITOR))
        archive.unlink()
        editor.chmod(editor.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    args.bin.mkdir(parents=True, exist_ok=True)
    link = args.bin / "godot"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(editor)

    wanted = tuple(name for name in WEB_TEMPLATES if not (args.templates / name).exists())
    if wanted:
        logger.info("Reading %s out of the export template bundle", ", ".join(wanted))
        args.templates.mkdir(parents=True, exist_ok=True)
        for name, data in remote_members(f"{RELEASES}/{TEMPLATES}", wanted).items():
            zipfile.ZipFile(io.BytesIO(data)).testzip()
            (args.templates / name).write_bytes(data)
    logger.info("Godot %s ready: %s, templates in %s", VERSION, link, args.templates)


if __name__ == "__main__":
    main()
