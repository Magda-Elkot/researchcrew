"""Research endpoints: start a job, read it, follow its progress with Server-Sent Events.

- `POST /research` stores a `queued` job and hands it to the runner (202 + job id).
- `GET /research/{id}` returns status, report (also as Markdown), citations, usage, cost.
- `GET /research/{id}/events` streams the job's `ProgressEvent`s as SSE (`id:` = event number,
  so a reconnecting client resumes with `Last-Event-ID`); the stream ends with the final event.

Before a job is read, overdue jobs are marked failed (the timeout, DECISIONS #87).
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.agents.pipeline import RunResult
from app.agents.report import to_markdown
from app.api.jobs import TERMINAL_STATUSES, JobRecord, JobStore
from app.api.runner import FINAL_EVENTS, JobRunner
from app.config import Settings
from app.schemas import Depth, JobCreated, JobResult, ResearchRequest

router = APIRouter(prefix="/research", tags=["research"])


class JobView(JobResult):
    """GET /research/{id}: the SPEC's JobResult plus what the frontend shows."""

    question: str
    depth: Depth
    created_at: datetime
    report_markdown: str | None = None


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _store(request: Request) -> JobStore:
    store: JobStore = request.app.state.store
    store.expire_overdue(_settings(request).run_timeout_s + _settings(request).job_timeout_grace_s)
    return store


def _runner(request: Request) -> JobRunner:
    runner: JobRunner = request.app.state.runner
    return runner


StoreDep = Annotated[JobStore, Depends(_store)]


def _job(job_id: str, store: StoreDep) -> JobRecord:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id!r}")
    return job


JobDep = Annotated[JobRecord, Depends(_job)]


@router.post("", status_code=202)
def create_job(
    body: ResearchRequest, store: StoreDep, runner: Annotated[JobRunner, Depends(_runner)]
) -> JobCreated:
    job_id = store.create(body.question, body.depth)
    runner.submit(job_id, body.question, body.depth)
    return JobCreated(job_id=job_id)


@router.get("/{job_id}")
def get_job(job: JobDep) -> JobView:
    view: dict[str, object] = {
        "job_id": job.id,
        "question": job.question,
        "depth": job.depth,
        "created_at": job.created_at,
        "status": job.status,  # the job row decides (e.g. a timeout after the result)
        "error": job.error,
    }
    if job.result_json is not None:
        result = RunResult.model_validate_json(job.result_json)
        for name in ("report", "citations", "token_usage", "cost_usd", "latency_s"):
            view[name] = getattr(result, name)
        if result.report is not None:
            view["report_markdown"] = to_markdown(result.report, rtl_wrapper=False)
    return JobView.model_validate(view)


@router.get("/{job_id}/events", response_class=EventSourceResponse)
async def job_events(
    job: JobDep,
    request: Request,
    last_event_id: Annotated[int | None, Header()] = None,
) -> AsyncIterator[ServerSentEvent]:
    store: JobStore = request.app.state.store
    max_running = _settings(request).run_timeout_s + _settings(request).job_timeout_grace_s
    poll_s = _settings(request).sse_poll_interval_s
    seen = last_event_id or 0
    while True:
        # Local SQLite reads take well under a millisecond, so they run on the event loop.
        store.expire_overdue(max_running)
        current = store.get(job.id)
        ended = current is None or current.status in TERMINAL_STATUSES
        # Read events *after* the status: the final event is saved in the same transaction
        # as the end status, so once `ended` is seen, this read includes it.
        for seq, event in store.events_after(job.id, seen):
            seen = seq
            yield ServerSentEvent(data=event, id=str(seq))
            if event.type in FINAL_EVENTS:
                return
        if ended:
            return  # its final event was sent before (a reconnect after the end)
        await asyncio.sleep(poll_s)
