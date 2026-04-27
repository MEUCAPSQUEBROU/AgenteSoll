from __future__ import annotations

import asyncio
from collections import defaultdict

from soll.adapters.buffer_store.base import BufferEntry, BufferStore


class InMemoryBufferStore(BufferStore):
    """Backend em memória para testes. Não usar em produção."""

    def __init__(self) -> None:
        self._data: dict[str, list[BufferEntry]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def append(self, user_number: str, entry: BufferEntry, ttl_seconds: int) -> int:
        async with self._lock:
            self._data[user_number].append(entry)
            return len(self._data[user_number])

    async def last_message_id(self, user_number: str) -> str | None:
        async with self._lock:
            entries = self._data.get(user_number)
            if not entries:
                return None
            return entries[-1].message_id

    async def drain(self, user_number: str) -> list[BufferEntry]:
        async with self._lock:
            entries = self._data.pop(user_number, [])
            return list(entries)

    async def restore(
        self, user_number: str, entries: list[BufferEntry], ttl_seconds: int
    ) -> None:
        async with self._lock:
            self._data[user_number] = list(entries)

    async def length(self, user_number: str) -> int:
        async with self._lock:
            return len(self._data.get(user_number, []))
