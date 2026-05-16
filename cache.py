from __future__ import annotations

import json
import os
import time
from collections import defaultdict, deque
from typing import Any


try:
    import redis
except ModuleNotFoundError:
    redis = None


REDIS_URL = os.getenv("REDIS_URL", "").strip()
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "80"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

_memory_cache: dict[str, tuple[float, Any]] = {}
_memory_hits: dict[str, deque[float]] = defaultdict(deque)
_redis_client = None


def redis_client():
    global _redis_client
    if not REDIS_URL or redis is None:
        return None
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def cache_backend_name() -> str:
    return "redis" if redis_client() is not None else "memory"


def cache_get(key: str) -> Any | None:
    client = redis_client()
    if client is not None:
        raw = client.get(key)
        return json.loads(raw) if raw else None

    item = _memory_cache.get(key)
    if not item:
        return None
    expires_at, value = item
    if expires_at < time.time():
        _memory_cache.pop(key, None)
        return None
    return value


def cache_set(key: str, value: Any, ttl_seconds: int = 60) -> None:
    client = redis_client()
    if client is not None:
        client.setex(key, ttl_seconds, json.dumps(value))
        return
    _memory_cache[key] = (time.time() + ttl_seconds, value)


def rate_limit_allowed(identity: str) -> bool:
    key = f"rate:{identity}"
    client = redis_client()
    if client is not None:
        count = client.incr(key)
        if count == 1:
            client.expire(key, RATE_LIMIT_WINDOW_SECONDS)
        return int(count) <= RATE_LIMIT_REQUESTS

    now = time.time()
    hits = _memory_hits[key]
    while hits and hits[0] <= now - RATE_LIMIT_WINDOW_SECONDS:
        hits.popleft()
    if len(hits) >= RATE_LIMIT_REQUESTS:
        return False
    hits.append(now)
    return True
