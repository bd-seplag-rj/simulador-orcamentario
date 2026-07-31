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
from engine import sigfis as SG

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


@st.cache_resource(show_spinner="Lendo planilhas SIGFIS…")
def _sigfis():
    """Carrega os .xls reais de despesa e receita (se presentes na raiz)."""
    out = {"despesa": None, "receita": None, "erro": None}
    try:
        out["despesa"] = SG.carregar_despesa()
    except Exception as e:  # noqa: BLE001
        out["erro"] = f"despesa: {e}"
    try:
        out["receita"] = SG.carregar_receita()
    except Exception as e:  # noqa: BLE001
        out["erro"] = f"{out['erro'] or ''} receita: {e}".strip()
    return out


SIG = _sigfis()
MESES_PT = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
            "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


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
    _tem_sigfis = SIG["despesa"] is not None
    _opcoes = (["Planilha SIGFIS (.xls local)"] if _tem_sigfis else []) + [
        "Protótipo (sem dados)", "Arquivo exportado (CSV/Excel)", "Conexão direta (banco)"]
    fonte_dados = st.radio(
        "Origem da despesa", _opcoes, horizontal=True,
        help="SIGFIS: planilha real já presente no projeto. Arquivo: export do "
             "phpMyAdmin. Conexão direta requer MySQL acessível (Remote MySQL/SSH).")

    base_despesa = None
    df_funcao = None
    df_uo = None
    db_erro = None
    ds = None   # DespesaSigfis quando a fonte é a planilha real

    def _seletor_metrica():
        return st.radio("Métrica de execução (estágio usado como “realizado”)",
                        ["Empenhado", "Liquidado", "Pago"], horizontal=True,
                        help="Empenhado = compromisso · Liquidado = bem/serviço reconhecido "
                             "· Pago = desembolso de caixa.")

    if fonte_dados == "Planilha SIGFIS (.xls local)":
        ds = SIG["despesa"]
        st.success(f"📄 {ds.arquivo} · {len(ds.df):,} linhas · {ds.ano} · "
                   f"acumulado até **{MESES_PT[ds.n_meses-1]}** ({ds.n_meses}/12 meses) · "
                   f"estágio **Pago**", icon="✅")
        anualizar = st.checkbox(
            f"Anualizar a execução por run-rate (× 12/{ds.n_meses}) para alimentar os índices",
            value=True,
            help="Os dados cobrem apenas parte do ano. Sem anualizar, comparar "
                 f"{ds.n_meses} meses de despesa com a receita ANUAL projetada "
                 "subestima Pessoal/RCL, poupança do CAPAG e serviço da dívida.")
        gd = SG.despesa_por_gd(ds, anualizar=anualizar)
        base_despesa = D.montar_base_despesa(gd, ano_base=ds.ano, metrica="Pago")
        df_funcao = SG.despesa_por_funcao(ds).rename(columns={"funcao": "tit_funcao"})
        df_uo = SG.despesa_por_uo(ds).head(12)
        if anualizar:
            st.caption(f"⚙️ Índices calculados com despesa **anualizada** "
                       f"(× {12/ds.n_meses:.2f}). Os quadros de análise abaixo mostram "
                       "os valores **acumulados reais**, sem projeção.")
        else:
            st.warning("Índices usando execução parcial contra receita anual — "
                       "Pessoal/RCL e poupança ficarão artificialmente baixos.", icon="⚠️")
        st.caption("Este export traz apenas o estágio **Pago** (sem empenhado/liquidado), "
                   "portanto não é possível apurar restos a pagar. [VALIDAR-SEFAZ]")

    elif fonte_dados == "Arquivo exportado (CSV/Excel)":
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
    elif ds is None:
        # Bloco genérico (CSV / banco). Com SIGFIS, a "Análise geral" abaixo
        # cobre isso com os valores acumulados reais, sem anualização.
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

    # -------------------------------------------------------------------
    # Análise geral + trajetória por UO (requer a planilha SIGFIS)
    # -------------------------------------------------------------------
    if ds is not None:
        st.divider()
        st.markdown("### 📈 Análise geral dos gastos")

        serie_total = SG.serie_mensal_uo(ds)          # Estado inteiro
        pago_total = float(serie_total.sum())
        dot_total = float(ds.df["Dotação Atualizada"].sum() * C.DB_ESCALA_PARA_BI)
        dot_ini = float(ds.df["Dotação Inicial"].sum() * C.DB_ESCALA_PARA_BI)
        ritmo = ds.n_meses / 12.0
        proj_ano = pago_total / ritmo                 # run-rate anualizado
        # categorias em valores REAIS acumulados (sem anualizar) para esta seção
        gd_real = SG.despesa_por_gd(ds, anualizar=False)
        cat = gd_real.groupby("categoria")["execucao"].sum().to_dict()
        obrig = sum(cat.get(k, 0.0) for k in ("pessoal", "juros", "amortizacao"))
        discric = pago_total - obrig

        a = st.columns(5)
        a[0].metric("Pago acumulado", f"R$ {pago_total:.1f} bi",
                    f"{ds.n_meses}/12 meses")
        a[1].metric("Dotação atualizada", f"R$ {dot_total:.1f} bi",
                    f"{(dot_total-dot_ini):+.1f} vs inicial")
        a[2].metric("Execução", f"{pago_total/dot_total*100:.1f}%",
                    f"ritmo linear {ritmo*100:.0f}%")
        a[3].metric("Projeção run-rate", f"R$ {proj_ano:.1f} bi",
                    f"{proj_ano/dot_total*100:.0f}% da dotação")
        a[4].metric("Despesa obrigatória", f"{obrig/pago_total*100:.1f}%",
                    f"discricionária {discric/pago_total*100:.1f}%",
                    delta_color="off")
        st.caption("Obrigatória = pessoal + juros + amortização (GND 1, 2 e 6). "
                   "A discricionária é o espaço real de decisão do alocador.")

        g1, g2 = st.columns([3, 2])
        with g1:
            st.markdown("**Trajetória mensal do Estado (Pago)**")
            fig = go.Figure()
            fig.add_trace(go.Bar(x=list(serie_total.index), y=list(serie_total.values),
                                 name="Pago no mês", marker_color="#4575b4"))
            fig.add_trace(go.Scatter(x=list(serie_total.index),
                                     y=list(serie_total.cumsum().values),
                                     name="Acumulado", mode="lines+markers",
                                     yaxis="y2", line=dict(color="#d73027")))
            fig.update_layout(height=340, margin=dict(t=10, b=10),
                              yaxis=dict(title="R$ bi (mês)"),
                              yaxis2=dict(title="acumulado", overlaying="y",
                                          side="right", showgrid=False),
                              legend=dict(orientation="h"))
            st.plotly_chart(fig, width='stretch')
        with g2:
            st.markdown("**Composição por GND**")
            rot_gnd = {"pessoal": "1 Pessoal", "juros": "2 Juros", "custeio": "3 Custeio",
                       "investimento": "4 Investim.", "inversoes": "5 Inversões",
                       "amortizacao": "6 Amortiz."}
            it = [(rot_gnd[k], cat.get(k, 0.0)) for k in rot_gnd if cat.get(k, 0.0) > 0]
            fig = go.Figure(go.Pie(labels=[i[0] for i in it], values=[i[1] for i in it],
                                   hole=0.45))
            fig.update_layout(height=340, margin=dict(t=10, b=10),
                              legend=dict(orientation="h"))
            st.plotly_chart(fig, width='stretch')

        st.markdown("**Execução por função — onde o dinheiro está sendo gasto**")
        dff = SG.despesa_por_funcao(ds).head(12).copy()
        dff["execucao_pct"] = dff["execucao"] / dff["dot_atual"].replace(0, pd.NA) * 100
        fig = go.Figure()
        fig.add_trace(go.Bar(y=dff["funcao"], x=dff["dot_atual"], orientation="h",
                             name="Dotação atualizada", marker_color="#c6dbef"))
        fig.add_trace(go.Bar(y=dff["funcao"], x=dff["execucao"], orientation="h",
                             name="Pago", marker_color="#2171b5"))
        fig.update_layout(height=420, margin=dict(t=10, b=10), barmode="overlay",
                          xaxis_title="R$ bi", yaxis=dict(autorange="reversed"),
                          legend=dict(orientation="h"))
        st.plotly_chart(fig, width='stretch')

        # ---------------- Subseção: trajetória por UO ----------------
        st.divider()
        st.markdown("### 🏛️ Trajetória de gastos por Unidade Orçamentária")
        todas_uo = SG.despesa_por_uo(ds)
        opts = todas_uo["cod_uo"].tolist()
        rotulos_uo = dict(zip(todas_uo["cod_uo"], todas_uo["tit_uo"]))
        sel_uo = st.selectbox(
            "Escolha a Unidade Orçamentária (UO)", opts,
            format_func=lambda c: f"{rotulos_uo.get(c, '')} ({c})",
            help="Ordenadas por valor pago. A trajetória mostra o gasto mês a mês.")
        det = SG.detalhe_uo(ds, sel_uo)
        serie_uo = SG.serie_mensal_uo(ds, sel_uo)

        u = st.columns(5)
        u[0].metric("Pago acumulado", f"R$ {det['pago']:.2f} bi")
        u[1].metric("Dotação atualizada", f"R$ {det['dot_atual']:.2f} bi",
                    f"{det['dot_atual']-det['dot_inicial']:+.2f} vs inicial")
        u[2].metric("Execução", f"{det['execucao_pct']:.1f}%",
                    f"{det['execucao_pct']-ritmo*100:+.1f} p.p. vs ritmo")
        u[3].metric("Participação no Estado", f"{det['pago']/pago_total*100:.1f}%")
        u[4].metric("Ações orçamentárias", f"{det['n_acoes']}")

        t1, t2 = st.columns([3, 2])
        with t1:
            st.markdown(f"**{det['sigla']} — gasto mês a mês**")
            fig = go.Figure()
            fig.add_trace(go.Bar(x=list(serie_uo.index), y=list(serie_uo.values),
                                 name="Pago no mês", marker_color="#238b45"))
            fig.add_trace(go.Scatter(x=list(serie_uo.index),
                                     y=list(serie_uo.cumsum().values),
                                     name="Acumulado", mode="lines+markers",
                                     yaxis="y2", line=dict(color="#d73027")))
            media = float(serie_uo.mean())
            fig.add_hline(y=media, line_dash="dot", line_color="#888",
                          annotation_text=f"média R$ {media:.2f} bi")
            fig.update_layout(height=360, margin=dict(t=10, b=10),
                              yaxis=dict(title="R$ bi (mês)"),
                              yaxis2=dict(title="acumulado", overlaying="y",
                                          side="right", showgrid=False),
                              legend=dict(orientation="h"))
            st.plotly_chart(fig, width='stretch')
        with t2:
            st.markdown("**Por GND nesta UO**")
            pc = det["por_categoria"]
            it = [(rot_gnd.get(k, k), v) for k, v in pc.items() if v > 0]
            it.sort(key=lambda x: -x[1])
            if it:
                fig = go.Figure(go.Bar(x=[i[1] for i in it], y=[i[0] for i in it],
                                       orientation="h", marker_color="#238b45"))
                fig.update_layout(height=360, margin=dict(t=10, b=10),
                                  xaxis_title="R$ bi",
                                  yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, width='stretch')

        with st.expander("Detalhe mensal por GND nesta UO"):
            tab = SG.serie_mensal_uo_por_gnd(ds, sel_uo)
            tab.index = [rot_gnd.get(i, i) for i in tab.index]
            st.dataframe(tab.round(3), width='stretch')


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
res = S.avaliar_cenario(cen_ativo, anchors, base_despesa, ds)
res_presets = {k: S.avaliar_cenario(v, anchors, base_despesa, ds)
               for k, v in presets.items()}


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

    # =====================================================================
    # Subseção: execução da receita por Unidade Gestora (dados reais SIGFIS)
    # =====================================================================
    rs = SIG["receita"]
    if rs is None:
        st.divider()
        st.info("Planilha de receita do SIGFIS não encontrada na raiz do projeto — "
                "a subseção por UG fica indisponível.", icon="📄")
    else:
        st.divider()
        st.markdown("### 🏦 Previsão × Realização da receita por Unidade Gestora")
        ug_tab = SG.receita_por_ug(rs)
        tot_prev = float(ug_tab["previsao"].sum())
        tot_real = float(ug_tab["realizada"].sum())
        n_meses_rec = len(rs.meses)
        ritmo_rec = n_meses_rec / 12.0

        st.caption(f"Fonte: {rs.arquivo} · {len(rs.classificada):,} linhas classificadas · "
                   f"acumulado até **{MESES_PT[n_meses_rec-1]}** ({n_meses_rec}/12 meses). "
                   "Valores da coluna *Receitas Realizadas* (acumulada).")

        opts_ug = ["__TODAS__"] + ug_tab["cod_ug"].tolist()
        rot_ug = dict(zip(ug_tab["cod_ug"], ug_tab["nome_ug"]))
        sel_ug = st.selectbox(
            "Escolha a Unidade Gestora (UG)", opts_ug,
            format_func=lambda c: ("▣ Todas as UGs (consolidado)" if c == "__TODAS__"
                                   else f"{rot_ug.get(c, '')} ({c})"),
            help="Ordenadas por receita realizada.")

        if sel_ug == "__TODAS__":
            prev, real = tot_prev, tot_real
            titulo = "Consolidado — todas as UGs"
            rub = SG.receita_por_rubrica(rs)
            detalhe = None
        else:
            linha = ug_tab[ug_tab["cod_ug"] == sel_ug].iloc[0]
            prev, real = float(linha["previsao"]), float(linha["realizada"])
            titulo = f"{linha['nome_ug']} ({sel_ug})"
            rub = SG.receita_por_rubrica(rs, sel_ug)
            detalhe = SG.receita_detalhe_ug(rs, sel_ug)

        pct = (real / prev * 100) if prev else 0.0
        gap = pct - ritmo_rec * 100
        m = st.columns(5)
        m[0].metric("Previsão inicial (ano)", f"R$ {prev:.2f} bi")
        m[1].metric("Realizada (acumulada)", f"R$ {real:.2f} bi")
        m[2].metric("Realização", f"{pct:.1f}%", f"{gap:+.1f} p.p. vs ritmo")
        m[3].metric("Projeção run-rate", f"R$ {real/ritmo_rec:.2f} bi",
                    f"{(real/ritmo_rec)/prev*100-100:+.0f}% vs previsão" if prev else "")
        m[4].metric("Participação no total", f"{real/tot_real*100:.1f}%" if tot_real else "—")
        if gap < -5:
            st.warning(f"⚠️ Arrecadação **abaixo do ritmo do ano** ({pct:.1f}% realizado "
                       f"contra {ritmo_rec*100:.0f}% do calendário) — risco de frustração.",
                       icon="⚠️")
        elif gap > 5:
            st.success(f"Arrecadação **acima do ritmo** ({pct:.1f}% vs {ritmo_rec*100:.0f}% "
                       "do calendário).", icon="📈")

        st.markdown(f"**{titulo} — previsão × realizada por rubrica**")
        rub_p = rub[rub["previsao"] + rub["realizada"] > 0].head(12)
        fig = go.Figure()
        fig.add_trace(go.Bar(y=rub_p["label"], x=rub_p["previsao"], orientation="h",
                             name="Previsão inicial (ano)", marker_color="#c6dbef"))
        fig.add_trace(go.Bar(y=rub_p["label"], x=rub_p["realizada"], orientation="h",
                             name=f"Realizada (até {MESES_PT[n_meses_rec-1]})",
                             marker_color="#2171b5"))
        fig.update_layout(height=380, margin=dict(t=10, b=10), barmode="overlay",
                          xaxis_title="R$ bi", yaxis=dict(autorange="reversed"),
                          legend=dict(orientation="h"))
        st.plotly_chart(fig, width='stretch')

        tabela = rub_p[["label", "previsao", "realizada", "realiz_pct"]].rename(
            columns={"label": "Rubrica", "previsao": "Previsão (R$ bi)",
                     "realizada": "Realizada (R$ bi)", "realiz_pct": "Realização %"})
        st.dataframe(tabela.round(2), width='stretch', hide_index=True)

        if detalhe is not None and not detalhe.empty:
            with st.expander(f"Naturezas de receita desta UG ({len(detalhe)})"):
                st.dataframe(
                    detalhe[["COD NR", "TIT NR", "previsao", "realizada", "realiz_pct"]]
                    .rename(columns={"COD NR": "Cód.", "TIT NR": "Natureza",
                                     "previsao": "Previsão (R$ bi)",
                                     "realizada": "Realizada (R$ bi)",
                                     "realiz_pct": "Realização %"}).round(3),
                    width='stretch', hide_index=True)

        diag = SG.diagnostico_receita(rs, None if sel_ug == "__TODAS__" else sel_ug)
        with st.expander("⚠️ Série mensal bruta — diagnóstico de qualidade do dado"):
            st.error(
                "As colunas mensais deste export **não representam arrecadação mensal**: "
                f"a soma dos meses (R$ {diag['soma_mensal']:.1f} bi) diverge "
                f"{diag['razao']:.1f}× da coluna acumulada *Receitas Realizadas* "
                f"(R$ {diag['acumulada']:.1f} bi). Elas carregam movimentação financeira "
                "bruta — ex.: o ICMS aparece com R$ 116 bi em Janeiro, acima da própria "
                "previsão anual. Por isso o painel usa a coluna acumulada, e a série "
                "mensal fica aqui apenas como diagnóstico. **[VALIDAR-SEFAZ]**", icon="🚨")
            serie_r = SG.receita_serie_mensal(rs, None if sel_ug == "__TODAS__" else sel_ug)
            fig = go.Figure(go.Bar(x=list(serie_r.index), y=list(serie_r.values),
                                   marker_color="#fc8d59"))
            fig.update_layout(height=260, margin=dict(t=10, b=10),
                              yaxis_title="R$ bi (movimentação, não reconciliada)")
            st.plotly_chart(fig, width='stretch')
            st.caption(f"Linhas de movimentação/intra (natureza «-») excluídas das "
                       f"agregações: R$ {diag['movimentacao_excluida']:.1f} bi.")


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

    # ------------------------------------------------------------------
    # DTP — Despesa Total com Pessoal (LRF arts. 18-20)
    # ------------------------------------------------------------------
    st.divider()
    st.markdown("### ⚖️ Despesa Total com Pessoal (DTP) — LRF arts. 18 a 20")
    if res.dtp is None:
        st.info("A apuração da DTP requer a planilha SIGFIS. Selecione "
                "**Planilha SIGFIS** na aba *Execução (SIAFE)*.", icon="📄")
        _p_pldo = C.ANCORAS_PLDO_2027["pessoal_sobre_rcl"] * 100
        st.caption(f"Referência do PLDO 2027: {_p_pldo:.2f}% da RCL.")
    else:
        t = res.dtp
        _p_pldo = C.ANCORAS_PLDO_2027["pessoal_sobre_rcl"] * 100
        d1 = st.columns(4)
        d1[0].metric("DTP / RCL (apurada)", f"{t.razao*100:.2f}%",
                     f"{t.razao*100-t.limite*100:+.2f} p.p. vs teto de 60%",
                     delta_color="inverse")
        d1[1].metric("DTP líquida", f"R$ {t.dtp_liquida:.2f} bi",
                     f"bruta {t.dtp_bruta:.2f}")
        d1[2].metric("RCL (LRF)", f"R$ {t.rcl:.2f} bi")
        d1[3].metric("Referência PLDO 2027", f"{_p_pldo:.2f}%",
                     f"{t.razao*100-_p_pldo:+.2f} p.p. vs apurado",
                     delta_color="off")
        if abs(t.razao * 100 - _p_pldo) <= 3:
            st.success(f"✅ Reconciliação: a DTP apurada ({t.razao*100:.2f}%) fica a "
                       f"{abs(t.razao*100-_p_pldo):.2f} p.p. da referência do PLDO "
                       f"({_p_pldo:.2f}%) — metodologias compatíveis.", icon="✅")

        cA, cB = st.columns(2)
        with cA:
            st.markdown("**Composição da DTP**")
            comp = pd.DataFrame([{"Componente": k, "R$ bi": v}
                                 for k, v in t.componentes.items()])
            fig = go.Figure(go.Bar(x=comp["R$ bi"], y=comp["Componente"],
                                   orientation="h", marker_color="#6a51a3"))
            fig.update_layout(height=240, margin=dict(t=10, b=10), xaxis_title="R$ bi",
                              yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, width='stretch')
        with cB:
            st.markdown("**Deduções aplicadas (art. 19, § 1º)**")
            if t.deducoes:
                for k, v in t.deducoes.items():
                    st.markdown(f"- {k}: **R$ {v:.3f} bi**")
            tot_ded = sum(t.deducoes.values())
            st.caption(f"Total deduzido: R$ {tot_ded:.3f} bi "
                       f"({tot_ded/t.dtp_bruta*100:.2f}% da DTP bruta)")
            for o in t.observacoes:
                st.caption("• " + o)

        st.markdown("**Sublimites por Poder (art. 20, II)**")
        pp = t.por_poder.copy()

        def _cor(s):
            return [f"color: {CORES.get(v, '#888')}; font-weight:700" for v in s]
        st.dataframe(pp.style.apply(_cor, subset=["Status"]).format({
            "DTP (R$ bi)": "{:.2f}", "% da RCL": "{:.2f}",
            "Limite %": "{:.0f}", "Margem p.p.": "{:+.2f}"}),
            width='stretch', hide_index=True)
        st.caption(C.DTP_STATUS_VALIDACAO)

        with st.expander("Como a DTP é apurada aqui (e onde ela difere do RGF)"):
            st.markdown(
                "**Entra (art. 18):** GND 1 — Pessoal e Encargos Sociais, de todos os "
                "Poderes, incluindo ativos, inativos e pensionistas.\n\n"
                "**Sai (art. 19, § 1º):** indenizações por demissão e PDV; despesas de "
                "decisão judicial de período anterior (precatórios); inativos custeados "
                "por recursos vinculados ao RPPS — *esta última está desligada*, porque "
                "no ERJ os inativos são custeados sobretudo por royalties (fonte STN 704) "
                "e pelo Tesouro, e não pela arrecadação de contribuições dos segurados. "
                "Ligá-la derrubaria o indicador de ~67% para ~39%.\n\n"
                "**RCL (art. 2º, IV):** receitas correntes menos as parcelas entregues aos "
                "Municípios, as contribuições dos servidores ao RPPS e as receitas "
                "intraorçamentárias.\n\n"
                "**Diferenças conhecidas para o RGF:** a LRF apura em 12 meses e aqui há "
                f"{t.n_meses} meses anualizados; a base é o estágio *pago*; o "
                "enquadramento da Defensoria Pública no Executivo e a atribuição de "
                "Poder dos inativos são heurísticas.")


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

    st.markdown("#### Divergências conhecidas (dado real × PLDO)")
    st.caption("Apuradas na auditoria dos índices. Reexecute com "
               "`python scripts/auditoria_indices.py`.")
    for _k, _d in C.DIVERGENCIAS_CONHECIDAS.items():
        with st.expander(f"⚖️ {_d['titulo']}"):
            st.markdown(_d["detalhe"])
            st.info(_d["acao"], icon="🔍")

    st.markdown("#### Base de receita (origem dos números)")
    st.caption(C.BASELINE_2026["_fonte"] +
               f" · fator de dedução da RCL medido no dado real: "
               f"{C.FATOR_DEDUCAO_RCL:.4f}")
    _bl = pd.DataFrame([
        {"Rubrica": C.RUBRICAS[r]["label"], "Baseline 2026 (R$ bi)": v}
        for r, v in C.BASELINE_2026.items()
        if r in C.RUBRICAS and C.RUBRICAS[r]["recorrente"]
    ]).set_index("Rubrica")
    st.dataframe(_bl.round(2), width='stretch')

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
