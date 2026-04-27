from __future__ import annotations

from abc import ABC, abstractmethod


class Transcriber(ABC):
    @abstractmethod
    async def transcribe(self, *, data: bytes, mime_type: str, filename: str = "audio.ogg") -> str:
        """Transcreve áudio em texto. Retorna string vazia em silêncio total."""
