from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from soll.logging_setup import get_logger

log = get_logger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


class SheetsImagesStore:
    """Lookup do catalogo de imagens via Google Sheets.

    Le a aba uma unica vez (lazy, no primeiro `get`) e mantem em memoria pelo
    resto da vida do processo. Pra refletir mudancas na planilha, restart no
    container.

    Schema esperado da aba (header na primeira linha):
        | id | descricao | filename |

    A URL final servida ao Z-API e composta como `{base_url}/images/{filename}`.
    """

    def __init__(
        self,
        *,
        credentials_path: Path,
        spreadsheet_id: str,
        worksheet_name: str,
        base_url: str,
    ) -> None:
        self._credentials_path = credentials_path
        self._spreadsheet_id = spreadsheet_id
        self._worksheet_name = worksheet_name
        self._base_url = base_url.rstrip("/")
        self._lock = asyncio.Lock()
        self._cache: dict[str, dict[str, Any]] | None = None

    async def get(self, image_id: str) -> dict[str, Any] | None:
        cache = await self._ensure_loaded()
        return cache.get(image_id)

    async def _ensure_loaded(self) -> dict[str, dict[str, Any]]:
        if self._cache is not None:
            return self._cache
        async with self._lock:
            if self._cache is not None:
                return self._cache
            try:
                rows = await asyncio.to_thread(self._load_sync)
            except Exception as exc:
                log.warning(
                    "images.load_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                self._cache = {}
                return self._cache
            built: dict[str, dict[str, Any]] = {}
            for row in rows:
                image_id = str(row.get("id") or "").strip()
                filename = str(row.get("filename") or "").strip()
                if not image_id or not filename:
                    continue
                built[image_id] = {
                    "id": image_id,
                    "descricao": str(row.get("descricao") or "").strip(),
                    "filename": filename,
                    "url": f"{self._base_url}/images/{filename}",
                }
            self._cache = built
            log.info(
                "images.loaded",
                worksheet=self._worksheet_name,
                count=len(built),
            )
            return built

    def _load_sync(self) -> list[dict[str, Any]]:
        creds: Credentials = Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
            str(self._credentials_path), scopes=_SCOPES
        )
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(self._spreadsheet_id)
        ws = spreadsheet.worksheet(self._worksheet_name)
        records: list[dict[str, Any]] = ws.get_all_records()
        return records
