"""
vinculacoes.py — Vinculações constitucionais de educação (MDE) e saúde (ASPS)
apuradas sobre os dados reais, com regras explícitas e configuráveis.

Base de cálculo (art. 212 CF / LC 141): receita de impostos + transferências,
deduzidas as parcelas entregues aos Municípios. O FECP fica fora (adicional de
ICMS vinculado ao Fundo de Combate à Pobreza).

Aplicação: despesa paga na função correspondente (12 Educação / 10 Saúde),
opcionalmente somada aos inativos daquela área (Função 9, identificados pelo
título da ação) — inclusão que é escolha metodológica, ver config.VINCULACOES.

LIMITAÇÕES declaradas: a apuração oficial é do RREO e tem regras finas que a
base disponível não permite reproduzir (ASPS exclui certas despesas; a MDE tem
tratamento próprio para restos a pagar e para o resultado do FUNDEB). Use como
apoio à decisão, não como substituto do RREO.
"""
from __future__ import annotations
from dataclasses import dataclass, field

import pandas as pd

from . import config as C


@dataclass
class ResultadoVinculacao:
    chave: str
    label: str
    base_calculo: float      # R$ bi
    aplicado: float          # R$ bi
    percentual: float        # aplicado / base
    minimo: float
    status: str              # OK | ABAIXO
    faltante: float          # R$ bi para atingir o piso (0 se cumprido)
    componentes: dict = field(default_factory=dict)
    validacao: str = ""


def base_calculo(rs, usar: str = "Previsão Inicial") -> dict:
    """Base das vinculações (R$ bi) com os componentes explícitos."""
    esc = C.DB_ESCALA_PARA_BI
    cls = rs.classificada.copy()
    cod = cls["COD NR"].astype(str)

    impostos = cls[cod.str.startswith(C.VINC_BASE_IMPOSTOS)][usar].sum() * esc
    transfer = cls[cod.str.startswith(C.VINC_BASE_TRANSFERENCIAS)][usar].sum() * esc
    # cota-parte dos Municípios (deduções, valores negativos)
    m_mun = (cod.str.startswith("9")
             & cls["TIT NR"].astype(str).str.contains("Munic", case=False))
    municipios = cls[m_mun][usar].sum() * esc          # negativo

    fecp = 0.0
    if not C.VINC_BASE_EXCLUI_FECP:
        fecp = cls[cod.str.startswith("1114502")][usar].sum() * esc

    base = impostos + transfer + municipios + fecp
    return {
        "base": float(base),
        "impostos": float(impostos),
        "transferencias": float(transfer),
        "cota_parte_municipios": float(municipios),
        "fecp_incluido": float(fecp),
    }


def _aplicado(ds, cfg: dict, anualizar: bool = True) -> dict:
    """Despesa aplicada na função da vinculação (+ inativos da área, se a
    configuração mandar). Retorna componentes em R$ bi."""
    esc = C.DB_ESCALA_PARA_BI
    fator = (12.0 / ds.n_meses) if (anualizar and ds.n_meses) else 1.0
    d = ds.df
    direto = d[d["Função"] == cfg["funcao"]]["Pago"].sum() * esc * fator

    inativos = 0.0
    if cfg.get("incluir_inativos"):
        m = ((d["Função"] == 9)
             & d["Tit Ação"].astype(str).str.contains(cfg["palavras_inativos"],
                                                      case=False, regex=True))
        inativos = d[m]["Pago"].sum() * esc * fator
    return {"direto": float(direto), "inativos": float(inativos),
            "total": float(direto + inativos)}


def avaliar(rs, ds, acrescimos: dict | None = None,
            base_override: float | None = None,
            escala: float = 1.0,
            anualizar: bool = True) -> dict:
    """Avalia todas as vinculações.

    `acrescimos`: {chave_vinculacao: R$ bi} — despesa adicional simulada.
    `base_override`: usa outra base de cálculo (ex.: projetada para 2027).
    `escala`: fator aplicado À DESPESA quando se projeta para um ano futuro.
        Precisa acompanhar a escala usada na base — projetar a base sem
        projetar a aplicação derrubaria o percentual artificialmente.
    """
    acrescimos = acrescimos or {}
    comp_base = base_calculo(rs)
    base = base_override if base_override is not None else comp_base["base"]

    out = {}
    for chave, cfg in C.VINCULACOES.items():
        ap = _aplicado(ds, cfg, anualizar)
        ap = {k: v * escala for k, v in ap.items()}
        extra = float(acrescimos.get(chave, 0.0))
        aplicado = ap["total"] + extra
        pct = (aplicado / base) if base else 0.0
        falta = max(0.0, cfg["minimo"] * base - aplicado)
        out[chave] = ResultadoVinculacao(
            chave=chave, label=cfg["label"], base_calculo=base,
            aplicado=aplicado, percentual=pct, minimo=cfg["minimo"],
            status="OK" if pct >= cfg["minimo"] else "ABAIXO",
            faltante=falta,
            componentes={**ap, "acrescimo_simulado": extra,
                         "base_componentes": comp_base},
            validacao=cfg["validacao"],
        )
    return out


def resumo_base(rs) -> pd.DataFrame:
    c = base_calculo(rs)
    linhas = [
        ("Impostos próprios (ICMS, IPVA, ITD, IRRF)", c["impostos"]),
        ("Transferências (FPE, IPI-Exp.)", c["transferencias"]),
        ("(−) Cota-parte dos Municípios", c["cota_parte_municipios"]),
    ]
    if c["fecp_incluido"]:
        linhas.append(("FECP (incluído por configuração)", c["fecp_incluido"]))
    linhas.append(("= Base de cálculo", c["base"]))
    return pd.DataFrame(linhas, columns=["Componente", "R$ bi"])
