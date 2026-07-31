"""
receita.py — Motor de projeção de receita por rubrica + calibração.

Cada rubrica projeta 2027-2029 a partir do BASELINE_2026 e dos drivers macro
do cenário, usando as elasticidades/fatores declarados em config.ELASTICIDADES.
Fórmulas documentadas por rubrica; nada de número mágico solto.

Fluxo:
    drivers (por ano) ── projetar_receitas() ──> DataFrame por rubrica/ano
                                              └─> agregados (Rec. Corrente, RCL)
    calibrar() resolve os absolutos de pessoal e estoque de dívida para que o
    cenário-base reproduza as razões do PLDO 2027 (68,57% / 263% / 277%).
"""

from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd

from . import config as C


# ---------------------------------------------------------------------------
# Estrutura de um cenário de drivers
# ---------------------------------------------------------------------------
@dataclass
class Cenario:
    """Conjunto de drivers macro por ano + choques discretos."""
    nome: str
    drivers: dict            # {driver: {ano: valor}}
    choque_servico_divida: dict = field(default_factory=dict)  # {ano: R$ bi}
    propag_ativo: bool = True
    fndr_status: str = "parcial"   # aceito | parcial | rejeitado
    investimento_executado_frac: float = 0.80  # fração do investimento exigido
    descricao: str = ""

    def d(self, driver: str, ano: int) -> float:
        return self.drivers[driver][ano]


def cenario_base() -> Cenario:
    """Cenário-base: âncoras do PLDO (Focus 06/03/2026)."""
    drivers = {k: dict(v["ancora"]) for k, v in C.DRIVERS_MACRO.items()}
    return Cenario(
        nome="Base (PLDO 2027)",
        drivers=drivers,
        propag_ativo=True,
        fndr_status="parcial",
        descricao="Parâmetros-âncora do PLDO 2027.",
    )


# ---------------------------------------------------------------------------
# Projeção por rubrica
# ---------------------------------------------------------------------------
def _proj_composta(cen: Cenario, ano: int, e_pib: float, pass_ipca: float,
                   e_cambio: float = 0.0) -> float:
    """Multiplicador acumulado do ANO_BASE até `ano` por crescimento composto:
       g_t = e_pib*pib_real_t + pass_ipca*ipca_t + e_cambio*var_cambio_t.
    O câmbio entra pela variação relativa ano a ano (parte do ANO_BASE)."""
    mult = 1.0
    cambio_prev = cen.drivers["cambio"].get(C.ANO_BASE, cen.d("cambio", C.ANOS[0]))
    for a in range(C.ANOS[0], ano + 1):
        pib = cen.d("pib_real", a) / 100.0
        ipca = cen.d("ipca", a) / 100.0
        cambio_a = cen.d("cambio", a)
        var_cambio = (cambio_a - cambio_prev) / cambio_prev if cambio_prev else 0.0
        g = e_pib * pib + pass_ipca * ipca + e_cambio * var_cambio
        mult *= (1.0 + g)
        cambio_prev = cambio_a
    return mult


def projetar_receitas(cen: Cenario) -> pd.DataFrame:
    """Projeta cada rubrica recorrente 2027-2029. Retorna DataFrame:
       colunas = anos; index = rubricas; + linhas agregadas."""
    base = C.BASELINE_2026
    linhas = {}

    for rub, elast in C.ELASTICIDADES.items():
        vals = {}
        for ano in C.ANOS:
            b = base[rub]
            if rub == "irrf" or rub == "rpps":
                # crescimento vegetativo composto da folha (3,44% a.a.)
                f = elast["fator_vegetativo"]
                anos_passados = ano - C.ANO_BASE
                vals[ano] = b * (1.0 + f) ** anos_passados
            elif rub == "fecp":
                # razão fixa sobre o ICMS do mesmo ano
                razao = base["fecp"] / base["icms"]
                vals[ano] = None  # preenchido depois (depende de ICMS já projetado)
            elif rub == "royalties_pe":
                brent = cen.d("brent", ano) / elast["brent_ref"]
                cambio = cen.d("cambio", ano) / elast["cambio_ref"]
                prod = cen.d("producao_oleo", ano)
                vals[ano] = b * brent * cambio * prod
            elif rub == "outras_correntes":
                vals[ano] = b * _proj_composta(cen, ano, 0.0,
                                               elast["passthrough_ipca"])
            else:
                vals[ano] = b * _proj_composta(
                    cen, ano,
                    elast.get("e_pib_real", 0.0),
                    elast.get("passthrough_ipca", 0.0),
                    elast.get("e_cambio", 0.0),
                )
        linhas[rub] = vals

    df = pd.DataFrame(linhas).T  # rubricas x anos
    # FECP depende do ICMS já projetado
    razao_fecp = base["fecp"] / base["icms"]
    for ano in C.ANOS:
        df.loc["fecp", ano] = df.loc["icms", ano] * razao_fecp

    df = df[C.ANOS]  # ordem das colunas
    return df


def fatores_rcl() -> float:
    """Soma das exclusões aplicadas à receita corrente bruta (art. 2º, IV LRF):
    deduções constitucionais + contribuições dos servidores + intraorçamentárias."""
    return (C.FATOR_DEDUCAO_RCL + C.FATOR_CONTRIB_SERVIDORES
            + C.FATOR_INTRAORCAMENTARIA)


def agregar(df_rub: pd.DataFrame) -> pd.DataFrame:
    """Adiciona linhas agregadas: Receita Corrente (bruta) e RCL (LRF).

    A RCL segue o art. 2º, IV da LRF: exclui as parcelas entregues aos
    Municípios, as contribuições dos servidores ao RPPS e as receitas
    intraorçamentárias (duplicação). Ver a composição em config.
    """
    recorrentes = [r for r, m in C.RUBRICAS.items()
                   if m["recorrente"] and r in df_rub.index]
    rec_corrente = df_rub.loc[recorrentes].sum()
    rcl = rec_corrente * (1.0 - fatores_rcl())

    out = df_rub.copy()
    out.loc["RECEITA_CORRENTE"] = rec_corrente
    out.loc["RCL"] = rcl
    # componentes da RCL (transparência: nunca só o agregado)
    out.loc["RCL_DED_MUNICIPIOS"] = rec_corrente * C.FATOR_DEDUCAO_RCL
    out.loc["RCL_DED_CONTRIB_SERV"] = rec_corrente * C.FATOR_CONTRIB_SERVIDORES
    out.loc["RCL_DED_INTRA"] = rec_corrente * C.FATOR_INTRAORCAMENTARIA
    return out


# ---------------------------------------------------------------------------
# Calibração — resolve absolutos de pessoal / dívida para reproduzir o PLDO
# ---------------------------------------------------------------------------
@dataclass
class Anchors:
    """Absolutos calibrados no cenário-base (ficam fixos como 'estoque'/trajetória
    e evoluem por regra própria nos demais cenários)."""
    pessoal_2026: float           # folha base 2026 (cresce 3,44%/ano)
    dc_2027: float                # estoque Dívida Consolidada 2027
    dcl_2027: float               # estoque Dívida Consolidada Líquida 2027
    rcl_base_2027: float          # RCL do cenário-base em 2027 (referência)


def calibrar() -> Anchors:
    """Roda o cenário-base, mede a RCL 2027 e ancora pessoal/dívida às razões
    do PLDO (68,57% / 263% / 277%)."""
    cen = cenario_base()
    agg = agregar(projetar_receitas(cen))
    rcl_2027 = float(agg.loc["RCL", 2027])

    a = C.ANCORAS_PLDO_2027
    pessoal_2027 = a["pessoal_sobre_rcl"] * rcl_2027
    pessoal_2026 = pessoal_2027 / (1.0 + C.ELASTICIDADES["irrf"]["fator_vegetativo"])
    dc_2027 = a["dc_sobre_rcl"] * rcl_2027
    dcl_2027 = a["dcl_sobre_rcl"] * rcl_2027
    return Anchors(pessoal_2026, dc_2027, dcl_2027, rcl_2027)


def trajetoria_pessoal(anchors: Anchors) -> dict:
    """Folha por ano: base 2026 crescendo 3,44% a.a. (vegetativo, independe de RCL)."""
    f = C.ELASTICIDADES["irrf"]["fator_vegetativo"]
    return {ano: anchors.pessoal_2026 * (1.0 + f) ** (ano - C.ANO_BASE)
            for ano in C.ANOS}


def trajetoria_divida(anchors: Anchors, cen: Cenario) -> dict:
    """Estoque de Dívida Consolidada por ano.

    Modelo: estoque indexado (IGP-M/IPCA — proxy da correção contratual) e
    acrescido do choque de serviço da dívida do cenário (ex.: ACO 3.678).
    Sob Propag assinado, contratos passam a IPCA; sem Propag mantém-se a
    indexação mais cara (proxy IGP-M) — daí a sensibilidade que o painel testa.
    Retorna {ano: {"dc":..., "dcl":...}}.
    """
    out = {}
    dc = anchors.dc_2027
    dcl = anchors.dcl_2027
    for i, ano in enumerate(C.ANOS):
        indexador = cen.d("ipca", ano) / 100.0 if cen.propag_ativo \
            else cen.d("igpm", ano) / 100.0
        if i == 0:
            dc_ano, dcl_ano = dc, dcl
        else:
            dc_ano = out[C.ANOS[i - 1]]["dc"] * (1.0 + indexador)
            dcl_ano = out[C.ANOS[i - 1]]["dcl"] * (1.0 + indexador)
        choque = cen.choque_servico_divida.get(ano, 0.0)
        out[ano] = {"dc": dc_ano + choque, "dcl": dcl_ano + choque,
                    "indexador": indexador, "choque": choque}
    return out
