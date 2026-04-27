from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MessageSender = Literal["user", "agent", "attendant", "unknown"]


class MediaReference(BaseModel):
    """Referência abstrata para mídia recebida via webhook.

    Z-API: `url` vem direto do payload (URL pública sem auth).
    Meta:  `media_id` vem do payload; provider resolve a URL temporária autenticada.
    """

    model_config = ConfigDict(frozen=True)

    url: str | None = None
    media_id: str | None = None
    mime_type: str | None = None


class TextContent(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImageContent(BaseModel):
    type: Literal["image"] = "image"
    media: MediaReference
    caption: str | None = None
    single_view: bool = False


class AudioContent(BaseModel):
    type: Literal["audio"] = "audio"
    media: MediaReference


class DocumentContent(BaseModel):
    type: Literal["document"] = "document"
    media: MediaReference
    file_name: str | None = None


class VideoContent(BaseModel):
    type: Literal["video"] = "video"
    media: MediaReference
    caption: str | None = None


class StickerContent(BaseModel):
    type: Literal["sticker"] = "sticker"
    media: MediaReference


class UnsupportedContent(BaseModel):
    type: Literal["unsupported"] = "unsupported"
    reason: str = "Tipo de mensagem não suportado"


ContentMessage = Annotated[
    TextContent
    | ImageContent
    | AudioContent
    | DocumentContent
    | VideoContent
    | StickerContent
    | UnsupportedContent,
    Field(discriminator="type"),
]


class FilteredPayload(BaseModel):
    """Saída do parser do provider, antes da regra de descarte (FilteredReturn)."""

    message_id: str
    user_wpp_name: str
    user_number: str
    message_sender: MessageSender
    broadcast: bool
    is_group: bool
    is_forwarded: bool = False
    is_edit: bool = False
    content: ContentMessage


class TextMessage(BaseModel):
    """Saída do ConvertToText: o `text` é o que entra no Buffer e depois no agente."""

    message_id: str
    user_number: str
    text: str
    original_type: Literal["text", "image", "audio", "document", "video"]
    metadata: dict[str, object] = Field(default_factory=dict)
