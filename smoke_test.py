"""Smoke test do motor — valida calibração contra as razões do PLDO 2027."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from engine import receita as R
from engine import cenarios as S

anchors = R.calibrar()
print(f"Calibração: RCL base 2027 = R$ {anchors.rcl_base_2027:.1f} bi")
print(f"  pessoal 2026 = {anchors.pessoal_2026:.1f} | DC 2027 = {anchors.dc_2027:.1f} | DCL 2027 = {anchors.dcl_2027:.1f}")

cens = S.cenarios_predefinidos()
res_base = S.avaliar_cenario(cens["base"], anchors)

df = res_base.df_receita
print("\n== Receita por rubrica (R$ bi) ==")
print(df.round(2).to_string())

rcl27 = df.loc["RCL", 2027]
pess27 = res_base.pessoal[2027]
dc27 = res_base.divida[2027]["dc"]
dcl27 = res_base.divida[2027]["dcl"]
print("\n== Checagem das razões-âncora do PLDO 2027 ==")
print(f"  Pessoal/RCL = {pess27/rcl27*100:.2f}%  (esperado 68,57%)")
print(f"  DC/RCL      = {dc27/rcl27*100:.2f}%  (esperado 263%)")
print(f"  DCL/RCL     = {dcl27/rcl27*100:.2f}%  (esperado 277%)")

rpe27 = df.loc["royalties_pe", 2027]
print(f"  R&PE 2027   = R$ {rpe27:.1f} bi  (referência ~30,7)")
icms_petr = (df.loc["icms", 2027] + rpe27) / df.loc["RECEITA_CORRENTE", 2027]
print(f"  (ICMS+petróleo)/Rec.Corrente = {icms_petr*100:.1f}%  (referência ~66,7%)")

print("\n== CAPAG por cenário (2027) ==")
for k, cen in cens.items():
    res = S.avaliar_cenario(cen, anchors)
    c = res.capag[2027]
    p = res.propag[2027]
    print(f"  {k:12s}: CAPAG={c.nota_final} (end {c.endividamento:.2f}/{c.rating_endividamento}, "
          f"pou {c.poupanca:.2f}/{c.rating_poupanca}, liq {c.liquidez:.2f}/{c.rating_liquidez}) | "
          f"Propag={p.indice:.0f}")

print("\n== LRF (base, 2027) ==")
for nome, it in res_base.lrf[2027].itens.items():
    print(f"  {nome:22s}: {it['valor']*100:6.2f}%  limite {it['limite']*100:.0f}%  -> {it['status']}")

print("\n== Alertas ACO 3.678 ==")
res_aco = S.avaliar_cenario(cens["aco_3678"], anchors)
for a in res_aco.alertas:
    print("  -", a)
print("\nOK.")
