from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from soll.schemas import FilteredPayload, MediaReference


@dataclass(frozen=True)
class MediaContent:
    data: bytes
    mime_type: str
    filename: str | None = None


@dataclass(frozen=True)
class SendResult:
    message_id: str
    status: str


class WhatsAppProvider(ABC):
    """Contrato dos provedores de WhatsApp (Z-API, Meta Cloud API, etc)."""

    @abstractmethod
    def parse_webhook(self, raw_body: dict[str, object]) -> FilteredPayload | None:
        """Normaliza payload bruto em FilteredPayload.

        Retorna None para eventos que não são mensagens (delivery, presence, status, etc).
        """

    @abstractmethod
    async def fetch_media(self, ref: MediaReference) -> MediaContent:
        """Resolve uma MediaReference em bytes + mime_type."""

    @abstractmethod
    async def send_text(self, to: str, text: str) -> SendResult: ...

    @abstractmethod
    async def send_audio(self, to: str, audio_url: str) -> SendResult: ...

    @abstractmethod
    async def send_image(
        self, to: str, image_url: str, caption: str | None = None
    ) -> SendResult: ...
