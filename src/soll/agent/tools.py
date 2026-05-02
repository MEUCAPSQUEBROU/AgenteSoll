from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from soll.adapters.calendar import CalendarClient
from soll.agent.lead_store import LeadStore
from soll.core.cal_kwats import calculate_savings
from soll.logging_setup import get_logger

log = get_logger(__name__)

ToolFn = Callable[..., Awaitable[Any]]

_BR_TZ = timezone(timedelta(hours=-3))
_MEETING_DURATION_MIN = 30


def _build_meeting_description(lead: dict[str, Any], user_number: str) -> str:
    nome = lead.get("primeiro_nome", "Lead")
    cidade = lead.get("cidade", "—")
    valor = lead.get("valor_conta", "—")
    tipo = lead.get("tipo_imovel", "—")
    telhado = lead.get("tipo_telhado", "—")
    sol = lead.get("incidencia_sol", "—")
    classif = lead.get("classificacao", "—")
    return (
        f"Análise de proposta de energia solar — Sollar System × {nome}\n\n"
        f"Lead:\n"
        f"  Nome: {nome}\n"
        f"  Telefone: +{user_number}\n"
        f"  Cidade: {cidade}\n"
        f"  Conta de luz: R$ {valor}/mês\n"
        f"  Tipo de imóvel: {tipo}\n"
        f"  Telhado: {telhado}\n"
        f"  Incidência de sol: {sol}\n"
        f"  Classificação: {classif}\n\n"
        f"(Reunião agendada automaticamente pelo agente Soll v7.)"
    )


def build_tools(
    *,
    store: LeadStore,
    user_number: str,
    calendar_client: CalendarClient | None = None,
) -> list[ToolFn]:
    """Constroi as tools do agente Soll com `store` e `user_number` em closure.

    O estado do lead e injetado diretamente no prompt do turno (ver SollAgent.run),
    portanto nao ha tool de leitura — apenas tools de escrita/acao.
    O LLM nao precisa (e nao deve) passar `user_number` — ele e bound aqui pra
    que cada Agent so opere sobre o proprio lead.

    Se `calendar_client` for None, a tool `agendarReuniao` nao e exposta —
    o LLM nao tem como tentar agendar reuniao quando o Calendar esta desabilitado.
    """

    async def atualizarInfoLead(campo: str, valor: str) -> dict[str, Any]:  # noqa: N802
        """Atualiza um campo do lead. Chame uma vez por campo (uma chamada = um campo).

        Campos validos: `primeiro_nome`, `classificacao`, `etapa_funil`,
        `valor_conta`, `kwh`, `cidade`, `tipo_imovel`, `tipo_telhado`,
        `incidencia_sol`.

        `tipo_imovel` aceita um dos quatro valores combinados:
        `CASA_PROPRIA`, `CASA_ALUGADA`, `EMPRESA_PROPRIA`, `EMPRESA_ALUGADA`.
        Salve depois de capturar tipo (casa/empresa) E posse (propria/alugada).

        Para campos numericos (`valor_conta`, `kwh`), passe o numero como string (ex: "750").
        Retorna o lead atualizado.
        """
        result = await store.upsert_field(user_number, campo, valor)
        return result

    async def CalKWats(valor_fatura: float, tipo_imovel: str) -> dict[str, Any]:  # noqa: N802
        """Calcula a ESTIMATIVA de economia com energia solar.

        Aplica reducao de 78% (residencial) ou 85% (empresarial) sobre o valor da
        fatura. O resultado e estimativa, nao garantia — sempre apresentar como tal.

        Args:
            valor_fatura: Valor mensal da conta em R$. Se o lead informou em kWh,
                converta antes (`valor_fatura = kwh * 0.95`).
            tipo_imovel: Um dos quatro combinados (`CASA_PROPRIA`, `CASA_ALUGADA`,
                `EMPRESA_PROPRIA`, `EMPRESA_ALUGADA`). So o prefixo (CASA vs
                EMPRESA) afeta o percentual; a posse e dado da ficha.

        Retorna dicionario com campos ja formatados em BRL prontos pra inserir
        nas mensagens (`gasto_atual_estimado`, `gasto_com_solar_estimado`,
        `economia_mensal_valor`, `economia_anual_estimada`, `percentual_economia`,
        `consumo_analisado`, `tipo_imovel`).
        """
        try:
            estimate = calculate_savings(valor_fatura, tipo_imovel)
        except ValueError as exc:
            log.warning(
                "tool.CalKWats_error",
                user_number=user_number,
                valor_fatura=valor_fatura,
                tipo_imovel=tipo_imovel,
                error=str(exc),
            )
            return {"error": str(exc)}
        log.info(
            "tool.CalKWats",
            user_number=user_number,
            valor_fatura=valor_fatura,
            tipo_imovel=tipo_imovel,
        )
        return dict(estimate.model_dump())

    async def department(motivo: str) -> dict[str, Any]:
        """Encerra o atendimento da Soll e transfere o lead para outro departamento.

        Use quando: lead fora de Sergipe, insistencia em topico fora do escopo,
        ou qualquer caso que justifique sair do funil de pre-venda.

        Apos chamar, NAO envie mais mensagens ao lead alem da mensagem de encerramento.
        """
        await store.upsert_field(user_number, "department_motivo", motivo)
        await store.upsert_field(user_number, "etapa_funil", "ENCERRADO")
        log.info("tool.department", user_number=user_number, motivo=motivo)
        return {"status": "encerrado", "motivo": motivo}

    async def agendarReuniao(data: str, horario: str) -> dict[str, Any]:  # noqa: N802
        """Cria a reuniao no Google Calendar com link Meet auto-gerado.

        PRECONDICAO ABSOLUTA — NUNCA chame esta tool sem que o lead tenha
        EXPLICITAMENTE confirmado UM slot especifico (data + horario juntos).
        Chamar sem confirmacao = lead recebe link Meet sem ter pedido = bug grave.

        Conta como confirmacao:
          - "pode ser amanha as 9h"
          - "fechou, hoje 17h"
          - "ta bom, 11h amanha entao"

        NAO conta como confirmacao (responda em TEXTO oferecendo slots, NAO chame a tool):
          - "amanha" sozinho (falta horario)
          - "qual horario voce tem?"  (e pergunta, nao aceite)
          - "que tem disponivel?"     (idem)
          - "qualquer um"  / "voce decide"  (ofereca 2 opcoes concretas antes)
          - "manha" / "tarde" sem horario especifico

        Pre-requisitos adicionais: dados minimos do lead ja coletados (nome,
        cidade, valor_conta, tipo_imovel). Apos sucesso, envie o link do Meet
        pro lead na proxima mensagem.

        Args:
            data: Data da reuniao em formato ISO `YYYY-MM-DD` (ex: "2026-05-05").
            horario: Horario em formato 24h `HH:MM` (ex: "14:30"). Fuso de Brasilia.

        Retorna dicionario com `meet_link`, `data_formatada` (DD/MM/YYYY),
        `horario`, e `status`. Em caso de erro, retorna `{"error": "..."}`.

        Efeitos colaterais: atualiza o lead com `etapa_funil=AGENDADO`, `Data`,
        `Horario`, e `Reuniao=meet_link` automaticamente — voce NAO precisa
        chamar `atualizarInfoLead` pra esses campos depois.
        """
        if calendar_client is None:
            return {"error": "calendar_disabled"}
        try:
            start = datetime.fromisoformat(f"{data}T{horario}:00").replace(tzinfo=_BR_TZ)
        except ValueError as exc:
            log.warning(
                "tool.agendarReuniao_invalid_input",
                user_number=user_number,
                data=data,
                horario=horario,
                error=str(exc),
            )
            return {"error": f"data ou horario invalido: {exc}"}

        end = start + timedelta(minutes=_MEETING_DURATION_MIN)
        lead = await store.get(user_number)
        nome = lead.get("primeiro_nome", "Lead")

        try:
            result = await calendar_client.create_meeting(
                summary=f"Sollar System × {nome} — Análise de energia solar",
                start=start,
                end=end,
                description=_build_meeting_description(lead, user_number),
            )
        except Exception as exc:
            log.warning(
                "tool.agendarReuniao_calendar_failed",
                user_number=user_number,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {"error": f"falha ao criar evento: {exc}"}

        await store.upsert_field(user_number, "etapa_funil", "AGENDADO")
        await store.upsert_field(user_number, "Data", data)
        await store.upsert_field(user_number, "Horário", horario)
        await store.upsert_field(user_number, "Reunião", result.meet_link)

        log.info(
            "tool.agendarReuniao",
            user_number=user_number,
            event_id=result.event_id,
            data=data,
            horario=horario,
        )
        return {
            "status": "ok",
            "meet_link": result.meet_link,
            "data_formatada": start.strftime("%d/%m/%Y"),
            "horario": horario,
        }

    tools: list[ToolFn] = [atualizarInfoLead, CalKWats, department]
    if calendar_client is not None:
        tools.append(agendarReuniao)
    return tools
