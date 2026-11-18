"""The FastAPI app: startup checks, research endpoints, /health and Prometheus /metrics.

`create_app()` builds it (tests pass a fake `run_fn` instead of the real crew); the module-level
`app` is what uvicorn serves. The lifespan fails fast on a missing key, opens the SQLite job
store, marks jobs a previous process left unfinished as failed, and starts the job runner.
Serve it with ONE worker process: jobs run in this process's threads (DECISIONS #7, #86).
"""

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.agents.pipeline import run_research
from app.api.jobs import JobStore
from app.api.routes import router
from app.api.runner import JobRunner, RunFn
from app.config import get_settings, require
from app.log import get_logger
from app.observability import flush_tracing, setup_tracing

logger = get_logger(__name__)

# Keys a research run needs; missing ones stop the API at startup with the variable's name.
REQUIRED_KEYS: tuple[str, ...] = ("GROQ_API_KEY", "TAVILY_API_KEY")
RESTART_MESSAGE = "The server restarted before this job finished. Please submit it again."

REQUESTS = Counter("http_requests_total", "Total HTTP requests.", ["route", "status"])
LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency in seconds.", ["route", "status"]
)


def _route_label(request: Request) -> str:
    """Use the route template (e.g. /research/{id}) so label cardinality stays bounded."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


async def metrics_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    start = time.perf_counter()
    status = "500"
    try:
        response = await call_next(request)
        status = str(response.status_code)
        return response
    finally:
        route = _route_label(request)
        REQUESTS.labels(route=route, status=status).inc()
        LATENCY.labels(route=route, status=status).observe(time.perf_counter() - start)


async def health() -> dict[str, str]:
    return {"status": "ok", "version": get_settings().app_version}


async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def create_app(run_fn: RunFn = run_research) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Fail fast on missing configuration before serving any request."""
        require(*REQUIRED_KEYS)
        settings = get_settings()
        setup_tracing(settings)
        store = JobStore(settings.jobs_db_path)
        abandoned = store.fail_unfinished(RESTART_MESSAGE)
        runner = JobRunner(store, settings, run_fn)
        app.state.settings, app.state.store, app.state.runner = settings, store, runner
        logger.info(
            "api starting",
            extra={"version": settings.app_version, "abandoned_jobs": abandoned},
        )
        yield
        runner.shutdown()
        flush_tracing()
        logger.info("api stopping")

    app = FastAPI(title="ResearchCrew", version=get_settings().app_version, lifespan=lifespan)
    app.middleware("http")(metrics_middleware)
    app.include_router(router)
    app.add_api_route("/health", health, methods=["GET"])
    app.add_api_route("/metrics", metrics, methods=["GET"])
    return app


app = create_app()
