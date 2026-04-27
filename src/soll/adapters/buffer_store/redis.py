from __future__ import annotations

import json

from redis.asyncio import Redis

from soll.adapters.buffer_store.base import BufferEntry, BufferStore

_KEY_PREFIX = "soll:buffer"


def _key(user_number: str) -> str:
    return f"{_KEY_PREFIX}:{user_number}"


def _encode(entry: BufferEntry) -> bytes:
    return json.dumps({"id": entry.message_id, "t": entry.text}).encode("utf-8")


def _decode(raw: bytes) -> BufferEntry:
    payload = json.loads(raw.decode("utf-8"))
    return BufferEntry(message_id=payload["id"], text=payload["t"])


class RedisBufferStore(BufferStore):
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def append(self, user_number: str, entry: BufferEntry, ttl_seconds: int) -> int:
        key = _key(user_number)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.rpush(key, _encode(entry))
            pipe.expire(key, ttl_seconds)
            results = await pipe.execute()
        return int(results[0])

    async def last_message_id(self, user_number: str) -> str | None:
        raw = await self._redis.lindex(_key(user_number), -1)
        if raw is None:
            return None
        return _decode(raw).message_id

    async def drain(self, user_number: str) -> list[BufferEntry]:
        key = _key(user_number)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.lrange(key, 0, -1)
            pipe.delete(key)
            results = await pipe.execute()
        raw_entries = results[0] or []
        return [_decode(raw) for raw in raw_entries]

    async def restore(
        self, user_number: str, entries: list[BufferEntry], ttl_seconds: int
    ) -> None:
        if not entries:
            return
        key = _key(user_number)
        encoded = [_encode(e) for e in entries]
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.delete(key)
            pipe.rpush(key, *encoded)
            pipe.expire(key, ttl_seconds)
            await pipe.execute()

    async def length(self, user_number: str) -> int:
        return int(await self._redis.llen(_key(user_number)))
