from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from soll.adapters.transcriber.base import Transcriber
from soll.adapters.vision.base import VisionDescriber
from soll.adapters.whatsapp.base import WhatsAppProvider
from soll.logging_setup import get_logger
from soll.schemas import (
    AudioContent,
    DocumentContent,
    FilteredPayload,
    ImageContent,
    TextContent,
    TextMessage,
    VideoContent,
)

log = get_logger(__name__)

AUDIO_FALLBACK = "[áudio inaudível]"
IMAGE_FALLBACK = "[imagem não processada]"
PDF_FALLBACK = "[documento PDF ilegível]"

PDF_MAX_PAGES = 10
PDF_MAX_BYTES = 5 * 1024 * 1024


class ConvertToText:
    """Converte um ContentMessage em TextMessage, normalizando mídia em texto."""

    def __init__(
        self,
        *,
        whatsapp_provider: WhatsAppProvider,
        transcriber: Transcriber,
        vision: VisionDescriber,
    ) -> None:
        self._provider = whatsapp_provider
        self._transcriber = transcriber
        self._vision = vision

    async def __call__(self, payload: FilteredPayload) -> TextMessage | None:
        ctx = {"user_number": payload.user_number, "message_id": payload.message_id}
        content = payload.content

        if isinstance(content, TextContent):
            return TextMessage(
                message_id=payload.message_id,
                user_number=payload.user_number,
                text=content.text,
                original_type="text",
            )

        if isinstance(content, AudioContent):
            text, meta = await self._handle_audio(content, ctx)
            return TextMessage(
                message_id=payload.message_id,
                user_number=payload.user_number,
                text=text,
                original_type="audio",
                metadata=meta,
            )

        if isinstance(content, ImageContent):
            text = await self._handle_image(content, ctx)
            return TextMessage(
                message_id=payload.message_id,
                user_number=payload.user_number,
                text=text,
                original_type="image",
                metadata={"single_view": content.single_view},
            )

        if isinstance(content, DocumentContent):
            text = await self._handle_document(content, ctx)
            if text is None:
                return None
            return TextMessage(
                message_id=payload.message_id,
                user_number=payload.user_number,
                text=text,
                original_type="document",
                metadata={"file_name": content.file_name or ""},
            )

        if isinstance(content, VideoContent):
            # TODO: extrair frames + áudio em paralelo. Hoje só transcreve via Whisper.
            text, meta = await self._handle_video(content, ctx)
            return TextMessage(
                message_id=payload.message_id,
                user_number=payload.user_number,
                text=text,
                original_type="video",
                metadata=meta,
            )

        return None

    async def _handle_audio(
        self, content: AudioContent, ctx: dict[str, str]
    ) -> tuple[str, dict[str, object]]:
        try:
            media = await self._provider.fetch_media(content.media)
            transcription = await self._transcriber.transcribe(
                data=media.data, mime_type=media.mime_type, filename="audio.ogg"
            )
        except Exception as exc:
            log.warning("convert.audio_failed", error=str(exc), **ctx)
            return AUDIO_FALLBACK, {"transcription_failed": True}

        if not transcription:
            log.info("convert.audio_empty", **ctx)
            return AUDIO_FALLBACK, {"transcription_empty": True}

        return transcription, {}

    async def _handle_image(self, content: ImageContent, ctx: dict[str, str]) -> str:
        if not content.media.url:
            log.warning("convert.image_no_url", **ctx)
            return f"{IMAGE_FALLBACK} {content.caption or ''}".strip()
        try:
            return await self._vision.describe(
                image_url=content.media.url, caption=content.caption
            )
        except Exception as exc:
            log.warning("convert.image_failed", error=str(exc), **ctx)
            fallback = IMAGE_FALLBACK
            if content.caption:
                fallback = f"{fallback} (legenda: {content.caption})"
            return fallback

    async def _handle_document(
        self, content: DocumentContent, ctx: dict[str, str]
    ) -> str | None:
        mime = (content.media.mime_type or "").lower()
        if mime != "application/pdf":
            log.info(
                "convert.document_discarded",
                mime_type=mime,
                file_name=content.file_name,
                **ctx,
            )
            return None

        try:
            media = await self._provider.fetch_media(content.media)
        except Exception as exc:
            log.warning("convert.pdf_fetch_failed", error=str(exc), **ctx)
            return PDF_FALLBACK

        truncated = False
        data = media.data
        if len(data) > PDF_MAX_BYTES:
            log.info(
                "convert.pdf_truncated_bytes", original=len(data), limit=PDF_MAX_BYTES, **ctx
            )
            data = data[:PDF_MAX_BYTES]
            truncated = True

        try:
            reader = PdfReader(BytesIO(data))
        except PdfReadError as exc:
            log.warning("convert.pdf_unreadable", error=str(exc), **ctx)
            return PDF_FALLBACK

        pages = reader.pages[:PDF_MAX_PAGES]
        if len(reader.pages) > PDF_MAX_PAGES:
            log.info(
                "convert.pdf_truncated_pages",
                total=len(reader.pages),
                limit=PDF_MAX_PAGES,
                **ctx,
            )
            truncated = True

        chunks = [page.extract_text() or "" for page in pages]
        text = "\n".join(chunk.strip() for chunk in chunks if chunk.strip())
        if not text:
            return PDF_FALLBACK

        prefix = f"te enviei um documento PDF chamado '{content.file_name or 'documento'}', com o seguinte conteúdo:\n"
        if truncated:
            prefix += "(conteúdo truncado)\n"
        return prefix + text

    async def _handle_video(
        self, content: VideoContent, ctx: dict[str, str]
    ) -> tuple[str, dict[str, object]]:
        try:
            media = await self._provider.fetch_media(content.media)
            transcription = await self._transcriber.transcribe(
                data=media.data, mime_type=media.mime_type, filename="video.mp4"
            )
        except Exception as exc:
            log.warning("convert.video_failed", error=str(exc), **ctx)
            fallback = AUDIO_FALLBACK
            if content.caption:
                fallback = f"{fallback} (legenda: {content.caption})"
            return fallback, {"transcription_failed": True}

        if not transcription:
            return AUDIO_FALLBACK, {"transcription_empty": True}

        if content.caption:
            transcription = f"{transcription}\n(legenda do vídeo: {content.caption})"
        return transcription, {}
