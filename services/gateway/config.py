import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

# A cold start measured about 3 minutes. A worker that crashes at startup never fails its call,
# so this limit is what ends the job and stops the billing.
WORKER_LIMIT_S = 600
WORKER_LIMIT_MESSAGE = (
    "The sound worker did not finish within 10 minutes, so the job was stopped. "
    "Raw trimming remains available."
)


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(env("JUNK_DATA_DIR", "data")))
    mode: str = field(default_factory=lambda: env("JUNK_MODE", "auto"))
    origin: str = field(default_factory=lambda: env("CORS_ALLOWED_ORIGIN", "http://127.0.0.1:5173"))
    session_secret: str = field(default_factory=lambda: env("JUNK_API_SESSION_SECRET"), repr=False)
    meta_key: str = field(default_factory=lambda: env("MODEL_API_KEY"), repr=False)
    image_model: str = field(default_factory=lambda: env("META_IMAGE_MODEL", "muse-image-1.0"))
    modal_enabled: bool = field(
        default_factory=lambda: (
            env("JUNK_MODAL_ENABLED").lower() == "true"
            or bool(env("MODAL_TOKEN_ID") or env("MODAL_TOKEN_SECRET"))
        )
    )
    modal_app: str = field(default_factory=lambda: env("JUNK_MODAL_APP", "junk-living-sampler"))
    modal_volume: str = field(
        default_factory=lambda: env("JUNK_MODAL_VOLUME", "junk-session-media")
    )
    # Across the whole site. One new object is about three: a cut, a sound and a painting.
    daily_request_limit: int = field(
        default_factory=lambda: int(env("JUNK_DAILY_REQUEST_LIMIT", "90"))
    )
    # New work stops once this month's Modal usage reaches this, or as soon as anything is charged.
    modal_monthly_limit: float = field(
        default_factory=lambda: float(env("JUNK_MODAL_MONTHLY_LIMIT", "20"))
    )
    meta_monthly_limit: float = field(
        default_factory=lambda: float(env("JUNK_META_MONTHLY_LIMIT", "100"))
    )
    max_upload: int = 200 * 1024 * 1024
    ttl_hours: int = 24

    def __post_init__(self) -> None:
        if self.mode == "auto":
            object.__setattr__(
                self, "mode", "live" if self.meta_key or self.modal_enabled else "mock"
            )
        if not self.session_secret and self.mode == "mock":
            object.__setattr__(self, "session_secret", "local-mock-only")
        elif not self.session_secret and self.mode == "live" and self.local_origin:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            path = self.data_dir / ".session-secret"
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                secret = path.read_text(encoding="utf-8").strip()
            else:
                secret = secrets.token_urlsafe(48)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(secret)
            object.__setattr__(self, "session_secret", secret)

    @property
    def local_origin(self) -> bool:
        return urlparse(self.origin).hostname in {"localhost", "127.0.0.1", "::1"}

    def allows_origin(self, origin: str) -> bool:
        if origin == self.origin:
            return True
        expected, received = urlparse(self.origin), urlparse(origin)
        return (
            self.local_origin
            and received.hostname in {"localhost", "127.0.0.1", "::1"}
            and expected.scheme == received.scheme
            and expected.port == received.port
        )

    @property
    def browser_origins(self) -> list[str]:
        if not self.local_origin:
            return [self.origin]
        parsed = urlparse(self.origin)
        port = f":{parsed.port}" if parsed.port else ""
        return [f"{parsed.scheme}://{host}{port}" for host in ("127.0.0.1", "localhost", "[::1]")]

    def validate(self) -> None:
        if self.mode not in {"mock", "live"}:
            raise ValueError("JUNK_MODE must be auto, mock or live")
        if self.mode == "mock" and (self.meta_key or self.modal_enabled):
            raise ValueError(
                "Credentials are configured but JUNK_MODE=mock. Use auto or live; configured providers never fall back to mock output."
            )
        if self.mode == "live" and len(self.session_secret) < 32:
            raise ValueError("Hosted live mode requires JUNK_API_SESSION_SECRET of 32+ characters")
        if self.mode == "live" and not self.local_origin and not self.origin.startswith("https://"):
            raise ValueError("Hosted live mode requires an HTTPS CORS_ALLOWED_ORIGIN")
        if bool(env("MODAL_TOKEN_ID")) != bool(env("MODAL_TOKEN_SECRET")):
            raise ValueError("Set both MODAL_TOKEN_ID and MODAL_TOKEN_SECRET")
