"""
dados_arquivo.py — Fonte de despesa a partir de ARQUIVO exportado do phpMyAdmin.

Alternativa à conexão direta (engine/db.py) para quando só há phpMyAdmin web:
exporta-se a tabela `despesa` (Export → CSV) e o dashboard lê o arquivo e faz
as MESMAS agregações por Grupo de Despesa que o banco faria — alimentando o
mesmo pipeline (engine.despesa.montar_base_despesa) e atualizando os índices.

Aceita CSV (recomendado) e, se `openpyxl` estiver instalado, .xlsx.
Honra engine.config.COLS (nomes de coluna), DB_ESCALA_PARA_BI (escala) e
MAPA_GD_POR_DIGITO (classificação do GND pelo 1º dígito do Cod GD).
"""
from __future__ import annotations
import io
import pandas as pd

from . import config as C
from .db import _categoria_gd  # reaproveita a mesma regra de classificação GND

# Colunas numéricas candidatas (as que existirem no export são coeridas a float)
_NUMERICAS = ["dot_inicial", "dot_atual", "despesa_autorizada",
              "empenhado", "liquidado", "pago"]


def _coerce_num(serie: pd.Series) -> pd.Series:
    """Converte para float aceitando vírgula decimal e separador de milhar."""
    if serie.dtype.kind in "if":
        return serie.astype(float)
    s = (serie.astype(str)
         .str.replace(" ", "", regex=False)   # espaço fino
         .str.replace(" ", "", regex=False)
         .str.replace(".", "", regex=False)          # remove milhar (se houver)
         .str.replace(",", ".", regex=False))        # vírgula decimal -> ponto
    out = pd.to_numeric(s, errors="coerce")
    # Se quase tudo virou NaN, o formato já era ponto-decimal: tenta direto.
    if out.notna().mean() < 0.5:
        out = pd.to_numeric(serie, errors="coerce")
    return out.fillna(0.0)


def ler_export(fonte, nome: str = "") -> pd.DataFrame:
    """Lê o arquivo exportado (caminho, bytes ou file-like do Streamlit).
    Retorna DataFrame cru com as colunas físicas de config.COLS presentes."""
    nome = (nome or getattr(fonte, "name", "") or str(fonte)).lower()

    if nome.endswith((".xlsx", ".xls")):
        try:
            df = pd.read_excel(fonte)
        except ImportError as e:  # openpyxl ausente
            raise RuntimeError(
                "Leitura de Excel requer 'openpyxl' (pip install openpyxl). "
                "Alternativa: exporte como CSV no phpMyAdmin.") from e
    else:
        # CSV — tenta detectar separador e encoding automaticamente
        raw = fonte.read() if hasattr(fonte, "read") else None
        if raw is not None:
            if isinstance(raw, str):
                raw = raw.encode("utf-8")
            buf = lambda: io.BytesIO(raw)  # noqa: E731
        else:
            buf = lambda: fonte  # noqa: E731  (caminho em disco)
        ultimo_erro = None
        df = None
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                df = pd.read_csv(buf(), sep=None, engine="python", encoding=enc)
                break
            except Exception as e:  # noqa: BLE001
                ultimo_erro = e
        if df is None:
            raise RuntimeError(f"Não consegui ler o CSV: {ultimo_erro}")

    return df


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    """Coere colunas numéricas e garante ano/mes inteiros. Não escala aqui."""
    df = df.copy()
    for logico in _NUMERICAS:
        col = C.COLS[logico]
        if col in df.columns:
            df[col] = _coerce_num(df[col])
    for logico in ("ano", "mes"):
        col = C.COLS[logico]
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return df


def validar_colunas(df: pd.DataFrame) -> list[str]:
    """Retorna a lista de colunas ESSENCIAIS ausentes (para avisar o usuário)."""
    essenciais = ["cod_gd", "empenhado", "dot_atual", "ano"]
    faltando = [C.COLS[k] for k in essenciais if C.COLS[k] not in df.columns]
    return faltando


def anos_disponiveis(df: pd.DataFrame) -> list[int]:
    col = C.COLS["ano"]
    if col not in df.columns:
        return []
    vals = pd.to_numeric(df[col], errors="coerce").dropna().astype(int).unique()
    return sorted(vals.tolist(), reverse=True)


def _metrica_fisica(metrica: str) -> str:
    metrica = metrica if metrica in ("Empenhado", "Liquidado", "Pago") else C.DB_METRICA_PADRAO
    return metrica  # nomes físicos == rótulos


def _filtra_ano(df: pd.DataFrame, ano: int) -> pd.DataFrame:
    col = C.COLS["ano"]
    return df[pd.to_numeric(df[col], errors="coerce") == ano]


def agregar_gd(df: pd.DataFrame, ano: int, metrica: str) -> pd.DataFrame:
    """Mesma saída de db.despesa_por_gd (R$ bi): cod_gd, tit_gd, execucao,
    dot_atual, dot_inicial, categoria."""
    d = _filtra_ano(_norm(df), ano)
    m = _metrica_fisica(metrica)   # nome físico da coluna == rótulo (Empenhado/…)
    cod, tit = C.COLS["cod_gd"], C.COLS["tit_gd"]
    g = (d.groupby([cod, tit], dropna=False)
           .agg(execucao=(m, "sum"),
                dot_atual=(C.COLS["dot_atual"], "sum"),
                dot_inicial=(C.COLS["dot_inicial"], "sum"))
           .reset_index()
           .rename(columns={cod: "cod_gd", tit: "tit_gd"}))
    for c in ("execucao", "dot_atual", "dot_inicial"):
        g[c] = g[c].astype(float) * C.DB_ESCALA_PARA_BI
    g["categoria"] = g["cod_gd"].map(_categoria_gd)
    return g


def agregar_funcao(df: pd.DataFrame, ano: int, metrica: str) -> pd.DataFrame:
    d = _filtra_ano(_norm(df), ano)
    m = _metrica_fisica(metrica)
    fu, tf = C.COLS["funcao"], C.COLS["tit_funcao"]
    g = (d.groupby([fu, tf], dropna=False)
           .agg(execucao=(m, "sum"), dot_atual=(C.COLS["dot_atual"], "sum"))
           .reset_index().rename(columns={fu: "funcao", tf: "tit_funcao"}))
    for c in ("execucao", "dot_atual"):
        g[c] = g[c].astype(float) * C.DB_ESCALA_PARA_BI
    return g.sort_values("execucao", ascending=False)


def agregar_uo(df: pd.DataFrame, ano: int, metrica: str, limite: int = 20) -> pd.DataFrame:
    d = _filtra_ano(_norm(df), ano)
    m = _metrica_fisica(metrica)
    uo, tu = C.COLS["cod_uo"], C.COLS["tit_uo"]
    g = (d.groupby([uo, tu], dropna=False)
           .agg(execucao=(m, "sum"), dot_atual=(C.COLS["dot_atual"], "sum"))
           .reset_index().rename(columns={uo: "cod_uo", tu: "tit_uo"}))
    for c in ("execucao", "dot_atual"):
        g[c] = g[c].astype(float) * C.DB_ESCALA_PARA_BI
    return g.sort_values("execucao", ascending=False).head(limite)
