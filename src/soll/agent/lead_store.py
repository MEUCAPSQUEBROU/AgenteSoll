from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from soll.logging_setup import get_logger

log = get_logger(__name__)

LeadData = dict[str, Any]


class LeadStore:
    """Persistencia simples de leads em JSON. Lock async garante leitura/escrita atomicas.

    Para a iteracao atual (fixtures de desenvolvimento). Sera substituido por um
    backend real (Postgres/Redis) quando o agente for pra producao.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def get(self, user_number: str) -> LeadData:
        async with self._lock:
            data = await self._load()
        return dict(data.get(user_number, {}))

    async def upsert_field(self, user_number: str, campo: str, valor: Any) -> LeadData:
        async with self._lock:
            data = await self._load()
            lead = dict(data.get(user_number, {}))
            lead[campo] = valor
            data[user_number] = lead
            await self._save(data)
        log.info("lead_store.upsert", user_number=user_number, campo=campo)
        return lead

    async def _load(self) -> dict[str, LeadData]:
        if not self._path.exists():
            return {}
        text = await asyncio.to_thread(self._path.read_text, encoding="utf-8")
        if not text.strip():
            return {}
        parsed: dict[str, LeadData] = json.loads(text)
        return parsed

    async def _save(self, data: dict[str, LeadData]) -> None:
        text = json.dumps(data, ensure_ascii=False, indent=2)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._path.write_text, text, encoding="utf-8")
