"""In-process async pub/sub. The sim publishes world events; WebSocket clients
subscribe. Also keeps a ring buffer so a freshly-connected client can replay the
recent past and the town looks alive instantly."""
from __future__ import annotations

import asyncio
from collections import deque


class EventBus:
    def __init__(self, history: int = 200):
        self._subs: set[asyncio.Queue] = set()
        self._recent: deque = deque(maxlen=history)

    def publish(self, event: dict) -> None:
        self._recent.append(event)
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def recent(self) -> list[dict]:
        return list(self._recent)


BUS = EventBus()
