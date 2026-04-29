from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from soll.adapters.buffer_store.memory import InMemoryBufferStore
from soll.agent.lead_store import LeadStore
from soll.agent.soll_agent import SollAgent
from soll.agent.tools import build_tools
from soll.config import Settings, load_settings
from soll.core.clear_conversation import clear_conversation, is_clear_command
from soll.logging_setup import configure_logging, get_logger

log = get_logger(__name__)

_MODEL_ID = "gpt-4o-mini"
_USER_PROMPT = "[bold cyan]você[/] [dim]❯[/] "
_HELP_LINES = (
    "[bold]/help[/]      mostrar esta ajuda",
    "[bold]/reset[/]     limpar histórico (não-op por enquanto)",
    "[bold]/apagar .[/]  apagar lead, buffer e histórico do agente",
    "[bold]/quit[/]      sair",
)


def _build_agent(settings: Settings) -> tuple[SollAgent, LeadStore]:
    store = LeadStore(Path(settings.leads_fake_path))
    agent = SollAgent(
        openai_api_key=settings.openai_api_key,
        model_id=_MODEL_ID,
        tools_builder=lambda user_number: list(
            build_tools(store=store, user_number=user_number)
        ),
        state_provider=store.get,
        redis_url=settings.redis_url,
    )
    return agent, store


def _banner(user_number: str) -> Panel:
    body = Text.from_markup(
        f"[bold]usuário[/]  {user_number}\n"
        f"[bold]modelo[/]   {_MODEL_ID}\n"
        f"[bold]comandos[/] /help · /reset · /quit"
    )
    return Panel(
        body,
        title="[bold yellow]Soll v7[/]",
        title_align="left",
        border_style="yellow",
        padding=(0, 1),
    )


def _agent_panel(text: str) -> Panel:
    return Panel(
        Text(text, style="white"),
        title="[bold green]soll[/]",
        title_align="left",
        border_style="green",
        padding=(0, 1),
    )


async def _read_line(console: Console) -> str | None:
    try:
        return await asyncio.to_thread(console.input, _USER_PROMPT)
    except EOFError:
        return None


async def repl(
    *,
    user_number: str,
    agent: SollAgent,
    lead_store: LeadStore,
    console: Console,
) -> None:
    console.print(_banner(user_number))
    console.print()
    buffer_store = InMemoryBufferStore()

    while True:
        line = await _read_line(console)
        if line is None:
            console.print()
            return
        text = line.strip()
        if not text:
            continue

        if text in {"/quit", "/exit"}:
            return
        if text == "/help":
            for line_help in _HELP_LINES:
                console.print(f"  {line_help}")
            console.print()
            continue
        if text == "/reset":
            console.print("[dim](reset não tem efeito no stub atual)[/]\n")
            continue
        if is_clear_command(text):
            result = await clear_conversation(
                user_number,
                lead_store=lead_store,
                buffer_store=buffer_store,
                agent_invalidator=agent.forget,
            )
            console.print(
                f"[dim]apagado: lead={result.lead_cleared} "
                f"buffer={result.buffer_messages_dropped} "
                f"agent={result.agent_invalidated}[/]\n"
            )
            continue

        try:
            with console.status("[dim]pensando...[/]", spinner="dots"):
                response = await agent.run(user_number=user_number, text=text)
        except Exception as exc:
            log.exception("cli.agent_error", user_number=user_number)
            console.print(f"[bold red]erro[/]: {exc}\n")
            continue

        console.print(_agent_panel(response))
        console.print()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="soll-cli", description="REPL local para testar o agente Soll"
    )
    parser.add_argument(
        "--user",
        default="cli-user",
        help="Número/identificador simulado do usuário (default: cli-user)",
    )
    args = parser.parse_args()

    settings = load_settings()
    configure_logging(settings.log_level, pretty=settings.log_pretty)

    console = Console()
    agent, lead_store = _build_agent(settings)
    try:
        asyncio.run(
            repl(
                user_number=args.user,
                agent=agent,
                lead_store=lead_store,
                console=console,
            )
        )
    except KeyboardInterrupt:
        pass
    console.print("[dim]até mais.[/]")


if __name__ == "__main__":
    main()
