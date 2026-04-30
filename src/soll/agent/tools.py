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

    return [atualizarInfoLead, CalKWats, department]
