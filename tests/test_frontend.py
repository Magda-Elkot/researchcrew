"""Tests for the frontend: the SSE client (mock HTTP transport) and the page (Streamlit AppTest)."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from frontend.client import ApiClient, parse_sse

APP = str(Path(__file__).parents[1] / "frontend" / "streamlit_app.py")


def sse(*events: tuple[int, str]) -> str:
    return "".join(f'data: {{"type": "{t}", "message": "m"}}\nid: {i}\n\n' for i, t in events)


def test_parse_sse_reads_blocks_and_skips_comments() -> None:
    lines = [": ping", "", 'data: {"type": "a"}', "id: 7", "", "id: 8", 'data:{"type": "b"}']
    assert list(parse_sse(lines)) == [("7", {"type": "a"}), ("8", {"type": "b"})]


def test_parse_sse_yields_each_event_as_soon_as_it_is_complete() -> None:
    def lines() -> Iterator[str]:
        yield from ['data: {"type": "a"}', ""]
        raise AssertionError("read past the first event")

    assert next(parse_sse(lines())) == ("", {"type": "a"})


def test_start_and_job() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert json.loads(request.content) == {"question": "q", "depth": "deep"}
            return httpx.Response(202, json={"job_id": "j1"})
        return httpx.Response(200, json={"job_id": "j1", "status": "running"})

    client = ApiClient("http://api", transport=httpx.MockTransport(handle))
    assert client.start("q", "deep") == "j1"
    assert client.job("j1")["status"] == "running"


def test_follow_reconnects_after_a_drop_and_resumes_from_the_last_id() -> None:
    seen_headers: list[str | None] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("last-event-id"))
        if len(seen_headers) == 1:
            # Event 1 arrives whole, then the connection drops in the middle of event 2.
            partial = sse((1, "agent_started")) + 'data: {"type": "agent_fini'
            return httpx.Response(200, stream=Dropping(partial))
        return httpx.Response(200, text=sse((2, "agent_finished"), (3, "job_completed")))

    client = ApiClient("http://api", transport=httpx.MockTransport(handle))
    types = [event["type"] for event in client.follow("j1")]
    assert types == ["agent_started", "agent_finished", "job_completed"]
    assert seen_headers == [None, "1"]


def test_follow_gives_up_after_the_retries() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("api down")

    client = ApiClient("http://api", transport=httpx.MockTransport(handle))
    with pytest.raises(httpx.ConnectError):
        list(client.follow("j1", retries=2))


class Dropping(httpx.SyncByteStream):
    """Sends some bytes, then fails like a dropped connection."""

    def __init__(self, text: str) -> None:
        self.text = text

    def __iter__(self) -> Iterator[bytes]:
        yield self.text.encode()
        raise httpx.ReadError("connection dropped")


# --- the page -------------------------------------------------------------------------


def done_job(language: str) -> dict[str, Any]:
    return {
        "job_id": "j1",
        "status": "completed",
        "question": "q",
        "depth": "quick",
        "report": {"language": language},
        "report_markdown": "# العنوان\n\nنص [1].\n\n<script>alert(1)</script>",
        "citations": [{"number": 1}],
        "token_usage": {"total_tokens": 53039},
        "cost_usd": 0.0106,
        "latency_s": 428.3,
        "error": None,
    }


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"job": done_job("ar")}
    events = [
        {"type": "agent_started", "agent": "Researcher", "message": "started"},
        {"type": "job_completed", "agent": None, "message": "report ready"},
    ]
    monkeypatch.setattr(ApiClient, "job", lambda self, job_id: state["job"])
    monkeypatch.setattr(ApiClient, "follow", lambda self, job_id, retries=3: iter(events))
    monkeypatch.setattr(ApiClient, "start", lambda self, q, d: "j1")
    return state


def test_the_page_starts_with_an_empty_form() -> None:
    page = AppTest.from_file(APP).run()
    assert not page.exception
    assert page.title[0].value == "ResearchCrew"
    assert page.text_area[0].value is None or page.text_area[0].value == ""
    assert page.radio[0].value == "quick"


def test_submitting_shows_progress_and_an_rtl_report(fake_api: dict[str, Any]) -> None:
    page = AppTest.from_file(APP).run()
    page.text_area[0].input("ما هي الطاقة؟")
    page.button[0].click().run()
    assert not page.exception
    assert page.session_state["job_id"] == "j1"
    feed = [t.value for t in page.text]
    assert feed == ["▶ Researcher: started", "✅ report ready"]
    [report] = [m for m in page.markdown if m.value.startswith("# العنوان")]
    assert report.proto.allow_html is False  # model/web text can't inject HTML
    assert [metric.value for metric in page.metric] == ["1", "53,039", "$0.0106", "428 s"]


def test_a_failed_job_shows_its_error(fake_api: dict[str, Any]) -> None:
    fake_api["job"] = {**done_job("en"), "status": "failed", "error": "Daily limit reached."}
    page = AppTest.from_file(APP)
    page.session_state["job_id"] = "j1"
    page.run()
    assert not page.exception
    assert page.error[0].value == "Daily limit reached."


def test_no_frontend_file_shadows_a_project_package() -> None:
    # Streamlit puts frontend/ first on sys.path: a frontend/app.py would replace our `app`
    # package for every import (this broke the page once; pytest had `app` imported already).
    folder = Path(APP).parent
    assert not any((folder / f"{name}.py").exists() for name in ("app", "mcp_servers"))
