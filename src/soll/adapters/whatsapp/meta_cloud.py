from __future__ import annotations

from soll.adapters.whatsapp.base import MediaContent, SendResult, WhatsAppProvider
from soll.schemas import FilteredPayload, MediaReference


class MetaCloudProvider(WhatsAppProvider):
    """Skeleton para o futuro adapter da Meta Cloud API (WhatsApp Business Platform).

    Diferenças críticas em relação a Z-API:
      - Webhook entrega `media_id`, não URL pública.
      - Para baixar mídia: GET /{media_id} com Bearer → URL temporária; depois GET nessa URL.
      - Token tem expiração curta (~5min).
    """

    def parse_webhook(self, raw_body: dict[str, object]) -> FilteredPayload | None:
        raise NotImplementedError("MetaCloudProvider.parse_webhook não implementado nesta iteração")

    async def fetch_media(self, ref: MediaReference) -> MediaContent:
        raise NotImplementedError("MetaCloudProvider.fetch_media não implementado nesta iteração")

    async def send_text(self, to: str, text: str) -> SendResult:
        raise NotImplementedError

    async def send_audio(self, to: str, audio_url: str) -> SendResult:
        raise NotImplementedError

    async def send_image(
        self, to: str, image_url: str, caption: str | None = None
    ) -> SendResult:
        raise NotImplementedError
