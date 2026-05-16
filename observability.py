from __future__ import annotations

import logging
import time
from collections import Counter

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("interview_prep")
request_counter: Counter[str] = Counter()
status_counter: Counter[int] = Counter()
total_latency_ms = 0.0


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        global total_latency_ms
        started = time.perf_counter()
        response = await call_next(request)
        latency_ms = (time.perf_counter() - started) * 1000
        total_latency_ms += latency_ms
        request_counter[request.url.path] += 1
        status_counter[response.status_code] += 1
        logger.info(
            "request method=%s path=%s status=%s latency_ms=%.2f",
            request.method,
            request.url.path,
            response.status_code,
            latency_ms,
        )
        return response


def metrics_snapshot() -> dict[str, object]:
    total_requests = sum(request_counter.values())
    avg_latency = total_latency_ms / total_requests if total_requests else 0.0
    return {
        "requests_total": total_requests,
        "requests_by_path": dict(request_counter),
        "responses_by_status": dict(status_counter),
        "avg_latency_ms": round(avg_latency, 2),
    }
