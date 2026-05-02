from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build  # type: ignore[import-untyped]

from soll.adapters.calendar.base import CalendarClient, MeetingResult
from soll.logging_setup import get_logger

log = get_logger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


class GoogleCalendarClient(CalendarClient):
    """Cria eventos no Google Calendar com link Meet auto-gerado.

    Usa OAuth user credentials (refresh token salvo via `tools.auth_calendar`).
    Em Testing mode o refresh token expira em 7 dias — quando isso acontece,
    `create_meeting` falha com `RefreshError` e e preciso re-rodar o auth.
    """

    def __init__(
        self,
        *,
        client_path: Path,
        token_path: Path,
        calendar_id: str = "primary",
    ) -> None:
        self._client_path = client_path
        self._token_path = token_path
        self._calendar_id = calendar_id
        self._service: Resource | None = None

    async def _ensure_service(self) -> Resource:
        if self._service is not None:
            return self._service
        self._service = await asyncio.to_thread(self._build_service_sync)
        return self._service

    def _build_service_sync(self) -> Resource:
        if not self._token_path.exists():
            raise RuntimeError(
                f"Refresh token nao encontrado em {self._token_path}. "
                "Rode `python -m soll.tools.auth_calendar` antes."
            )
        creds = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
            str(self._token_path), _SCOPES
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self._token_path.write_text(creds.to_json(), encoding="utf-8")
            log.info("calendar.token_refreshed")
        service: Resource = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return service

    async def is_slot_free(self, *, start: datetime, end: datetime) -> bool:
        """Verifica via freebusy.query se o intervalo [start, end) esta livre.

        Retorna True se NENHUM evento ocupa qualquer parte do intervalo.
        Falha de API e tratada como "indisponivel" pra ser conservador (False) —
        o agente vai propor outro horario em vez de tentar agendar as cegas.
        """
        service = await self._ensure_service()
        body: dict[str, Any] = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "items": [{"id": self._calendar_id}],
        }
        try:
            result = await asyncio.to_thread(
                lambda: service.freebusy().query(body=body).execute()
            )
        except Exception as exc:
            log.warning(
                "calendar.freebusy_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False
        busy_blocks = (
            result.get("calendars", {}).get(self._calendar_id, {}).get("busy", [])
        )
        return len(busy_blocks) == 0

    async def create_meeting(
        self,
        *,
        summary: str,
        start: datetime,
        end: datetime,
        description: str = "",
        attendee_emails: list[str] | None = None,
    ) -> MeetingResult:
        service = await self._ensure_service()
        body: dict[str, Any] = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
            "conferenceData": {
                "createRequest": {
                    "requestId": f"soll-{uuid.uuid4().hex[:12]}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }
        if attendee_emails:
            body["attendees"] = [{"email": e} for e in attendee_emails]

        event = await asyncio.to_thread(
            lambda: service.events()
            .insert(
                calendarId=self._calendar_id,
                body=body,
                conferenceDataVersion=1,
                sendUpdates="all" if attendee_emails else "none",
            )
            .execute()
        )

        meet_link = ""
        for ep in event.get("conferenceData", {}).get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri", "")
                break

        result = MeetingResult(
            event_id=event["id"],
            html_link=event["htmlLink"],
            meet_link=meet_link,
            start=start,
            end=end,
        )
        log.info(
            "calendar.event_created",
            event_id=result.event_id,
            meet=bool(meet_link),
            attendees=len(attendee_emails or []),
        )
        return result
