from __future__ import annotations

from typing import Literal, cast

import httpx

from soll.adapters.whatsapp.base import MediaContent, SendResult, WhatsAppProvider
from soll.logging_setup import get_logger
from soll.schemas import (
    AudioContent,
    ContentMessage,
    DocumentContent,
    FilteredPayload,
    ImageContent,
    MediaReference,
    MessageSender,
    StickerContent,
    TextContent,
    UnsupportedContent,
    VideoContent,
)

log = get_logger(__name__)

_SUPPORTED_KEYS = {"text", "image", "audio", "document", "video", "sticker"}


def _fix_brazilian_phone(phone: int | str) -> str:
    """Insere o nono dígito em números brasileiros legados de 12 caracteres.

    Z-API às vezes entrega sem o '9' adicional que celulares brasileiros passaram
    a ter. O dígito vai logo após o DDD (posição 5, índice 4).
    """
    num = str(phone)
    if len(num) == 12:
        return num[:4] + "9" + num[4:]
    return num


def _resolve_sender(*, from_me: bool, from_api: bool) -> MessageSender:
    if from_me and from_api:
        return "agent"
    if not from_me and not from_api:
        return "user"
    if from_me and not from_api:
        return "attendant"
    return "unknown"


def _parse_content(body: dict[str, object]) -> ContentMessage:
    msg_type = next((k for k in body if k in _SUPPORTED_KEYS), None)

    if msg_type == "text":
        text_block = cast(dict[str, object], body.get("text", {}))
        return TextContent(text=cast(str, text_block.get("message", "")))

    if msg_type == "image":
        image_block = cast(dict[str, object], body.get("image", {}))
        return ImageContent(
            media=MediaReference(
                url=cast(str | None, image_block.get("imageUrl")),
                mime_type=cast(str | None, image_block.get("mimeType")),
            ),
            caption=cast(str | None, image_block.get("caption")),
            single_view=bool(image_block.get("viewOnce", False)),
        )

    if msg_type == "audio":
        audio_block = cast(dict[str, object], body.get("audio", {}))
        return AudioContent(
            media=MediaReference(
                url=cast(str | None, audio_block.get("audioUrl")),
                mime_type=cast(str | None, audio_block.get("mimeType", "audio/ogg")),
            ),
        )

    if msg_type == "document":
        doc_block = cast(dict[str, object], body.get("document", {}))
        return DocumentContent(
            media=MediaReference(
                url=cast(str | None, doc_block.get("documentUrl")),
                mime_type=cast(str | None, doc_block.get("mimeType")),
            ),
            file_name=cast(str | None, doc_block.get("fileName")),
        )

    if msg_type == "video":
        video_block = cast(dict[str, object], body.get("video", {}))
        return VideoContent(
            media=MediaReference(
                url=cast(str | None, video_block.get("videoUrl")),
                mime_type=cast(str | None, video_block.get("mimeType")),
            ),
            caption=cast(str | None, video_block.get("caption")),
        )

    if msg_type == "sticker":
        sticker_block = cast(dict[str, object], body.get("sticker", {}))
        return StickerContent(
            media=MediaReference(
                url=cast(str | None, sticker_block.get("stickerUrl")),
                mime_type=cast(str | None, sticker_block.get("mimeType")),
            ),
        )

    return UnsupportedContent()


def parse_zapi_payload(body: dict[str, object]) -> FilteredPayload | None:
    """Converte payload bruto da Z-API em FilteredPayload normalizado.

    Retorna None se for evento administrativo (sem messageId, ou type != ReceivedCallback).
    """
    event_type = body.get("type")
    if event_type and event_type != "ReceivedCallback":
        return None

    message_id = cast(str | None, body.get("messageId"))
    if not message_id:
        return None

    is_edit = bool(body.get("isEdit", False))
    if is_edit:
        log.info("zapi.edit_ignored", message_id=message_id)
        return None

    return FilteredPayload(
        message_id=message_id,
        user_wpp_name=cast(str, body.get("senderName") or ""),
        user_number=_fix_brazilian_phone(cast(str | int, body.get("phone") or "")),
        message_sender=_resolve_sender(
            from_me=bool(body.get("fromMe", False)),
            from_api=bool(body.get("fromApi", False)),
        ),
        broadcast=bool(body.get("broadcast", False)),
        is_group=bool(body.get("isGroup", False)),
        is_forwarded=bool(body.get("forwarded", False)),
        is_edit=is_edit,
        content=_parse_content(body),
    )


class ZAPIProvider(WhatsAppProvider):
    """Implementação Z-API. Acesso a mídia = baixar URL pública do payload."""

    def __init__(
        self,
        *,
        instance_id: str,
        token: str,
        client_token: str,
        delay_typing: int = 3,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._instance_id = instance_id
        self._token = token
        self._client_token = client_token
        self._delay_typing = delay_typing
        self._http = http_client or httpx.AsyncClient(timeout=30.0)

    def parse_webhook(self, raw_body: dict[str, object]) -> FilteredPayload | None:
        return parse_zapi_payload(raw_body)

    async def fetch_media(self, ref: MediaReference) -> MediaContent:
        if not ref.url:
            raise ValueError("Z-API media reference must include `url`")
        response = await self._http.get(ref.url)
        response.raise_for_status()
        return MediaContent(
            data=response.content,
            mime_type=ref.mime_type or response.headers.get("content-type", "application/octet-stream"),
        )

    async def _send_payload(self, endpoint: Literal["text", "audio", "image"], payload: dict[str, object]) -> SendResult:
        url = (
            f"https://api.z-api.io/instances/{self._instance_id}"
            f"/token/{self._token}/send-{endpoint}"
        )
        headers = {"Client-Token": self._client_token}
        response = await self._http.post(url, json=payload, headers=headers)
        response.raise_for_status()
        body = response.json()
        return SendResult(
            message_id=cast(str, body.get("messageId", "")),
            status="sent",
        )

    async def send_text(self, to: str, text: str) -> SendResult:
        payload: dict[str, object] = {"phone": to, "message": text}
        if self._delay_typing > 0:
            payload["delayTyping"] = self._delay_typing
        return await self._send_payload("text", payload)

    async def send_audio(self, to: str, audio_url: str) -> SendResult:
        return await self._send_payload("audio", {"phone": to, "audio": audio_url})

    async def send_image(
        self, to: str, image_url: str, caption: str | None = None
    ) -> SendResult:
        payload: dict[str, object] = {"phone": to, "image": image_url}
        if caption:
            payload["caption"] = caption
        return await self._send_payload("image", payload)

    async def aclose(self) -> None:
        await self._http.aclose()
