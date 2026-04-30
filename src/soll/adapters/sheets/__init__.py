from pathlib import Path

from soll.adapters.sheets.base import LeadMirror, NoOpLeadMirror
from soll.adapters.sheets.gspread_mirror import GSpreadLeadMirror
from soll.config import Settings

__all__ = ["LeadMirror", "NoOpLeadMirror", "GSpreadLeadMirror", "build_lead_mirror"]


def build_lead_mirror(settings: Settings) -> LeadMirror:
    """Constroi o mirror conforme settings. Retorna NoOp se desabilitado."""
    if not settings.google_sheets_enabled:
        return NoOpLeadMirror()
    if not settings.google_sheets_credentials_path or not settings.google_sheets_spreadsheet_id:
        return NoOpLeadMirror()
    return GSpreadLeadMirror(
        credentials_path=Path(settings.google_sheets_credentials_path),
        spreadsheet_id=settings.google_sheets_spreadsheet_id,
        worksheet_name=settings.google_sheets_worksheet,
    )
