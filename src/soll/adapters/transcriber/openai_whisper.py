from __future__ import annotations

from openai import AsyncOpenAI

from soll.adapters.transcriber.base import Transcriber


class OpenAIWhisperTranscriber(Transcriber):
    def __init__(self, *, client: AsyncOpenAI, model: str = "whisper-1") -> None:
        self._client = client
        self._model = model

    async def transcribe(
        self, *, data: bytes, mime_type: str, filename: str = "audio.ogg"
    ) -> str:
        result = await self._client.audio.transcriptions.create(
            model=self._model,
            file=(filename, data, mime_type),
        )
        return (result.text or "").strip()
