from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any


class EventHub:
    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)

    def subscribe(self, conversation_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subs[conversation_id].append(queue)
        return queue

    def unsubscribe(self, conversation_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        listeners = self._subs.get(conversation_id, [])
        if queue in listeners:
            listeners.remove(queue)
        if not listeners:
            self._subs.pop(conversation_id, None)

    async def publish(self, conversation_id: str, event: dict[str, Any]) -> None:
        for queue in list(self._subs.get(conversation_id, [])):
            await queue.put(event)

    def format_sse(self, event: dict[str, Any]) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
