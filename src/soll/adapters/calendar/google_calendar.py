from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build  # type: ignore[import-untyped]

from soll.adapters.calendar.base import CalendarClient, MeetingResult
from soll.logging_setup import get_logger

log = get_logger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_BR_TZ = timezone(timedelta(hours=-3))
_BUSINESS_HOURS = (9, 10, 11, 14, 15, 16, 17)
_MEETING_DURATION_MIN = 30


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

    async def next_free_slots(
        self,
        *,
        count: int = 3,
        horizon_days: int = 7,
        start_date: datetime | None = None,
    ) -> list[datetime]:
        """Retorna os proximos `count` slots livres de 30min em dias uteis,
        dentro de `horizon_days` dias a partir de `start_date` (default = agora).

        Quando `start_date` e fornecido (lead pediu um dia especifico tipo
        "quarta"), a busca COMECA daquela data; horizonte aplica em cima dela.

        Horario comercial: 09h-12h e 14h-18h (sem 12h e 13h por almoco).
        Faz UMA freebusy.query cobrindo o horizonte inteiro e filtra os
        candidatos contra os busy_blocks retornados — eficiente.
        Falha de API e tratada como lista vazia.
        """
        service = await self._ensure_service()
        now = datetime.now(_BR_TZ)
        anchor = start_date if start_date is not None else now
        candidates: list[datetime] = []
        cursor = anchor.date()
        days_checked = 0
        while days_checked < horizon_days and len(candidates) < count * 4:
            if cursor.weekday() < 5:
                for h in _BUSINESS_HOURS:
                    slot = datetime(
                        cursor.year, cursor.month, cursor.day, h, 0, 0, tzinfo=_BR_TZ
                    )
                    if slot > now + timedelta(minutes=15):
                        candidates.append(slot)
            cursor = cursor + timedelta(days=1)
            days_checked += 1

        if not candidates:
            return []

        time_min = candidates[0]
        time_max = candidates[-1] + timedelta(minutes=_MEETING_DURATION_MIN)
        body: dict[str, Any] = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "items": [{"id": self._calendar_id}],
        }
        try:
            result = await asyncio.to_thread(
                lambda: service.freebusy().query(body=body).execute()
            )
        except Exception as exc:
            log.warning(
                "calendar.next_free_slots_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            # Propaga em vez de retornar [] silenciosamente — assim o tool
            # reporta erro ao agente e ele para de fingir "agenda lotada".
            raise

        busy_blocks = (
            result.get("calendars", {}).get(self._calendar_id, {}).get("busy", [])
        )
        busy_intervals: list[tuple[datetime, datetime]] = []
        for b in busy_blocks:
            try:
                bs = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
                be = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
                busy_intervals.append((bs, be))
            except (KeyError, ValueError):
                continue

        free: list[datetime] = []
        for slot in candidates:
            slot_end = slot + timedelta(minutes=_MEETING_DURATION_MIN)
            overlaps = any(
                slot < be and slot_end > bs for bs, be in busy_intervals
            )
            if not overlaps:
                free.append(slot)
                if len(free) >= count:
                    break
        return free

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
