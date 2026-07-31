"""Lista colunas e domínios da tabela painel_subor para conferir o mapeamento.
Rode:
    python scripts/descobrir_dominios.py

Use a saída para validar:
  - se os nomes de coluna em engine/config.py::COLS batem com os reais;
  - se o "Cod GD" segue a codificação GND 1..6 (MAPA_GD_POR_DIGITO);
  - quais anos existem para escolher o ano-base.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from engine import db as DB  # noqa: E402

print("== Colunas da tabela ==")
try:
    print(DB.listar_colunas().to_string(index=False))
except Exception as e:  # noqa: BLE001
    print(f"(erro ao listar colunas: {e})")

print("\n== Grupos de Despesa (Cod GD / Tit GD) ==")
dom = DB.dominios()
gd = dom["grupos_despesa"].copy()
gd["categoria_mapeada"] = gd["cod_gd"].map(DB._categoria_gd)
print(gd.to_string(index=False))

print("\n== Anos disponíveis ==")
print(dom["anos"].to_string(index=False))

print("\n== Funções (top 15 por nº de linhas) ==")
print(dom["funcoes"].head(15).to_string(index=False))

print("\nConfira se 'categoria_mapeada' está correta para cada GND. "
      "Se não, ajuste MAPA_GD_POR_DIGITO em engine/config.py.")
