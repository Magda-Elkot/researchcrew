"""The frontend's HTTP client for the ResearchCrew API (no Streamlit code, so it is testable).

`follow` reads the SSE stream of a job and reconnects with `Last-Event-ID` if the connection
drops, so the progress feed neither stops nor repeats events.
"""

import json
from collections.abc import Iterable, Iterator
from itertools import chain
from typing import Any

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.log import get_logger

logger = get_logger(__name__)

FINAL_EVENTS = ("job_completed", "job_failed")
# The API sends a keep-alive comment every 15 s, so a 60 s silence means a dead connection.
STREAM_TIMEOUT = httpx.Timeout(10.0, read=60.0)


class FrontendSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # Where the frontend reaches the API (compose sets http://api:8000).
    api_url: str = "http://127.0.0.1:8000"


def parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, dict[str, Any]]]:
    """(id, data) per SSE event. An event is `field: value` lines ended by a blank line;
    lines starting with ":" are comments (keep-alive pings)."""
    fields: dict[str, str] = {}
    # chain(), not [*lines, ""]: a list would wait for the whole stream before the first event.
    for line in chain(lines, [""]):
        if line == "":
            if "data" in fields:
                yield fields.get("id", ""), json.loads(fields["data"])
            fields = {}
        elif not line.startswith(":"):
            name, _, value = line.partition(":")
            fields[name] = value.removeprefix(" ")


class ApiClient:
    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None) -> None:
        self.http = httpx.Client(base_url=base_url, timeout=10.0, transport=transport)

    def start(self, question: str, depth: str) -> str:
        response = self.http.post("/research", json={"question": question, "depth": depth})
        response.raise_for_status()
        job_id: str = response.json()["job_id"]
        return job_id

    def job(self, job_id: str) -> dict[str, Any]:
        response = self.http.get(f"/research/{job_id}")
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data

    def events(self, job_id: str, last_id: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
        headers = {"Last-Event-ID": last_id} if last_id else {}
        with self.http.stream(
            "GET", f"/research/{job_id}/events", headers=headers, timeout=STREAM_TIMEOUT
        ) as response:
            response.raise_for_status()
            yield from parse_sse(response.iter_lines())

    def follow(self, job_id: str, retries: int = 3) -> Iterator[dict[str, Any]]:
        """Every event of the job until the final one, reconnecting up to `retries` times."""
        last_id = ""
        failures = 0
        while True:
            try:
                for event_id, event in self.events(job_id, last_id):
                    last_id = event_id or last_id
                    failures = 0
                    yield event
                    if event.get("type") in FINAL_EVENTS:
                        return
                return  # the server ended the stream (the job had already ended)
            except httpx.TransportError as exc:  # includes dropped connections and timeouts
                failures += 1
                logger.warning(
                    "progress stream dropped",
                    extra={"job_id": job_id, "attempt": failures, "error": type(exc).__name__},
                )
                if failures > retries:
                    raise
