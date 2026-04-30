from __future__ import annotations

from typing import Any, Protocol


class LeadMirror(Protocol):
    """Espelha o estado do lead em um sink externo (planilha, CRM, etc.).

    O store primario (Redis/JSON) continua sendo a fonte da verdade. O mirror
    e best-effort: falha no destino nao pode quebrar o fluxo do agente.
    """

    async def upsert(self, user_number: str, lead: dict[str, Any]) -> None: ...

    async def aclose(self) -> None: ...


class NoOpLeadMirror:
    """Mirror desligado (para testes ou quando GOOGLE_SHEETS_ENABLED=false)."""

    async def upsert(self, user_number: str, lead: dict[str, Any]) -> None:
        return None

    async def aclose(self) -> None:
        return None
