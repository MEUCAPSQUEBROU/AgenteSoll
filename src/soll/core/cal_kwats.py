from __future__ import annotations

from pydantic import BaseModel, ConfigDict

DEFAULT_TARIFA_POR_KWH = 0.95

# Taxa de disponibilidade mínima cobrada pela distribuidora mesmo quando o
# sistema solar zera o consumo da rede. A escala reflete o tipo de ligação
# estimado a partir do consumo mensal:
#   - Monofásico (até 150 kWh)   → 30 kWh
#   - Bifásico   (151-300 kWh)   → 50 kWh
#   - Trifásico  (acima de 300)  → 100 kWh
TAXA_MONOFASICO_KWH = 30
TAXA_BIFASICO_KWH = 50
TAXA_TRIFASICO_KWH = 100

LIMITE_MONOFASICO_KWH = 150
LIMITE_BIFASICO_KWH = 300


class SavingsEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    consumo_analisado: float
    gasto_atual_estimado: str
    gasto_com_solar_estimado: str
    economia_mensal_valor: str
    economia_anual_estimada: str
    percentual_economia: str


def calculate_savings(
    valor_fatura: float,
    tarifa_por_kwh: float = DEFAULT_TARIFA_POR_KWH,
) -> SavingsEstimate:
    """Estima a economia mensal/anual de um lead a partir do valor da fatura.

    Replica o comportamento do node `CalKWats` do fluxo n8n (v6).
    """
    if valor_fatura <= 0:
        raise ValueError("valor_fatura must be > 0")
    if tarifa_por_kwh <= 0:
        raise ValueError("tarifa_por_kwh must be > 0")

    consumo_kwh = valor_fatura / tarifa_por_kwh
    taxa_disponibilidade_kwh = _taxa_disponibilidade(consumo_kwh)

    custo_atual = consumo_kwh * tarifa_por_kwh
    custo_com_solar = taxa_disponibilidade_kwh * tarifa_por_kwh
    economia_mensal = custo_atual - custo_com_solar
    percentual = (economia_mensal / custo_atual) * 100

    return SavingsEstimate(
        consumo_analisado=round(consumo_kwh, 2),
        gasto_atual_estimado=_format_brl(custo_atual),
        gasto_com_solar_estimado=_format_brl(custo_com_solar),
        economia_mensal_valor=_format_brl(economia_mensal),
        economia_anual_estimada=_format_brl(economia_mensal * 12),
        percentual_economia=f"{percentual:.2f}%",
    )


def _taxa_disponibilidade(consumo_kwh: float) -> int:
    if consumo_kwh <= LIMITE_MONOFASICO_KWH:
        return TAXA_MONOFASICO_KWH
    if consumo_kwh <= LIMITE_BIFASICO_KWH:
        return TAXA_BIFASICO_KWH
    return TAXA_TRIFASICO_KWH


def _format_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
