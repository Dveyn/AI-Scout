from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

logger = logging.getLogger(__name__)

_subscribers: list[asyncio.Queue[dict[str, Any]]] = []


def publish_event(event_type: str, payload: dict[str, Any] | None = None) -> None:
    message = {"type": event_type, "payload": payload or {}}
    for queue in list(_subscribers):
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            pass


async def event_stream() -> AsyncGenerator[str, None]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
    _subscribers.append(queue)
    try:
        yield f"data: {json.dumps({'type': 'connected'})}\n\n"
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"
    finally:
        if queue in _subscribers:
            _subscribers.remove(queue)
