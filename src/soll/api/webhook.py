from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from openai import AsyncOpenAI
from redis.asyncio import Redis, from_url

from soll.adapters.buffer_store.base import BufferStore
from soll.adapters.buffer_store.redis import RedisBufferStore
from soll.adapters.calendar import build_calendar_client
from soll.adapters.sheets import build_lead_mirror
from soll.adapters.transcriber.openai_whisper import OpenAIWhisperTranscriber
from soll.adapters.vision.openai_vision import OpenAIVisionDescriber
from soll.adapters.whatsapp.base import WhatsAppProvider
from soll.adapters.whatsapp.meta_cloud import MetaCloudProvider
from soll.adapters.whatsapp.zapi import ZAPIProvider
from soll.agent.lead_store import LeadStore
from soll.agent.soll_agent import AgentRunner, SollAgent
from soll.agent.tools import build_tools
from soll.config import Settings, load_settings
from soll.logging_setup import configure_logging, get_logger
from soll.core.buffer import Buffer
from soll.core.clear_conversation import clear_conversation, is_clear_command
from soll.core.convert_to_text import ConvertToText
from soll.core.filtered_return import filtered_return
from soll.schemas import TextContent

log = get_logger(__name__)


def _build_provider(settings: Settings, http: httpx.AsyncClient) -> WhatsAppProvider:
    if settings.whatsapp_provider == "zapi":
        return ZAPIProvider(
            instance_id=settings.zapi_instance_id,
            token=settings.zapi_token,
            client_token=settings.zapi_client_token,
            http_client=http,
        )
    return MetaCloudProvider()


def create_app(
    *,
    settings: Settings | None = None,
    redis_client: Redis | None = None,
    agent: AgentRunner | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level, pretty=settings.log_pretty)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        http = httpx.AsyncClient(timeout=30.0)
        redis = redis_client or from_url(settings.redis_url, decode_responses=False)
        openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

        provider = _build_provider(settings, http)
        transcriber = OpenAIWhisperTranscriber(
            client=openai_client, model=settings.openai_transcription_model
        )
        vision = OpenAIVisionDescriber(
            client=openai_client, model=settings.openai_vision_model
        )
        convert = ConvertToText(
            whatsapp_provider=provider, transcriber=transcriber, vision=vision
        )
        buffer_store = RedisBufferStore(redis)
        buffer = Buffer(
            store=buffer_store,
            debounce_seconds=settings.buffer_debounce_seconds,
            max_messages=settings.buffer_max_messages,
            ttl_seconds=settings.buffer_key_ttl_seconds,
        )
        mirror = build_lead_mirror(settings)
        calendar_client = build_calendar_client(settings)
        lead_store = LeadStore(Path(settings.leads_fake_path), mirror=mirror)
        runner: AgentRunner = agent or SollAgent(
            openai_api_key=settings.openai_api_key,
            model_id=settings.openai_agent_model,
            tools_builder=lambda user_number: list(
                build_tools(
                    store=lead_store,
                    user_number=user_number,
                    calendar_client=calendar_client,
                )
            ),
            state_provider=lead_store.get,
            redis_url=settings.redis_url,
        )

        app.state.settings = settings
        app.state.http = http
        app.state.redis = redis
        app.state.provider = provider
        app.state.convert = convert
        app.state.buffer = buffer
        app.state.buffer_store = buffer_store
        app.state.lead_store = lead_store
        app.state.agent = runner

        try:
            yield
        finally:
            await http.aclose()
            await redis.aclose()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhook/zapi")
    async def zapi_webhook(request: Request) -> dict[str, str]:
        body = await request.json()
        provider: WhatsAppProvider = request.app.state.provider
        settings: Settings = request.app.state.settings
        redis: Redis = request.app.state.redis
        agent: AgentRunner = request.app.state.agent

        parsed = provider.parse_webhook(body)
        if parsed is None:
            return {"status": "ignored", "reason": "non_message_event"}

        dedup_key = f"soll:dedup:{parsed.message_id}"
        was_new = await redis.set(dedup_key, "1", nx=True, ex=settings.webhook_dedup_ttl_seconds)
        if not was_new:
            log.info(
                "webhook.duplicate", message_id=parsed.message_id, user_number=parsed.user_number
            )
            return {"status": "ignored", "reason": "duplicate"}

        accepted = filtered_return(parsed)
        if accepted is None:
            return {"status": "ignored", "reason": "filtered"}

        if isinstance(accepted.content, TextContent) and is_clear_command(
            accepted.content.text
        ):
            lead_store: LeadStore = request.app.state.lead_store
            buffer_store: BufferStore = request.app.state.buffer_store
            await clear_conversation(
                accepted.user_number,
                lead_store=lead_store,
                buffer_store=buffer_store,
                agent_invalidator=getattr(agent, "forget", None),
            )
            await provider.send_text(accepted.user_number, "Conversa apagada.")
            return {"status": "cleared", "message_id": parsed.message_id}

        convert: ConvertToText = request.app.state.convert
        text_msg = await convert(accepted)
        if text_msg is None:
            return {"status": "ignored", "reason": "converted_to_none"}

        buffer: Buffer = request.app.state.buffer

        async def callback(user_number: str, combined: str) -> None:
            response = await agent.run(user_number=user_number, text=combined)
            await provider.send_text(user_number, response)
            log.info(
                "agent.response",
                user_number=user_number,
                response_length=len(response),
            )

        asyncio.create_task(buffer.add_and_process(text_msg, callback))
        return {"status": "accepted", "message_id": parsed.message_id}

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        "soll.api.webhook:app",
        host="0.0.0.0",
        port=8000,
        log_config=None,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
