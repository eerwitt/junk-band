import shutil
import time
from pathlib import Path


def expired_sessions(root: Path, older_than_hours: float) -> list[Path]:
    """Session folders nothing has touched for that long. Anything else in the root is left alone."""
    expired = []
    for session in root.iterdir():
        if (
            not session.is_dir()
            or len(session.name) != 32
            or any(c not in "0123456789abcdef" for c in session.name)
        ):
            continue
        resolved = session.resolve(strict=True)
        if resolved.parent != root.resolve(strict=True):
            raise ValueError("Refusing a path outside the media root")
        files = list(resolved.iterdir())
        modified = max((path.stat().st_mtime for path in files), default=session.stat().st_mtime)
        if time.time() - modified > older_than_hours * 3600:
            expired.append(resolved)
    return expired


def remove_expired_sessions(root: Path, older_than_hours: float) -> int:
    expired = expired_sessions(root, older_than_hours)
    for session in expired:
        shutil.rmtree(session)
    return len(expired)
