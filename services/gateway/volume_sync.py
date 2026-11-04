"""Keeps the shared Modal volume in step without stalling the site or pulling files from under it."""

import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Saves close together go out as one.
GATHER_SECONDS = 1.0
COMMIT_RETRY_SECONDS = 5.0
# A reload is refused while a file is open, which only lasts as long as one download.
RELOAD_ATTEMPTS = 40
RELOAD_WAIT_SECONDS = 0.5


class VolumeSync:
    """Commits happen on their own thread, because one can take half a minute.

    Reloads are only for seeing what the GPU worker wrote. While one runs, the volume can refuse
    other requests' reads and writes, so nothing reloads just because a request came in.
    """

    def __init__(
        self,
        commit: Callable[[], None],
        reload: Callable[[], None],
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._commit = commit
        self._reload = reload
        self._sleep = sleep
        self._lock = threading.Lock()
        self._dirty = threading.Event()
        self._start = threading.Lock()
        self._thread: threading.Thread | None = None

    def flush(self) -> None:
        """Ask for a save and return straight away."""
        self._dirty.set()
        with self._start:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()

    def commit_now(self) -> None:
        """Save and wait, for when the GPU worker is about to read what was written."""
        self._dirty.clear()
        with self._lock:
            self._commit()

    def reload(self) -> None:
        """See what the GPU worker wrote, saving first so nothing of ours is lost."""
        refusal: RuntimeError | None = None
        for _ in range(RELOAD_ATTEMPTS):
            with self._lock:
                try:
                    self._commit()
                    self._reload()
                    return
                except RuntimeError as error:
                    refusal = error
            self._sleep(RELOAD_WAIT_SECONDS)
        raise RuntimeError("The shared volume stayed busy") from refusal

    def _run(self) -> None:
        while True:
            self._dirty.wait()
            self._sleep(GATHER_SECONDS)
            self._dirty.clear()
            try:
                with self._lock:
                    self._commit()
            except Exception as error:
                logger.warning("Volume commit failed, trying again: %s", error)
                self._dirty.set()
                self._sleep(COMMIT_RETRY_SECONDS)
