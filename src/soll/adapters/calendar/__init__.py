from pathlib import Path

from soll.adapters.calendar.base import CalendarClient, MeetingResult
from soll.adapters.calendar.google_calendar import GoogleCalendarClient
from soll.config import Settings

__all__ = [
    "CalendarClient",
    "MeetingResult",
    "GoogleCalendarClient",
    "build_calendar_client",
]


def build_calendar_client(settings: Settings) -> CalendarClient | None:
    """Constroi o client de Calendar conforme settings. Retorna None se desabilitado."""
    if not settings.google_calendar_enabled:
        return None
    if not (
        settings.google_calendar_oauth_client_path
        and settings.google_calendar_oauth_token_path
    ):
        return None
    return GoogleCalendarClient(
        client_path=Path(settings.google_calendar_oauth_client_path),
        token_path=Path(settings.google_calendar_oauth_token_path),
        calendar_id=settings.google_calendar_id,
    )
