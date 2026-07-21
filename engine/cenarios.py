"""
cenarios.py — Orquestra cenários e produz o resultado consolidado.

- Cenários pré-definidos: base, otimista, pessimista e o ADVERSO DE FÁBRICA
  (ACO nº 3.678), além de suporte a cenário customizado (sliders do painel).
- avaliar_cenario() roda receita -> despesa/dívida -> CAPAG/Propag/LRF e
  devolve um objeto único que o painel consome.

Convenção de despesa (protótipo): a despesa é modelada a partir da folha
(pessoal, trajetória vegetativa calibrada), do serviço da dívida (derivado do
estoque + choques) e de um custeio/discricionária que fecha o resultado
primário-alvo. Tudo [CALIBRACAO-PROTOTIPO] — substituir por SIAFE/execução.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import copy
import pandas as pd

from . import config as C
from . import receita as R
from . import indicadores as I


# ---------------------------------------------------------------------------
# Cenários pré-definidos (deltas sobre a âncora do PLDO)
# ---------------------------------------------------------------------------
def _aplica_delta(base: R.Cenario, deltas: dict, nome: str, desc: str,
                  **kw) -> R.Cenario:
    drivers = copy.deepcopy(base.drivers)
    for drv, dv in deltas.items():
        for ano in C.ANOS:
            drivers[drv][ano] = round(drivers[drv][ano] + dv, 4)
    cen = R.Cenario(nome=nome, drivers=drivers, descricao=desc)
    for k, v in kw.items():
        setattr(cen, k, v)
    return cen


def cenarios_predefinidos() -> dict:
    base = R.cenario_base()

    otimista = _aplica_delta(
        base,
        {"pib_real": +1.0, "brent": +12.0, "selic": -1.0, "ipca": -0.5},
        "Otimista",
        "PIB +1,0 p.p.; Brent +US$12; Selic -1,0 p.p.; IPCA -0,5 p.p.",
        fndr_status="aceito", investimento_executado_frac=0.95,
    )
    pessimista = _aplica_delta(
        base,
        {"pib_real": -1.5, "brent": -18.0, "cambio": +0.60, "selic": +1.5,
         "ipca": +1.5},
        "Pessimista",
        "PIB -1,5 p.p.; Brent -US$18; câmbio +0,60; Selic +1,5 p.p.; IPCA +1,5 p.p.",
        fndr_status="parcial", investimento_executado_frac=0.65,
    )

    # Adverso de fábrica — ACO nº 3.678 (choque nomeado, +R$ 11,7 bi serviço)
    aco = copy.deepcopy(base)
    aco.nome = C.CENARIO_ACO_3678["nome"]
    aco.descricao = C.CENARIO_ACO_3678["descricao"]
    aco.choque_servico_divida = {2027: C.CENARIO_ACO_3678["choque_servico_divida_2027"]}
    aco.propag_ativo = C.CENARIO_ACO_3678["propag_ativo"]   # False
    aco.fndr_status = "rejeitado"

    return {
        "base": base,
        "otimista": otimista,
        "pessimista": pessimista,
        "aco_3678": aco,
    }


# ---------------------------------------------------------------------------
# Avaliação completa de um cenário
# ---------------------------------------------------------------------------
@dataclass
class ResultadoCenario:
    nome: str
    descricao: str
    df_receita: pd.DataFrame          # rubricas + agregados por ano
    pessoal: dict                     # {ano: R$ bi}
    divida: dict                      # {ano: {dc, dcl, ...}}
    servico_divida: dict              # {ano: R$ bi}
    capag: dict                       # {ano: CAPAGResultado}
    propag: dict                      # {ano: PropagResultado}
    lrf: dict                         # {ano: LRFResultado}
    qualidade: dict                   # {ano: dict}
    alertas: list = field(default_factory=list)


def avaliar_cenario(cen: R.Cenario, anchors: R.Anchors) -> ResultadoCenario:
    df = R.agregar(R.projetar_receitas(cen))
    pessoal = R.trajetoria_pessoal(anchors)
    divida = R.trajetoria_divida(anchors, cen)

    capag, propag, lrf, qualidade = {}, {}, {}, {}
    servico = {}
    alertas = []

    for ano in C.ANOS:
        rcl = float(df.loc["RCL", ano])
        rec_corrente = float(df.loc["RECEITA_CORRENTE", ano])
        dc = divida[ano]["dc"]
        dcl = divida[ano]["dcl"]

        # Serviço da dívida (protótipo): juros de caixa ~ Selic sobre o estoque
        # + amortização padrão + choque do cenário. [CALIBRACAO-PROTOTIPO]
        selic = cen.d("selic", ano) / 100.0
        juros = dc * (selic * 0.30)          # juros efetivos de caixa
        amortizacao = dc * 0.02
        choque = divida[ano]["choque"]
        servico_base = juros + amortizacao
        servico[ano] = servico_base + choque

        # Despesa corrente (protótipo): pessoal (folha calibrada) + custeio
        # (outras desp. correntes primárias, fração da RCL) + juros. A amortização
        # é despesa de capital e não entra na poupança corrente.
        custeio = rcl * 0.44                  # [CALIBRACAO-PROTOTIPO]
        despesa_corrente = pessoal[ano] + custeio + juros + choque * 0.6
        rec_corr_ajustada = rec_corrente      # ajustes STN [VALIDAR-STN]

        # Caixa/obrigações (protótipo) para liquidez do CAPAG
        caixa_bruto = rcl * 0.08
        obrig_fin = caixa_bruto * (1.15 if not cen.propag_ativo else 0.85)

        capag[ano] = I.calcular_capag(
            ano, dc=dc, rcl=rcl,
            despesa_corrente=despesa_corrente,
            receita_corrente_ajustada=rec_corr_ajustada,
            obrigacoes_financeiras=obrig_fin, caixa_bruto=caixa_bruto,
        )

        # Propag — receita primária disponível = saldo primário corrente
        # (RCL menos despesas primárias correntes; exclui juros).
        receita_primaria_disp = rcl - pessoal[ano] - custeio
        servico_pre_propag = servico_base  # sem choque
        propag[ano] = I.calcular_propag(
            ano, rcl=rcl, servico_divida=servico[ano],
            receita_primaria_disp=receita_primaria_disp, cen=cen,
            servico_pre_propag=servico_pre_propag,
        )
        if propag[ano].alerta_resim and "FNDR rejeitado" not in " ".join(alertas):
            alertas.append("FNDR rejeitado ⇒ contrapartidas sobem a 2%/2% — re-simulação disparada.")

        # LRF / vinculações (base saúde/educ = impostos + transferências)
        base_se = float(df.loc[["icms", "ipva", "itd", "fpe_ipiexp"], ano].sum())
        aplic_saude = base_se * 0.12          # protótipo: exatamente no piso
        aplic_educacao = base_se * 0.25
        lrf[ano] = I.calcular_lrf(
            ano, pessoal=pessoal[ano], rcl=rcl, dcl=dcl,
            aplic_saude=aplic_saude, aplic_educacao=aplic_educacao,
            base_saude_educ=base_se,
        )

        qualidade[ano] = I.qualidade_receita(df, ano, rec_corrente)

    # Alertas macro herdados do PLDO
    if cen.choque_servico_divida:
        alertas.append(
            f"Cenário ACO 3.678: +R$ {sum(cen.choque_servico_divida.values()):.1f} bi "
            "no serviço da dívida (2027)."
        )

    return ResultadoCenario(
        nome=cen.nome, descricao=cen.descricao, df_receita=df,
        pessoal=pessoal, divida=divida, servico_divida=servico,
        capag=capag, propag=propag, lrf=lrf, qualidade=qualidade, alertas=alertas,
    )
