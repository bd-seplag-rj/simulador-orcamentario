"""Testa a conexão com o banco e mostra um resumo. Rode:
    python scripts/testar_conexao.py
Lê credenciais de .streamlit/secrets.toml [mysql] OU das variáveis SIMULADOR_DB_*.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from engine import db as DB  # noqa: E402

try:
    cfg = DB.get_config()
    print(f"Conectando em {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']} "
          f"(tabela {cfg['table']})…")
    info = DB.testar_conexao()
    print(f"✅ OK — {info['linhas']:,} linhas em `{info['tabela']}`.")
    anos = DB.anos_disponiveis()
    print(f"Anos disponíveis: {anos}")
except Exception as e:  # noqa: BLE001
    print(f"❌ Falhou: {e}")
    sys.exit(1)
