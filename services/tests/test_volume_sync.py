import asyncio
import threading
from pathlib import Path

import pytest

from services.gateway import repository as repository_module
from services.gateway.character_jobs import CharacterJobs
from services.gateway.config import Settings
from services.gateway.limits import SiteGuard
from services.gateway.models import CharacterJob, CharacterRequest
from services.gateway.repository import Repository
from services.gateway.volume_sync import RELOAD_ATTEMPTS, VolumeSync

SESSION = "a" * 32
JOB = "b" * 32


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository_module, "REFUSAL_WAIT_SECONDS", 0)


def test_a_flush_does_not_wait_for_a_slow_commit() -> None:
    release = threading.Event()
    committed = threading.Event()

    def slow_commit() -> None:
        release.wait(5)
        committed.set()

    sync = VolumeSync(slow_commit, lambda: None, sleep=lambda _: None)
    sync.flush()
    assert not committed.is_set(), "flush returned before the commit was allowed to finish"
    release.set()
    assert committed.wait(5), "The commit still happens"


def test_commit_and_reload_never_overlap() -> None:
    running = threading.Lock()
    overlaps = []

    def work() -> None:
        if not running.acquire(blocking=False):
            overlaps.append(True)
            return
        threading.Event().wait(0.002)
        running.release()

    sync = VolumeSync(work, work, sleep=lambda _: None)
    threads = [threading.Thread(target=sync.reload) for _ in range(4)]
    threads += [threading.Thread(target=sync.commit_now) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not overlaps


def test_reload_saves_first_and_waits_out_open_files() -> None:
    calls: list[str] = []

    def reload() -> None:
        calls.append("reload")
        if calls.count("reload") < 3:
            raise RuntimeError("there are open files")

    VolumeSync(lambda: calls.append("commit"), reload, sleep=lambda _: None).reload()
    assert calls[:2] == ["commit", "reload"]
    assert calls.count("reload") == 3


def test_reload_says_so_when_the_volume_stays_busy() -> None:
    attempts = []

    def reload() -> None:
        attempts.append(1)
        raise RuntimeError("there are open files")

    with pytest.raises(RuntimeError, match="stayed busy"):
        VolumeSync(lambda: None, reload, sleep=lambda _: None).reload()
    assert len(attempts) == RELOAD_ATTEMPTS


def test_repository_rides_out_a_brief_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = Repository(tmp_path)
    real_mkdir = Path.mkdir
    refusals = [PermissionError(1, "Operation not permitted")] * 3

    def refusing_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        if refusals:
            raise refusals.pop()
        real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", refusing_mkdir)
    repository.write(SESSION, f"{JOB}.json", {"ok": True})
    assert repository.read(SESSION, f"{JOB}.json") == {"ok": True}


def test_a_lasting_refusal_still_reaches_the_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = Repository(tmp_path)

    def refuse(self: Path, *args: object, **kwargs: object) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(Path, "mkdir", refuse)
    with pytest.raises(PermissionError):
        repository.folder(SESSION)


def test_bookkeeping_failure_does_not_sink_paid_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = SiteGuard(tmp_path, 10, 20, lambda: None, enabled=True, uses_modal=False)
    real_mkdir = Path.mkdir

    def refuse(self: Path, *args: object, **kwargs: object) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(Path, "mkdir", refuse)
    guard.add_meta_spend(0.01)
    monkeypatch.setattr(Path, "mkdir", real_mkdir)
    guard.add_meta_spend(0.01)
    assert guard.meta_spent() == pytest.approx(0.01)


def test_a_dropped_request_leaves_no_ghost_in_the_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class DroppedGuard:
        async def admit(self) -> None:
            raise asyncio.CancelledError

    monkeypatch.setattr(
        "services.gateway.character_jobs.MetaAdapter.segmentation_available", lambda: True
    )
    repository = Repository(tmp_path)
    settings = Settings(data_dir=tmp_path, mode="live", meta_key="test")
    jobs = CharacterJobs(settings, repository, lambda: None, DroppedGuard())  # type: ignore[arg-type]
    repository.path(SESSION, f"{JOB}-cutout.png").write_bytes(b"cutout")

    async def attempt() -> None:
        with pytest.raises(asyncio.CancelledError):
            await jobs.submit(SESSION, CharacterRequest(cutout_id=JOB, description="tin"))

    asyncio.run(attempt())
    assert jobs.queue._line == []


def test_a_failure_that_cannot_be_saved_is_not_called_a_restart(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    jobs = CharacterJobs(Settings(data_dir=tmp_path, mode="mock"), repository, lambda: None)
    job = CharacterJob(
        id=JOB,
        status="processing",
        stage="painting",
        source_cutout_url="/assets/x.png",
        provenance="test",
    )
    repository.write(SESSION, f"{JOB}-character.json", job.model_dump())

    async def fail() -> None:
        raise ValueError("The painting failed")

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(1, "Operation not permitted")

    loop = asyncio.new_event_loop()
    task = loop.create_task(fail())
    loop.run_until_complete(asyncio.wait([task]))
    loop.close()
    original = repository.write
    repository.write = refuse  # type: ignore[method-assign]
    jobs._finish(SESSION, job, task)
    repository.write = original  # type: ignore[method-assign]
    seen = jobs.get(SESSION, JOB)
    assert seen.status == "failed"
    assert "restarted" not in (seen.error or "")
