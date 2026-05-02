# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Comandos comuns

Tudo via `uv` (Python 3.11+) ou Docker Compose. Não rodar `pip` direto.

```bash
# Rodar
uv run python main.py                      # CLI / REPL — modo principal de dev
uv run python main.py --user 5579999       # CLI simulando outro número
uv run python main.py server               # FastAPI / webhook em :8000
docker compose up -d                       # sobe soll + cloudflared
docker compose --profile local-redis up    # sobe também redis local

# Lint / tipos / testes
uv run mypy                                # strict, configurado em pyproject
uv run ruff check
uv run ruff format
uv run pytest                              # pasta tests/ existe vazia (só .gitkeep)
uv run pytest tests/path::test_x -k name   # single test

# Operacional
tail -f logs/soll.log                      # forma primária de debug — tudo cai aqui (uvicorn + structlog + httpx)
docker compose logs -f soll                # mesma coisa, via Docker (sem timestamp duplo do structlog)
docker compose restart soll                # após mudar código em src/ (volume mount → hot-reload no import)
docker compose up -d soll                  # após mudar docker-compose.yml (recreate)
docker compose exec soll bash              # entrar no container

# Confirmar modelo ativo dentro do container
docker compose exec soll python -c "from soll.config import load_settings; print(load_settings().openai_agent_model)"
```

Mudança em `src/` é **hot-reloaded** porque `./src` é volume mount. Mudança em `Dockerfile` ou `pyproject.toml` exige `docker compose build`.

## Big picture

Pipeline inbound (webhook):

```
Z-API → POST /webhook/zapi
  ↓ ZAPIProvider.parse_webhook  (descarta isEdit, non-ReceivedCallback)
  ↓ Redis SETNX dedup           (TTL = WEBHOOK_DEDUP_TTL_SECONDS)
  ↓ filtered_return             (descarta grupo, broadcast, agent echo, attendant, sticker, unsupported)
  ↓ /apagar . curto-circuito    (TextContent exato → clear_conversation + send_text "Conversa apagada.")
  ↓ ConvertToText               (text passthrough · Whisper p/ áudio · Vision p/ imagem · pypdf p/ pdf)
  ↓ Buffer.add_and_process      (debounce 8s ou max 20 msgs, RedisBufferStore)
  ↓ SollAgent.run               (Agno Agent + OpenAI OPENAI_AGENT_MODEL, sessão por user_number)
  ↓ provider.send_text          (POST z-api send-text)
```

`api/webhook.py:create_app` faz toda a wiring no `lifespan`. Cada serviço externo tem um adapter com par `base.py` + impl (`adapters/whatsapp`, `adapters/transcriber`, `adapters/vision`, `adapters/buffer_store`, `adapters/sheets`, `adapters/calendar`). DI sempre via construtor — nunca singleton ou import-time mutável.

## Divergência importante: CLI vs Webhook

`SollAgent` aceita `tools_builder` e `state_provider` opcionais. Os dois entrypoints wired parcialmente diferente:

- **`cli.py:_build_agent`** — wiring completo: `tools_builder=build_tools(...)` (busca lead, atualiza lead, agendar reunião) + `state_provider=store.get` (LeadStore).
- **`api/webhook.py`** — `LeadStore` **já é instanciado** (pra `/apagar .` funcionar), mas o `SollAgent` é construído sem `tools_builder` nem `state_provider`. Resultado: em produção via webhook, agente vê `<lead_state>{}</lead_state>` e tem zero tools — ele responde texto normal mas **nunca chama `agendarReuniao`, `atualizarInfoLead`, etc**. Sintoma típico: lead pede pra marcar reunião, agente diz que vai marcar, **nada acontece** (zero linhas de `tool.*`/`calendar.*` no `logs/soll.log`).

Pra fechar a divergência: passar `tools_builder=lambda u: list(build_tools(store=lead_store, user_number=u, calendar_client=build_calendar_client(settings)))` e `state_provider=lead_store.get` na criação do `SollAgent` no `lifespan`. ~10 linhas, espelhando `_build_agent` do CLI.

## Configuração

- **Tudo via env** (`pydantic-settings`, `src/soll/config.py`). **Nunca** chamar `load_dotenv` espalhado pelo código.
- `.env` na raiz é gitignored. `.env.example` é referência.
- Modelo do agente: `OPENAI_AGENT_MODEL` (default `gpt-4.1-mini`). Trocar = editar `.env` + `docker compose restart soll`. Não mexer em código.
- Credenciais Google (Sheets + Calendar OAuth) ficam em `JsonConsole/` — gitignored, montada read-only no container via `./JsonConsole:/app/JsonConsole:ro`. Token OAuth do Calendar precisa ser gerado localmente (consent flow no browser) antes de rodar no container.
- Redis: por default usa Redis Cloud (URL no `.env`). Pra Redis local: `docker compose --profile local-redis up`.
- Timezone: container roda com `TZ=America/Sao_Paulo` (env no `docker-compose.yml`). `time.localtime`, `datetime.now()` e logs vão em horário de Sergipe.

## Convenções

- `mypy --strict` deve passar (configurado em `pyproject.toml`).
- Logging via `structlog` (`get_logger(__name__)`); JSON em prod, pretty se `LOG_PRETTY=true`.
- Nomes de identificador em inglês; strings de domínio (prompts, mensagens ao lead) em português.
- Sem comentários óbvios — só anotar o "porquê" não-óbvio.
- Sem `from __future__` ausente: todos os módulos novos usam `from __future__ import annotations`.
- Commits: convencional (`feat:`, `chore:`, `fix:`).

## Operacional / túnel / logs

- **Túnel**: `https://soll.canequeiro.shop` é exposto via Cloudflare Tunnel rodando como serviço `cloudflared` no `docker-compose.yml`. Token em `CLOUDFLARE_TUNNEL_TOKEN` no `.env`. Detalhes (incluindo a restrição de uma réplica por vez) estão na memória de projeto.
- **Logs persistentes**: o `command:` do serviço `soll` faz `tee -a /app/logs/soll.log` (volume `./logs:/app/logs`), capturando stdout+stderr de tudo (uvicorn access, structlog, httpx). Arquivo é dono do `root` (limpar = `sudo truncate -s 0 logs/soll.log`). Defesa em profundidade: docker-compose também tem `logging: max-size=10m max-file=5` no json-file driver.
- **Restart policies**: ambos `soll` e `cloudflared` com `restart: unless-stopped` — sobrevivem a crash/reboot.

## Fora de escopo da iteração atual

- Adapter Meta Cloud API (apenas skeleton com `NotImplementedError` em `adapters/whatsapp/meta_cloud.py`).
- Persistência completa de leads em CRM (atualmente: JSON local + espelho Sheets assíncrono).
- Suite de testes (`tests/` existe vazia; `pytest` + `respx` + `fakeredis` já em deps).
