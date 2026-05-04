from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import ValueInputOption, rowcol_to_a1
from gspread.worksheet import Worksheet

from soll.adapters.sheets.base import LeadMirror
from soll.logging_setup import get_logger

log = get_logger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

_ID_COLUMN = "id"
_TELEFONE_COLUMN = "telefone"
_DDD_COLUMN = "ddd"
_CREATED_AT = "created_at"
_UPDATED_AT = "updated_at"
_STATUS_COLUMN = "status"
_ETAPA_FUNIL = "etapa_funil"

_LEAD_ID_PREFIX = "SOLL-"
_LEAD_ID_PAD = 6
_LEAD_ID_PATTERN = re.compile(rf"^{_LEAD_ID_PREFIX}(\d+)$")

_BRAZIL_DDI = "55"
_BRAZIL_E164_LENGTH = 13

# Derivação de `status` a partir de `etapa_funil`. Tudo que não for terminal
# (AGENDADO/TRANSFERIDO/ENCERRADO) conta como EM_ATENDIMENTO. Sem `etapa_funil`,
# é lead novo que ainda não entrou no fluxo.
_TERMINAL_STATUS = {
    "AGENDADO": "AGENDADO",
    "TRANSFERIDO": "TRANSFERIDO",
    "ENCERRADO": "ENCERRADO",
}


def _derive_status(etapa_funil: Any) -> str:
    if not etapa_funil:
        return "NOVO"
    return _TERMINAL_STATUS.get(str(etapa_funil), "EM_ATENDIMENTO")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_brazilian_phone(user_number: str) -> tuple[str, str] | None:
    """Decompoe `user_number` E.164 brasileiro em (ddd, telefone_com_ddd).

    Espera formato `55 + DDD(2) + numero(9)` totalizando 13 digitos.
    Retorna None pra qualquer outro formato (ex: `cli-user`).
    """
    digits = user_number.strip()
    if (
        not digits.isdigit()
        or len(digits) != _BRAZIL_E164_LENGTH
        or not digits.startswith(_BRAZIL_DDI)
    ):
        return None
    return digits[2:4], digits[2:]


def _next_lead_id(existing_ids: list[Any]) -> str:
    max_seq = 0
    for raw in existing_ids:
        if not isinstance(raw, str):
            continue
        match = _LEAD_ID_PATTERN.match(raw)
        if match:
            max_seq = max(max_seq, int(match.group(1)))
    return f"{_LEAD_ID_PREFIX}{max_seq + 1:0{_LEAD_ID_PAD}d}"


class GSpreadLeadMirror(LeadMirror):
    """Espelha leads numa Google Sheet via gspread.

    Estrategia de upsert: lookup por `telefone` (DDD+numero, derivado do
    `user_number`). Se encontrou, atualiza so as celulas dos campos presentes
    no `lead`. Se nao, faz append e gera `id` no formato `SOLL-XXXXXX`.

    Apenas chaves cujo nome esta no header da aba sao escritas; campos extras
    sao ignorados silenciosamente. Timestamps `created_at`/`updated_at` e
    `id`/`telefone`/`ddd` sao preenchidos automaticamente quando essas colunas
    existem no header.
    """

    def __init__(
        self,
        *,
        credentials_path: Path,
        spreadsheet_id: str,
        worksheet_name: str,
    ) -> None:
        self._credentials_path = credentials_path
        self._spreadsheet_id = spreadsheet_id
        self._worksheet_name = worksheet_name
        self._lock = asyncio.Lock()
        self._worksheet: Worksheet | None = None
        self._header: list[str] | None = None
        self._col_index: dict[str, int] = {}

    async def _ensure_connected(self) -> Worksheet:
        if self._worksheet is not None:
            return self._worksheet
        ws = await asyncio.to_thread(self._connect_sync)
        header = await asyncio.to_thread(ws.row_values, 1)
        self._worksheet = ws
        self._header = header
        self._col_index = {name: idx + 1 for idx, name in enumerate(header) if name}
        log.info(
            "sheets.connected",
            spreadsheet_id=self._spreadsheet_id,
            worksheet=self._worksheet_name,
            columns=len(header),
        )
        return ws

    def _connect_sync(self) -> Worksheet:
        creds: Credentials = Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
            str(self._credentials_path), scopes=_SCOPES
        )
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(self._spreadsheet_id)
        return spreadsheet.worksheet(self._worksheet_name)

    async def upsert(self, user_number: str, lead: dict[str, Any]) -> None:
        try:
            async with self._lock:
                ws = await self._ensure_connected()
                await asyncio.to_thread(self._upsert_sync, ws, user_number, lead)
        except Exception as exc:
            log.warning(
                "sheets.upsert_failed",
                user_number=user_number,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    def _upsert_sync(
        self, ws: Worksheet, user_number: str, lead: dict[str, Any]
    ) -> None:
        parsed = _parse_brazilian_phone(user_number)
        if parsed is None:
            log.warning("sheets.invalid_user_number", user_number=user_number)
            return
        ddd, telefone = parsed

        telefone_col = self._col_index.get(_TELEFONE_COLUMN)
        if telefone_col is None:
            log.warning("sheets.no_telefone_column", header=self._header)
            return

        telefones = ws.col_values(telefone_col)
        try:
            row_num = telefones.index(telefone) + 1
        except ValueError:
            row_num = 0

        now = _now_iso()
        payload = {**lead, _TELEFONE_COLUMN: telefone, _DDD_COLUMN: ddd}

        if row_num == 0:
            id_col = self._col_index.get(_ID_COLUMN)
            if id_col is not None:
                existing_ids = ws.col_values(id_col)
                payload[_ID_COLUMN] = _next_lead_id(existing_ids)
            payload.setdefault(_CREATED_AT, now)
        payload[_UPDATED_AT] = now
        if _STATUS_COLUMN in self._col_index:
            payload[_STATUS_COLUMN] = _derive_status(payload.get(_ETAPA_FUNIL))

        if row_num == 0:
            assert self._header is not None
            row = [str(payload.get(col, "")) for col in self._header]
            ws.append_row(row, value_input_option=ValueInputOption.user_entered)
            log.info(
                "sheets.appended",
                user_number=user_number,
                lead_id=payload.get(_ID_COLUMN),
                fields=len(payload),
            )
            return

        updates: list[dict[str, Any]] = []
        for field, value in payload.items():
            col_idx = self._col_index.get(field)
            if col_idx is None:
                continue
            updates.append(
                {
                    "range": rowcol_to_a1(row_num, col_idx),
                    "values": [[str(value) if value is not None else ""]],
                }
            )
        if updates:
            ws.batch_update(updates, value_input_option=ValueInputOption.user_entered)
            log.info(
                "sheets.updated",
                user_number=user_number,
                row=row_num,
                fields=len(updates),
            )

    async def aclose(self) -> None:
        self._worksheet = None
        self._header = None
        self._col_index = {}
