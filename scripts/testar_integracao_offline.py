"""Valida a lógica de integração SEM um banco vivo:
  1) sem credenciais -> erro amigável;
  2) despesa real (df sintético no formato de db.despesa_por_gd) -> índices atualizados.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
from engine import db as DB, despesa as D, receita as R, cenarios as S

# 1) Sem credenciais
os.environ.pop("SIMULADOR_DB_NAME", None)
os.environ.pop("SIMULADOR_DB_USER", None)
try:
    DB.get_config()
    print("1) ❌ deveria ter falhado sem credenciais")
except DB.DBConfigError as e:
    print(f"1) ✅ erro amigável sem credenciais: {e}")

# 2) df sintético como o db.despesa_por_gd() retornaria (já em R$ bi)
df_gd = pd.DataFrame({
    "cod_gd": ["1", "2", "3", "4", "5", "6"],
    "tit_gd": ["Pessoal e Encargos", "Juros e Encargos", "Outras Desp. Correntes",
               "Investimentos", "Inversões Financeiras", "Amortização"],
    "execucao": [63.0, 6.0, 40.0, 4.0, 1.0, 9.0],
    "dot_atual": [65.0, 6.5, 44.0, 7.0, 1.5, 9.5],
    "dot_inicial": [64.0, 6.0, 43.0, 8.0, 1.5, 9.0],
})
df_gd["categoria"] = df_gd["cod_gd"].map(DB._categoria_gd)
print("\n2) Categorias mapeadas:")
print(df_gd[["cod_gd", "categoria", "execucao"]].to_string(index=False))

base = D.montar_base_despesa(df_gd, ano_base=2026, metrica="Empenhado")
print(f"\n   pessoal={base.pessoal:.1f} juros={base.juros:.1f} custeio={base.custeio:.1f} "
      f"invest={base.investimento:.1f} amort={base.amortizacao:.1f}")
print(f"   desp. corrente={base.despesa_corrente:.1f} | serviço dívida={base.servico_divida:.1f} "
      f"| execução={base.execucao_pct*100:.1f}%")

anchors = R.calibrar()
cen = S.cenarios_predefinidos()["base"]

res_proto = S.avaliar_cenario(cen, anchors, base_despesa=None)
res_real = S.avaliar_cenario(cen, anchors, base_despesa=base)

print("\n3) Índices 2027 — protótipo vs execução real:")
for nome, r in [("protótipo", res_proto), ("real    ", res_real)]:
    c = r.capag[2027]
    l = r.lrf[2027].itens
    print(f"   [{nome}] fonte_despesa={r.fonte_despesa:24s} "
          f"Pessoal/RCL={l['Pessoal / RCL']['valor']*100:.1f}% "
          f"poupança={c.poupanca:.2f}/{c.rating_poupanca} "
          f"serviço={r.servico_divida[2027]:.1f} Propag={r.propag[2027].indice:.0f}")

print("\n✅ Integração validada offline.")
