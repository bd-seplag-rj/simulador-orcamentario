"""
db.py — Camada de acesso ao banco (MySQL/MariaDB via phpMyAdmin).

Lê a execução de DESPESA da tabela `painel_subor` e agrega para os índices.

Credenciais (NUNCA no código):
  1) Preferencial — .streamlit/secrets.toml, seção [mysql]:
         [mysql]
         host = "..."; port = 3306; database = "..."
         user = "consulta"; password = "..."
  2) Alternativa — variáveis de ambiente:
         SIMULADOR_DB_HOST, SIMULADOR_DB_PORT, SIMULADOR_DB_NAME,
         SIMULADOR_DB_USER, SIMULADOR_DB_PASSWORD

O usuário do banco deve ter apenas SELECT (somente leitura).

Todas as funções de leitura são cacheadas por 10 min no contexto Streamlit.
Fora do Streamlit (scripts/smoke), funcionam normalmente sem cache.
"""
from __future__ import annotations
import os
from urllib.parse import quote_plus
import pandas as pd
from sqlalchemy import create_engine, text

from . import config as C

# cache opcional: só quando rodando dentro do Streamlit
try:
    import streamlit as st
    _cache = st.cache_data(ttl=600, show_spinner=False)

    def _get_secrets():
        """Lê [mysql] do secrets.toml; retorna None se não houver arquivo/seção."""
        try:
            if "mysql" in st.secrets:
                return dict(st.secrets["mysql"])
        except Exception:  # noqa: BLE001  (arquivo de secrets ausente)
            return None
        return None
except Exception:  # noqa: BLE001  (fora do contexto Streamlit)
    def _cache(f):  # no-op
        return f

    def _get_secrets():
        return None


class DBConfigError(RuntimeError):
    pass


def get_config() -> dict:
    """Resolve credenciais de secrets.toml OU de variáveis de ambiente."""
    sec = _get_secrets()
    if sec:
        cfg = {
            "host": sec.get("host", "localhost"),
            "port": int(sec.get("port", 3306)),
            "database": sec.get("database"),
            "user": sec.get("user"),
            "password": sec.get("password", ""),
            "table": sec.get("table", C.DB_TABELA),
        }
    else:
        cfg = {
            "host": os.getenv("SIMULADOR_DB_HOST", "localhost"),
            "port": int(os.getenv("SIMULADOR_DB_PORT", "3306")),
            "database": os.getenv("SIMULADOR_DB_NAME"),
            "user": os.getenv("SIMULADOR_DB_USER"),
            "password": os.getenv("SIMULADOR_DB_PASSWORD", ""),
            "table": os.getenv("SIMULADOR_DB_TABLE", C.DB_TABELA),
        }
    if not cfg["database"] or not cfg["user"]:
        raise DBConfigError(
            "Credenciais ausentes. Preencha .streamlit/secrets.toml [mysql] "
            "ou as variáveis SIMULADOR_DB_*."
        )
    return cfg


_ENGINE = None


def get_engine():
    global _ENGINE
    if _ENGINE is None:
        c = get_config()
        url = (f"mysql+pymysql://{c['user']}:{quote_plus(c['password'])}"
               f"@{c['host']}:{c['port']}/{c['database']}?charset=utf8mb4")
        _ENGINE = create_engine(url, pool_pre_ping=True, pool_recycle=1800)
    return _ENGINE


def testar_conexao() -> dict:
    """Ping simples + contagem de linhas. Levanta exceção se falhar."""
    eng = get_engine()
    tbl = get_config()["table"]
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
        n = conn.execute(text(f"SELECT COUNT(*) FROM `{tbl}`")).scalar()
    return {"ok": True, "linhas": int(n), "tabela": tbl}


def _col(logico: str) -> str:
    """Nome físico da coluna, com crase para uso em SQL."""
    return f"`{C.COLS[logico]}`"


# ---------------------------------------------------------------------------
# Descoberta de domínios (rodar antes de mapear GND/anos)
# ---------------------------------------------------------------------------
@_cache
def listar_colunas() -> pd.DataFrame:
    tbl = get_config()["table"]
    return pd.read_sql(text(f"SHOW COLUMNS FROM `{tbl}`"), get_engine())


@_cache
def dominios() -> dict:
    """Distintos de Grupo de Despesa, anos e funções — para conferir mapeamentos."""
    tbl = get_config()["table"]
    eng = get_engine()
    gd = pd.read_sql(text(
        f"SELECT {_col('cod_gd')} AS cod_gd, {_col('tit_gd')} AS tit_gd, "
        f"COUNT(*) AS n FROM `{tbl}` GROUP BY 1,2 ORDER BY 1"), eng)
    anos = pd.read_sql(text(
        f"SELECT DISTINCT {_col('ano')} AS ano FROM `{tbl}` ORDER BY 1 DESC"), eng)
    func = pd.read_sql(text(
        f"SELECT {_col('funcao')} AS funcao, {_col('tit_funcao')} AS tit_funcao, "
        f"COUNT(*) AS n FROM `{tbl}` GROUP BY 1,2 ORDER BY 3 DESC"), eng)
    return {"grupos_despesa": gd, "anos": anos, "funcoes": func}


@_cache
def anos_disponiveis() -> list[int]:
    tbl = get_config()["table"]
    df = pd.read_sql(text(
        f"SELECT DISTINCT {_col('ano')} AS ano FROM `{tbl}` "
        f"WHERE {_col('ano')} IS NOT NULL ORDER BY 1 DESC"), get_engine())
    return [int(x) for x in df["ano"].tolist()]


# ---------------------------------------------------------------------------
# Agregações de execução (o coração da integração)
# ---------------------------------------------------------------------------
def _metrica_col(metrica: str) -> str:
    metrica = metrica if metrica in ("Empenhado", "Liquidado", "Pago") else C.DB_METRICA_PADRAO
    return f"`{metrica}`"


@_cache
def despesa_por_gd(ano: int, metrica: str = None) -> pd.DataFrame:
    """Soma da execução e da dotação por Grupo de Despesa, para um ano.
    Retorna colunas: cod_gd, tit_gd, execucao, dot_atual, dot_inicial (R$ bi)."""
    metrica = metrica or C.DB_METRICA_PADRAO
    tbl = get_config()["table"]
    m = _metrica_col(metrica)
    sql = text(
        f"SELECT {_col('cod_gd')} AS cod_gd, {_col('tit_gd')} AS tit_gd, "
        f"SUM({m}) AS execucao, SUM({_col('dot_atual')}) AS dot_atual, "
        f"SUM({_col('dot_inicial')}) AS dot_inicial "
        f"FROM `{tbl}` WHERE {_col('ano')} = :ano GROUP BY 1,2")
    df = pd.read_sql(sql, get_engine(), params={"ano": ano})
    for c in ("execucao", "dot_atual", "dot_inicial"):
        df[c] = df[c].astype(float) * C.DB_ESCALA_PARA_BI
    df["categoria"] = df["cod_gd"].map(_categoria_gd)
    return df


@_cache
def despesa_por_funcao(ano: int, metrica: str = None) -> pd.DataFrame:
    metrica = metrica or C.DB_METRICA_PADRAO
    tbl = get_config()["table"]
    m = _metrica_col(metrica)
    sql = text(
        f"SELECT {_col('funcao')} AS funcao, {_col('tit_funcao')} AS tit_funcao, "
        f"SUM({m}) AS execucao, SUM({_col('dot_atual')}) AS dot_atual "
        f"FROM `{tbl}` WHERE {_col('ano')} = :ano GROUP BY 1,2 "
        f"ORDER BY execucao DESC")
    df = pd.read_sql(sql, get_engine(), params={"ano": ano})
    for c in ("execucao", "dot_atual"):
        df[c] = df[c].astype(float) * C.DB_ESCALA_PARA_BI
    return df


@_cache
def despesa_por_uo(ano: int, metrica: str = None, limite: int = 20) -> pd.DataFrame:
    metrica = metrica or C.DB_METRICA_PADRAO
    tbl = get_config()["table"]
    m = _metrica_col(metrica)
    sql = text(
        f"SELECT {_col('cod_uo')} AS cod_uo, {_col('tit_uo')} AS tit_uo, "
        f"SUM({m}) AS execucao, SUM({_col('dot_atual')}) AS dot_atual "
        f"FROM `{tbl}` WHERE {_col('ano')} = :ano GROUP BY 1,2 "
        f"ORDER BY execucao DESC LIMIT :lim")
    df = pd.read_sql(sql, get_engine(), params={"ano": ano, "lim": limite})
    for c in ("execucao", "dot_atual"):
        df[c] = df[c].astype(float) * C.DB_ESCALA_PARA_BI
    return df


def _categoria_gd(cod_gd) -> str:
    """1º dígito do Cod GD -> categoria (padrão GND). 'outros' se não bater."""
    if cod_gd is None:
        return "outros"
    for ch in str(cod_gd):
        if ch.isdigit():
            return C.MAPA_GD_POR_DIGITO.get(ch, "outros")
    return "outros"
