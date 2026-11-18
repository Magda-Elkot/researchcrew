"""Tests for the research endpoints and the SSE stream (the crew is a fake; no LLM, no MCP)."""

import json
import threading
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.pipeline import RunResult
from app.api.jobs import JobStore
from app.api.main import RESTART_MESSAGE, create_app
from app.config import Settings
from app.schemas import Citation, Depth, ProgressEvent, Report, Section, utc_now
from app.tools.guarded import EmitFn


def arabic_report() -> Report:
    return Report(
        title="الطاقة الشمسية",
        language="ar",
        executive_summary="انخفضت التكلفة [1].",
        sections=[Section(heading="التكلفة", body_markdown="انخفضت التكلفة [1].")],
        citations=[Citation(number=1, source="irena-2023", title="IRENA", evidence_id="sq1-e1")],
    )


class FakeCrew:
    """Emits two progress events, then waits for `release` (set at once unless a test holds it)."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.release.set()
        self.started = threading.Event()
        self.calls: list[tuple[str, Depth]] = []

    def __call__(
        self,
        question: str,
        depth: Depth,
        settings: Settings,
        emit: EmitFn | None = None,
        *,
        job_id: str | None = None,
    ) -> RunResult:
        assert emit is not None and job_id is not None
        self.calls.append((question, depth))
        emit(ProgressEvent(job_id=job_id, type="agent_started", agent="Planner", message="go"))
        self.started.set()
        self.release.wait(5)
        emit(ProgressEvent(job_id=job_id, type="agent_finished", agent="Planner", message="ok"))
        emit(ProgressEvent(job_id=job_id, type="job_completed", message="report ready"))
        report = arabic_report()
        return RunResult(
            job_id=job_id,
            status="completed",
            question=question,
            depth=depth,
            model="fake",
            report=report,
            citations=report.citations,
            cost_usd=0.01,
            latency_s=12.5,
            trace_id="b" * 32,
        )


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("SSE_POLL_INTERVAL_S", "0.01")


@pytest.fixture
def crew() -> FakeCrew:
    return FakeCrew()


@pytest.fixture
def client(crew: FakeCrew) -> Iterator[TestClient]:
    with TestClient(create_app(run_fn=crew)) as test_client:
        yield test_client


def sse_events(client: TestClient, job_id: str, **headers: str) -> list[tuple[str, dict[str, Any]]]:
    """(id, data) of every event on the stream, read until the server ends it.

    An SSE event is a block of `field: value` lines ended by a blank line, in any order."""
    events: list[tuple[str, dict[str, Any]]] = []
    fields: dict[str, str] = {}
    with client.stream("GET", f"/research/{job_id}/events", headers=headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in [*response.iter_lines(), ""]:
            if line == "":
                if "data" in fields:
                    events.append((fields.get("id", ""), json.loads(fields["data"])))
                fields = {}
            elif not line.startswith(":"):  # ": ping" keep-alive comments
                name, _, value = line.partition(": ")
                fields[name] = value
    return events


def test_post_returns_202_and_the_job_completes(client: TestClient, crew: FakeCrew) -> None:
    response = client.post("/research", json={"question": "  ما هي الطاقة؟ ", "depth": "deep"})
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    events = sse_events(client, job_id)
    assert [data["type"] for _, data in events] == [
        "agent_started",
        "agent_finished",
        "job_completed",
    ]
    assert all(data["job_id"] == job_id for _, data in events)
    assert set(events[0][1]) == {"job_id", "type", "agent", "message", "timestamp"}  # SPEC format
    assert crew.calls == [("ما هي الطاقة؟", "deep")]  # the question arrives stripped

    job = client.get(f"/research/{job_id}").json()
    assert job["status"] == "completed"
    assert (job["question"], job["depth"]) == ("ما هي الطاقة؟", "deep")
    assert job["report"]["title"] == "الطاقة الشمسية"
    assert job["citations"][0]["number"] == 1
    assert (job["cost_usd"], job["latency_s"]) == (0.01, 12.5)
    assert job["report_markdown"].startswith("# الطاقة الشمسية")
    assert "<div" not in job["report_markdown"]  # the frontend sets the direction itself
    assert job["trace_id"] == "b" * 32
    assert job["trace_url"] == "http://localhost:3000/trace/" + "b" * 32


def test_a_running_job_has_no_report_yet(client: TestClient, crew: FakeCrew) -> None:
    crew.release.clear()
    job_id = client.post("/research", json={"question": "q"}).json()["job_id"]
    assert crew.started.wait(5)
    job = client.get(f"/research/{job_id}").json()
    assert (job["status"], job["depth"], job["report"], job["report_markdown"]) == (
        "running",
        "quick",
        None,
        None,
    )
    crew.release.set()


def test_reconnecting_with_last_event_id_skips_seen_events(client: TestClient) -> None:
    job_id = client.post("/research", json={"question": "q"}).json()["job_id"]
    first_id = sse_events(client, job_id)[0][0]
    rest = sse_events(client, job_id, **{"Last-Event-ID": first_id})
    assert [data["type"] for _, data in rest] == ["agent_finished", "job_completed"]


def test_a_stream_opened_after_the_end_replays_and_stops(client: TestClient) -> None:
    job_id = client.post("/research", json={"question": "q"}).json()["job_id"]
    events = sse_events(client, job_id)
    last_id = events[-1][0]
    assert sse_events(client, job_id) == events  # replay from the start
    assert sse_events(client, job_id, **{"Last-Event-ID": last_id}) == []  # nothing left


def test_unknown_job_is_404(client: TestClient) -> None:
    assert client.get("/research/nope").status_code == 404
    assert client.get("/research/nope/events").status_code == 404


@pytest.mark.parametrize(
    "body",
    [{"question": ""}, {"question": "   "}, {"question": "q", "depth": "medium"}, {}],
)
def test_invalid_requests_are_422(client: TestClient, body: dict[str, str]) -> None:
    assert client.post("/research", json=body).status_code == 422


def test_an_overdue_job_is_failed_and_its_stream_ends(
    monkeypatch: pytest.MonkeyPatch, crew: FakeCrew
) -> None:
    monkeypatch.setenv("RUN_TIMEOUT_S", "1")
    monkeypatch.setenv("JOB_TIMEOUT_GRACE_S", "0")
    crew.release.clear()
    with TestClient(create_app(run_fn=crew)) as client:
        job_id = client.post("/research", json={"question": "q"}).json()["job_id"]
        assert crew.started.wait(5)
        store: JobStore = client.app.state.store  # type: ignore[attr-defined]
        later = utc_now() + timedelta(seconds=5)
        store.now = lambda: later  # five seconds pass

        events = sse_events(client, job_id)
        assert events[-1][1]["type"] == "job_failed"
        job = client.get(f"/research/{job_id}").json()
        assert job["status"] == "failed"
        assert job["error"] == "Timed out: no result after 1 s."
        crew.release.set()  # the late result is ignored
    with TestClient(create_app(run_fn=crew)) as client:
        assert client.get(f"/research/{job_id}").json()["status"] == "failed"


def test_jobs_left_unfinished_fail_at_startup(crew: FakeCrew) -> None:
    store = JobStore(Settings().jobs_db_path)
    job_id = store.create("q", "quick")
    with TestClient(create_app(run_fn=crew)) as client:
        job = client.get(f"/research/{job_id}").json()
    assert (job["status"], job["error"]) == ("failed", RESTART_MESSAGE)
