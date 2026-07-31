"""
auditoria_indices.py — Confere os índices contra os dados reais de receita e
despesa (planilhas SIGFIS). Reexecutável: rode sempre que trocar as planilhas.

    python scripts/auditoria_indices.py

Verifica, passo a passo e com números explícitos:
  1. Receita  — baseline por rubrica × planilha; fator de dedução da RCL;
                fechamento (bruto − deduções = total da planilha).
  2. Despesa  — soma por GND × total pago; anualização; correntes × capital.
  3. Índices  — recalcula CAPAG, LRF e Propag "na mão" e compara com o motor.
Cada checagem imprime OK ou DIVERGE com a magnitude.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from engine import config as C, sigfis as SG, despesa as D, receita as R, cenarios as S  # noqa: E402

TOL = 0.01          # 1% de tolerância relativa
falhas = []


def chk(nome, obtido, esperado, tol=TOL, unidade=""):
    if esperado == 0:
        ok = abs(obtido) < 1e-9
        rel = 0.0
    else:
        rel = abs(obtido - esperado) / abs(esperado)
        ok = rel <= tol
    status = "OK      " if ok else "DIVERGE "
    print(f"  [{status}] {nome}: {obtido:,.3f}{unidade} vs {esperado:,.3f}{unidade}"
          + ("" if ok else f"  (dif {rel*100:.1f}%)"))
    if not ok:
        falhas.append(nome)
    return ok


print("=" * 78)
print("AUDITORIA DE ÍNDICES — dados reais SIGFIS")
print("=" * 78)

rs = SG.carregar_receita()
ds = SG.carregar_despesa()
print(f"Receita: {rs.arquivo}")
print(f"Despesa: {ds.arquivo}  ({ds.n_meses}/12 meses, ano {ds.ano})")

# ---------------------------------------------------------------- 1) RECEITA
print("\n1) RECEITA — baseline × planilha")
base_real = SG.baseline_por_rubrica(rs, "Previsão Inicial")
for rub, val in sorted(base_real.items(), key=lambda x: -x[1]):
    if rub in C.BASELINE_2026:
        chk(f"baseline {rub}", C.BASELINE_2026[rub], val, unidade=" bi")
    else:
        print(f"  [INFO    ] {rub} = {val:,.3f} bi (fora do BASELINE_2026)")

# nenhuma rubrica real pode ficar de fora do BASELINE_2026 (senão some da projeção)
faltantes = [r for r in base_real if r not in C.BASELINE_2026]
if faltantes:
    falhas.append("rubricas ausentes no BASELINE_2026")
    print(f"  [DIVERGE ] rubricas fora do BASELINE_2026: {faltantes}")
else:
    print("  [OK      ] todas as rubricas reais estão no BASELINE_2026")
soma_base = sum(C.BASELINE_2026[r] for r in base_real if r in C.BASELINE_2026)
chk("baseline total = receita bruta da planilha", soma_base, sum(base_real.values()),
    unidade=" bi")

fd = SG.fator_deducao_rcl(rs, "Previsão Inicial")
chk("FATOR_DEDUCAO_RCL", C.FATOR_DEDUCAO_RCL, fd["fator"], tol=0.02)
print(f"           correntes brutas {fd['correntes_brutas']:.2f} − deduções "
      f"{fd['deducoes']:.2f} = RCL implícita {fd['rcl_implicita']:.2f} bi")

# fechamento: bruto − deduções deve reproduzir o total da planilha
esc = C.DB_ESCALA_PARA_BI
total_planilha = rs.classificada["Previsão Inicial"].sum() * esc
bruto = sum(base_real.values())
chk("fechamento receita (bruto − deduções)", bruto - fd["deducoes"], total_planilha,
    unidade=" bi")

# ---------------------------------------------------------------- 2) DESPESA
print("\n2) DESPESA — GND × total pago")
gd = SG.despesa_por_gd(ds, anualizar=False)
pago_total = ds.df["Pago"].sum() * esc
chk("soma por GND = total pago", gd["execucao"].sum(), pago_total, unidade=" bi")

bd = D.montar_base_despesa(gd, ano_base=ds.ano, metrica="Pago")
chk("correntes + capital = total", bd.despesa_corrente + bd.despesa_capital
    + bd.por_categoria.get("outros", 0.0), pago_total, unidade=" bi")
chk("serviço da dívida = juros + amortização", bd.servico_divida,
    bd.juros + bd.amortizacao, unidade=" bi")

fator = 12.0 / ds.n_meses
gd_a = SG.despesa_por_gd(ds, anualizar=True)
chk("anualização (× 12/n_meses)", gd_a["execucao"].sum(), pago_total * fator,
    unidade=" bi")
chk("dotação NÃO anualizada", gd_a["dot_atual"].sum(), gd["dot_atual"].sum(),
    unidade=" bi")

# ---------------------------------------------------------------- 3) ÍNDICES
print("\n3) ÍNDICES — motor × cálculo manual")
anchors = R.calibrar()
cen = S.cenarios_predefinidos()["base"]
base_a = D.montar_base_despesa(gd_a, ano_base=ds.ano, metrica="Pago")
res = S.avaliar_cenario(cen, anchors, base_despesa=base_a, sigfis_despesa=ds)

ANO = C.ANOS[0]
rcl = float(res.df_receita.loc["RCL", ANO])
rec_corr = float(res.df_receita.loc["RECEITA_CORRENTE", ANO])
chk("RCL = receita corrente × (1 − exclusões LRF)", rcl,
    rec_corr * (1 - R.fatores_rcl()), unidade=" bi")
chk("RCL = corrente − municípios − contrib.serv − intra", rcl,
    rec_corr - float(res.df_receita.loc["RCL_DED_MUNICIPIOS", ANO])
    - float(res.df_receita.loc["RCL_DED_CONTRIB_SERV", ANO])
    - float(res.df_receita.loc["RCL_DED_INTRA", ANO]), unidade=" bi")

dsp = res.despesa[ANO]
pess, cust, juros = dsp["pessoal"], dsp["custeio"], dsp["juros"]

# LRF — Pessoal/RCL
lrf = res.lrf[ANO].itens
chk("Pessoal/RCL", lrf["Pessoal / RCL"]["valor"], pess / rcl)
# CAPAG — endividamento e poupança
cap = res.capag[ANO]
dc = res.divida[ANO]["dc"]
chk("CAPAG endividamento = DC/RCL", cap.endividamento, dc / rcl)
chk("CAPAG poupança = desp.corrente/rec.corrente", cap.poupanca,
    dsp["despesa_corrente"] / rec_corr)
chk("desp. corrente = pessoal + custeio + juros", dsp["despesa_corrente"],
    pess + cust + juros + dsp["choque"] * 0.6, unidade=" bi")
# Propag — saldo primário
prop = res.propag[ANO]
chk("Propag: aporte FEF = contrapartida × RCL", prop.contrapartidas["aporte_fef"],
    prop.contrapartidas["fef_%"] * rcl, unidade=" bi")
soma_pesos = sum(s["peso"] for s in prop.subindicadores.values())
chk("Propag: pesos somam 1,00", soma_pesos, 1.0)
idx = sum(s["score"] * s["peso"] for s in prop.subindicadores.values())
chk("Propag: índice = Σ(score × peso)", prop.indice, idx)

# ---- DTP (LRF arts. 18-20) ----
print("\n3b) DTP — Despesa Total com Pessoal")
t = res.dtp
gnd1 = ds.df[ds.df["Gr Desp"] == 1]["Pago"].sum() * esc * fator
chk("DTP bruta = GND 1 anualizado", t.dtp_bruta, gnd1, unidade=" bi")
chk("DTP líquida = bruta − deduções", t.dtp_liquida,
    t.dtp_bruta - sum(t.deducoes.values()), unidade=" bi")
chk("componentes = DTP bruta", sum(t.componentes.values()), t.dtp_bruta, unidade=" bi")
chk("DTP/RCL", t.razao, t.dtp_liquida / t.rcl)
chk("soma dos Poderes = DTP/RCL", t.por_poder["% da RCL"].sum() / 100, t.razao)
chk("sublimites somam 60%", sum(C.LRF_SUBLIMITES.values()),
    C.LRF["pessoal_rcl_teto"])
# reconciliação com o PLDO
pldo = C.ANCORAS_PLDO_2027["pessoal_sobre_rcl"] * 100
dif = abs(t.razao * 100 - pldo)
print(f"  [{'OK      ' if dif <= 3 else 'ATENÇÃO '}] reconciliação com PLDO: "
      f"{t.razao*100:.2f}% vs {pldo:.2f}% (dif {dif:.2f} p.p.)")
if dif > 3:
    falhas.append("DTP diverge do PLDO em mais de 3 p.p.")

# Coerência de universo: despesa anualizada vs receita anual
print("\n4) COERÊNCIA DE UNIVERSO (o erro mais perigoso)")
print(f"  receita corrente {ANO}: {rec_corr:.2f} bi (ANUAL, projetada)")
print(f"  despesa pessoal  {ANO}: {pess:.2f} bi (real anualizada × {fator:.2f})")
razao = pess / rcl * 100
print(f"  -> Pessoal/RCL = {razao:.1f}%")
if not (40 <= razao <= 90):
    falhas.append("Pessoal/RCL fora da faixa plausível")
    print("  [DIVERGE ] fora da faixa plausível (40–90%)")
else:
    print("  [OK      ] dentro da faixa plausível")
print(f"  referência PLDO 2027: {C.ANCORAS_PLDO_2027['pessoal_sobre_rcl']*100:.2f}% "
      f"(DTP da LRF — base metodológica diferente, ver DIVERGENCIAS_CONHECIDAS)")

print("\n" + "=" * 78)
if falhas:
    print(f"RESULTADO: {len(falhas)} divergência(s): " + "; ".join(falhas))
    sys.exit(1)
print("RESULTADO: todas as checagens passaram.")
