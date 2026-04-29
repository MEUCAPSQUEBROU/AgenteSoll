from __future__ import annotations

from pydantic import BaseModel, ConfigDict

DEFAULT_TARIFA_POR_KWH = 0.95

# Percentual estimado de reducao da conta de energia apos instalacao solar.
# Reflete a reducao maxima tipica antes da taxa minima da concessionaria.
# Fonte: Soll v6 spec doc, secao 12 (FAQ "E possivel zerar a conta?").
PERCENTUAL_REDUCAO_RESIDENCIAL = 0.78
PERCENTUAL_REDUCAO_EMPRESARIAL = 0.85


class SavingsEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    consumo_analisado: float
    gasto_atual_estimado: str
    gasto_com_solar_estimado: str
    economia_mensal_valor: str
    economia_anual_estimada: str
    percentual_economia: str
    tipo_imovel: str


def calculate_savings(
    valor_fatura: float,
    tipo_imovel: str,
    tarifa_por_kwh: float = DEFAULT_TARIFA_POR_KWH,
) -> SavingsEstimate:
    """Estima a economia mensal/anual com base no perfil do imovel.

    Residencial (CASA_*) reduz aprox. 78% da conta. Empresarial (EMPRESA_*)
    reduz aprox. 85%. O resultado e ESTIMATIVA, nao garantia.

    Se o lead informou consumo em kWh, multiplique por `tarifa_por_kwh` antes
    de chamar (`valor_fatura = kwh * tarifa_por_kwh`).
    """
    if valor_fatura <= 0:
        raise ValueError("valor_fatura must be > 0")
    if tarifa_por_kwh <= 0:
        raise ValueError("tarifa_por_kwh must be > 0")

    perfil, percentual = _resolver_perfil(tipo_imovel)
    consumo_kwh = valor_fatura / tarifa_por_kwh
    economia_mensal = valor_fatura * percentual
    custo_com_solar = valor_fatura - economia_mensal

    return SavingsEstimate(
        consumo_analisado=round(consumo_kwh, 2),
        gasto_atual_estimado=_format_brl(valor_fatura),
        gasto_com_solar_estimado=_format_brl(custo_com_solar),
        economia_mensal_valor=_format_brl(economia_mensal),
        economia_anual_estimada=_format_brl(economia_mensal * 12),
        percentual_economia=f"{percentual * 100:.2f}%",
        tipo_imovel=perfil,
    )


def _resolver_perfil(tipo_imovel: str) -> tuple[str, float]:
    normalized = tipo_imovel.upper().strip()
    if normalized.startswith("EMPRESA"):
        return "EMPRESARIAL", PERCENTUAL_REDUCAO_EMPRESARIAL
    if normalized.startswith("CASA"):
        return "RESIDENCIAL", PERCENTUAL_REDUCAO_RESIDENCIAL
    raise ValueError(
        f"tipo_imovel invalido: {tipo_imovel!r}. "
        "Esperado: CASA_PROPRIA, CASA_ALUGADA, EMPRESA_PROPRIA ou EMPRESA_ALUGADA."
    )


def _format_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
