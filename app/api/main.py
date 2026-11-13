"""Placeholder FastAPI app for Phase 1: startup key check, /health and Prometheus /metrics."""

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.config import get_settings, require
from app.log import get_logger

logger = get_logger(__name__)

# Keys the API needs at startup. Empty in Phase 1; Phase 3/4 add e.g. "GROQ_API_KEY".
REQUIRED_KEYS: tuple[str, ...] = ()

REQUESTS = Counter("http_requests_total", "Total HTTP requests.", ["route", "status"])
LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency in seconds.", ["route", "status"]
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Fail fast on missing configuration before serving any request."""
    require(*REQUIRED_KEYS)
    logger.info("api starting", extra={"version": get_settings().app_version})
    yield
    logger.info("api stopping")


app = FastAPI(title="ResearchCrew", version=get_settings().app_version, lifespan=lifespan)


def _route_label(request: Request) -> str:
    """Use the route template (e.g. /research/{id}) so label cardinality stays bounded."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


@app.middleware("http")
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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": get_settings().app_version}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
