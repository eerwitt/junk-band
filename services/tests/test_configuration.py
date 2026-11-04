import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from services.gateway.app import create_app
from services.gateway.config import Settings
from services.gateway.environment import load_environment


@pytest.fixture(autouse=True)
def clean_provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "JUNK_MODE",
        "MODEL_API_KEY",
        "MODAL_TOKEN_ID",
        "MODAL_TOKEN_SECRET",
        "JUNK_MODAL_ENABLED",
        "JUNK_API_SESSION_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


def test_auto_configuration_is_evaluated_when_settings_are_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert Settings(data_dir=tmp_path).mode == "mock"
    monkeypatch.setenv("MODEL_API_KEY", "test-provider-key")
    first = Settings(data_dir=tmp_path)
    first.validate()
    assert first.mode == "live"
    assert len(first.session_secret) >= 32
    assert Settings(data_dir=tmp_path).session_secret == first.session_secret
    assert "test-provider-key" not in repr(first)
    with pytest.raises(ValueError, match="never fall back"):
        Settings(mode="mock", data_dir=tmp_path).validate()


def test_environment_file_is_literal_and_never_overrides_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".env"
    path.write_text(
        'MODEL_API_KEY="test-file-key"\nJUNK_MODE=auto # provider selection\nexport JUNK_DATA_DIR="C:\\data\\junk"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_API_KEY", "test-shell-key")
    monkeypatch.delenv("JUNK_DATA_DIR", raising=False)
    load_environment(path)
    assert Settings(data_dir=tmp_path).meta_key == "test-shell-key"
    assert Settings(session_secret="x" * 40).data_dir == Path("C:\\data\\junk")
    monkeypatch.delenv("JUNK_DATA_DIR")
    path.write_text('MODEL_API_KEY="private-value\n', encoding="utf-8")
    with pytest.raises(ValueError, match="MODEL_API_KEY") as error:
        load_environment(path)
    assert "private-value" not in str(error.value)


def test_missing_providers_fail_explicitly_in_live_mode(tmp_path: Path) -> None:
    settings = Settings(mode="live", data_dir=tmp_path, session_secret="x" * 40)
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/health").json()
        assert health["mode"] == "live" and not health["sam"] and not health["audio"]
        result = client.post(
            "/api/separate",
            json={"media_id": "a" * 32, "start_s": 0, "end_s": 4, "description": "tin"},
        )
        assert result.status_code == 503
        assert "Modal" in result.json()["detail"]


def test_local_live_cookies_and_origin_aliases(tmp_path: Path) -> None:
    settings = Settings(mode="live", data_dir=tmp_path, session_secret="x" * 40)
    assert settings.allows_origin("http://localhost:5173")
    assert not settings.allows_origin("http://localhost:5174")
    assert not settings.allows_origin("https://example.com")
    with TestClient(create_app(settings)) as client:
        content = io.BytesIO()
        Image.new("RGB", (20, 20), "orange").save(content, format="PNG")
        response = client.post(
            "/api/media",
            files={"file": ("source.png", content.getvalue(), "image/png")},
            headers={"Origin": "https://example.com"},
        )
        assert response.status_code == 403
        response = client.post(
            "/api/media",
            files={"file": ("source.png", content.getvalue(), "image/png")},
            headers={"Origin": "http://localhost:5173"},
        )
        assert response.status_code == 200
        assert "junk_session=" in response.headers["set-cookie"]
        assert "; Secure" not in response.headers["set-cookie"]


def test_hosted_live_configuration_requires_explicit_session_secret(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        Settings(mode="live", data_dir=tmp_path, origin="https://example.com").validate()
    assert not (tmp_path / ".session-secret").exists()
