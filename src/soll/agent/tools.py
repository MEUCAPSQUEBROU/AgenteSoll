from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from soll.agent.lead_store import LeadStore
from soll.core.cal_kwats import calculate_savings
from soll.logging_setup import get_logger

log = get_logger(__name__)

ToolFn = Callable[..., Awaitable[Any]]


def build_tools(*, store: LeadStore, user_number: str) -> list[ToolFn]:
    """Constroi as tools do agente Soll com `store` e `user_number` em closure.

    O estado do lead e injetado diretamente no prompt do turno (ver SollAgent.run),
    portanto nao ha tool de leitura — apenas tools de escrita/acao.
    O LLM nao precisa (e nao deve) passar `user_number` — ele e bound aqui pra
    que cada Agent so opere sobre o proprio lead.
    """

    async def atualizarInfoLead(campo: str, valor: str) -> dict[str, Any]:  # noqa: N802
        """Atualiza um campo do lead. Chame uma vez por campo (uma chamada = um campo).

        Campos validos: `primeiro_nome`, `classificacao`, `etapa_funil`,
        `valor_conta`, `kwh`, `cidade`, `tipo_imovel`, `tipo_telhado`, `incidencia_sol`.

        Para campos numericos (`valor_conta`, `kwh`), passe o numero como string (ex: "750").
        Retorna o lead atualizado.
        """
        result = await store.upsert_field(user_number, campo, valor)
        return result

    async def CalKWats(valor_fatura: float) -> dict[str, Any]:  # noqa: N802
        """Calcula a economia aproximada com energia solar a partir do valor da fatura em R$.

        Retorna um dicionario com campos ja formatados em BRL prontos pra inserir
        nas mensagens (`gasto_atual_estimado`, `gasto_com_solar_estimado`,
        `economia_mensal_valor`, `economia_anual_estimada`, `percentual_economia`,
        `consumo_analisado`).

        Se o lead informou kWh em vez de R$, multiplique por 0.95 antes de chamar.
        Se valor_fatura <= 0, retorna `{"error": ...}` — peca confirmacao do valor ao lead.
        """
        try:
            estimate = calculate_savings(valor_fatura)
        except ValueError as exc:
            log.warning(
                "tool.CalKWats_error",
                user_number=user_number,
                valor_fatura=valor_fatura,
                error=str(exc),
            )
            return {"error": str(exc)}
        log.info("tool.CalKWats", user_number=user_number, valor_fatura=valor_fatura)
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

    return [atualizarInfoLead, CalKWats, department]
