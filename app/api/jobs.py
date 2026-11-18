"""SQLite store for API jobs and their progress events (DECISIONS #85).

Two tables: `jobs` (one row per research request: status, timestamps, result JSON, error) and
`events` (every `ProgressEvent`, numbered by an autoincrement `seq`). The worker thread writes,
the SSE endpoint reads the events after the last `seq` it sent, so no in-memory queue is needed
and a client can reconnect.

Every method opens its own short connection (sqlite3 connections must not be shared between
threads); WAL mode lets readers and the writer work at the same time. Status changes are
conditional updates (`... WHERE status = 'running'`), so a late result can't overwrite a job that
was already marked failed by the timeout.
"""

import sqlite3
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from pydantic import AwareDatetime, BaseModel

from app.log import get_logger
from app.schemas import Depth, JobStatus, ProgressEvent, utc_now

logger = get_logger(__name__)

TERMINAL_STATUSES: tuple[JobStatus, ...] = ("completed", "failed")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    question    TEXT NOT NULL,
    depth       TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    result_json TEXT,
    error       TEXT
);
CREATE TABLE IF NOT EXISTS events (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT NOT NULL REFERENCES jobs(id),
    event_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_by_job ON events (job_id, seq);
"""


def _insert_event(db: sqlite3.Connection, event: ProgressEvent) -> int:
    cursor = db.execute(
        "INSERT INTO events (job_id, event_json) VALUES (?, ?)",
        (event.job_id, event.model_dump_json()),
    )
    return int(cursor.lastrowid or 0)


class JobRecord(BaseModel):
    """One row of the `jobs` table."""

    id: str
    question: str
    depth: Depth
    status: JobStatus
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    result_json: str | None = None
    error: str | None = None


class JobStore:
    """Jobs and events in one SQLite file."""

    def __init__(self, path: str | Path, now: Callable[[], datetime] = utc_now) -> None:
        self.path = Path(path)
        self.now = now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:  # commits on success, rolls back on error
                yield db
        finally:
            db.close()

    def _stamp(self) -> str:
        return self.now().isoformat()

    # --- jobs -----------------------------------------------------------------

    def create(self, question: str, depth: Depth) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._connect() as db:
            db.execute(
                "INSERT INTO jobs (id, question, depth, status, created_at) "
                "VALUES (?, ?, ?, 'queued', ?)",
                (job_id, question, depth, self._stamp()),
            )
        return job_id

    def get(self, job_id: str) -> JobRecord | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return JobRecord.model_validate(dict(row)) if row else None

    def start(self, job_id: str) -> bool:
        """queued → running. False if the job is no longer queued."""
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE jobs SET status = 'running', started_at = ? "
                "WHERE id = ? AND status = 'queued'",
                (self._stamp(), job_id),
            )
        return cursor.rowcount == 1

    def finish(
        self,
        job_id: str,
        status: JobStatus,
        result_json: str,
        error: str | None = None,
        events: Sequence[ProgressEvent] = (),
    ) -> bool:
        """running → completed/failed with the result and the final `events`, in one
        transaction: a reader never sees an ended job without its final event. False if the
        job had already ended (e.g. marked failed by the timeout): the late result is dropped."""
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE jobs SET status = ?, finished_at = ?, result_json = ?, error = ? "
                "WHERE id = ? AND status = 'running'",
                (status, self._stamp(), result_json, error, job_id),
            )
            if cursor.rowcount != 1:
                return False
            for event in events:
                _insert_event(db, event)
        return True

    def fail(self, job_id: str, error: str) -> bool:
        """Any unfinished state → failed, plus a `job_failed` event (one transaction).
        False if the job had already ended."""
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE jobs SET status = 'failed', finished_at = ?, error = ? "
                "WHERE id = ? AND status IN ('queued', 'running')",
                (self._stamp(), error, job_id),
            )
            if cursor.rowcount != 1:
                return False
            _insert_event(db, ProgressEvent(job_id=job_id, type="job_failed", message=error))
        return True

    def expire_overdue(self, max_running_s: float) -> list[str]:
        """Mark jobs running longer than `max_running_s` as failed; returns their ids."""
        with self._connect() as db:
            rows = db.execute("SELECT id, started_at FROM jobs WHERE status = 'running'").fetchall()
        now = self.now()
        expired = []
        for row in rows:
            started = datetime.fromisoformat(row["started_at"])
            if (now - started).total_seconds() > max_running_s and self.fail(
                row["id"], f"Timed out: no result after {round(max_running_s)} s."
            ):
                logger.warning("job timed out", extra={"job_id": row["id"]})
                expired.append(row["id"])
        return expired

    def fail_unfinished(self, reason: str) -> int:
        """At startup: jobs a previous process left queued/running can never finish."""
        with self._connect() as db:
            ids = [
                row["id"]
                for row in db.execute(
                    "SELECT id FROM jobs WHERE status IN ('queued', 'running')"
                ).fetchall()
            ]
        return sum(self.fail(job_id, reason) for job_id in ids)

    # --- events ---------------------------------------------------------------

    def add_event(self, event: ProgressEvent) -> int:
        with self._connect() as db:
            return _insert_event(db, event)

    def events_after(self, job_id: str, seq: int = 0) -> list[tuple[int, ProgressEvent]]:
        """Events of one job with a sequence number above `seq`, oldest first."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT seq, event_json FROM events WHERE job_id = ? AND seq > ? ORDER BY seq",
                (job_id, seq),
            ).fetchall()
        return [(row["seq"], ProgressEvent.model_validate_json(row["event_json"])) for row in rows]
