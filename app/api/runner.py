"""Runs research jobs in background worker threads (DECISIONS #86-87).

`run_research` blocks for minutes, so it can't run on FastAPI's event loop. A
`ThreadPoolExecutor` with `MAX_CONCURRENT_JOBS` workers (default 1) runs one job at a time;
later jobs wait in its queue with the status `queued`.

Progress events go straight into the job store, except the final `job_completed`/`job_failed`:
those are held back and saved together with the result (one transaction), so a client that
reacts to the final event always finds the result with GET.
"""

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Protocol

from app.agents.pipeline import RunResult, run_research
from app.api.jobs import JobStore
from app.config import Settings
from app.log import get_logger
from app.schemas import Depth, EventType, ProgressEvent
from app.tools.guarded import EmitFn

logger = get_logger(__name__)

FINAL_EVENTS: tuple[EventType, ...] = ("job_completed", "job_failed")


class RunFn(Protocol):
    """The part of `run_research` the runner uses (tests pass a fake)."""

    def __call__(
        self,
        question: str,
        depth: Depth,
        settings: Settings,
        emit: EmitFn | None = None,
        *,
        job_id: str | None = None,
    ) -> RunResult: ...


class JobRunner:
    """Owns the worker threads; `submit` returns at once."""

    def __init__(self, store: JobStore, settings: Settings, run_fn: RunFn = run_research) -> None:
        self.store = store
        self.settings = settings
        self.run_fn = run_fn
        self._pool = ThreadPoolExecutor(
            max_workers=settings.max_concurrent_jobs, thread_name_prefix="crew"
        )

    def submit(self, job_id: str, question: str, depth: Depth) -> Future[None]:
        return self._pool.submit(self._run, job_id, question, depth)

    def shutdown(self) -> None:
        """Drop queued jobs; a running crew can't be stopped and ends with the process."""
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _run(self, job_id: str, question: str, depth: Depth) -> None:
        if not self.store.start(job_id):
            return  # no longer queued (e.g. failed at a restart)
        held: list[ProgressEvent] = []

        def emit(event: ProgressEvent) -> None:
            if event.type in FINAL_EVENTS:
                held.append(event)
                return
            try:
                self.store.add_event(event)
            except Exception:  # a lost progress event must not stop the research run
                logger.exception("could not save progress event", extra={"job_id": job_id})

        try:
            result = self.run_fn(question, depth, self.settings, emit, job_id=job_id)
        except Exception as exc:  # run_research never raises; this guards against bugs
            logger.exception("job crashed", extra={"job_id": job_id})
            self.store.fail(job_id, f"Internal error: {type(exc).__name__}")
            return

        if not held:  # the pipeline always emits one, but the stream must end either way
            final: EventType = "job_completed" if result.status == "completed" else "job_failed"
            held.append(ProgressEvent(job_id=job_id, type=final, message=result.error or "done"))
        saved = self.store.finish(
            job_id, result.status, result.model_dump_json(), result.error, events=held
        )
        if not saved:
            logger.warning("result arrived after the job had ended", extra={"job_id": job_id})
