"""Comando administrativo `/apagar .` — limpa o estado da conversa atual.

Apaga, para um `user_number`:
- O registro do lead no `LeadStore` (estado persistido entre turnos).
- O buffer de debounce no `BufferStore` (mensagens pendentes ainda não enviadas
  ao agente).
- (Opcional) O cache in-memory do `Agent` Agno via `agent_invalidator`, para que
  o histórico de conversa do agente seja resetado.

Não está documentado no Soll v6 — é utilitário de desenvolvimento/operação.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from soll.adapters.buffer_store.base import BufferStore
from soll.agent.lead_store import LeadStore
from soll.logging_setup import get_logger

log = get_logger(__name__)

CLEAR_COMMAND = "/apagar ."

AgentInvalidator = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class ClearResult:
    user_number: str
    lead_cleared: bool
    buffer_messages_dropped: int
    agent_invalidated: bool


def is_clear_command(text: str) -> bool:
    """True se o texto for exatamente o comando `/apagar .` (após strip)."""
    return text.strip() == CLEAR_COMMAND


async def clear_conversation(
    user_number: str,
    *,
    lead_store: LeadStore,
    buffer_store: BufferStore,
    agent_invalidator: AgentInvalidator | None = None,
) -> ClearResult:
    """Limpa o estado da conversa atual de `user_number`.

    `agent_invalidator` é opcional: passe uma callable que remova o `Agent`
    in-memory do cache do `SollAgent` (ex.: `lambda u: agent.forget(u)`).
    Sem ele, apenas o lead e o buffer são apagados — o histórico in-memory
    do Agno permanece até o próximo restart do processo.
    """
    lead_cleared = await lead_store.delete(user_number)
    entries = await buffer_store.drain(user_number)
    buffer_dropped = len(entries)

    agent_invalidated = False
    if agent_invalidator is not None:
        await agent_invalidator(user_number)
        agent_invalidated = True

    log.info(
        "core.clear_conversation",
        user_number=user_number,
        lead_cleared=lead_cleared,
        buffer_dropped=buffer_dropped,
        agent_invalidated=agent_invalidated,
    )
    return ClearResult(
        user_number=user_number,
        lead_cleared=lead_cleared,
        buffer_messages_dropped=buffer_dropped,
        agent_invalidated=agent_invalidated,
    )
