"""Tests for app.api.runner.JobRunner (the crew is always a fake)."""

import threading
from pathlib import Path

import pytest

from app.agents.pipeline import RunResult
from app.api.jobs import JobStore
from app.api.runner import JobRunner
from app.config import Settings
from app.schemas import Depth, ProgressEvent
from app.tools.guarded import EmitFn


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "jobs.db")


def fake_run(status: str = "completed", error: str | None = None):  # type: ignore[no-untyped-def]
    def run(
        question: str,
        depth: Depth,
        settings: Settings,
        emit: EmitFn | None = None,
        *,
        job_id: str | None = None,
    ) -> RunResult:
        assert emit is not None and job_id is not None
        emit(ProgressEvent(job_id=job_id, type="agent_started", agent="Planner", message="go"))
        final = "job_completed" if status == "completed" else "job_failed"
        emit(ProgressEvent(job_id=job_id, type=final, message=error or "report ready"))  # type: ignore[arg-type]
        return RunResult(
            job_id=job_id,
            status=status,  # type: ignore[arg-type]
            question=question,
            depth=depth,
            model="fake",
            error=error,
        )

    return run


def test_a_job_runs_and_its_final_event_is_saved_with_the_result(store: JobStore) -> None:
    runner = JobRunner(store, Settings(), run_fn=fake_run())
    job_id = store.create("q", "quick")
    runner.submit(job_id, "q", "quick").result(timeout=5)

    job = store.get(job_id)
    assert job is not None
    assert job.status == "completed"
    assert RunResult.model_validate_json(job.result_json or "").question == "q"
    assert [e.type for _, e in store.events_after(job_id)] == ["agent_started", "job_completed"]
    runner.shutdown()


def test_a_failed_run_is_stored_with_its_error(store: JobStore) -> None:
    runner = JobRunner(store, Settings(), run_fn=fake_run("failed", "daily limit"))
    job_id = store.create("q", "quick")
    runner.submit(job_id, "q", "quick").result(timeout=5)
    job = store.get(job_id)
    assert job is not None
    assert (job.status, job.error) == ("failed", "daily limit")
    assert store.events_after(job_id)[-1][1].type == "job_failed"
    runner.shutdown()


def test_a_crash_marks_the_job_failed(store: JobStore) -> None:
    def crash(*args: object, **kwargs: object) -> RunResult:
        raise KeyError("bug")

    runner = JobRunner(store, Settings(), run_fn=crash)  # type: ignore[arg-type]
    job_id = store.create("q", "quick")
    runner.submit(job_id, "q", "quick").result(timeout=5)
    job = store.get(job_id)
    assert job is not None
    assert (job.status, job.error) == ("failed", "Internal error: KeyError")
    runner.shutdown()


def test_a_late_result_does_not_overwrite_a_timeout(store: JobStore) -> None:
    release = threading.Event()
    inner = fake_run()

    def slow(*args, **kwargs):  # type: ignore[no-untyped-def]
        release.wait(5)
        return inner(*args, **kwargs)

    runner = JobRunner(store, Settings(), run_fn=slow)
    job_id = store.create("q", "quick")
    future = runner.submit(job_id, "q", "quick")
    while store.get(job_id).status != "running":  # type: ignore[union-attr]
        pass
    store.fail(job_id, "Timed out")
    release.set()
    future.result(timeout=5)
    job = store.get(job_id)
    assert job is not None
    assert (job.status, job.error) == ("failed", "Timed out")
    assert [e.type for _, e in store.events_after(job_id)].count("job_completed") == 0
    runner.shutdown()


def test_jobs_wait_their_turn_with_one_worker(store: JobStore) -> None:
    release = threading.Event()
    inner = fake_run()

    def blocking(*args, **kwargs):  # type: ignore[no-untyped-def]
        release.wait(5)
        return inner(*args, **kwargs)

    runner = JobRunner(store, Settings(max_concurrent_jobs=1), run_fn=blocking)
    first, second = store.create("a", "quick"), store.create("b", "quick")
    f1, f2 = runner.submit(first, "a", "quick"), runner.submit(second, "b", "quick")
    while store.get(first).status != "running":  # type: ignore[union-attr]
        pass
    assert store.get(second).status == "queued"  # type: ignore[union-attr]
    release.set()
    f1.result(timeout=5)
    f2.result(timeout=5)
    assert store.get(second).status == "completed"  # type: ignore[union-attr]
    runner.shutdown()
