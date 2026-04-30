"""Auth helper de primeira vez pra Google Calendar / Meet.

Roda o fluxo OAuth `InstalledAppFlow.run_local_server` — abre o browser,
o dono do Gmail da Sollar autoriza, o script captura o code via redirect
em localhost e salva o refresh token em
`GOOGLE_CALENDAR_OAUTH_TOKEN_PATH` (default: JsonConsole/calendar-oauth-token.json).

Uso:
    PYTHONPATH=src .venv/bin/python -m soll.tools.auth_calendar

Requisitos:
- `GOOGLE_CALENDAR_OAUTH_CLIENT_PATH` aponta pra OAuth Client JSON do GCP.
- O usuario que vai autorizar tem que estar listado em "Test users" no
  consent screen (em Testing mode).
- Em Testing mode, o refresh token expira em ~7 dias. Re-roda esse script
  quando isso acontecer (ou publica o app na Google).
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

from soll.config import load_settings

_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _harden_token_perms(token_path: Path) -> None:
    os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)


def main() -> int:
    settings = load_settings()

    client_path = Path(settings.google_calendar_oauth_client_path)
    token_path = Path(settings.google_calendar_oauth_token_path)

    if not client_path.exists():
        print(
            f"[erro] OAuth client JSON nao encontrado: {client_path}\n"
            f"       Confira GOOGLE_CALENDAR_OAUTH_CLIENT_PATH no .env",
            file=sys.stderr,
        )
        return 1

    print(f"==> Lendo OAuth client de: {client_path}")
    print(f"==> Token sera salvo em:    {token_path}")
    print(f"==> Escopo solicitado:      {_SCOPES[0]}")
    print()
    print("Vai abrir uma janela do browser. Faca login com o Gmail da Sollar")
    print("(o mesmo que esta em 'Test users' no consent screen).")
    print("Aviso amarelo 'App nao verificado' = normal: clica Avancado >")
    print("Continuar para Soll - Agente Sollar System > Permitir.")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), _SCOPES)
    creds = flow.run_local_server(
        port=0,
        prompt="consent",
        access_type="offline",
        authorization_prompt_message="Abrindo {url} no navegador padrao...",
        success_message="Autorizacao OK. Pode fechar essa aba.",
    )

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    _harden_token_perms(token_path)

    print()
    print(f"[ok] Refresh token salvo em {token_path} (chmod 600).")
    print("    Agora o adapter de Calendar pode criar eventos sem mais consent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
