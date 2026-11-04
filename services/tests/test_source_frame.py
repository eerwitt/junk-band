import io
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from services.gateway.app import create_app
from services.gateway.config import Settings


def test_private_video_frame_uses_real_decode_and_cache_without_model_access(
    tmp_path: Path,
) -> None:
    source = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=64x32:r=2",
            "-t",
            "2",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    settings = Settings(
        mode="live",
        meta_key="",
        modal_enabled=False,
        session_secret="x" * 40,
        data_dir=tmp_path / "data",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        media = client.post(
            "/api/media", files={"file": (source.name, source.read_bytes(), "video/mp4")}
        ).json()
        path = f"/api/media/{media['id']}/frame?frame_s=0.5"
        result = client.get(path)
        assert result.status_code == 200 and result.headers["content-type"] == "image/png"
        assert result.headers["cache-control"] == "private, no-store"
        with Image.open(io.BytesIO(result.content)) as image:
            assert image.size == (64, 32)
            r, g, b = image.convert("RGB").getpixel((10, 10))
            assert r > 240 and g < 10 and b < 10
        assert client.get(path).content == result.content
        assert len(list(settings.data_dir.glob("*/*-preview.png"))) == 1
        assert not list(settings.data_dir.glob("*/*.tmp.png"))
        for frame in (-1, 21, 2.0):
            assert client.get(f"/api/media/{media['id']}/frame?frame_s={frame}").status_code == 422
        with TestClient(app) as stranger:
            assert stranger.get(path).status_code == 404


def test_preview_orients_phone_photo_and_rejects_audio_only_sources(tmp_path: Path) -> None:
    import wave

    photo = Image.new("RGB", (40, 20), "orange")
    exif = Image.Exif()
    exif[274] = 6
    encoded = io.BytesIO()
    photo.save(encoded, format="JPEG", exif=exif)
    with TestClient(create_app(Settings(mode="mock", data_dir=tmp_path))) as client:
        media = client.post(
            "/api/media", files={"file": ("phone.jpg", encoded.getvalue(), "image/jpeg")}
        ).json()
        result = client.get(f"/api/media/{media['id']}/frame")
        assert result.status_code == 200
        with Image.open(io.BytesIO(result.content)) as frame:
            assert frame.size == (20, 40)
        wav = io.BytesIO()
        with wave.open(wav, "wb") as sound:
            sound.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            sound.writeframes(bytes(8000 * 4))
        audio = client.post(
            "/api/media", files={"file": ("sound.wav", wav.getvalue(), "audio/wav")}
        ).json()
        assert client.get(f"/api/media/{audio['id']}/frame").status_code == 422
