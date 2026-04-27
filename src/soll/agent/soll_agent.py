from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from soll.agent.prompts import build_system_prompt
from soll.logging_setup import get_logger

log = get_logger(__name__)

ToolsBuilder = Callable[[str], list[Callable[..., Awaitable[Any]]]]
StateProvider = Callable[[str], Awaitable[dict[str, Any]]]


class AgentRunner(Protocol):
    async def run(self, *, user_number: str, text: str) -> str: ...


class SollAgentStub:
    """Stub que ecoa a entrada — usado em testes e como fallback."""

    async def run(self, *, user_number: str, text: str) -> str:
        log.info("agent.stub_invoked", user_number=user_number, length=len(text))
        return f"[STUB] Recebi: {text}"


def _no_tools(_: str) -> list[Callable[..., Awaitable[Any]]]:
    return []


async def _empty_state(_: str) -> dict[str, Any]:
    return {}


class SollAgent:
    """Agente Agno real. Mantém um Agent por user_number p/ preservar histórico
    da conversa (in-memory). Quando houver storage backend persistente, esse
    cache é substituído por sessão Agno.

    `tools_builder` recebe o user_number e retorna a lista de tools fechadas
    sobre ele (cada Agent opera apenas sobre o proprio lead).

    `state_provider` retorna o estado atual do lead. Em cada turno, esse estado
    e prefixado na mensagem do usuario entre tags <lead_state>, eliminando a
    necessidade de uma tool de leitura (que causava loop de chamadas).
    """

    def __init__(
        self,
        *,
        openai_api_key: str,
        model_id: str = "gpt-4o-mini",
        system_prompt_builder: Callable[[str], str] = build_system_prompt,
        tools_builder: ToolsBuilder = _no_tools,
        state_provider: StateProvider = _empty_state,
    ) -> None:
        self._api_key = openai_api_key
        self._model_id = model_id
        self._build_prompt = system_prompt_builder
        self._build_tools = tools_builder
        self._state_provider = state_provider
        self._agents: dict[str, Agent] = {}

    def _get_or_create(self, user_number: str) -> Agent:
        existing = self._agents.get(user_number)
        if existing is not None:
            return existing
        agent = Agent(
            model=OpenAIChat(id=self._model_id, api_key=self._api_key),
            instructions=self._build_prompt(user_number),
            tools=list(self._build_tools(user_number)),
            markdown=False,
            add_history_to_context=True,
        )
        self._agents[user_number] = agent
        return agent

    async def run(self, *, user_number: str, text: str) -> str:
        log.info("agent.invoked", user_number=user_number, length=len(text))
        agent = self._get_or_create(user_number)
        state = await self._state_provider(user_number)
        prefixed = self._prefix_state(state, text)
        response = await agent.arun(prefixed, session_id=user_number)
        content = getattr(response, "content", None)
        return str(content) if content is not None else ""

    @staticmethod
    def _prefix_state(state: dict[str, Any], text: str) -> str:
        rendered = json.dumps(state, ensure_ascii=False) if state else "{}"
        return f"<lead_state>{rendered}</lead_state>\n{text}"
