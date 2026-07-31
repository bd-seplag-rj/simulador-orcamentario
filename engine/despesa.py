"""
despesa.py — Base de despesa a partir da execução real (tabela painel_subor).

Converte a agregação por Grupo de Despesa (db.despesa_por_gd) em uma BaseDespesa
com os componentes que os índices precisam, e projeta 2027-2029.

Quando o painel tem banco conectado, esta base SUBSTITUI as premissas
[CALIBRACAO-PROTOTIPO] de despesa em cenarios.avaliar_cenario():
  - pessoal (GND 1)      -> Pessoal/RCL (LRF) e poupança (CAPAG)
  - juros (GND 2)        -> despesa corrente e serviço da dívida
  - custeio (GND 3)      -> despesa corrente / saldo primário (Propag)
  - investimento (GND 4) -> aderência ao investimento (Propag) e Bloco 5
  - amortização (GND 6)  -> serviço da dívida
"""
from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd

from . import config as C


@dataclass
class BaseDespesa:
    ano_base: int
    metrica: str
    por_categoria: dict           # categoria -> R$ bi (execução no ano_base)
    execucao_total: float
    dotacao_total: float
    fonte: str = "painel_subor (execução real)"
    detalhe_gd: pd.DataFrame = field(default=None, repr=False)

    # atalhos
    @property
    def pessoal(self):      return self.por_categoria.get("pessoal", 0.0)
    @property
    def juros(self):        return self.por_categoria.get("juros", 0.0)
    @property
    def custeio(self):      return self.por_categoria.get("custeio", 0.0)
    @property
    def investimento(self): return self.por_categoria.get("investimento", 0.0)
    @property
    def inversoes(self):    return self.por_categoria.get("inversoes", 0.0)
    @property
    def amortizacao(self):  return self.por_categoria.get("amortizacao", 0.0)

    @property
    def despesa_corrente(self):
        return sum(self.por_categoria.get(k, 0.0) for k in C.CATEGORIAS_CORRENTES)

    @property
    def despesa_capital(self):
        return sum(self.por_categoria.get(k, 0.0) for k in C.CATEGORIAS_CAPITAL)

    @property
    def servico_divida(self):
        return sum(self.por_categoria.get(k, 0.0) for k in C.CATEGORIAS_SERVICO_DIVIDA)

    @property
    def execucao_pct(self):
        return self.execucao_total / self.dotacao_total if self.dotacao_total else 0.0


def montar_base_despesa(df_gd: pd.DataFrame, ano_base: int, metrica: str) -> BaseDespesa:
    """Recebe o resultado de db.despesa_por_gd() e consolida por categoria."""
    por_cat = (df_gd.groupby("categoria")["execucao"].sum().to_dict())
    return BaseDespesa(
        ano_base=ano_base, metrica=metrica,
        por_categoria={k: float(v) for k, v in por_cat.items()},
        execucao_total=float(df_gd["execucao"].sum()),
        dotacao_total=float(df_gd["dot_atual"].sum()),
        detalhe_gd=df_gd,
    )


def projetar_despesa(base: BaseDespesa, cen) -> dict:
    """Projeta a despesa por ano a partir da base real.

    Regras de indexação (documentadas, revisáveis):
      pessoal      -> vegetativo 3,44% a.a. (folha)
      custeio      -> IPCA acumulado
      investimento -> IPCA acumulado
      inversões    -> IPCA acumulado
      juros        -> proporcional à Selic do ano vs Selic do ano-base
      amortização  -> IPCA acumulado (+ choque do cenário no serviço)
    Retorna {ano: {categoria: R$ bi, 'servico_divida':..., 'despesa_corrente':...}}.
    """
    veget = C.ELASTICIDADES["irrf"]["fator_vegetativo"]
    selic_base = cen.drivers["selic"].get(C.ANOS[0])  # referência de juros
    out = {}
    ipca_acum = 1.0
    for i, ano in enumerate(C.ANOS):
        ipca_acum *= (1.0 + cen.d("ipca", ano) / 100.0)
        exp = ano - base.ano_base
        selic_ratio = (cen.d("selic", ano) / selic_base) if selic_base else 1.0

        pessoal = base.pessoal * (1.0 + veget) ** exp
        custeio = base.custeio * ipca_acum
        investimento = base.investimento * ipca_acum
        inversoes = base.inversoes * ipca_acum
        juros = base.juros * selic_ratio * (1.0 + cen.d("ipca", ano) / 100.0) ** 0
        amortizacao = base.amortizacao * ipca_acum

        choque = cen.choque_servico_divida.get(ano, 0.0)
        servico = juros + amortizacao + choque
        despesa_corrente = pessoal + juros + custeio + choque * 0.6

        out[ano] = {
            "pessoal": pessoal, "juros": juros, "custeio": custeio,
            "investimento": investimento, "inversoes": inversoes,
            "amortizacao": amortizacao, "choque": choque,
            "servico_divida": servico, "despesa_corrente": despesa_corrente,
        }
    return out
