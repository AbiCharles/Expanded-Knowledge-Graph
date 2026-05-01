"""SSE event helper.

Each case has its own asyncio.Queue of events. The SSE endpoint pumps from
that queue. Producers (`emit`) and consumers (`stream`) live in different
asyncio tasks; the queue is the rendezvous.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class CaseEvent:
    """One event posted to the per-case stream.

    `kind` mirrors the framework's lineage stage names where possible,
    plus a few synthetic UI events:
        stage_bound | review_ready | decided | auto_approved | executed
        | clarification | cancelled | done
    """

    kind: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        return f"event: {self.kind}\ndata: {json.dumps(self.data, default=str)}\n\n"


class CaseEventBus:
    """Per-case fan-out. One producer, one consumer for now (the active SSE
    connection). Late subscribers don't replay history — the REST `GET /cases/{id}`
    fills that role."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[CaseEvent]] = {}
        self._closed: set[str] = set()

    def _queue(self, case_id: str) -> asyncio.Queue[CaseEvent]:
        if case_id not in self._queues:
            self._queues[case_id] = asyncio.Queue()
        return self._queues[case_id]

    async def emit(self, case_id: str, event: CaseEvent) -> None:
        if case_id in self._closed:
            return
        await self._queue(case_id).put(event)

    async def close(self, case_id: str) -> None:
        """Mark a case stream done. Consumers receive a sentinel event."""
        self._closed.add(case_id)
        await self._queue(case_id).put(CaseEvent(kind="done"))

    async def stream(self, case_id: str) -> AsyncIterator[CaseEvent]:
        queue = self._queue(case_id)
        while True:
            event = await queue.get()
            yield event
            if event.kind == "done":
                return
