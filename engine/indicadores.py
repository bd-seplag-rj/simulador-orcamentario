"""
indicadores.py — CAPAG, Índice Propag e limites da LRF/vinculações.

Todos os cortes/pesos vêm de config.py (versionados e com tag de validação).
Cada função devolve tanto o número quanto o "porquê" (componentes), porque o
painel deve SEMPRE exibir os componentes, nunca só o agregado.
"""

from __future__ import annotations
from dataclasses import dataclass
from . import config as C
from .receita import Cenario, Anchors


# ===========================================================================
# CAPAG  (3 indicadores; pior domina; liquidez trava)
# ===========================================================================
def _classificar(valor: float, faixas) -> str:
    for rating, lo, hi in faixas:
        if lo <= valor < hi:
            return rating
    return faixas[-1][0]


@dataclass
class CAPAGResultado:
    ano: int
    endividamento: float
    poupanca: float
    liquidez: float
    rating_endividamento: str
    rating_poupanca: str
    rating_liquidez: str
    nota_final: str
    componentes: dict


def calcular_capag(ano: int, dc: float, rcl: float,
                   despesa_corrente: float, receita_corrente_ajustada: float,
                   obrigacoes_financeiras: float, caixa_bruto: float
                   ) -> CAPAGResultado:
    """CAPAG simulado para um ano. Todas as entradas em R$ bi.

    Indicador I  Endividamento = DC / RCL
    Indicador II Poupança       = Desp. Corrente / Rec. Corrente Ajustada
    Indicador III Liquidez      = Obrig. Financeiras / Caixa Bruto
    """
    endiv = dc / rcl if rcl else float("inf")
    poup = despesa_corrente / receita_corrente_ajustada if receita_corrente_ajustada else float("inf")
    liq = obrigacoes_financeiras / caixa_bruto if caixa_bruto else float("inf")

    r_end = _classificar(endiv, C.CAPAG_FAIXAS["endividamento"]["faixas"])
    r_pou = _classificar(poup, C.CAPAG_FAIXAS["poupanca"]["faixas"])
    r_liq = _classificar(liq, C.CAPAG_FAIXAS["liquidez"]["faixas"])

    # Combinação (config.CAPAG_REGRA):
    if r_end == "C" or r_pou == "C":
        nota = "D"
    else:
        piores = {"A": 0, "B": 1, "C": 2}
        nota = max([r_end, r_pou], key=lambda r: piores[r])
    # Liquidez insuficiente trava em no máximo C
    if r_liq == "C" and nota in ("A", "B"):
        nota = "C"

    return CAPAGResultado(
        ano=ano, endividamento=endiv, poupanca=poup, liquidez=liq,
        rating_endividamento=r_end, rating_poupanca=r_pou, rating_liquidez=r_liq,
        nota_final=nota,
        componentes={
            "Endividamento (DC/RCL)": (endiv, r_end),
            "Poupança corrente": (poup, r_pou),
            "Liquidez": (liq, r_liq),
        },
    )


# ===========================================================================
# ÍNDICE PROPAG  (composto 0-100; pesos declarados)
# ===========================================================================
@dataclass
class PropagResultado:
    ano: int
    indice: float
    subindicadores: dict     # nome -> {"score":0-100, "peso":..., "detalhe":str}
    contrapartidas: dict     # fef/investimento efetivos (dependem do FNDR)
    alerta_resim: bool       # dispara re-simulação (FNDR rejeitado)


def calcular_propag(ano: int, rcl: float, servico_divida: float,
                    receita_primaria_disp: float, cen: Cenario,
                    servico_pre_propag: float) -> PropagResultado:
    """Índice Propag simulado. Subindicadores em config.PROPAG['pesos']."""
    p = C.PROPAG
    pesos = p["pesos"]

    # Contrapartidas efetivas dependem do status do ativo FNDR ofertado
    rejeitado = cen.fndr_status == "rejeitado"
    contr_fef = p["contrapartida_fef_rejeitado"] if rejeitado else p["contrapartida_fef"]
    contr_inv = p["contrapartida_inv_rejeitado"] if rejeitado else p["contrapartida_investimento"]

    aporte_fef_devido = contr_fef * rcl              # 1% (ou 2%) da RCL
    inv_exigido = contr_inv * rcl

    def clamp(x, lo=0.0, hi=100.0):
        return max(lo, min(hi, x))

    sub = {}

    # 1) Cobertura do aporte ao FEF — saldo primário corrente ÷ aporte devido.
    #    RP disponível negativo (custeio+pessoal > RCL) ⇒ score 0: o Estado não
    #    gera caixa primário para o compromisso sem comprimir custeio.
    razao_cob = (receita_primaria_disp / aporte_fef_devido) if aporte_fef_devido else 1.0
    cob = clamp(100.0 * razao_cob)
    sub["cobertura_fef"] = {
        "score": cob, "peso": pesos["cobertura_fef"],
        "detalhe": f"Saldo primário corrente R$ {receita_primaria_disp:.1f} bi vs aporte R$ {aporte_fef_devido:.2f} bi",
    }

    # 2) Aderência ao investimento obrigatório (risco de EXECUÇÃO)
    ader = clamp(100.0 * cen.investimento_executado_frac)
    sub["aderencia_investimento"] = {
        "score": ader, "peso": pesos["aderencia_investimento"],
        "detalhe": f"Execução {cen.investimento_executado_frac*100:.0f}% do exigido ({inv_exigido:.2f})",
    }

    # 3) Risco do ativo FNDR (semáforo)
    risco = float(p["semaforo_fndr"][cen.fndr_status])
    sub["risco_ativo_fndr"] = {
        "score": risco, "peso": pesos["risco_ativo_fndr"],
        "detalhe": f"FNDR: {cen.fndr_status} (único ativo ofertado)",
    }

    # 4) Folga do serviço da dívida vs patamar pré-Propag.
    #    Nível da folga mapeado de [50%..90%] -> [0..100], com bônus/penalidade
    #    pela variação frente ao serviço pré-Propag (efeito do choque ACO 3.678).
    folga_atual = (rcl - servico_divida) / rcl if rcl else 0.0
    folga_pre = (rcl - servico_pre_propag) / rcl if rcl else 0.0
    nivel = (folga_atual - 0.50) / (0.90 - 0.50) * 100.0
    delta = (folga_atual - folga_pre) * 400.0   # penaliza choque de serviço
    folga_score = clamp(nivel + delta)
    sub["folga_servico_divida"] = {
        "score": folga_score, "peso": pesos["folga_servico_divida"],
        "detalhe": f"Folga {folga_atual*100:.1f}% da RCL (pré-Propag {folga_pre*100:.1f}%)",
    }

    # 5) Sensibilidade ao IPCA (contratos passam a IPCA com o contrato assinado)
    #    menor IPCA => menor risco de correção => score maior.
    ipca = cen.d("ipca", ano)
    ipca_score = clamp(100.0 - (ipca - 3.5) * 12.0)
    sub["sensibilidade_ipca"] = {
        "score": ipca_score, "peso": pesos["sensibilidade_ipca"],
        "detalhe": f"IPCA {ipca:.2f}% — única indexação sob contrato assinado",
    }

    indice = sum(s["score"] * s["peso"] for s in sub.values())

    return PropagResultado(
        ano=ano, indice=indice, subindicadores=sub,
        contrapartidas={"fef_%": contr_fef, "investimento_%": contr_inv,
                        "aporte_fef": aporte_fef_devido, "inv_exigido": inv_exigido},
        alerta_resim=rejeitado,
    )


# ===========================================================================
# LRF / VINCULAÇÕES
# ===========================================================================
@dataclass
class LRFResultado:
    ano: int
    itens: dict   # nome -> {"valor":..., "limite":..., "status":..., "folga":...}


def _status_teto(valor, teto, alerta=None, prudencial=None):
    if valor > teto:
        return "ESTOURADO"
    if prudencial and valor > prudencial:
        return "PRUDENCIAL"
    if alerta and valor > alerta:
        return "ALERTA"
    return "OK"


def _status_piso(valor, piso):
    return "OK" if valor >= piso else "ABAIXO"


def calcular_lrf(ano: int, pessoal: float, rcl: float, dcl: float,
                 aplic_saude: float, aplic_educacao: float,
                 base_saude_educ: float, vinculacoes: dict | None = None
                 ) -> LRFResultado:
    """Limites da LRF e vinculações constitucionais.

    base_saude_educ = base de cálculo (receita de impostos + transferências).
    `vinculacoes`: resultados de engine.vinculacoes.avaliar() — quando presente,
    substitui a estimativa sintética de saúde/educação pelo dado apurado.
    """
    pessoal_rcl = pessoal / rcl if rcl else float("inf")
    dcl_rcl = dcl / rcl if rcl else float("inf")
    if vinculacoes:
        saude_pct = vinculacoes["saude"].percentual
        educ_pct = vinculacoes["educacao"].percentual
        base_saude_educ = vinculacoes["saude"].base_calculo
        aplic_saude = vinculacoes["saude"].aplicado
        aplic_educacao = vinculacoes["educacao"].aplicado
    else:
        saude_pct = aplic_saude / base_saude_educ if base_saude_educ else 0.0
        educ_pct = aplic_educacao / base_saude_educ if base_saude_educ else 0.0

    itens = {
        "Pessoal / RCL": {
            "valor": pessoal_rcl, "limite": C.LRF["pessoal_rcl_teto"],
            "status": _status_teto(pessoal_rcl, C.LRF["pessoal_rcl_teto"],
                                   C.LRF["pessoal_rcl_alerta"],
                                   C.LRF["pessoal_rcl_prudencial"]),
            "tipo": "teto",
        },
        "DCL / RCL": {
            "valor": dcl_rcl, "limite": C.LRF["dcl_rcl_teto"],
            "status": _status_teto(dcl_rcl, C.LRF["dcl_rcl_teto"]),
            "tipo": "teto",
        },
        "Saúde (mín. 12%)": {
            "valor": saude_pct, "limite": C.LRF["saude_min"],
            "status": _status_piso(saude_pct, C.LRF["saude_min"]),
            "tipo": "piso",
        },
        "Educação (mín. 25%)": {
            "valor": educ_pct, "limite": C.LRF["educacao_min"],
            "status": _status_piso(educ_pct, C.LRF["educacao_min"]),
            "tipo": "piso",
        },
    }
    return LRFResultado(ano=ano, itens=itens)


# ===========================================================================
# Métricas de QUALIDADE da receita (Bloco 4)
# ===========================================================================
def qualidade_receita(df_rub, ano: int, receita_corrente: float) -> dict:
    """Concentração (Herfindahl e top-2), dependência de petróleo,
    participação de não recorrente."""
    recorrentes = [r for r, m in C.RUBRICAS.items()
                   if m["recorrente"] and r in df_rub.index]
    vals = df_rub.loc[recorrentes, ano]
    total = vals.sum()
    shares = (vals / total) if total else vals * 0
    hhi = float((shares ** 2).sum())
    top2 = float(shares.sort_values(ascending=False).head(2).sum())
    petroleo = float(df_rub.loc["royalties_pe", ano] / receita_corrente) if receita_corrente else 0.0

    nao_rec = [r for r, m in C.RUBRICAS.items()
               if not m["recorrente"] and r in df_rub.index]
    nr_total = float(df_rub.loc[nao_rec, ano].sum()) if nao_rec else 0.0
    part_nr = nr_total / (total + nr_total) if (total + nr_total) else 0.0

    return {
        "hhi": hhi,
        "top2": top2,
        "dependencia_petroleo": petroleo,
        "participacao_nao_recorrente": part_nr,
    }
