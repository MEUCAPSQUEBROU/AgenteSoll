from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class BufferEntry:
    message_id: str
    text: str


class BufferStore(ABC):
    """Backend de armazenamento para o buffer de debounce."""

    @abstractmethod
    async def append(self, user_number: str, entry: BufferEntry, ttl_seconds: int) -> int:
        """Adiciona entry e retorna o tamanho atual da lista do usuário."""

    @abstractmethod
    async def last_message_id(self, user_number: str) -> str | None:
        """Retorna o message_id do último item da lista (ou None se vazia)."""

    @abstractmethod
    async def drain(self, user_number: str) -> list[BufferEntry]:
        """Lê e remove todas as entries do usuário."""

    @abstractmethod
    async def restore(self, user_number: str, entries: list[BufferEntry], ttl_seconds: int) -> None:
        """Reescreve a lista do usuário (usado para retry após falha do callback)."""

    @abstractmethod
    async def length(self, user_number: str) -> int: ...
