from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from soll.adapters.buffer_store.base import BufferEntry, BufferStore
from soll.logging_setup import get_logger
from soll.schemas import TextMessage

log = get_logger(__name__)

FlushCallback = Callable[[str, str], Awaitable[None]]
"""(user_number, combined_text) → None"""


class Buffer:
    """Debounce sobre um BufferStore. Identifica 'última mensagem' por message_id (não por texto)."""

    def __init__(
        self,
        *,
        store: BufferStore,
        debounce_seconds: float,
        max_messages: int,
        ttl_seconds: int,
    ) -> None:
        if debounce_seconds <= 0:
            raise ValueError("debounce_seconds must be > 0")
        if max_messages <= 0:
            raise ValueError("max_messages must be > 0")
        self._store = store
        self._debounce = debounce_seconds
        self._max = max_messages
        self._ttl = ttl_seconds

    async def add_and_process(self, message: TextMessage, callback: FlushCallback) -> None:
        entry = BufferEntry(message_id=message.message_id, text=message.text)
        ctx = {"user_number": message.user_number, "message_id": message.message_id}

        size = await self._store.append(message.user_number, entry, self._ttl)

        if size >= self._max:
            log.warning("buffer.flush_forced", size=size, limit=self._max, **ctx)
            await self._flush(message.user_number, callback)
            return

        await asyncio.sleep(self._debounce)

        last_id = await self._store.last_message_id(message.user_number)
        if last_id != message.message_id:
            log.debug("buffer.superseded", **ctx)
            return

        await self._flush(message.user_number, callback)

    async def _flush(self, user_number: str, callback: FlushCallback) -> None:
        entries = await self._store.drain(user_number)
        if not entries:
            return
        combined = "\n".join(e.text for e in entries if e.text)
        try:
            await callback(user_number, combined)
        except Exception as exc:
            log.error(
                "buffer.callback_failed",
                error=str(exc),
                user_number=user_number,
                count=len(entries),
            )
            await self._store.restore(user_number, entries, self._ttl)
            raise
