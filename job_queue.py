from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from observability import logger


try:
    from celery import Celery
except ModuleNotFoundError:
    Celery = None


CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "").strip()
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "").strip() or None

celery_app = (
    Celery("interview_prep", broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)
    if Celery is not None and CELERY_BROKER_URL
    else None
)


def queue_backend_name() -> str:
    return "celery" if celery_app is not None else "fastapi-background"


def enqueue(function: Callable[..., Any], *args: Any, **kwargs: Any) -> bool:
    if celery_app is None:
        return False
    task_name = f"{function.__module__}.{function.__name__}"
    celery_app.send_task(task_name, args=args, kwargs=kwargs)
    logger.info("queued_task backend=celery task=%s", task_name)
    return True
