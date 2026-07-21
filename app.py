"""
app.py — Painel de Simulação Orçamentária (ERJ / PLDO 2027).

Streamlit. Consome o motor em engine/. Estrutura de abas:
  Visão geral · Receita · CAPAG · Propag · LRF & Vinculações · Fontes & Governança

Princípios do passo 0 refletidos na UI:
  - todo driver mostra âncora, fonte e SLA de frescor;
  - cenários lado a lado; adverso ACO 3.678 pré-carregado;
  - CAPAG exibido como SIMULADO, com aviso de reconciliação contra a STN;
  - componentes sempre visíveis (nunca só o agregado);
  - separação recorrente × não recorrente.
"""
from __future__ import annotations
import copy
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import config as C
from engine import receita as R
from engine import cenarios as S
from engine import indicadores as I

st.set_page_config(page_title="Simulador Orçamentário — ERJ / PLDO 2027",
                   page_icon="📊", layout="wide")

CORES = {"A": "#1a9850", "B": "#91cf60", "C": "#fc8d59", "D": "#d73027",
         "OK": "#1a9850", "ALERTA": "#fee08b", "PRUDENCIAL": "#fc8d59",
         "ESTOURADO": "#d73027", "ABAIXO": "#d73027"}


@st.cache_data
def _anchors():
    return R.calibrar()


anchors = _anchors()
presets = S.cenarios_predefinidos()


# ---------------------------------------------------------------------------
# Sidebar — seleção de cenário e sliders de drivers
# ---------------------------------------------------------------------------
st.sidebar.title("⚙️ Cenário e drivers")

preset_labels = {
    "base": "Base (PLDO 2027)",
    "otimista": "Otimista",
    "pessimista": "Pessimista",
    "aco_3678": "⚠️ Adverso — ACO nº 3.678",
}
preset_key = st.sidebar.radio(
    "Cenário-semente", list(preset_labels), format_func=lambda k: preset_labels[k],
    help="Escolhe os valores iniciais dos sliders. Ajuste abaixo para simular.",
)
preset = presets[preset_key]

if "last_preset" not in st.session_state or st.session_state.last_preset != preset_key:
    st.session_state.last_preset = preset_key
    for drv in C.DRIVERS_MACRO:
        for ano in C.ANOS:
            st.session_state[f"{drv}_{ano}"] = preset.drivers[drv][ano]

ano_foco = st.sidebar.selectbox("Ano em foco", C.ANOS, index=0)

st.sidebar.markdown("### Drivers macro")
st.sidebar.caption(f"Âncoras: {C.METADADOS['fonte_macro']}")

drivers_custom = {drv: {} for drv in C.DRIVERS_MACRO}
for drv, meta in C.DRIVERS_MACRO.items():
    with st.sidebar.expander(f"{meta['label']}", expanded=(drv in ("pib_real", "brent", "selic"))):
        st.caption(f"📌 fonte: {meta['fonte']} · 🕒 SLA: {meta['sla_frescor']}")
        if meta.get("alerta"):
            st.warning(meta["alerta"], icon="⚠️")
        for ano in C.ANOS:
            lo, hi = meta["faixa_slider"]
            # valor corrente vem do session_state (pré-populado ao trocar de preset)
            drivers_custom[drv][ano] = st.slider(
                f"{ano}", float(lo), float(hi),
                step=float(meta["passo"]), key=f"{drv}_{ano}",
                help=f"Âncora PLDO {ano}: {meta['ancora'][ano]}",
            )

st.sidebar.markdown("### Contexto Propag")
fndr = st.sidebar.select_slider(
    "Status do ativo FNDR ofertado", options=["rejeitado", "parcial", "aceito"],
    value=preset.fndr_status,
    help="Único ativo ofertado à União, ainda não analisado. Rejeição eleva contrapartidas a 2%/2%.",
)
propag_ativo = st.sidebar.checkbox("Contrato Propag formalizado", value=preset.propag_ativo,
                                   help="Se desmarcado, indexação da dívida usa proxy IGP-M (mais cara).")
inv_exec = st.sidebar.slider("Execução do investimento obrigatório (%)", 0, 100,
                             int(preset.investimento_executado_frac * 100),
                             help="Risco de execução (empenho/liquidação), não de arrecadação.") / 100.0
choque_aco = st.sidebar.number_input(
    "Choque no serviço da dívida 2027 (R$ bi)", 0.0, 50.0,
    float(preset.choque_servico_divida.get(2027, 0.0)), step=0.5,
    help="Cenário ACO 3.678: +R$ 11,7 bi.",
)

# Monta cenário ativo a partir dos controles
cen_ativo = R.Cenario(
    nome=f"Ativo ({preset_labels[preset_key]})",
    drivers=copy.deepcopy(drivers_custom),
    choque_servico_divida={2027: choque_aco} if choque_aco > 0 else {},
    propag_ativo=propag_ativo, fndr_status=fndr,
    investimento_executado_frac=inv_exec,
    descricao=preset.descricao,
)

res = S.avaliar_cenario(cen_ativo, anchors)
res_presets = {k: S.avaliar_cenario(v, anchors) for k, v in presets.items()}


# ---------------------------------------------------------------------------
# Cabeçalho + avisos de governança
# ---------------------------------------------------------------------------
st.title("📊 Simulador Orçamentário — Estado do Rio de Janeiro")
st.caption(f"Base: {C.METADADOS['documento']} · unidade {C.UNIDADE}")

c1, c2 = st.columns(2)
c1.info(f"ℹ️ {C.METADADOS['capag_no_pldo']} O CAPAG abaixo é **simulado** e deve ser "
        "reconciliado contra a nota oficial da STN.", icon="ℹ️")
c2.warning(f"⚠️ {C.METADADOS['aviso_vigencia']}", icon="⚠️")

if res.alertas:
    for a in res.alertas:
        st.error(a, icon="🚨")


def kpi_card(col, titulo, valor, sub, cor=None):
    col.metric(titulo, valor, sub)
    if cor:
        col.markdown(f"<div style='height:4px;background:{cor};border-radius:2px'></div>",
                     unsafe_allow_html=True)


tabs = st.tabs(["Visão geral", "Receita", "CAPAG", "Propag",
                "LRF & Vinculações", "Fontes & Governança"])

# ===========================================================================
# 1) VISÃO GERAL
# ===========================================================================
with tabs[0]:
    st.subheader(f"Panorama — {ano_foco}")
    capag = res.capag[ano_foco]
    propag = res.propag[ano_foco]
    lrf = res.lrf[ano_foco]
    df = res.df_receita

    k = st.columns(5)
    kpi_card(k[0], "CAPAG (simulado)", capag.nota_final,
             f"endiv. {capag.endividamento:.2f}× RCL", CORES[capag.nota_final])
    kpi_card(k[1], "Índice Propag", f"{propag.indice:.0f}/100",
             f"FNDR: {cen_ativo.fndr_status}")
    pess = lrf.itens["Pessoal / RCL"]
    kpi_card(k[2], "Pessoal / RCL", f"{pess['valor']*100:.1f}%",
             f"teto {pess['limite']*100:.0f}% · {pess['status']}", CORES[pess["status"]])
    dclr = lrf.itens["DCL / RCL"]
    kpi_card(k[3], "DCL / RCL", f"{dclr['valor']*100:.0f}%",
             f"teto {dclr['limite']*100:.0f}% · {dclr['status']}", CORES[dclr["status"]])
    kpi_card(k[4], "Receita corrente", f"R$ {df.loc['RECEITA_CORRENTE', ano_foco]:.1f} bi",
             f"RCL R$ {df.loc['RCL', ano_foco]:.1f} bi")

    st.markdown("#### Cenários lado a lado")
    linhas = []
    for key, r in res_presets.items():
        c = r.capag[ano_foco]
        p = r.propag[ano_foco]
        l = r.lrf[ano_foco]
        linhas.append({
            "Cenário": preset_labels[key],
            "CAPAG": c.nota_final,
            "Endiv. (DC/RCL)": f"{c.endividamento:.2f}",
            "Propag": f"{p.indice:.0f}",
            "Pessoal/RCL": f"{l.itens['Pessoal / RCL']['valor']*100:.1f}%",
            "DCL/RCL": f"{l.itens['DCL / RCL']['valor']*100:.0f}%",
            "Rec. corrente": f"{r.df_receita.loc['RECEITA_CORRENTE', ano_foco]:.1f}",
            "Serviço dívida": f"{r.servico_divida[ano_foco]:.1f}",
        })
    # inclui o cenário ativo
    linhas.append({
        "Cenário": "▶ Ativo (sliders)",
        "CAPAG": capag.nota_final,
        "Endiv. (DC/RCL)": f"{capag.endividamento:.2f}",
        "Propag": f"{propag.indice:.0f}",
        "Pessoal/RCL": f"{pess['valor']*100:.1f}%",
        "DCL/RCL": f"{dclr['valor']*100:.0f}%",
        "Rec. corrente": f"{df.loc['RECEITA_CORRENTE', ano_foco]:.1f}",
        "Serviço dívida": f"{res.servico_divida[ano_foco]:.1f}",
    })
    st.dataframe(pd.DataFrame(linhas).set_index("Cenário"), width='stretch')

    st.markdown("#### Trajetória da receita corrente e da RCL")
    fig = go.Figure()
    fig.add_trace(go.Bar(x=C.ANOS, y=[df.loc["RECEITA_CORRENTE", a] for a in C.ANOS],
                         name="Receita corrente", marker_color="#4575b4"))
    fig.add_trace(go.Scatter(x=C.ANOS, y=[df.loc["RCL", a] for a in C.ANOS],
                             name="RCL", mode="lines+markers", line=dict(color="#d73027")))
    fig.update_layout(height=320, margin=dict(t=10, b=10), yaxis_title="R$ bi",
                      legend=dict(orientation="h"),
                      xaxis=dict(tickmode="array", tickvals=C.ANOS,
                                 ticktext=[str(a) for a in C.ANOS]))
    st.plotly_chart(fig, width='stretch')

# ===========================================================================
# 2) RECEITA
# ===========================================================================
with tabs[1]:
    st.subheader("Projeção de receita por rubrica")
    df = res.df_receita
    recorrentes = [r for r in C.ELASTICIDADES if r in df.index]
    tab_rub = df.loc[recorrentes].copy()
    tab_rub.index = [C.RUBRICAS[r]["label"] for r in recorrentes]
    st.dataframe(tab_rub.round(2), width='stretch')

    st.markdown("#### Composição da receita corrente (ano em foco)")
    vals = df.loc[recorrentes, ano_foco]
    labels = [C.RUBRICAS[r]["label"] for r in recorrentes]
    fig = go.Figure(go.Pie(labels=labels, values=vals, hole=0.45))
    fig.update_layout(height=380, margin=dict(t=10, b=10))
    st.plotly_chart(fig, width='stretch')

    q = res.qualidade[ano_foco]
    st.markdown("#### Bloco 4 — Qualidade da receita")
    qc = st.columns(4)
    qc[0].metric("Concentração (HHI)", f"{q['hhi']:.3f}",
                 help="Herfindahl das rubricas. Mais alto = mais concentrado.")
    qc[1].metric("Peso das 2 maiores", f"{q['top2']*100:.1f}%")
    qc[2].metric("Dependência de petróleo", f"{q['dependencia_petroleo']*100:.1f}%",
                 help="R&PE ÷ receita corrente (exógena: Brent/câmbio/produção).")
    qc[3].metric("Não recorrente", f"{q['participacao_nao_recorrente']*100:.1f}%",
                 help="Receita eventual sobre o total — não deve custear despesa permanente.")

    st.markdown("#### Recorrente × não recorrente")
    st.caption("O PLDO exclui receitas extraordinárias da projeção de ICMS para não "
               "superestimar. O painel replica a separação: despesa permanente não "
               "deve ser alocada contra receita de uma vez só.")
    nao_rec = [r for r, m in C.RUBRICAS.items() if not m["recorrente"]]
    nr = pd.DataFrame({
        "Rubrica": [C.RUBRICAS[r]["label"] for r in nao_rec],
        "2026 (informativo, R$ bi)": [C.BASELINE_2026.get(r, 0.0) for r in nao_rec],
        "Natureza": [C.RUBRICAS[r]["driver"] for r in nao_rec],
    }).set_index("Rubrica")
    st.dataframe(nr, width='stretch')

# ===========================================================================
# 3) CAPAG
# ===========================================================================
with tabs[2]:
    st.subheader(f"CAPAG simulado — {ano_foco}")
    st.warning(C.CAPAG_REGRA, icon="📏")
    st.info("Exibido em versão **simulada** (projeção sob o cenário). "
            "A versão apurada/oficial vem da STN e deve ser reconciliada. "
            "As faixas de corte precisam ser lidas da portaria STN vigente "
            "e versionadas.", icon="ℹ️")
    capag = res.capag[ano_foco]

    cc = st.columns([1, 2])
    cc[0].markdown(f"<div style='font-size:64px;font-weight:800;color:{CORES[capag.nota_final]}'>"
                   f"{capag.nota_final}</div><div>nota final (pior indicador)</div>",
                   unsafe_allow_html=True)
    with cc[1]:
        for nome, (val, rating) in capag.componentes.items():
            st.markdown(f"**{nome}** — {val:.2f} → "
                        f"<span style='color:{CORES[rating]};font-weight:700'>{rating}</span>",
                        unsafe_allow_html=True)
            st.progress(min(1.0, val / 3.0))

    st.markdown("#### Faixas de corte (versionadas — [VALIDAR-STN])")
    for key, meta in C.CAPAG_FAIXAS.items():
        faixas_txt = " · ".join(f"{r}: [{lo:.2f}, {hi:.2f})" for r, lo, hi in meta["faixas"])
        st.caption(f"**{meta['label']}** — {faixas_txt}  \n_{meta['status_validacao']}_")

    st.markdown("#### CAPAG simulado por cenário")
    rows = []
    for key, r in res_presets.items():
        c = r.capag[ano_foco]
        rows.append({"Cenário": preset_labels[key], "Nota": c.nota_final,
                     "Endividamento": f"{c.endividamento:.2f} ({c.rating_endividamento})",
                     "Poupança": f"{c.poupanca:.2f} ({c.rating_poupanca})",
                     "Liquidez": f"{c.liquidez:.2f} ({c.rating_liquidez})"})
    st.dataframe(pd.DataFrame(rows).set_index("Cenário"), width='stretch')

# ===========================================================================
# 4) PROPAG
# ===========================================================================
with tabs[3]:
    st.subheader(f"Índice de adesão sustentável ao Propag — {ano_foco}")
    st.caption(f"LC nº 212/2025 · amortização extraordinária "
               f"{C.PROPAG['amortizacao_extraordinaria']*100:.0f}% do estoque · "
               f"{C.PROPAG['status_validacao']}")
    propag = res.propag[ano_foco]
    if propag.alerta_resim:
        st.error("FNDR rejeitado ⇒ contrapartidas sobem a 2%/2%. Re-simulação necessária.", icon="🚨")

    pc = st.columns([1, 2])
    pc[0].metric("Índice composto", f"{propag.indice:.0f}/100")
    pc[0].caption(f"Contrapartidas efetivas: FEF {propag.contrapartidas['fef_%']*100:.0f}% · "
                  f"Invest. {propag.contrapartidas['investimento_%']*100:.0f}%")
    with pc[1]:
        for nome, s in propag.subindicadores.items():
            st.markdown(f"**{nome.replace('_', ' ')}** — {s['score']:.0f}/100 "
                        f"(peso {s['peso']*100:.0f}%)  \n<small>{s['detalhe']}</small>",
                        unsafe_allow_html=True)
            st.progress(s["score"] / 100.0)

    st.markdown("#### Decomposição (radar)")
    nomes = [n.replace("_", " ") for n in propag.subindicadores]
    scores = [s["score"] for s in propag.subindicadores.values()]
    fig = go.Figure(go.Scatterpolar(r=scores + [scores[0]], theta=nomes + [nomes[0]],
                                    fill="toself", line_color="#4575b4"))
    fig.update_layout(height=380, polar=dict(radialaxis=dict(range=[0, 100])),
                      margin=dict(t=30, b=10))
    st.plotly_chart(fig, width='stretch')

# ===========================================================================
# 5) LRF & VINCULAÇÕES
# ===========================================================================
with tabs[4]:
    st.subheader(f"Limites da LRF e vinculações — {ano_foco}")
    st.caption(C.LRF["obs_rrf"])
    lrf = res.lrf[ano_foco]
    for nome, it in lrf.itens.items():
        cor = CORES.get(it["status"], "#888")
        alvo = "≤" if it["tipo"] == "teto" else "≥"
        st.markdown(f"**{nome}** — {it['valor']*100:.1f}%  "
                    f"(limite {alvo} {it['limite']*100:.0f}%) → "
                    f"<span style='color:{cor};font-weight:700'>{it['status']}</span>",
                    unsafe_allow_html=True)
        frac = min(1.0, it["valor"] / (it["limite"] * (2 if it["tipo"] == "teto" else 1)))
        st.progress(frac)

    st.markdown("#### Destaque permanente")
    st.error("Pessoal e encargos projetados em **68,57% da RCL** (PLDO 2027), acima do "
             "teto de 60% da LRF — é o indicador que mais restringe o espaço de alocação.",
             icon="🔴")

# ===========================================================================
# 6) FONTES & GOVERNANÇA
# ===========================================================================
with tabs[5]:
    st.subheader("Registro de fontes e frescor (passo 0)")
    fichas = pd.DataFrame([
        {"Rubrica": m["label"], "Dono/Sistema": m["dono"], "Driver": m["driver"],
         "Modelo (PLDO)": m["modelo_pldo"], "Frequência": m["frequencia"],
         "Recorrente": "Sim" if m["recorrente"] else "Não", "Grupo": m["grupo"]}
        for m in C.RUBRICAS.values()
    ]).set_index("Rubrica")
    st.dataframe(fichas, width='stretch')

    st.markdown("#### SLA de frescor por driver macro")
    fr = pd.DataFrame([
        {"Driver": m["label"], "Âncora 2027": m["ancora"][2027], "Fonte": m["fonte"],
         "SLA de frescor": m["sla_frescor"]}
        for m in C.DRIVERS_MACRO.values()
    ]).set_index("Driver")
    st.dataframe(fr, width='stretch')

    st.markdown("#### Pendências de validação (governança de modelos)")
    st.markdown(
        "- **[VALIDAR-STN]** faixas de corte do CAPAG — ler portaria vigente e reconciliar contra nota oficial.\n"
        "- **[VALIDAR-COMITE]** pesos do índice Propag.\n"
        "- **[VALIDAR-JURIDICO]** aplicabilidade dos limites LRF sob RRF/Propag.\n"
        "- **[VALIDAR-SEFAZ]** elasticidades de receita por tributo.\n"
        "- **[CALIBRACAO-PROTOTIPO]** baseline absoluto 2026 — substituir por RREO/RGF oficial.\n"
    )
    st.caption("O simulador é ferramenta de apoio à decisão: implementa as premissas, "
               "não as decide. Modelagem de elasticidades e projeções de receita exigem "
               "validação por economistas e pela área jurídico-fiscal.")
