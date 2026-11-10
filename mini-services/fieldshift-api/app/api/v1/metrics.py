"""Prometheus metrics exposition (P2 observability).

``GET /api/v1/metrics`` returns the in-process counters/gauges/histograms in
Prometheus text exposition format (0.0.4), dependency-free. Intentionally
unauthenticated: the API binds to 127.0.0.1 in the sandbox and only route
templates are used as labels, so nothing user-identifying is exported.
Production deployments that expose this path publicly should front it with
network-level restrictions or a scrape-auth proxy.
"""

from fastapi import APIRouter, Response

from app.data_platform.observability import render_prometheus

router = APIRouter(tags=["observability"])


@router.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    return Response(
        content=render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
