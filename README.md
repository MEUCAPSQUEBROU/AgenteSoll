# Soll — Camada de pré-processamento

> [!WARNING]
> **Esse projeto está em fase de desenvolvimento, possivelmente não está funcionando certas funções.**

Refatoração do agente de pré-venda WhatsApp da **Sollar System Engenharia** (energia
solar fotovoltaica, Sergipe/Brasil) de **n8n (v6)** para **Python/Agno (v7)**.

Esta iteração implementa **somente a camada de pré-processamento** que entrega a
mensagem final, em texto, para o agente. O agente é um stub que ecoa a entrada.

## Pipeline

```
        ┌─────────────────────┐
        │  Z-API webhook       │  POST /webhook/zapi
        └──────────┬──────────┘
                   │ raw payload
                   ▼
        ┌─────────────────────┐
        │ ZAPIProvider        │  parse_webhook → FilteredPayload | None
        └──────────┬──────────┘
                   │
                   ▼
        ┌─────────────────────┐
        │ FilteredReturn      │  descarta grupo, broadcast, agent echo,
        │                     │  attendant, sticker, unsupported, unknown
        └──────────┬──────────┘
                   │ FilteredPayload
                   ▼
        ┌─────────────────────┐
        │ ConvertToText       │  texto → passthrough
        │   ├─ Transcriber    │  áudio/vídeo → Whisper
        │   ├─ VisionDescriber│  imagem → Vision (1ª pessoa)
        │   └─ pypdf          │  PDF → texto extraído
        └──────────┬──────────┘
                   │ TextMessage
                   ▼
        ┌─────────────────────┐
        │ Buffer (debounce)   │  agrupa mensagens consecutivas via
        │   on RedisBufferStore│  message_id; força flush em max=20
        └──────────┬──────────┘
                   │ combined_text
                   ▼
        ┌─────────────────────┐
        │ SollAgentStub       │  retorna f"[STUB] Recebi: {text}"
        └─────────────────────┘
```

## Como rodar localmente

### Via Docker (recomendado)

Pré-requisitos: Docker + Docker Compose.

```bash
# 1. configurar env
cp .env.example .env
# edite .env: OPENAI_API_KEY, REDIS_URL (Z-API só quando integrar)

# 2. build
docker compose build

# 3a. CLI iterativo p/ chatear com o agente (modo principal de dev)
docker compose run --rm soll python main.py

# 3b. servidor FastAPI (quando integrar Z-API/Meta)
docker compose up
# webhook em http://localhost:8000/webhook/zapi

# Redis: por padrão usa REDIS_URL do .env (ex: Redis Cloud).
# Para subir Redis local em vez disso:
docker compose --profile local-redis up
# e em .env: REDIS_URL=redis://redis:6379/0
```

### Via uv direto (sem Docker)

Pré-requisitos: Python 3.11+, [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env  # editar
uv run python main.py          # CLI (chat com o agente)
uv run python main.py server   # FastAPI / webhook Z-API
```

Equivalentes via scripts: `uv run soll-cli`, `uv run soll-server`.

`GET /health` → `{"status": "ok"}`

`POST /webhook/zapi` → recebe payload bruto da Z-API, processa e devolve
`{"status": "...", ...}` imediatamente. O agente roda em background.

## Lint e tipos

```bash
uv run mypy
uv run ruff check
```

## Variáveis de ambiente

Todas em `.env.example`. Resumidas:

| Variável | Default | Descrição |
|---|---|---|
| `OPENAI_API_KEY` | — | Obrigatório |
| `OPENAI_TRANSCRIPTION_MODEL` | `whisper-1` | Modelo de áudio |
| `OPENAI_VISION_MODEL` | `gpt-4o-mini` | Modelo de imagem |
| `REDIS_URL` | `redis://localhost:6379/0` | Backend do buffer e dedup |
| `BUFFER_DEBOUNCE_SECONDS` | `8` | Tempo de espera por nova mensagem |
| `BUFFER_MAX_MESSAGES` | `20` | Limite que dispara flush forçado |
| `BUFFER_KEY_TTL_SECONDS` | `3600` | TTL da chave do buffer no Redis |
| `WHATSAPP_PROVIDER` | `zapi` | `zapi` ou `meta_cloud` (skeleton) |
| `ZAPI_INSTANCE_ID` / `ZAPI_TOKEN` / `ZAPI_CLIENT_TOKEN` | — | Credenciais Z-API |
| `LOG_LEVEL` | `INFO` | |
| `LOG_PRETTY` | `false` | `true` em dev local p/ rich console |
| `WEBHOOK_DEDUP_TTL_SECONDS` | `3600` | TTL da chave de idempotência |

## Convenções

- `mypy --strict` deve passar.
- Logging estruturado via `structlog` (JSON em prod, pretty em dev).
- Configuração 100% via env (`pydantic-settings`); zero `load_dotenv` espalhado.
- Nomes em inglês; strings de domínio (prompts, fallbacks ao lead) em português.
- DI via construtor; sem variável global mutável.

## Layout

```
main.py                       # entrada única (cli | server)
src/soll/
├── config.py                # Settings (pydantic-settings)
├── schemas.py               # FilteredPayload, ContentMessage, TextMessage
├── logging_setup.py
├── cli.py                   # REPL local
├── core/
│   ├── filtered_return.py
│   ├── convert_to_text.py
│   └── buffer.py
├── adapters/
│   ├── whatsapp/{base,zapi,meta_cloud}.py
│   ├── transcriber/{base,openai_whisper}.py
│   ├── vision/{base,openai_vision}.py
│   └── buffer_store/{base,memory,redis}.py
├── agent/soll_agent.py      # stub
└── api/webhook.py           # FastAPI
```

## Fora de escopo desta iteração

- Lógica do agente Soll (SPIN, objeções, tools `buscarInfo`/`atualizarInfoLead`/`department`)
- Adapter real da Meta Cloud API (apenas skeleton com `NotImplementedError`)
- Persistência de leads (planilhas, CRM)
- Envio outbound (foco é só inbound)
# SollAgenteIA
