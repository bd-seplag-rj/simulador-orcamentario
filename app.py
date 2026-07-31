"""
app.py — Painel de Simulação Orçamentária (ERJ / PLDO 2027).

Streamlit, SEM barra lateral — todos os controles ficam em abas:
  Visão geral · Drivers macro · Receita · Execução (SIAFE) · CAPAG · Propag ·
  LRF & Vinculações · Fontes & Governança

Drivers macro são pré-preenchidos SEMPRE com o Boletim Focus mais recente
(engine/focus.py, API pública do BCB), com fallback nas âncoras do PLDO.
A receita projetada de óleo e gás tem botão para a ferramenta dedicada.
"""
from __future__ import annotations
import copy
import io
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import config as C
from engine import receita as R
from engine import cenarios as S
from engine import indicadores as I
from engine import db as DB
from engine import despesa as D
from engine import dados_arquivo as DA
from engine import focus as F

st.set_page_config(page_title="Simulador Orçamentário — ERJ / PLDO 2027",
                   page_icon="📊", layout="wide")

CORES = {"A": "#1a9850", "B": "#91cf60", "C": "#fc8d59", "D": "#d73027",
         "OK": "#1a9850", "ALERTA": "#fee08b", "PRUDENCIAL": "#fc8d59",
         "ESTOURADO": "#d73027", "ABAIXO": "#d73027"}

preset_labels = {
    "base": "Base (Focus)",
    "otimista": "Otimista",
    "pessimista": "Pessimista",
    "aco_3678": "⚠️ Adverso — ACO nº 3.678",
}


# ---------------------------------------------------------------------------
# Fontes cacheadas
# ---------------------------------------------------------------------------
@st.cache_data
def _anchors():
    return R.calibrar()


@st.cache_data(ttl=6 * 3600, show_spinner="Consultando o Boletim Focus (BCB)…")
def _focus():
    return F.ultimo_focus(C.ANOS)


@st.cache_data(ttl=600, show_spinner="Consultando o banco…")
def _carregar_base_despesa(ano: int, metrica: str):
    df_gd = DB.despesa_por_gd(ano, metrica)
    return D.montar_base_despesa(df_gd, ano_base=ano, metrica=metrica)


@st.cache_data(show_spinner="Lendo arquivo exportado…")
def _parse_arquivo(nome: str, conteudo: bytes) -> pd.DataFrame:
    return DA.ler_export(io.BytesIO(conteudo), nome=nome)


def _status_banco():
    try:
        return True, DB.testar_conexao()
    except Exception as e:  # noqa: BLE001
        return False, str(e)


anchors = _anchors()
presets = S.cenarios_predefinidos()
focus_info = _focus()
focus_vals = focus_info["valores"]
base_preset = presets["base"]


def _seed_para(preset_key: str) -> dict:
    """Valores-semente por driver = Focus (base) + delta do preset escolhido."""
    vals = {}
    for drv in C.DRIVERS_MACRO:
        vals[drv] = {}
        for ano in C.ANOS:
            delta = presets[preset_key].drivers[drv][ano] - base_preset.drivers[drv][ano]
            vals[drv][ano] = round(focus_vals[drv][ano] + delta, 4)
    return vals


# ---------------------------------------------------------------------------
# Cabeçalho + abas
# ---------------------------------------------------------------------------
st.title("📊 Simulador Orçamentário — Estado do Rio de Janeiro")
st.caption(f"Base: {C.METADADOS['documento']} · unidade {C.UNIDADE}")

tabs = st.tabs(["Visão geral", "Drivers macro", "Receita", "Execução (SIAFE)",
                "CAPAG", "Propag", "LRF & Vinculações", "Fontes & Governança"])


def kpi_card(col, titulo, valor, sub, cor=None):
    col.metric(titulo, valor, sub)
    if cor:
        col.markdown(f"<div style='height:4px;background:{cor};border-radius:2px'></div>",
                     unsafe_allow_html=True)


# ===========================================================================
# ABA 1 — DRIVERS MACRO  (entradas — preenchida primeiro para coletar inputs)
# ===========================================================================
with tabs[1]:
    st.subheader("Drivers macroeconômicos")
    if focus_info["ok"]:
        st.success(f"Campos pré-preenchidos com o Boletim **Focus de "
                   f"{focus_info['data_ref']}** (consulta em {focus_info['consultado_em']}). "
                   f"Brent e produção de óleo não constam do Focus.", icon="🎯")
    else:
        st.warning(f"Não foi possível consultar o Focus agora — usando âncoras do "
                   f"PLDO como padrão. Detalhe: {focus_info['erro']}", icon="⚠️")

    top = st.columns([3, 1])
    preset_key = top[0].radio("Cenário-semente", list(preset_labels),
                              format_func=lambda k: preset_labels[k], horizontal=True,
                              key="preset_key")
    ano_foco = top[1].selectbox("Ano em foco", C.ANOS, key="ano_foco")

    # Semeadura ao trocar de cenário (antes de instanciar os campos)
    if st.session_state.get("last_preset") != preset_key:
        st.session_state["last_preset"] = preset_key
        sv = _seed_para(preset_key)
        for drv in C.DRIVERS_MACRO:
            for ano in C.ANOS:
                st.session_state[f"drv_{drv}_{ano}"] = sv[drv][ano]
        p = presets[preset_key]
        st.session_state["ctx_fndr"] = p.fndr_status
        st.session_state["ctx_propag"] = p.propag_ativo
        st.session_state["ctx_inv"] = int(p.investimento_executado_frac * 100)
        st.session_state["ctx_choque"] = float(p.choque_servico_divida.get(2027, 0.0))

    if st.button("🔄 Restaurar valores do Focus", help="Recarrega os campos com o "
                 "cenário e o Focus mais recente."):
        st.session_state["last_preset"] = None
        st.rerun()

    st.markdown("#### Principais drivers (2027–2029)")
    drivers_custom = {drv: {} for drv in C.DRIVERS_MACRO}
    for drv, meta in C.DRIVERS_MACRO.items():
        origem = focus_info["origem"].get(drv, "fallback")
        selo = "🎯 Focus" if origem == "focus" else f"📌 {meta['fonte']}"
        st.markdown(f"**{meta['label']}** &nbsp;<small>{selo} · SLA: {meta['sla_frescor']}</small>",
                    unsafe_allow_html=True)
        if meta.get("alerta"):
            st.caption("⚠️ " + meta["alerta"])
        lo, hi = meta["faixa_slider"]
        cols = st.columns(3)
        for i, ano in enumerate(C.ANOS):
            drivers_custom[drv][ano] = cols[i].number_input(
                f"{ano}", min_value=float(lo), max_value=float(hi),
                step=float(meta["passo"]), key=f"drv_{drv}_{ano}", format="%.2f")
        if drv == "brent":
            st.link_button("🛢️ Abrir projeção de royalties de óleo e gás ↗",
                           "https://projecao-royalties-rj.streamlit.app/",
                           help="A receita projetada de óleo e gás é calculada em "
                                "ferramenta dedicada (Brent/câmbio/produção da ANP).")
        st.divider()

    with st.expander("Parâmetros de cenário (dívida / Propag)"):
        fndr = st.radio("Status do ativo FNDR ofertado",
                        ["rejeitado", "parcial", "aceito"], horizontal=True, key="ctx_fndr",
                        help="Único ativo ofertado à União; rejeição eleva contrapartidas a 2%/2%.")
        propag_ativo = st.checkbox("Contrato Propag formalizado", key="ctx_propag",
                                   help="Se desmarcado, indexação da dívida usa proxy IGP-M.")
        inv_exec = st.slider("Execução do investimento obrigatório (%)", 0, 100,
                             key="ctx_inv") / 100.0
        choque_aco = st.number_input("Choque no serviço da dívida 2027 (R$ bi)", 0.0, 50.0,
                                     step=0.5, key="ctx_choque",
                                     help="Cenário ACO 3.678: +R$ 11,7 bi.")


# ===========================================================================
# ABA 4 — EXECUÇÃO (SIAFE)  (fonte de dados + display; autônoma)
# ===========================================================================
with tabs[3]:
    st.subheader("Execução da despesa (SIAFE)")
    fonte_dados = st.radio(
        "Origem da despesa",
        ["Protótipo (sem dados)", "Arquivo exportado (CSV/Excel)", "Conexão direta (banco)"],
        horizontal=True,
        help="Arquivo: exporte a tabela `despesa` no phpMyAdmin (Export → CSV) e "
             "carregue aqui. Conexão direta requer MySQL acessível (Remote MySQL/SSH).")

    base_despesa = None
    df_funcao = None
    df_uo = None
    db_erro = None

    def _seletor_metrica():
        return st.radio("Métrica de execução (estágio usado como “realizado”)",
                        ["Empenhado", "Liquidado", "Pago"], horizontal=True,
                        help="Empenhado = compromisso · Liquidado = bem/serviço reconhecido "
                             "· Pago = desembolso de caixa.")

    if fonte_dados == "Arquivo exportado (CSV/Excel)":
        up = st.file_uploader("Arquivo da tabela `despesa`", type=["csv", "xlsx", "xls"],
                              help="phpMyAdmin → tabela `despesa` → Export → CSV → "
                                   "“Colunas na primeira linha”.")
        if up is not None:
            try:
                df_arq = _parse_arquivo(up.name, up.getvalue())
                faltando = DA.validar_colunas(df_arq)
                if faltando:
                    st.error("Colunas essenciais ausentes: " + ", ".join(faltando), icon="🚫")
                    with st.expander("Colunas encontradas"):
                        st.code(", ".join(map(str, df_arq.columns)))
                else:
                    anos_arq = DA.anos_disponiveis(df_arq)
                    cc = st.columns([1, 2])
                    ano_sel = cc[0].selectbox("Ano-base", anos_arq) if anos_arq else None
                    with cc[1]:
                        metrica = _seletor_metrica()
                    if ano_sel is not None:
                        gd = DA.agregar_gd(df_arq, int(ano_sel), metrica)
                        base_despesa = D.montar_base_despesa(gd, ano_base=int(ano_sel), metrica=metrica)
                        df_funcao = DA.agregar_funcao(df_arq, int(ano_sel), metrica)
                        df_uo = DA.agregar_uo(df_arq, int(ano_sel), metrica, limite=12)
                        st.success(f"Arquivo lido · {len(df_arq):,} linhas · base {ano_sel} "
                                   f"· {metrica}", icon="✅")
            except Exception as e:  # noqa: BLE001
                db_erro = str(e)
                st.error("Falha ao ler/agregar o arquivo. Usando protótipo.", icon="⚠️")
                with st.expander("Detalhe do erro"):
                    st.code(str(e))
        else:
            st.info("Aguardando o arquivo exportado do phpMyAdmin.", icon="⬆️")

    elif fonte_dados == "Conexão direta (banco)":
        ok, info = _status_banco()
        if not ok:
            db_erro = info
            st.error("Sem conexão com o banco. Usando protótipo.", icon="🚫")
            with st.expander("Detalhe do erro / como configurar"):
                st.code(info)
                st.caption("Requer MySQL acessível (Remote MySQL ou túnel SSH). "
                           "Ver INTEGRACAO_BANCO.md.")
        else:
            try:
                anos_db = DB.anos_disponiveis()
            except Exception as e:  # noqa: BLE001
                anos_db, db_erro = [], str(e)
            if anos_db:
                cc = st.columns([1, 2])
                ano_db = cc[0].selectbox("Ano-base", anos_db)
                with cc[1]:
                    metrica = _seletor_metrica()
                try:
                    base_despesa = _carregar_base_despesa(int(ano_db), metrica)
                    df_funcao = DB.despesa_por_funcao(int(ano_db), metrica).head(12)
                    df_uo = DB.despesa_por_uo(int(ano_db), metrica, limite=12)
                    st.success(f"Conectado · {info['linhas']:,} linhas · base {ano_db} "
                               f"· {metrica}", icon="✅")
                except Exception as e:  # noqa: BLE001
                    db_erro = str(e)
                    st.error("Falha ao agregar despesa. Usando protótipo.", icon="⚠️")
                    with st.expander("Detalhe do erro"):
                        st.code(str(e))

    st.divider()
    # ---- display da execução ----
    if base_despesa is None:
        st.info("Escolha **“Arquivo exportado (CSV/Excel)”** acima e carregue a "
                "exportação da tabela `despesa` do phpMyAdmin — os índices passam a "
                "usar a execução real. Sem dados, a despesa usa o modelo-protótipo.",
                icon="🗄️")
        st.markdown("**Como exportar no phpMyAdmin (sem acesso direto ao MySQL):**")
        st.markdown(
            "1. Abra o banco `painel_subor` → clique na tabela **`despesa`**.\n"
            "2. Aba **Export** → formato **CSV** → marque **“Colunas na primeira linha”**.\n"
            "3. Se for grande, exporte um ano: aba **SQL** → "
            "`SELECT * FROM despesa WHERE ano = 2026;` → Export.\n"
            "4. Baixe o `.csv` e carregue no campo acima.\n\n"
            "Detalhes e conexão direta em **INTEGRACAO_BANCO.md**.")
    else:
        bd = base_despesa
        st.success(f"Fonte: {bd.fonte} · ano-base {bd.ano_base} · métrica {bd.metrica}",
                   icon="🟢")
        e = st.columns(4)
        e[0].metric("Execução total", f"R$ {bd.execucao_total:.1f} bi")
        e[1].metric("Dotação atual", f"R$ {bd.dotacao_total:.1f} bi")
        e[2].metric("Execução", f"{bd.execucao_pct*100:.1f}%")
        e[3].metric("Serviço da dívida", f"R$ {bd.servico_divida:.1f} bi",
                    help="Juros (GND 2) + Amortização (GND 6)")

        st.markdown("#### Despesa por Grupo de Despesa (GND) — atualiza os índices")
        cats = ["pessoal", "juros", "custeio", "investimento", "inversoes", "amortizacao"]
        rotulos = {"pessoal": "1 Pessoal", "juros": "2 Juros", "custeio": "3 Custeio",
                   "investimento": "4 Investimento", "inversoes": "5 Inversões",
                   "amortizacao": "6 Amortização"}
        vals = [bd.por_categoria.get(c, 0.0) for c in cats]
        fig = go.Figure(go.Bar(x=[rotulos[c] for c in cats], y=vals, marker_color="#4575b4"))
        fig.update_layout(height=300, margin=dict(t=10, b=10), yaxis_title="R$ bi")
        st.plotly_chart(fig, width='stretch')
        st.caption("Correntes = pessoal + juros + custeio · Capital = investimento + "
                   "inversões + amortização. Alimenta Pessoal/RCL, poupança do CAPAG, "
                   "serviço da dívida e o saldo primário do Propag.")

        colf, colu = st.columns(2)
        with colf:
            st.markdown("**Top funções**")
            if df_funcao is not None and not df_funcao.empty:
                st.dataframe(df_funcao[["tit_funcao", "execucao", "dot_atual"]]
                             .rename(columns={"tit_funcao": "Função", "execucao": "Exec. (R$ bi)",
                                              "dot_atual": "Dotação"}).round(2),
                             width='stretch', hide_index=True)
            else:
                st.caption("Sem agregação por função para esta fonte/ano.")
        with colu:
            st.markdown("**Top unidades orçamentárias**")
            if df_uo is not None and not df_uo.empty:
                st.dataframe(df_uo[["tit_uo", "execucao", "dot_atual"]]
                             .rename(columns={"tit_uo": "UO", "execucao": "Exec. (R$ bi)",
                                              "dot_atual": "Dotação"}).round(2),
                             width='stretch', hide_index=True)
            else:
                st.caption("Sem agregação por UO para esta fonte/ano.")
        st.caption(C.DB_STATUS_VALIDACAO)


# ---------------------------------------------------------------------------
# Montagem do cenário ativo + avaliação (após coletar todas as entradas)
# ---------------------------------------------------------------------------
cen_ativo = R.Cenario(
    nome=f"Ativo ({preset_labels[preset_key]})",
    drivers=copy.deepcopy(drivers_custom),
    choque_servico_divida={2027: choque_aco} if choque_aco > 0 else {},
    propag_ativo=propag_ativo, fndr_status=fndr,
    investimento_executado_frac=inv_exec,
    descricao=presets[preset_key].descricao,
)
res = S.avaliar_cenario(cen_ativo, anchors, base_despesa)
res_presets = {k: S.avaliar_cenario(v, anchors, base_despesa) for k, v in presets.items()}


# ===========================================================================
# ABA 0 — VISÃO GERAL
# ===========================================================================
with tabs[0]:
    _fonte_badge = ("🟢 despesa: execução real" if res.fonte_despesa.startswith("real")
                    else "🟡 despesa: modelo-protótipo (sem banco)")
    _focus_badge = (f"🎯 drivers: Focus {focus_info['data_ref']}" if focus_info["ok"]
                    else "📌 drivers: âncoras PLDO (Focus indisponível)")
    st.caption(f"{_focus_badge} · {_fonte_badge}")

    c1, c2 = st.columns(2)
    c1.info(f"ℹ️ {C.METADADOS['capag_no_pldo']} O CAPAG é **simulado** e deve ser "
            "reconciliado contra a nota oficial da STN.", icon="ℹ️")
    c2.warning(f"⚠️ {C.METADADOS['aviso_vigencia']}", icon="⚠️")
    for a in res.alertas:
        st.error(a, icon="🚨")

    st.subheader(f"Panorama — {ano_foco}")
    capag = res.capag[ano_foco]
    propag = res.propag[ano_foco]
    lrf = res.lrf[ano_foco]
    df = res.df_receita

    k = st.columns(5)
    kpi_card(k[0], "CAPAG (simulado)", capag.nota_final,
             f"endiv. {capag.endividamento:.2f}× RCL", CORES[capag.nota_final])
    kpi_card(k[1], "Índice Propag", f"{propag.indice:.0f}/100", f"FNDR: {cen_ativo.fndr_status}")
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
            "Cenário": preset_labels[key], "CAPAG": c.nota_final,
            "Endiv. (DC/RCL)": f"{c.endividamento:.2f}", "Propag": f"{p.indice:.0f}",
            "Pessoal/RCL": f"{l.itens['Pessoal / RCL']['valor']*100:.1f}%",
            "DCL/RCL": f"{l.itens['DCL / RCL']['valor']*100:.0f}%",
            "Rec. corrente": f"{r.df_receita.loc['RECEITA_CORRENTE', ano_foco]:.1f}",
            "Serviço dívida": f"{r.servico_divida[ano_foco]:.1f}",
        })
    linhas.append({
        "Cenário": "▶ Ativo", "CAPAG": capag.nota_final,
        "Endiv. (DC/RCL)": f"{capag.endividamento:.2f}", "Propag": f"{propag.indice:.0f}",
        "Pessoal/RCL": f"{pess['valor']*100:.1f}%", "DCL/RCL": f"{dclr['valor']*100:.0f}%",
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
# ABA 2 — RECEITA
# ===========================================================================
with tabs[2]:
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
# ABA 4 (índice 4) — CAPAG
# ===========================================================================
with tabs[4]:
    st.subheader(f"CAPAG simulado — {ano_foco}")
    st.warning(C.CAPAG_REGRA, icon="📏")
    st.info("Exibido em versão **simulada** (projeção sob o cenário). A versão "
            "apurada/oficial vem da STN e deve ser reconciliada. As faixas de corte "
            "precisam ser lidas da portaria STN vigente e versionadas.", icon="ℹ️")
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
# ABA 5 — PROPAG
# ===========================================================================
with tabs[5]:
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
# ABA 6 — LRF & VINCULAÇÕES
# ===========================================================================
with tabs[6]:
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
# ABA 7 — FONTES & GOVERNANÇA
# ===========================================================================
with tabs[7]:
    st.subheader("Registro de fontes e frescor (passo 0)")
    fichas = pd.DataFrame([
        {"Rubrica": m["label"], "Dono/Sistema": m["dono"], "Driver": m["driver"],
         "Modelo (PLDO)": m["modelo_pldo"], "Frequência": m["frequencia"],
         "Recorrente": "Sim" if m["recorrente"] else "Não", "Grupo": m["grupo"]}
        for m in C.RUBRICAS.values()
    ]).set_index("Rubrica")
    st.dataframe(fichas, width='stretch')

    st.markdown("#### Drivers macro — origem e frescor")
    fr = pd.DataFrame([
        {"Driver": m["label"], "Valor 2027": focus_vals[drv][2027],
         "Origem": ("Focus " + str(focus_info["data_ref"]) if focus_info["origem"].get(drv) == "focus"
                    else "âncora PLDO"),
         "SLA de frescor": m["sla_frescor"]}
        for drv, m in C.DRIVERS_MACRO.items()
    ]).set_index("Driver")
    st.dataframe(fr, width='stretch')

    st.markdown("#### Pendências de validação (governança de modelos)")
    st.markdown(
        "- **[VALIDAR-STN]** faixas de corte do CAPAG — ler portaria vigente e reconciliar.\n"
        "- **[VALIDAR-COMITE]** pesos do índice Propag.\n"
        "- **[VALIDAR-JURIDICO]** aplicabilidade dos limites LRF sob RRF/Propag.\n"
        "- **[VALIDAR-SEFAZ]** elasticidades de receita por tributo.\n"
        "- **[CALIBRACAO-PROTOTIPO]** baseline absoluto 2026 — substituir por RREO/RGF oficial.\n"
    )
    st.caption("O simulador é ferramenta de apoio à decisão: implementa as premissas, "
               "não as decide. Modelagem de elasticidades e projeções de receita exigem "
               "validação por economistas e pela área jurídico-fiscal.")
