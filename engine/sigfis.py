"""
sigfis.py — Leitura dos exports reais do SIGFIS (.xls) de RECEITA e DESPESA.

Formato: OLE2/BIFF (xlrd), cabeçalho na linha 3, duas linhas de título acima.

REGRAS DE QUALIDADE DESCOBERTAS NOS DADOS (não alterar sem revalidar):

  RECEITA
    * A coluna confiável de realização é **"Receitas Realizadas"** (acumulada).
    * As colunas mensais NÃO são fluxo mensal de arrecadação: contêm
      movimentação financeira bruta. Evidência: ICMS tem "Janeiro" = R$ 116,1 bi
      contra realizada acumulada de R$ 38,2 bi e previsão anual de R$ 52,3 bi;
      os demais meses zeram. Somar os meses infla ~24x (R$ 1.691 bi).
      -> Exposta apenas como diagnóstico, com aviso. [VALIDAR-SEFAZ]
    * Linhas com natureza "-" (COD NR) são movimentação/intra: excluir das
      agregações por rubrica (têm 0 em "Receitas Realizadas").

  DESPESA
    * Só existe o estágio **PAGO**, mês a mês (não há empenhado/liquidado
      -> não é possível medir restos a pagar com este export).
    * As colunas mensais SÃO consistentes (total R$ 62,0 bi em 7 meses,
      46,5% da dotação atualizada de R$ 133,2 bi).
    * O Grupo de Despesa (GND) está na coluna **"Gr Desp"** (1..6, 9=reserva),
      e não em "Cod GD" como na tabela do banco.

Dados de referência: competência 8/2026, acumulado Jan–Jul/2026 (PARCIAL).
"""
from __future__ import annotations
import glob
import os
import re
from dataclasses import dataclass

import pandas as pd

from . import config as C

# Pasta padrão de busca dos arquivos
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_RE_MES = re.compile(r"^([1-9]\d?) - (.+)$")

# Naturezas de petróleo — LISTA EXPLÍCITA (auditável). Um prefixo curto não
# serve: "139999011" pegava só as pré-sal (110/111) e perdia 103/105/106/107/108;
# já "13999901" incluiria 1399990101 (Outras Receitas Patrimoniais), que não é
# petróleo.
NATUREZAS_PETROLEO = [
    "1399990103",  # Royalties até 5%
    "1399990105",  # Royalties excedente a 5%
    "1399990106",  # Participação Especial
    "1399990107",  # Fundo Especial do Petróleo (FEP)
    "1399990108",  # Royalties até 5% — PRÉ-SAL
    "1399990110",  # Royalties excedente a 5% — PRÉ-SAL
    "1399990111",  # Participação Especial — PRÉ-SAL
]

# COD NR (natureza da receita) -> rubrica do motor.
# ATENÇÃO: "11125" NÃO serve para IPVA — captura também o ITD (111252).
# IPVA = 111251 · ITD = 111252.
MAPA_NATUREZA = [
    ("1114501", "icms"),
    ("1114502", "fecp"),
    ("111251", "ipva"),
    ("111252", "itd"),
    ("1113", "irrf"),
    ("17115", "fpe_ipiexp"),   # cobre FPE (1711500) e IPI-Exp (1711530)
    ("17515", "fundeb"),
    ("1215", "rpps"),          # contribuições RPPS (civil/militar)
    ("7215", "rpps"),          # intraorçamentária patronal RPPS
]

# Categoria econômica pelo 1º dígito do COD NR:
#   1 correntes · 2 capital · 7 intraorçamentárias · 9 DEDUÇÕES (negativas)
CATEGORIAS_RECEITA_BRUTA = ("1", "2", "7")
CATEGORIA_DEDUCAO = "9"


def _achar(palavra: str) -> str | None:
    """Encontra o .xls cujo nome contém `palavra` (case-insensitive)."""
    for p in glob.glob(os.path.join(_RAIZ, "*.xls")) + glob.glob(os.path.join(_RAIZ, "*.xlsx")):
        if palavra.lower() in os.path.basename(p).lower():
            return p
    return None


def caminho_despesa() -> str | None:
    return _achar("DESPESA")


def caminho_receita() -> str | None:
    return _achar("Receita")


def planilhas_encontradas() -> list[str]:
    """Todos os .xls/.xlsx na raiz do projeto (para diagnóstico)."""
    achados = (glob.glob(os.path.join(_RAIZ, "*.xls"))
               + glob.glob(os.path.join(_RAIZ, "*.xlsx")))
    return [os.path.basename(p) for p in achados]


def diagnostico() -> dict:
    """Por que a leitura falhou? Separa 'arquivo ausente' de 'não sei ler'.

    Confundir os dois custa tempo: um pede o arquivo na pasta, o outro pede
    `pip install` — e a mensagem errada manda procurar no lugar errado.
    """
    leitores = {}
    for mod, formatos in (("xlrd", ".xls"), ("openpyxl", ".xlsx")):
        try:
            __import__(mod)
            leitores[mod] = f"instalado (lê {formatos})"
        except ImportError:
            leitores[mod] = f"AUSENTE — necessário para {formatos}"
    return {
        "raiz": _RAIZ,
        "planilhas_na_pasta": planilhas_encontradas(),
        "despesa": caminho_despesa(),
        "receita": caminho_receita(),
        "leitores": leitores,
    }


def _cols_mes(df: pd.DataFrame) -> list[str]:
    """Colunas mensais na ordem do mês (ignora '0 - Saldo inicial')."""
    achadas = [(int(m.group(1)), c) for c in df.columns
               if (m := _RE_MES.match(str(c).strip()))]
    return [c for _, c in sorted(achadas)]


def _num(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


# ===========================================================================
# DESPESA
# ===========================================================================
@dataclass
class DespesaSigfis:
    df: pd.DataFrame
    meses: list[str]
    ano: int
    arquivo: str

    @property
    def n_meses(self) -> int:
        return len(self.meses)


def carregar_despesa(caminho: str | None = None) -> DespesaSigfis:
    caminho = caminho or caminho_despesa()
    if not caminho:
        raise FileNotFoundError("Arquivo de DESPESA (.xls) não encontrado na raiz do projeto.")
    df = pd.read_excel(caminho, header=3, engine="xlrd")
    df.columns = [str(c).strip() for c in df.columns]
    # competência costuma estar na 1ª coluna sem nome (ex.: "8 / 2026")
    ano = 0
    prim = df.columns[0]
    for v in df[prim].dropna().astype(str).head(20):
        if m := re.search(r"/\s*(\d{4})", v):
            ano = int(m.group(1))
            break
    df = df[df["Cod UO"].notna()].copy()
    meses = _cols_mes(df)
    df = _num(df, meses + ["Dotação Inicial", "Dotação Atualizada"])
    df["Cod UO"] = df["Cod UO"].astype(str).str.strip()
    df["Pago"] = df[meses].sum(axis=1)
    df["categoria"] = df["Gr Desp"].map(_categoria_grdesp)
    return DespesaSigfis(df=df, meses=meses, ano=ano or C.ANO_BASE, arquivo=os.path.basename(caminho))


def _categoria_grdesp(gr) -> str:
    """'Gr Desp' (1..6, 9) -> categoria do motor. 9 = reserva -> 'outros'."""
    try:
        d = str(int(float(gr)))
    except (TypeError, ValueError):
        return "outros"
    return C.MAPA_GD_POR_DIGITO.get(d, "outros")


def despesa_por_gd(ds: DespesaSigfis, anualizar: bool = False) -> pd.DataFrame:
    """Formato compatível com engine.despesa.montar_base_despesa (R$ bi).

    `anualizar=True` projeta a execução parcial para o ano cheio por run-rate
    (× 12/n_meses). Necessário quando a base alimenta índices que a comparam
    com receita ANUAL (Pessoal/RCL, poupança do CAPAG etc.) — sem isso, 7 meses
    de despesa contra 12 de receita subestimam grosseiramente os indicadores.
    A dotação já é anual e nunca é escalada.
    """
    g = (ds.df.groupby("Gr Desp", dropna=False)
         .agg(execucao=("Pago", "sum"),
              dot_atual=("Dotação Atualizada", "sum"),
              dot_inicial=("Dotação Inicial", "sum"))
         .reset_index().rename(columns={"Gr Desp": "cod_gd"}))
    g["cod_gd"] = g["cod_gd"].map(lambda x: str(int(float(x))) if pd.notna(x) else "?")
    g["categoria"] = g["cod_gd"].map(lambda d: C.MAPA_GD_POR_DIGITO.get(d, "outros"))
    g["tit_gd"] = g["categoria"].str.capitalize()
    fator = (12.0 / ds.n_meses) if (anualizar and ds.n_meses) else 1.0
    g["execucao"] = g["execucao"] * C.DB_ESCALA_PARA_BI * fator
    for c in ("dot_atual", "dot_inicial"):
        g[c] = g[c] * C.DB_ESCALA_PARA_BI
    return g


def despesa_por_uo(ds: DespesaSigfis) -> pd.DataFrame:
    g = (ds.df.groupby(["Cod UO", "Sigla UO"], dropna=False)
         .agg(execucao=("Pago", "sum"),
              dot_atual=("Dotação Atualizada", "sum"),
              dot_inicial=("Dotação Inicial", "sum"))
         .reset_index().rename(columns={"Cod UO": "cod_uo", "Sigla UO": "tit_uo"}))
    for c in ("execucao", "dot_atual", "dot_inicial"):
        g[c] = g[c] * C.DB_ESCALA_PARA_BI
    g["execucao_pct"] = (g["execucao"] / g["dot_atual"].replace(0, pd.NA)) * 100
    return g.sort_values("execucao", ascending=False)


def despesa_por_funcao(ds: DespesaSigfis) -> pd.DataFrame:
    g = (ds.df.groupby("Função", dropna=False)
         .agg(execucao=("Pago", "sum"), dot_atual=("Dotação Atualizada", "sum"))
         .reset_index().rename(columns={"Função": "funcao"}))
    for c in ("execucao", "dot_atual"):
        g[c] = g[c] * C.DB_ESCALA_PARA_BI
    g["funcao"] = g["funcao"].map(lambda x: FUNCOES.get(_i(x), f"Função {_i(x)}"))
    return g.sort_values("execucao", ascending=False)


def serie_mensal_uo(ds: DespesaSigfis, cod_uo: str | None = None) -> pd.Series:
    """Pago mês a mês (R$ bi). cod_uo=None => total do Estado."""
    d = ds.df if cod_uo is None else ds.df[ds.df["Cod UO"] == str(cod_uo)]
    s = d[ds.meses].sum() * C.DB_ESCALA_PARA_BI
    s.index = [_RE_MES.match(c).group(2) for c in ds.meses]
    return s


def serie_mensal_uo_por_gnd(ds: DespesaSigfis, cod_uo: str | None = None) -> pd.DataFrame:
    d = ds.df if cod_uo is None else ds.df[ds.df["Cod UO"] == str(cod_uo)]
    g = d.groupby("categoria")[ds.meses].sum() * C.DB_ESCALA_PARA_BI
    g.columns = [_RE_MES.match(c).group(2) for c in ds.meses]
    return g


def detalhe_uo(ds: DespesaSigfis, cod_uo: str) -> dict:
    d = ds.df[ds.df["Cod UO"] == str(cod_uo)]
    esc = C.DB_ESCALA_PARA_BI
    pago = d["Pago"].sum() * esc
    dot = d["Dotação Atualizada"].sum() * esc
    return {
        "sigla": d["Sigla UO"].iloc[0] if len(d) else "",
        "pago": pago,
        "dot_inicial": d["Dotação Inicial"].sum() * esc,
        "dot_atual": dot,
        "execucao_pct": (pago / dot * 100) if dot else 0.0,
        "por_categoria": (d.groupby("categoria")["Pago"].sum() * esc).to_dict(),
        "linhas": len(d),
        "n_acoes": d["Cod Ação"].nunique(),
    }


# Funções orçamentárias (padrão federal) para rótulo legível
FUNCOES = {
    1: "Legislativa", 2: "Judiciária", 3: "Essencial à Justiça", 4: "Administração",
    5: "Defesa Nacional", 6: "Segurança Pública", 7: "Relações Exteriores",
    8: "Assistência Social", 9: "Previdência Social", 10: "Saúde", 11: "Trabalho",
    12: "Educação", 13: "Cultura", 14: "Direitos da Cidadania", 15: "Urbanismo",
    16: "Habitação", 17: "Saneamento", 18: "Gestão Ambiental", 19: "Ciência e Tecnologia",
    20: "Agricultura", 21: "Organização Agrária", 22: "Indústria", 23: "Comércio e Serviços",
    24: "Comunicações", 25: "Energia", 26: "Transporte", 27: "Desporto e Lazer",
    28: "Encargos Especiais", 99: "Reserva de Contingência",
}


def _i(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return -1


# ===========================================================================
# RECEITA
# ===========================================================================
@dataclass
class ReceitaSigfis:
    df: pd.DataFrame          # todas as linhas (inclui movimentação "-")
    classificada: pd.DataFrame  # apenas naturezas classificadas
    meses: list[str]
    arquivo: str


def carregar_receita(caminho: str | None = None) -> ReceitaSigfis:
    caminho = caminho or caminho_receita()
    if not caminho:
        raise FileNotFoundError("Arquivo de RECEITA (.xls) não encontrado na raiz do projeto.")
    df = pd.read_excel(caminho, header=3, engine="xlrd")
    df.columns = [str(c).strip() for c in df.columns]
    df = df[df["Cod. UG"].notna()].copy()
    meses = _cols_mes(df)
    df = _num(df, meses + ["Previsão Inicial", "Receitas Realizadas"])
    df["Cod. UG"] = df["Cod. UG"].astype(str).str.strip()
    df["COD NR"] = df["COD NR"].astype(str).str.strip()
    df["rubrica"] = df["COD NR"].map(_rubrica_natureza)
    cls = df[df["COD NR"] != "-"].copy()
    return ReceitaSigfis(df=df, classificada=cls, meses=meses,
                         arquivo=os.path.basename(caminho))


def _rubrica_natureza(cod: str) -> str:
    c = str(cod).strip()
    if c == "-":
        return "movimentacao"
    if c in NATUREZAS_PETROLEO:
        return "royalties_pe"
    for pref, rub in MAPA_NATUREZA:
        if c.startswith(pref):
            return rub
    return "outras_correntes"


def categoria_economica(cod: str) -> str:
    """1º dígito do COD NR: 1/2/7 = receita; 9 = dedução (valor negativo)."""
    c = str(cod).strip()
    return c[0] if c and c[0].isdigit() else "?"


def baseline_por_rubrica(rs: "ReceitaSigfis", usar: str = "Previsão Inicial") -> dict:
    """Receita BRUTA por rubrica (R$ bi), excluindo as deduções (categoria 9).

    As deduções (cota-parte de municípios, FUNDEB) são tratadas à parte pelo
    fator de dedução da RCL — misturá-las nas rubricas causaria DUPLA CONTAGEM,
    porque o motor já aplica FATOR_DEDUCAO_RCL sobre a receita bruta.
    """
    d = rs.classificada.copy()
    d["cat"] = d["COD NR"].map(categoria_economica)
    bruto = d[d["cat"].isin(CATEGORIAS_RECEITA_BRUTA)]
    g = bruto.groupby("rubrica")[usar].sum() * C.DB_ESCALA_PARA_BI
    return {k: float(v) for k, v in g.items()}


def fator_deducao_rcl(rs: "ReceitaSigfis", usar: str = "Previsão Inicial") -> dict:
    """Deduções ÷ receitas correntes brutas (cat 1 + 7), medido no dado real."""
    d = rs.classificada.copy()
    d["cat"] = d["COD NR"].map(categoria_economica)
    esc = C.DB_ESCALA_PARA_BI
    correntes = d[d["cat"].isin(("1", "7"))][usar].sum() * esc
    deducoes = abs(d[d["cat"] == CATEGORIA_DEDUCAO][usar].sum() * esc)
    return {"correntes_brutas": correntes, "deducoes": deducoes,
            "fator": (deducoes / correntes) if correntes else 0.0,
            "rcl_implicita": correntes - deducoes}


def receita_por_ug(rs: ReceitaSigfis) -> pd.DataFrame:
    """Previsão x Realizada por Unidade Gestora (R$ bi). Só naturezas classificadas."""
    esc = C.DB_ESCALA_PARA_BI
    g = (rs.classificada.groupby(["Cod. UG", "Unidade Gestora"], dropna=False)
         .agg(previsao=("Previsão Inicial", "sum"),
              realizada=("Receitas Realizadas", "sum"))
         .reset_index().rename(columns={"Cod. UG": "cod_ug", "Unidade Gestora": "nome_ug"}))
    g["previsao"] *= esc
    g["realizada"] *= esc
    g["realiz_pct"] = (g["realizada"] / g["previsao"].replace(0, pd.NA)) * 100
    return g.sort_values("realizada", ascending=False)


def receita_por_rubrica(rs: ReceitaSigfis, cod_ug: str | None = None) -> pd.DataFrame:
    esc = C.DB_ESCALA_PARA_BI
    d = rs.classificada
    if cod_ug:
        d = d[d["Cod. UG"] == str(cod_ug)]
    g = (d.groupby("rubrica", dropna=False)
         .agg(previsao=("Previsão Inicial", "sum"), realizada=("Receitas Realizadas", "sum"))
         .reset_index())
    g["previsao"] *= esc
    g["realizada"] *= esc
    g["realiz_pct"] = (g["realizada"] / g["previsao"].replace(0, pd.NA)) * 100
    rot = {r: C.RUBRICAS[r]["label"] for r in C.RUBRICAS}
    rot["fundeb"] = "FUNDEB"
    g["label"] = g["rubrica"].map(lambda r: rot.get(r, r))
    return g.sort_values("realizada", ascending=False)


def receita_detalhe_ug(rs: ReceitaSigfis, cod_ug: str) -> pd.DataFrame:
    """Naturezas de uma UG: previsão, realizada e %."""
    esc = C.DB_ESCALA_PARA_BI
    d = rs.classificada[rs.classificada["Cod. UG"] == str(cod_ug)]
    g = (d.groupby(["COD NR", "TIT NR"], dropna=False)
         .agg(previsao=("Previsão Inicial", "sum"), realizada=("Receitas Realizadas", "sum"))
         .reset_index())
    g["previsao"] *= esc
    g["realizada"] *= esc
    g["realiz_pct"] = (g["realizada"] / g["previsao"].replace(0, pd.NA)) * 100
    return g.sort_values("realizada", ascending=False)


def receita_serie_mensal(rs: ReceitaSigfis, cod_ug: str | None = None) -> pd.Series:
    """SÉRIE MENSAL BRUTA — movimentação financeira, NÃO realização orçamentária.
    Exposta só como diagnóstico, sempre com aviso. [VALIDAR-SEFAZ]"""
    d = rs.classificada
    if cod_ug:
        d = d[d["Cod. UG"] == str(cod_ug)]
    s = d[rs.meses].sum() * C.DB_ESCALA_PARA_BI
    s.index = [_RE_MES.match(c).group(2) for c in rs.meses]
    return s


def diagnostico_receita(rs: ReceitaSigfis, cod_ug: str | None = None) -> dict:
    """Quantifica a divergência entre soma mensal e a coluna acumulada."""
    esc = C.DB_ESCALA_PARA_BI
    d = rs.classificada
    if cod_ug:
        d = d[d["Cod. UG"] == str(cod_ug)]
    mensal = d[rs.meses].sum().sum() * esc
    acum = d["Receitas Realizadas"].sum() * esc
    mov = rs.df[rs.df["COD NR"] == "-"]
    if cod_ug:
        mov = mov[mov["Cod. UG"] == str(cod_ug)]
    return {
        "soma_mensal": mensal,
        "acumulada": acum,
        "razao": (mensal / acum) if acum else float("nan"),
        "movimentacao_excluida": mov[rs.meses].sum().sum() * esc,
        "confiavel": "Receitas Realizadas (acumulada)",
    }
