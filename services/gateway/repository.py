import hashlib
import hmac
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

Result = TypeVar("Result")
# A Modal volume can briefly refuse file operations while it reloads.
REFUSAL_ATTEMPTS = 20
REFUSAL_WAIT_SECONDS = 0.1


def through_refusals(action: Callable[[], Result]) -> Result:
    for _ in range(REFUSAL_ATTEMPTS - 1):
        try:
            return action()
        except PermissionError:
            time.sleep(REFUSAL_WAIT_SECONDS)
    return action()


def ensure_dir(path: Path, parents: bool = False) -> None:
    through_refusals(lambda: path.mkdir(parents=parents, exist_ok=True))


class Repository:
    """Opaque IDs, isolated session directories and atomic metadata writes."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def folder(self, session: str) -> Path:
        self.validate_id(session)
        path = self.root / session
        ensure_dir(path)
        return path

    @staticmethod
    def validate_id(value: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{32,64}", value):
            raise ValueError("Invalid opaque ID")

    def path(self, session: str, name: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32,64}(?:-[a-z]+){0,3}\.[a-z0-9]+", name):
            raise ValueError("Invalid asset path")
        return self.folder(session) / name

    def write(self, session: str, name: str, data: dict[str, Any]) -> None:
        path = self.path(session, name)
        temporary = path.with_suffix(".tmp")

        def save() -> None:
            temporary.write_text(json.dumps(data), encoding="utf-8")
            temporary.replace(path)

        through_refusals(save)

    def read(self, session: str, name: str) -> dict[str, Any]:
        path = self.path(session, name)
        return json.loads(through_refusals(lambda: path.read_text(encoding="utf-8")))


def sign_session(session: str, secret: str) -> str:
    signature = hmac.new(secret.encode(), session.encode(), hashlib.sha256).hexdigest()
    return f"{session}.{signature}"


def verify_session(cookie: str | None, secret: str) -> str | None:
    if not cookie or "." not in cookie:
        return None
    session, signature = cookie.split(".", 1)
    if not re.fullmatch(r"[a-f0-9]{32}", session):
        return None
    expected = sign_session(session, secret).split(".", 1)[1]
    return session if hmac.compare_digest(signature, expected) else None


def expired(path: Path, ttl_hours: int) -> bool:
    return time.time() - path.stat().st_mtime > ttl_hours * 3600
