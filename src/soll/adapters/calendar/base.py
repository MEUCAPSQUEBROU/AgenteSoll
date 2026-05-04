from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel


class MeetingResult(BaseModel):
    event_id: str
    html_link: str
    meet_link: str
    start: datetime
    end: datetime


class CalendarClient(Protocol):
    async def create_meeting(
        self,
        *,
        summary: str,
        start: datetime,
        end: datetime,
        description: str = "",
        attendee_emails: list[str] | None = None,
    ) -> MeetingResult: ...

    async def is_slot_free(self, *, start: datetime, end: datetime) -> bool: ...

    async def next_free_slots(
        self, *, count: int = 3, horizon_days: int = 7
    ) -> list[datetime]: ...
