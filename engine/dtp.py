"""
dtp.py — Despesa Total com Pessoal (LRF arts. 18-20) a partir da base SIGFIS.

DTP (art. 18): somatório dos gastos com ativos, inativos e pensionistas —
vencimentos e vantagens, subsídios, proventos, adicionais, gratificações,
horas extras, vantagens pessoais e encargos sociais. Na base disponível isso
corresponde ao **GND 1 (Pessoal e Encargos Sociais)**.

Deduções (art. 19, § 1º) — aplicadas conforme config.DTP_DEDUCOES:
  I e II  indenização por demissão e incentivo à demissão voluntária
  IV      decorrentes de decisão judicial de período anterior (precatórios)
  VI      inativos custeados por recursos vinculados ao RPPS (DESLIGADO por
          padrão no ERJ — ver a nota em config, é escolha jurídica)

Limites (art. 20, II): 60% da RCL no total, repartidos em Executivo 49%,
Judiciário 6%, Legislativo 3% (com TCE) e Ministério Público 2%.

LIMITAÇÕES DESTA APURAÇÃO (declaradas, não escondidas):
  * A LRF apura a DTP nos ÚLTIMOS 12 MESES. A planilha traz 7 meses de 2026,
    então o cálculo é anualizado por run-rate — aproximação, não a apuração
    oficial do RGF.
  * A base é o estágio PAGO (não há empenhado/liquidado no export).
  * A atribuição de Poder usa a Função orçamentária; os inativos (Função 9,
    concentrados nas UOs do RIOPREVIDÊNCIA) são atribuídos ao Poder de origem
    pelo título da ação (ex.: "Encargos com Inativos - Tribunal de Justiça").
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re

import pandas as pd

from . import config as C

# Função orçamentária -> Poder (art. 20, II)
FUNCAO_PODER = {
    1: "Legislativo",   # ALERJ + TCE-RJ
    2: "Judiciário",    # TJ
}
PODER_PADRAO = "Executivo"

# Função 3 (Essencial à Justiça) reúne MP, Defensoria e Procuradoria, mas a LRF
# dá limite próprio só ao Ministério Público (2%). PGE e DPGE ficam no
# Executivo (49%) — enquadramento da Defensoria é [VALIDAR-JURIDICO].
UO_MINISTERIO_PUBLICO = ("MP",)

# Palavras no título da ação que revelam o Poder de origem dos inativos
_PODER_POR_TITULO = [
    (r"tribunal de justi|judici", "Judiciário"),
    (r"minist[ée]rio p[úu]blico", "Ministério Público"),
    (r"assembleia|alerj|tribunal de contas|legislat", "Legislativo"),
]


def _poder_da_linha(funcao, titulo: str, sigla_uo: str = "") -> str:
    """Poder de uma linha de despesa. Para inativos (Função 9), infere o Poder
    de origem pelo título da ação; senão, Executivo."""
    try:
        f = int(float(funcao))
    except (TypeError, ValueError):
        f = -1
    if f in FUNCAO_PODER:
        return FUNCAO_PODER[f]
    if f == 3:  # Essencial à Justiça — só o MP tem limite próprio
        return ("Ministério Público" if str(sigla_uo).strip().upper()
                in UO_MINISTERIO_PUBLICO else PODER_PADRAO)
    if f == 9:  # Previdência — inativos/pensionistas
        t = str(titulo).lower()
        for padrao, poder in _PODER_POR_TITULO:
            if re.search(padrao, t):
                return poder
    return PODER_PADRAO


@dataclass
class ResultadoDTP:
    dtp_bruta: float                 # GND 1 total (R$ bi, já anualizado)
    deducoes: dict                   # nome -> R$ bi
    dtp_liquida: float               # DTP após deduções
    rcl: float
    razao: float                     # DTP / RCL
    limite: float                    # 60%
    status: str
    por_poder: pd.DataFrame          # DTP, limite e status por Poder
    componentes: dict                # ativos / inativos / pensionistas
    anualizado: bool
    n_meses: int
    observacoes: list = field(default_factory=list)


def _status(razao: float, teto: float) -> str:
    if razao > teto:
        return "ESTOURADO"
    if razao > teto * 0.95:
        return "PRUDENCIAL"
    if razao > teto * 0.90:
        return "ALERTA"
    return "OK"


def calcular_dtp(ds, rcl: float, anualizar: bool = True) -> ResultadoDTP:
    """Apura a DTP a partir de um `sigfis.DespesaSigfis` e da RCL (R$ bi)."""
    esc = C.DB_ESCALA_PARA_BI
    fator = (12.0 / ds.n_meses) if (anualizar and ds.n_meses) else 1.0
    obs = []

    d = ds.df
    p1 = d[d["Gr Desp"] == 1].copy()          # GND 1 = pessoal e encargos
    p1["_titulo"] = p1["Tit Ação"].astype(str)
    p1["_valor"] = p1["Pago"] * esc * fator
    p1["_poder"] = [_poder_da_linha(f, t, u)
                    for f, t, u in zip(p1["Função"], p1["_titulo"], p1["Sigla UO"])]

    dtp_bruta = float(p1["_valor"].sum())

    # ---- deduções do art. 19, § 1º -------------------------------------
    deducoes = {}
    mascara_deduzida = pd.Series(False, index=p1.index)

    reg = C.DTP_DEDUCOES["precatorios_periodo_anterior"]
    if reg["ativo"]:
        m = p1["_titulo"].str.contains("PRECAT|SENTEN", case=False, regex=True)
        deducoes["Precatórios / sentenças de período anterior"] = float(p1.loc[m, "_valor"].sum())
        mascara_deduzida |= m

    reg = C.DTP_DEDUCOES["indenizacao_demissao_pdv"]
    if reg["ativo"]:
        m = p1["_titulo"].str.contains("INDENIZ|DEMISS|VOLUNT", case=False, regex=True)
        deducoes["Indenização por demissão / PDV"] = float(p1.loc[m, "_valor"].sum())
        mascara_deduzida |= m

    reg = C.DTP_DEDUCOES["inativos_recursos_vinculados"]
    if reg["ativo"]:
        fontes = reg["fontes_stn_dedutiveis"]
        m = (p1["Função"] == 9) & (p1["Fonte STN"].isin(fontes))
        deducoes["Inativos com recursos vinculados ao RPPS"] = float(p1.loc[m, "_valor"].sum())
        mascara_deduzida |= m
    else:
        obs.append(
            "Dedução do art. 19, §1º, VI (inativos com recursos vinculados) está "
            "DESLIGADA: no ERJ os inativos são custeados sobretudo por royalties "
            "(fonte STN 704) e pelo Tesouro. " + reg["alerta"])

    dtp_liquida = dtp_bruta - sum(deducoes.values())

    # ---- componentes ----------------------------------------------------
    inat = p1[p1["Função"] == 9]
    m_pens = inat["_titulo"].str.contains("PENS", case=False)
    componentes = {
        "Ativos (demais funções)": float(p1[p1["Função"] != 9]["_valor"].sum()),
        "Inativos (Função 9)": float(inat.loc[~m_pens, "_valor"].sum()),
        "Pensionistas (Função 9)": float(inat.loc[m_pens, "_valor"].sum()),
    }

    # ---- por Poder ------------------------------------------------------
    liq = p1.loc[~mascara_deduzida]
    g = liq.groupby("_poder")["_valor"].sum()
    linhas = []
    for poder, teto in C.LRF_SUBLIMITES.items():
        val = float(g.get(poder, 0.0))
        razao_p = val / rcl if rcl else 0.0
        linhas.append({"Poder": poder, "DTP (R$ bi)": val,
                       "% da RCL": razao_p * 100, "Limite %": teto * 100,
                       "Margem p.p.": (teto - razao_p) * 100,
                       "Status": _status(razao_p, teto)})
    por_poder = pd.DataFrame(linhas).sort_values("DTP (R$ bi)", ascending=False)

    razao = dtp_liquida / rcl if rcl else 0.0
    if anualizar:
        obs.append(f"DTP anualizada por run-rate (× {fator:.2f}) sobre {ds.n_meses} "
                   "meses. A LRF apura em 12 meses — aproximação.")
    obs.append("Base: estágio PAGO (o export não traz empenhado/liquidado).")

    return ResultadoDTP(
        dtp_bruta=dtp_bruta, deducoes=deducoes, dtp_liquida=dtp_liquida,
        rcl=rcl, razao=razao, limite=C.LRF["pessoal_rcl_teto"],
        status=_status(razao, C.LRF["pessoal_rcl_teto"]),
        por_poder=por_poder, componentes=componentes,
        anualizado=anualizar, n_meses=ds.n_meses, observacoes=obs,
    )
