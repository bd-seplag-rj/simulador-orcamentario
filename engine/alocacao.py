"""
alocacao.py — Simulador de nova despesa: "cabe no orçamento e o que acontece?"

O usuário propõe uma ou mais despesas (UO, valor, grupo de despesa, função) e
o motor responde três perguntas distintas — que muita gente confunde:

  1. HÁ AUTORIZAÇÃO?  saldo de dotação da UO (espaço orçamentário)
  2. HÁ DINHEIRO?     resultado primário / margem fiscal do Estado
  3. É LEGAL?         limites da LRF (DTP e sublimite do Poder), vinculações,
                      DCL/RCL e, se a despesa for continuada, os arts. 16 e 17

Depois recalcula CAPAG, Propag, LRF e vinculações COM a despesa e mostra o
delta contra o cenário sem ela.

Veredito:
  VIÁVEL              nenhuma restrição violada
  VIÁVEL COM RESSALVA piora indicador, estoura dotação ou exige compensação
  INVIÁVEL            viola limite legal (teto da LRF, piso de vinculação)
"""
from __future__ import annotations
from dataclasses import dataclass, field
import copy

import pandas as pd

from . import config as C
from . import cenarios as S
from . import despesa as D
from . import dtp as DTP

# Categorias que o usuário pode propor (GND)
CATEGORIAS = {
    "pessoal": "1 — Pessoal e Encargos",
    "custeio": "3 — Outras Despesas Correntes (custeio)",
    "investimento": "4 — Investimentos",
    "inversoes": "5 — Inversões Financeiras",
    "amortizacao": "6 — Amortização da Dívida",
}
CATEGORIAS_CORRENTES = ("pessoal", "custeio", "juros")


@dataclass
class Proposta:
    cod_uo: str
    sigla_uo: str
    valor: float                 # R$ bi
    categoria: str               # chave de CATEGORIAS
    funcao: int = 0              # função orçamentária (0 = não informada)
    recorrente: bool = True      # despesa obrigatória de caráter continuado?
    poder: str = "Executivo"

    @property
    def e_corrente(self) -> bool:
        return self.categoria in CATEGORIAS_CORRENTES

    @property
    def vinculacao(self) -> str | None:
        """Se a função da proposta alimenta uma vinculação constitucional."""
        for chave, cfg in C.VINCULACOES.items():
            if int(self.funcao or 0) == cfg["funcao"]:
                return chave
        return None


@dataclass
class Checagem:
    nome: str
    status: str          # OK | ATENCAO | BLOQUEIO
    detalhe: str
    folga: float | None = None    # R$ bi disponíveis (None = não aplicável)


@dataclass
class ResultadoAlocacao:
    propostas: list
    total: float
    verdicto: str
    checagens: list
    res_antes: object
    res_depois: object
    deltas: dict = field(default_factory=dict)
    margem_maxima: dict = field(default_factory=dict)
    observacoes: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Espaço orçamentário (autorização) — saldo de dotação da UO
# ---------------------------------------------------------------------------
def saldo_dotacao(ds, cod_uo: str, anualizar: bool = True) -> dict:
    esc = C.DB_ESCALA_PARA_BI
    d = ds.df[ds.df["Cod UO"] == str(cod_uo)]
    fator = (12.0 / ds.n_meses) if (anualizar and ds.n_meses) else 1.0
    dot = float(d["Dotação Atualizada"].sum() * esc)
    pago = float(d["Pago"].sum() * esc)
    proj = pago * fator                      # projeção do gasto no ano
    return {"dotacao": dot, "pago": pago, "projetado": proj,
            "saldo": dot - proj, "execucao_pct": (pago / dot * 100) if dot else 0.0}


def mapa_uo_poder(ds) -> dict:
    """Poder de cada UO, pela função predominante das suas despesas."""
    d = ds.df.copy()
    d["_poder"] = [DTP._poder_da_linha(f, t, u) for f, t, u
                   in zip(d["Função"], d["Tit Ação"].astype(str), d["Sigla UO"])]
    principal = (d.groupby(["Cod UO", "_poder"])["Pago"].sum()
                 .reset_index().sort_values("Pago", ascending=False)
                 .drop_duplicates("Cod UO"))
    return dict(zip(principal["Cod UO"], principal["_poder"]))


# ---------------------------------------------------------------------------
# Margem fiscal — resultado primário
# ---------------------------------------------------------------------------
def resultado_primario(res, ano: int) -> dict:
    """Espaço fiscal do exercício.

    ATENÇÃO ao universo: a receita comparável à despesa NÃO é a RCL. A RCL
    exclui intraorçamentárias e contribuições dos servidores — mas essas
    receitas financiam despesas que ESTÃO na despesa total. Usar a RCL aqui
    produziria déficit artificial. A base correta é a receita corrente bruta
    menos as parcelas entregues aos Municípios (que saem do caixa).

      Receita disponível = receita corrente − cota-parte dos Municípios
      Despesa primária   = despesa total − juros − amortização
      Resultado primário = receita disponível − despesa primária
    """
    df = res.df_receita
    rec_corrente = float(df.loc["RECEITA_CORRENTE", ano])
    ded_mun = float(df.loc["RCL_DED_MUNICIPIOS", ano]) if "RCL_DED_MUNICIPIOS" in df.index else 0.0
    receita_disp = rec_corrente - ded_mun

    dsp = res.despesa.get(ano, {})
    juros = dsp.get("juros", 0.0)
    amort = dsp.get("amortizacao", 0.0)
    despesa_total = sum(dsp.get(k, 0.0) for k in
                        ("pessoal", "custeio", "investimento", "inversoes",
                         "juros", "amortizacao"))
    despesa_primaria = despesa_total - juros - amort
    prim = receita_disp - despesa_primaria
    return {"receita_primaria": receita_disp,
            "despesa_primaria": despesa_primaria,
            "despesa_total": despesa_total,
            "resultado_primario": prim,
            "margem_orcamentaria": receita_disp - despesa_total,
            "juros": juros, "amortizacao": amort,
            "resultado_nominal": prim - juros - amort}


# ---------------------------------------------------------------------------
# Simulação
# ---------------------------------------------------------------------------
def simular(cen, anchors, base_despesa, ds, rs, propostas: list,
            ano: int | None = None) -> ResultadoAlocacao:
    """Avalia as propostas e devolve viabilidade + impacto nos índices."""
    ano = ano or C.ANOS[0]
    total = float(sum(p.valor for p in propostas))

    inc_cat, inc_poder, inc_vinc = {}, {}, {}
    for p in propostas:
        inc_cat[p.categoria] = inc_cat.get(p.categoria, 0.0) + p.valor
        if p.categoria == "pessoal":
            inc_poder[p.poder] = inc_poder.get(p.poder, 0.0) + p.valor
        v = p.vinculacao
        if v:
            inc_vinc[v] = inc_vinc.get(v, 0.0) + p.valor

    # anos afetados: despesa continuada vale do ano em foco em diante;
    # despesa por uma vez só afeta o ano em foco.
    recorrente = any(p.recorrente for p in propostas)
    anos_afetados = [a for a in C.ANOS if a >= ano] if recorrente else [ano]

    res_antes = S.avaliar_cenario(cen, anchors, base_despesa, ds, rs)
    res_depois = S.avaliar_cenario(
        cen, anchors, base_despesa, ds, rs,
        acrescimos={"categoria": inc_cat, "poder": inc_poder,
                    "vinculacao": inc_vinc, "anos": anos_afetados})

    checagens = []
    obs = []

    # -- 1) autorização orçamentária (por UO) ----------------------------
    for p in propostas:
        sd = saldo_dotacao(ds, p.cod_uo)
        if p.valor <= sd["saldo"]:
            checagens.append(Checagem(
                f"Dotação — {p.sigla_uo}", "OK",
                f"Saldo de dotação R$ {sd['saldo']:.2f} bi comporta a despesa "
                f"(execução atual {sd['execucao_pct']:.1f}%).", sd["saldo"]))
        else:
            checagens.append(Checagem(
                f"Dotação — {p.sigla_uo}", "ATENCAO",
                f"Excede o saldo de dotação em R$ {p.valor - sd['saldo']:.2f} bi — "
                "exige crédito adicional com indicação de fonte (art. 43 da Lei "
                "4.320).", sd["saldo"]))

    # -- 2) margem fiscal -------------------------------------------------
    rp_antes = resultado_primario(res_antes, ano)
    rp_depois = resultado_primario(res_depois, ano)
    margem = rp_antes["margem_orcamentaria"]
    margem_dep = rp_depois["margem_orcamentaria"]
    if margem_dep >= 0:
        checagens.append(Checagem(
            "Receita disponível (margem orçamentária)", "OK",
            f"Há margem: receita disponível R$ {rp_antes['receita_primaria']:.2f} bi "
            f"contra despesa total R$ {rp_antes['despesa_total']:.2f} bi. "
            f"A margem cai de R$ {margem:.2f} para R$ {margem_dep:.2f} bi.",
            margem))
    elif margem >= 0:
        checagens.append(Checagem(
            "Receita disponível (margem orçamentária)", "BLOQUEIO",
            f"A despesa proposta (R$ {total:.2f} bi) supera a margem disponível "
            f"de R$ {margem:.2f} bi e leva o orçamento a déficit de "
            f"R$ {abs(margem_dep):.2f} bi.", margem))
    else:
        checagens.append(Checagem(
            "Receita disponível (margem orçamentária)", "BLOQUEIO",
            f"O orçamento JÁ está deficitário em R$ {abs(margem):.2f} bi antes "
            "desta proposta — não há receita disponível.", margem))

    # resultado primário (capacidade de honrar o serviço da dívida)
    st_p = "OK" if rp_depois["resultado_primario"] >= rp_depois["juros"] else "ATENCAO"
    checagens.append(Checagem(
        "Resultado primário vs juros", st_p,
        f"Primário de R$ {rp_antes['resultado_primario']:.2f} → "
        f"R$ {rp_depois['resultado_primario']:.2f} bi, contra juros de "
        f"R$ {rp_depois['juros']:.2f} bi.",
        rp_antes["resultado_primario"]))

    # -- 3) LRF — pessoal (DTP total e sublimite do Poder) ----------------
    if inc_poder and res_depois.dtp is not None:
        t0, t1 = res_antes.dtp, res_depois.dtp
        teto = C.LRF["pessoal_rcl_teto"]
        folga_total = (teto - t0.razao) * t0.rcl
        st = "OK"
        if t1.razao > teto:
            st = "BLOQUEIO" if t0.razao <= teto else "ATENCAO"
        elif t1.razao > teto * 0.95:
            st = "ATENCAO"
        det = (f"DTP/RCL vai de {t0.razao*100:.2f}% para {t1.razao*100:.2f}% "
               f"(teto {teto*100:.0f}%).")
        if t0.razao > teto:
            det += " O limite JÁ estava estourado antes da proposta — "
            det += "art. 23 da LRF veda aumento de despesa com pessoal."
            st = "BLOQUEIO"
        checagens.append(Checagem("LRF — Despesa Total com Pessoal", st, det,
                                  folga_total))
        # sublimite por Poder
        pp0 = t0.por_poder.set_index("Poder")
        pp1 = t1.por_poder.set_index("Poder")
        for poder in inc_poder:
            if poder in pp1.index:
                a, b = pp0.loc[poder, "% da RCL"], pp1.loc[poder, "% da RCL"]
                lim = pp1.loc[poder, "Limite %"]
                stp = "OK" if b <= lim else ("BLOQUEIO" if a <= lim else "BLOQUEIO")
                checagens.append(Checagem(
                    f"LRF — sublimite do {poder}", stp,
                    f"{a:.2f}% → {b:.2f}% da RCL (limite {lim:.0f}%).",
                    (lim - a) / 100 * t0.rcl))

    # -- 4) vinculações ---------------------------------------------------
    v0 = res_antes.vinculacoes.get(ano)
    v1 = res_depois.vinculacoes.get(ano)
    if v0 and v1:
        for chave, r1 in v1.items():
            r0 = v0[chave]
            if r1.status == "ABAIXO":
                st = "BLOQUEIO" if r0.status == "OK" else "ATENCAO"
                det = (f"{r1.percentual*100:.2f}% do mínimo de "
                       f"{r1.minimo*100:.0f}% — faltam R$ {r1.faltante:.2f} bi.")
            else:
                st = "OK"
                det = (f"{r0.percentual*100:.2f}% → {r1.percentual*100:.2f}% "
                       f"(mínimo {r1.minimo*100:.0f}%).")
            checagens.append(Checagem(f"Vinculação — {r1.label}", st, det,
                                      None))

    # -- 5) despesa continuada (arts. 16 e 17) ----------------------------
    if any(p.recorrente for p in propostas):
        checagens.append(Checagem(
            "LRF arts. 16 e 17 — despesa continuada", "ATENCAO",
            "Despesa obrigatória de caráter continuado exige estimativa de "
            "impacto orçamentário-financeiro no exercício e nos dois seguintes, "
            "declaração de adequação à LOA/LDO/PPA e medidas de compensação "
            "(aumento permanente de receita ou redução permanente de despesa).",
            None))
        obs.append(
            f"Impacto continuado estimado: {ano} R$ {total:.2f} bi · "
            f"{ano+1} R$ {total*1.0344:.2f} bi · {ano+2} R$ {total*1.0344**2:.2f} bi "
            "(reajuste vegetativo de 3,44% a.a.).")

    # -- deltas dos índices ----------------------------------------------
    c0, c1 = res_antes.capag[ano], res_depois.capag[ano]
    p0, p1 = res_antes.propag[ano], res_depois.propag[ano]
    l0, l1 = res_antes.lrf[ano].itens, res_depois.lrf[ano].itens
    deltas = {
        "CAPAG nota": (c0.nota_final, c1.nota_final),
        "CAPAG poupança": (c0.poupanca, c1.poupanca),
        "CAPAG endividamento": (c0.endividamento, c1.endividamento),
        "CAPAG liquidez": (c0.liquidez, c1.liquidez),
        "Propag índice": (p0.indice, p1.indice),
        "Pessoal/RCL": (l0["Pessoal / RCL"]["valor"], l1["Pessoal / RCL"]["valor"]),
        "DCL/RCL": (l0["DCL / RCL"]["valor"], l1["DCL / RCL"]["valor"]),
        "Resultado primário": (rp_antes["resultado_primario"],
                               rp_depois["resultado_primario"]),
    }

    # -- margem máxima por restrição --------------------------------------
    margem = {"Margem orçamentária": max(0.0, rp_antes["margem_orcamentaria"])}
    for p in propostas[:1]:
        margem[f"Dotação {p.sigla_uo}"] = max(0.0, saldo_dotacao(ds, p.cod_uo)["saldo"])
    if res_antes.dtp is not None and inc_poder:
        t0 = res_antes.dtp
        margem["LRF pessoal (até o teto)"] = max(
            0.0, (C.LRF["pessoal_rcl_teto"] - t0.razao) * t0.rcl)

    # -- veredito ---------------------------------------------------------
    if any(c.status == "BLOQUEIO" for c in checagens):
        verdicto = "INVIÁVEL"
    elif any(c.status == "ATENCAO" for c in checagens):
        verdicto = "VIÁVEL COM RESSALVA"
    else:
        verdicto = "VIÁVEL"

    return ResultadoAlocacao(
        propostas=propostas, total=total, verdicto=verdicto,
        checagens=checagens, res_antes=res_antes, res_depois=res_depois,
        deltas=deltas, margem_maxima=margem, observacoes=obs)
