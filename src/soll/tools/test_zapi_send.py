"""Teste rapido de envio via Z-API.

Uso:
    PYTHONPATH=src .venv/bin/python -m soll.tools.test_zapi_send <telefone> [mensagem]

Exemplos:
    # Envia mensagem default pro Joao da planilha
    python -m soll.tools.test_zapi_send 5579988880001

    # Envia mensagem custom
    python -m soll.tools.test_zapi_send 5579988880001 "Oi, teste do agente Soll v7."

Pre-requisitos:
- ZAPI_INSTANCE_ID, ZAPI_TOKEN, ZAPI_CLIENT_TOKEN no .env
- Instancia Z-API conectada com WhatsApp (QR escaneado)

Antes de mandar, valida `/status` da instancia. Se nao estiver conectada,
aborta sem chamar o `send-text`.
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from soll.adapters.whatsapp.zapi import ZAPIProvider
from soll.config import load_settings

_DEFAULT_MESSAGE = (
    "Soll v7 conectado via Z-API. Teste de integracao OK. "
    "(Mensagem automatica do ambiente de desenvolvimento.)"
)


async def _check_connected(
    http: httpx.AsyncClient,
    *,
    instance_id: str,
    token: str,
    client_token: str,
) -> bool:
    base = f"https://api.z-api.io/instances/{instance_id}/token/{token}"
    r = await http.get(
        f"{base}/status",
        headers={"Client-Token": client_token},
        timeout=15.0,
    )
    r.raise_for_status()
    body = r.json()
    return bool(body.get("connected"))


async def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Uso: python -m soll.tools.test_zapi_send <telefone> [mensagem]",
            file=sys.stderr,
        )
        return 2

    phone = sys.argv[1]
    message = sys.argv[2] if len(sys.argv) > 2 else _DEFAULT_MESSAGE

    settings = load_settings()
    if not settings.zapi_instance_id or not settings.zapi_token:
        print("[erro] credenciais Z-API ausentes no .env", file=sys.stderr)
        return 1

    async with httpx.AsyncClient(timeout=30.0) as http:
        connected = await _check_connected(
            http,
            instance_id=settings.zapi_instance_id,
            token=settings.zapi_token,
            client_token=settings.zapi_client_token,
        )
        if not connected:
            print(
                "[erro] instancia Z-API nao esta conectada com WhatsApp.\n"
                "       Acesse app.z-api.io, escaneie o QR code, e tente de novo.",
                file=sys.stderr,
            )
            return 1

        provider = ZAPIProvider(
            instance_id=settings.zapi_instance_id,
            token=settings.zapi_token,
            client_token=settings.zapi_client_token,
            http_client=http,
        )
        print(f"==> Enviando para +{phone}")
        print(f"    Mensagem: {message[:80]}{'...' if len(message) > 80 else ''}")
        result = await provider.send_text(phone, message)
        print(f"[ok] message_id={result.message_id}  status={result.status}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
