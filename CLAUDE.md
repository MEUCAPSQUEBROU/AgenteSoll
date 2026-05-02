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
docker compose logs -f soll                # acompanhar webhook em tempo real
docker compose restart soll                # após mudar config (não código — esse tem hot-reload via volume)
docker compose exec soll bash              # entrar no container
```

Mudança em `src/` é **hot-reloaded** porque `./src` é volume mount. Mudança em `Dockerfile` ou `pyproject.toml` exige `docker compose build`.

## Big picture

Pipeline inbound (webhook):

```
Z-API → POST /webhook/zapi
  ↓ ZAPIProvider.parse_webhook  (descarta isEdit, non-ReceivedCallback)
  ↓ Redis SETNX dedup           (TTL = WEBHOOK_DEDUP_TTL_SECONDS)
  ↓ filtered_return             (descarta grupo, broadcast, agent echo, attendant, sticker, unsupported)
  ↓ ConvertToText               (text passthrough · Whisper p/ áudio · Vision p/ imagem · pypdf p/ pdf)
  ↓ Buffer.add_and_process      (debounce 8s ou max 20 msgs, RedisBufferStore)
  ↓ SollAgent.run               (Agno Agent + OpenAI gpt-4o-mini, sessão por user_number)
  ↓ provider.send_text          (POST z-api send-text)
```

`api/webhook.py:create_app` faz toda a wiring no `lifespan`. Cada serviço externo tem um adapter com par `base.py` + impl (`adapters/whatsapp`, `adapters/transcriber`, `adapters/vision`, `adapters/buffer_store`, `adapters/sheets`, `adapters/calendar`). DI sempre via construtor — nunca singleton ou import-time mutável.

## Divergência importante: CLI vs Webhook

`SollAgent` aceita `tools_builder` e `state_provider` opcionais. **Os dois entrypoints wired diferente:**

- **`cli.py:_build_agent`** — wiring completo: `tools_builder=build_tools(...)` (busca lead, atualiza lead, agendar reunião) e `state_provider=store.get` (LeadStore).
- **`api/webhook.py`** — instancia `SollAgent(openai_api_key=..., redis_url=...)` **sem tools nem state_provider**. Em produção via webhook, o agente roda só com `<lead_state>{}</lead_state>` e zero tools.

Se for trabalhar no agente via webhook, replicar o wiring do CLI (montar `LeadStore` + `build_tools` + `state_provider`) no `lifespan` da `create_app`.

## Configuração

- **Tudo via env** (`pydantic-settings`, `src/soll/config.py`). **Nunca** chamar `load_dotenv` espalhado pelo código.
- `.env` na raiz é gitignored. `.env.example` é referência.
- Credenciais Google (Sheets + Calendar OAuth) ficam em `JsonConsole/` — gitignored, montada read-only no container via `./JsonConsole:/app/JsonConsole:ro`. Token OAuth do Calendar precisa ser gerado localmente (consent flow no browser) antes de rodar no container.
- Redis: por default usa Redis Cloud (URL no `.env`). Pra Redis local: `docker compose --profile local-redis up`.

## Convenções

- `mypy --strict` deve passar (configurado em `pyproject.toml`).
- Logging via `structlog` (`get_logger(__name__)`); JSON em prod, pretty se `LOG_PRETTY=true`.
- Nomes de identificador em inglês; strings de domínio (prompts, mensagens ao lead) em português.
- Sem comentários óbvios — só anotar o "porquê" não-óbvio.
- Sem `from __future__` ausente: todos os módulos novos usam `from __future__ import annotations`.
- Commits: convencional (`feat:`, `chore:`, `fix:`).

## Operacional / túnel

`https://soll.canequeiro.shop` é exposto via Cloudflare Tunnel rodando como serviço `cloudflared` no `docker-compose.yml`. O token do túnel está em `CLOUDFLARE_TUNNEL_TOKEN` no `.env`. Detalhes (incluindo a restrição de uma réplica por vez) estão na memória de projeto.

## Fora de escopo da iteração atual

- Adapter Meta Cloud API (apenas skeleton com `NotImplementedError` em `adapters/whatsapp/meta_cloud.py`).
- Persistência completa de leads em CRM (atualmente: JSON local + espelho Sheets assíncrono).
- Suite de testes (`tests/` existe vazia; `pytest` + `respx` + `fakeredis` já em deps).
