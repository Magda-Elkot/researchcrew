"""Tests for app.api.jobs: the SQLite job and event store."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.api.jobs import JobStore
from app.schemas import ProgressEvent


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path: Path, clock: Clock) -> JobStore:
    return JobStore(tmp_path / "sub" / "jobs.db", now=clock)


def event(job_id: str, type_: str = "agent_started") -> ProgressEvent:
    return ProgressEvent(job_id=job_id, type=type_, agent="Researcher", message="m")  # type: ignore[arg-type]


def test_create_and_get(store: JobStore, clock: Clock) -> None:
    job_id = store.create("ما هي الطاقة؟", "quick")
    job = store.get(job_id)
    assert job is not None
    assert (job.question, job.depth, job.status) == ("ما هي الطاقة؟", "quick", "queued")
    assert job.created_at == clock.value
    assert store.get("nope") is None


def test_the_database_folder_is_created(tmp_path: Path) -> None:
    JobStore(tmp_path / "a" / "b" / "jobs.db")
    assert (tmp_path / "a" / "b" / "jobs.db").exists()


def test_status_moves_forward_only(store: JobStore) -> None:
    job_id = store.create("q", "quick")
    assert store.start(job_id)
    assert not store.start(job_id)  # already running
    assert store.finish(job_id, "completed", '{"x": 1}')
    job = store.get(job_id)
    assert job is not None
    assert (job.status, job.result_json) == ("completed", '{"x": 1}')
    assert job.finished_at is not None
    assert not store.finish(job_id, "failed", "{}")  # ended jobs stay ended
    assert not store.fail(job_id, "late")


def test_fail_adds_a_job_failed_event(store: JobStore) -> None:
    job_id = store.create("q", "quick")
    assert store.fail(job_id, "boom")
    job = store.get(job_id)
    assert job is not None
    assert (job.status, job.error) == ("failed", "boom")
    [(_, last)] = store.events_after(job_id)
    assert (last.type, last.message) == ("job_failed", "boom")


def test_overdue_jobs_fail_and_a_late_result_is_dropped(store: JobStore, clock: Clock) -> None:
    slow = store.create("slow", "quick")
    fresh = store.create("fresh", "quick")
    queued = store.create("queued", "quick")
    store.start(slow)
    clock.advance(500)
    store.start(fresh)
    clock.advance(500)  # slow: 1000 s running, fresh: 500 s

    assert store.expire_overdue(960) == [slow]
    assert store.expire_overdue(960) == []  # only once
    assert store.get(fresh).status == "running"  # type: ignore[union-attr]
    assert store.get(queued).status == "queued"  # type: ignore[union-attr]
    job = store.get(slow)
    assert job is not None
    assert job.status == "failed"
    assert job.error == "Timed out: no result after 960 s."
    assert not store.finish(slow, "completed", "{}")  # the worker thread finished too late


def test_fail_unfinished_cleans_up_after_a_restart(store: JobStore) -> None:
    running, queued, done = (store.create(q, "quick") for q in ("a", "b", "c"))
    store.start(running)
    store.start(done)
    store.finish(done, "completed", "{}")
    assert store.fail_unfinished("server restarted") == 2
    assert store.get(running).status == "failed"  # type: ignore[union-attr]
    assert store.get(queued).error == "server restarted"  # type: ignore[union-attr]
    assert store.get(done).status == "completed"  # type: ignore[union-attr]


def test_events_are_numbered_per_store_and_filtered_by_job(store: JobStore) -> None:
    a, b = store.create("a", "quick"), store.create("b", "quick")
    first = store.add_event(event(a))
    store.add_event(event(b))
    third = store.add_event(event(a, "agent_finished"))
    assert first < third
    assert [seq for seq, _ in store.events_after(a)] == [first, third]
    [(seq, ev)] = store.events_after(a, first)
    assert (seq, ev.type, ev.agent) == (third, "agent_finished", "Researcher")
    assert store.events_after(a, third) == []


def test_two_store_objects_share_the_file(tmp_path: Path) -> None:
    writer, reader = JobStore(tmp_path / "j.db"), JobStore(tmp_path / "j.db")
    job_id = writer.create("q", "deep")
    writer.add_event(event(job_id))
    assert reader.get(job_id) is not None
    assert len(reader.events_after(job_id)) == 1


def test_finish_saves_the_final_events_only_if_it_wins(store: JobStore) -> None:
    job_id = store.create("q", "quick")
    store.start(job_id)
    assert store.finish(job_id, "completed", "{}", events=[event(job_id, "job_completed")])
    assert [e.type for _, e in store.events_after(job_id)] == ["job_completed"]
    other = store.create("q", "quick")
    store.start(other)
    store.fail(other, "Timed out")
    assert not store.finish(other, "completed", "{}", events=[event(other, "job_completed")])
    assert [e.type for _, e in store.events_after(other)] == ["job_failed"]
