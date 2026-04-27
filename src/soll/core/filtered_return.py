from __future__ import annotations

from soll.logging_setup import get_logger
from soll.schemas import (
    FilteredPayload,
    StickerContent,
    UnsupportedContent,
)

log = get_logger(__name__)


def filtered_return(payload: FilteredPayload) -> FilteredPayload | None:
    """Aplica regras de descarte. Retorna None quando a mensagem não deve seguir.

    Descarta:
    - Grupo
    - Broadcast
    - Eco do agente (mensagens enviadas pela própria instância via API)
    - Sender desconhecido
    - Tipo não suportado
    - Sticker isolado (stickers não levam caption no WhatsApp)
    - Mensagem do attendant (intervenção humana — TODO: pausar agente para esse lead)
    """
    ctx = {
        "user_number": payload.user_number,
        "message_id": payload.message_id,
    }

    if payload.is_group:
        log.info("filter.discarded", reason="group", **ctx)
        return None

    if payload.broadcast:
        log.info("filter.discarded", reason="broadcast", **ctx)
        return None

    if payload.message_sender == "agent":
        log.debug("filter.discarded", reason="agent_echo", **ctx)
        return None

    if payload.message_sender == "attendant":
        # TODO: marcar lead como "pausado" para o agente não responder durante intervenção humana.
        log.info("filter.discarded", reason="attendant_intervention", **ctx)
        return None

    if payload.message_sender == "unknown":
        log.info("filter.discarded", reason="unknown_sender", **ctx)
        return None

    if isinstance(payload.content, UnsupportedContent):
        log.info("filter.discarded", reason="unsupported_type", **ctx)
        return None

    if isinstance(payload.content, StickerContent):
        log.info("filter.discarded", reason="sticker_only", **ctx)
        return None

    return payload
