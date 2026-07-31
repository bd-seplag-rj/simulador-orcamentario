"""
config.py — Fonte única de verdade dos parâmetros do simulador (ERJ / PLDO 2027).

TODO O QUE É "PREMISSA" MORA AQUI e em nenhum outro lugar do código:
  - âncoras de drivers macro (Focus 06/03/2026, conforme PLDO 2027);
  - fichas de fonte por rubrica de receita (dono, sistema, driver, frequência);
  - elasticidades / fatores de projeção por rubrica;
  - faixas de corte do CAPAG  ........ tag [VALIDAR-STN]
  - pesos do índice Propag  .......... tag [VALIDAR-COMITE]
  - limites da LRF / vinculações  .... tag [VALIDAR-JURIDICO]
  - baseline absoluto 2026  .......... tag [CALIBRACAO-PROTOTIPO]

Convenção de versionamento: cada bloco de premissa carrega `fonte`, `data_ref`
e, quando aplicável, um `status_validacao`. O painel exibe isso como "frescor".

IMPORTANTE (ressalvas herdadas do passo 0):
  * O PLDO 2027 NÃO publica CAPAG — as faixas aqui são padrão de referência e
    precisam ser lidas da portaria STN vigente e reconciliadas contra a nota
    oficial. Ver `CAPAG_FAIXAS[...]["status_validacao"]`.
  * Onde o PLDO deu razões (pessoal 68,57% RCL, DC 263%, DCL 277%) mas não o
    absoluto, o baseline é CALIBRADO para reproduzir a razão no cenário-base.
    Ver engine/receita.py::calibrar().
  * Confirmar se este PLDO é a versão vigente — as metas podem mudar na PLOA
    2027 caso a adesão ao Propag se concretize.
"""

from __future__ import annotations

# Unidade monetária padrão do motor: R$ bilhões.
UNIDADE = "R$ bi"
ANOS = [2027, 2028, 2029]
ANO_BASE = 2026

METADADOS = {
    "documento": "PLDO 2027 — Estado do Rio de Janeiro",
    "fonte_macro": "Relatório Focus/BCB de 06/03/2026 (conforme PLDO)",
    "aviso_vigencia": (
        "Confirmar se este PLDO é a versão vigente; metas podem ser ajustadas "
        "na PLOA 2027 caso a adesão ao Propag se concretize."
    ),
    "capag_no_pldo": "CAPAG não é publicado no PLDO — calculado pelo painel.",
}

# ---------------------------------------------------------------------------
# 1) DRIVERS MACRO — âncoras do PLDO (viram sliders no painel)
#    valor-âncora por ano + metadados de frescor.
# ---------------------------------------------------------------------------
DRIVERS_MACRO = {
    "pib_real": {
        "label": "PIB nacional (% a.a.)",
        "unidade": "% a.a.",
        "ancora": {2027: 1.80, 2028: 2.00, 2029: 2.00},
        "faixa_slider": (-4.0, 6.0),
        "passo": 0.10,
        "fonte": "Focus/BCB 06/03/2026",
        "sla_frescor": "trimestral (recalibra elasticidades)",
    },
    "cambio": {
        "label": "Câmbio (R$/US$)",
        "unidade": "R$/US$",
        "ancora": {2027: 5.50, 2028: 5.50, 2029: 5.50},
        "faixa_slider": (3.50, 8.00),
        "passo": 0.05,
        "fonte": "Focus/BCB 06/03/2026",
        "sla_frescor": "diário (mercado)",
    },
    "ipca": {
        "label": "IPCA (% a.a.)",
        "unidade": "% a.a.",
        "ancora": {2027: 3.80, 2028: 3.50, 2029: 3.50},
        "faixa_slider": (0.0, 12.0),
        "passo": 0.10,
        "fonte": "Focus/BCB 06/03/2026",
        "sla_frescor": "mensal",
    },
    "igpm": {
        "label": "IGP-M (% a.a.)",
        "unidade": "% a.a.",
        "ancora": {2027: 4.00, 2028: 3.83, 2029: 3.73},
        "faixa_slider": (-2.0, 15.0),
        "passo": 0.10,
        "fonte": "Focus/BCB 06/03/2026",
        "sla_frescor": "mensal",
    },
    "selic": {
        "label": "Selic (% a.a.)",
        "unidade": "% a.a.",
        "ancora": {2027: 10.50, 2028: 10.00, 2029: 9.50},
        "faixa_slider": (5.0, 18.0),
        "passo": 0.25,
        "fonte": "Focus/BCB 06/03/2026",
        "sla_frescor": "diário (curva) / semanal (Focus)",
    },
    "brent": {
        "label": "Brent (US$/barril)",
        "unidade": "US$/bbl",
        "ancora": {2027: 79.25, 2028: 79.25, 2029: 79.25},
        "faixa_slider": (30.0, 140.0),
        "passo": 0.25,
        "fonte": "EIA (repetido em 2028-29 por ausência de estimativa longa)",
        "sla_frescor": "diário (mercado)",
        "alerta": (
            "PLDO admite: Brent de 2028/2029 é repetição de 2027 por falta de "
            "estimativa EIA de longo prazo. Risco material sobre R$ ~30,7 bi."
        ),
    },
    "producao_oleo": {
        "label": "Índice de produção ANP (base 2027=1,00)",
        "unidade": "índice",
        "ancora": {2027: 1.00, 2028: 1.00, 2029: 1.00},
        "faixa_slider": (0.70, 1.30),
        "passo": 0.01,
        "fonte": "Curva de produção ANP / ACT ANP nº 01/15",
        "sla_frescor": "mensal",
    },
}

# ---------------------------------------------------------------------------
# 2) FICHAS DE FONTE POR RUBRICA (Registro de Fontes — passo 0)
#    dono, sistema, driver principal, modelo declarado no PLDO, frequência,
#    e se a rubrica é RECORRENTE (entra na projeção-base) ou não.
# ---------------------------------------------------------------------------
RUBRICAS = {
    "icms": {
        "label": "ICMS",
        "dono": "SEFAZ / SUBTES",
        "driver": "IBC-Br (proxy PIB) + câmbio",
        "modelo_pldo": "Modelo exógeno",
        "frequencia": "Mensal",
        "recorrente": True,
        "grupo": "Tributária própria",
    },
    "fecp": {
        "label": "FECP",
        "dono": "SEFAZ",
        "driver": "Proporção fixa sobre ICMS",
        "modelo_pldo": "Derivado do ICMS",
        "frequencia": "Mensal",
        "recorrente": True,
        "grupo": "Tributária própria",
    },
    "ipva": {
        "label": "IPVA",
        "dono": "SEFAZ",
        "driver": "IBC-Br + sazonalidade",
        "modelo_pldo": "Híbrido (ARIMA + IBC-Br)",
        "frequencia": "Mensal (forte sazonalidade)",
        "recorrente": True,
        "grupo": "Tributária própria",
    },
    "itd": {
        "label": "ITD",
        "dono": "SEFAZ",
        "driver": "Atividade econômica",
        "modelo_pldo": "Híbrido",
        "frequencia": "Mensal",
        "recorrente": True,
        "grupo": "Tributária própria",
    },
    "irrf": {
        "label": "IRRF",
        "dono": "SEFAZ / folha",
        "driver": "Crescimento vegetativo da folha (3,44%)",
        "modelo_pldo": "Base 2026 + fator vegetativo",
        "frequencia": "Mensal",
        "recorrente": True,
        "grupo": "Tributária própria",
    },
    "royalties_pe": {
        "label": "Royalties e Part. Especial (R&PE)",
        "dono": "SEFAZ via ACT ANP nº 01/15",
        "driver": "Brent × câmbio × produção",
        "modelo_pldo": "Estimativa ANP + preço/câmbio",
        "frequencia": "Mensal",
        "recorrente": True,
        "grupo": "Petróleo (exógena)",
    },
    "fpe_ipiexp": {
        "label": "FPE / IPI-Exp.",
        "dono": "Tesouro Nacional",
        "driver": "PIB + IPCA (arrecadação federal)",
        "modelo_pldo": "Fator PIB+IPCA",
        "frequencia": "Decendial (FPE)",
        "recorrente": True,
        "grupo": "Transferências",
    },
    "rpps": {
        "label": "Contribuições RPPS",
        "dono": "RIOPREVIDÊNCIA",
        "driver": "Folha, planos segregados",
        "modelo_pldo": "Atuarial",
        "frequencia": "Mensal",
        "recorrente": True,
        "grupo": "Contribuições",
    },
    "outras_correntes": {
        "label": "Outras receitas correntes",
        "dono": "Diversos",
        "driver": "IPCA (recomposição real)",
        "modelo_pldo": "Indexação",
        "frequencia": "Mensal",
        "recorrente": True,
        "grupo": "Outras correntes",
    },
    # --- NÃO RECORRENTES / EVENTUAIS (fora da projeção-base; cadastradas) ---
    "lc194_2022": {
        "label": "Compensação LC nº 194/2022",
        "dono": "STN",
        "driver": "Cronograma legal (R$ 3,6 bi em 3 anos)",
        "modelo_pldo": "Valor fixo cronograma",
        "frequencia": "Anual",
        "recorrente": False,
        "grupo": "Não recorrente",
    },
    "op_credito": {
        "label": "Operações de crédito / alienação de bens",
        "dono": "SEFAZ / SUBTES",
        "driver": "Eventual",
        "modelo_pldo": "Eventual",
        "frequencia": "Eventual",
        "recorrente": False,
        "grupo": "Não recorrente",
    },
    "divida_ativa": {
        "label": "Recuperação de dívida ativa",
        "dono": "PGE",
        "driver": "Esforço de cobrança",
        "modelo_pldo": "Eventual",
        "frequencia": "Mensal (volátil)",
        "recorrente": False,
        "grupo": "Não recorrente",
    },
}

# ---------------------------------------------------------------------------
# 3) BASELINE 2026 (R$ bi) — [CALIBRACAO-PROTOTIPO]
#    Valores de partida do protótipo. O PLDO deu razões, não todos os
#    absolutos; estes números são internamente consistentes e devem ser
#    SUBSTITUÍDOS pelos valores oficiais do RREO/RGF na fundação de dados.
#    A calibração (receita.py) ajusta pessoal e estoque de dívida para
#    reproduzir as razões do PLDO no cenário-base.
# ---------------------------------------------------------------------------
BASELINE_2026 = {
    # rubrica -> R$ bi em 2026
    "icms": 52.0,
    "fecp": 2.60,
    "ipva": 6.50,
    "itd": 1.20,
    "irrf": 7.00,
    "royalties_pe": 30.70,      # com Brent/câmbio/produção nas âncoras => 30,7 em 2027
    "fpe_ipiexp": 5.50,
    "rpps": 9.00,
    "outras_correntes": 12.20,
    # não recorrentes (informativo; não entram na base recorrente)
    "lc194_2022": 1.20,
    "op_credito": 0.0,
    "divida_ativa": 1.50,
    "_fonte": "[CALIBRACAO-PROTOTIPO] — substituir por RREO/RGF oficial",
}

# Parcela das receitas correntes deduzida para chegar à RCL
# (transf. constitucionais a municípios, dedução FUNDEB, etc.).
# [CALIBRACAO-PROTOTIPO] — ajustar ao cálculo normativo do RGF.
FATOR_DEDUCAO_RCL = 0.235   # ~23,5% de deduções sobre receita corrente bruta

# ---------------------------------------------------------------------------
# 4) ELASTICIDADES / FATORES DE PROJEÇÃO POR RUBRICA
#    Cada rubrica declara COMO responde aos drivers. Documentado e revisável.
#    Nomeclatura: e_<driver> = elasticidade (var. % receita / var. % driver)
#    ou passthrough direto quando indicado.
# ---------------------------------------------------------------------------
ELASTICIDADES = {
    "icms": {
        # crescimento nominal ~ e_pib*PIB_real + passthrough IPCA (efeito preço)
        "e_pib_real": 1.10,
        "passthrough_ipca": 0.90,
        "e_cambio": 0.05,   # câmbio afeta base de importados
        "fonte": "Modelo exógeno PLDO (IBC-Br+câmbio) — elasticidades [VALIDAR-SEFAZ]",
    },
    "fecp": {"prop_icms": None},  # None => recalculado como razão fixa do ICMS base
    "ipva": {
        "e_pib_real": 0.60,
        "passthrough_ipca": 0.70,   # valor venal da frota
        "fonte": "Híbrido ARIMA+IBC-Br [VALIDAR-SEFAZ]",
    },
    "itd": {
        "e_pib_real": 1.00,
        "passthrough_ipca": 0.80,
        "fonte": "Atividade econômica [VALIDAR-SEFAZ]",
    },
    "irrf": {
        "fator_vegetativo": 0.0344,  # 3,44% a.a. crescimento da folha (PLDO)
        "fonte": "Crescimento vegetativo da folha 3,44% (PLDO)",
    },
    "royalties_pe": {
        # R&PE_t = base * (Brent_t/Brent_ref) * (cambio_t/cambio_ref) * prod_t
        "brent_ref": 79.25,
        "cambio_ref": 5.50,
        "fonte": "Estimativa ANP + preço/câmbio (ACT ANP nº 01/15)",
    },
    "fpe_ipiexp": {
        # cresce com arrecadação federal ~ PIB_real + IPCA
        "e_pib_real": 1.00,
        "passthrough_ipca": 1.00,
        "fonte": "Fator PIB+IPCA (Tesouro Nacional)",
    },
    "rpps": {
        "fator_vegetativo": 0.0344,  # acompanha folha
        "fonte": "Atuarial / folha [VALIDAR-RIOPREVIDENCIA]",
    },
    "outras_correntes": {
        "passthrough_ipca": 1.00,
        "fonte": "Indexação IPCA",
    },
}

# ---------------------------------------------------------------------------
# 5) CAPAG — faixas de corte  [VALIDAR-STN]
#    Nota final = PIOR componente domina (com regra de trava por liquidez).
#    ATENÇÃO: valores de referência. LER da portaria STN vigente e
#    RECONCILIAR contra a nota oficial publicada. CAPAG não vem do PLDO.
# ---------------------------------------------------------------------------
CAPAG_FAIXAS = {
    "endividamento": {   # Dívida Consolidada / RCL  (menor = melhor)
        "label": "Endividamento (DC/RCL)",
        "sentido": "menor_melhor",
        "faixas": [("A", 0.00, 0.60), ("B", 0.60, 1.50), ("C", 1.50, 99.0)],
        "status_validacao": "[VALIDAR-STN] faixas de referência — ler portaria vigente",
    },
    "poupanca": {        # Despesa Corrente / Receita Corrente Ajustada
        "label": "Poupança corrente (DespCorr/RecCorrAjust)",
        "sentido": "menor_melhor",
        "faixas": [("A", 0.00, 0.90), ("B", 0.90, 0.95), ("C", 0.95, 99.0)],
        "status_validacao": "[VALIDAR-STN] faixas de referência",
    },
    "liquidez": {        # Obrigações Financeiras / Disponibilidade de Caixa Bruta
        "label": "Liquidez (ObrigFin/CaixaBruto)",
        "sentido": "menor_melhor",
        "faixas": [("A", 0.00, 1.00), ("C", 1.00, 99.0)],
        "status_validacao": "[VALIDAR-STN] abaixo de 1,0 indica caixa suficiente",
    },
}
# Regra de combinação: C em endividamento OU poupança rebaixa para D;
# liquidez >= 1,0 (rating C) trava a nota em no máximo C.
CAPAG_REGRA = (
    "Nota final pelo pior indicador. Endividamento=C ou Poupança=C ⇒ D. "
    "Liquidez insuficiente (≥1,0) limita a nota a C. [VALIDAR-STN]"
)

# ---------------------------------------------------------------------------
# 6) ÍNDICE PROPAG (composto, 0–100) — pesos  [VALIDAR-COMITE]
#    LC nº 212/2025. ERJ optou por amortização extraordinária de 20% do
#    estoque ⇒ contrapartidas 1% FEF + 1% investimentos (combinação mais leve),
#    CONDICIONADA à aceitação do ativo ofertado (FNDR — único ativo, não
#    analisado). Rejeição eleva contrapartidas para até 2%/2%.
# ---------------------------------------------------------------------------
PROPAG = {
    "amortizacao_extraordinaria": 0.20,    # 20% do estoque
    "contrapartida_fef": 0.01,             # 1% (sobe p/ 2% se ativo rejeitado)
    "contrapartida_investimento": 0.01,    # 1% (sobe p/ 2% se ativo rejeitado)
    "contrapartida_fef_rejeitado": 0.02,
    "contrapartida_inv_rejeitado": 0.02,
    "pesos": {   # somam 1,00 — declarados e revisáveis pelo comitê
        "cobertura_fef": 0.25,
        "aderencia_investimento": 0.20,
        "risco_ativo_fndr": 0.25,
        "folga_servico_divida": 0.20,
        "sensibilidade_ipca": 0.10,
    },
    "status_validacao": "[VALIDAR-COMITE] pesos e composição do índice",
    "semaforo_fndr": {"aceito": 100, "parcial": 50, "rejeitado": 0},
}

# ---------------------------------------------------------------------------
# 7) LIMITES LRF / VINCULAÇÕES  [VALIDAR-JURIDICO]
# ---------------------------------------------------------------------------
LRF = {
    "pessoal_rcl_teto": 0.60,        # 60% RCL (Poder Executivo — art. 20 LRF)
    "pessoal_rcl_alerta": 0.54,      # 90% do teto (limite de alerta)
    "pessoal_rcl_prudencial": 0.57,  # 95% do teto (limite prudencial)
    "saude_min": 0.12,               # 12% (EC 29)
    "educacao_min": 0.25,            # 25% (art. 212 CF)
    "dcl_rcl_teto": 2.00,            # 200% RCL (Res. SF nº 40/2001)
    "obs_rrf": (
        "ERJ em RRF e em adesão ao Propag: aplicabilidade e cronograma de "
        "reenquadramento têm tratamento próprio. [VALIDAR-JURIDICO]"
    ),
}

# Razões-âncora do PLDO 2027 usadas na CALIBRAÇÃO do baseline (cenário-base
# deve reproduzi-las). Ver receita.py::calibrar().
ANCORAS_PLDO_2027 = {
    "pessoal_sobre_rcl": 0.6857,   # 68,57% da RCL (acima do teto de 60%)
    "dc_sobre_rcl": 2.63,          # Dívida Consolidada = 263% da RCL
    "dcl_sobre_rcl": 2.77,         # Dívida Consolidada Líquida = 277% da RCL
    "royalties_pe_2027": 30.7,     # R$ ~30,7 bi (referência de magnitude)
    "peso_icms_petroleo": 0.6667,  # ICMS + petróleo ~ 2/3 da receita
}

# ---------------------------------------------------------------------------
# 8) CENÁRIO ADVERSO DE FÁBRICA — ACO nº 3.678  (nomeado pela Fazenda)
# ---------------------------------------------------------------------------
CENARIO_ACO_3678 = {
    "nome": "Adverso — ACO nº 3.678 (não manutenção da liminar)",
    "descricao": (
        "Não manutenção da liminar da ACO nº 3.678: exclusão do RRF e não "
        "formalização do contrato no âmbito do Propag. Serviço da dívida "
        "sobe R$ 11,7 bi em 2027."
    ),
    "choque_servico_divida_2027": 11.7,   # R$ bi adicionais
    "propag_ativo": False,                # contrato não formalizado
    "fonte": "PLDO 2027 — risco fiscal dominante nomeado pela SEFAZ/RJ",
}

# ===========================================================================
# 9) INTEGRAÇÃO COM O BANCO (execução de DESPESA — tabela painel_subor)
#    Conecta o lado da despesa (SIAFE) para substituir as premissas
#    [CALIBRACAO-PROTOTIPO] por execução real e atualizar os índices.
#    Credenciais NÃO ficam aqui — vão em .streamlit/secrets.toml ou env vars
#    (ver engine/db.py). Aqui ficam só nome da tabela e mapeamentos.
# ===========================================================================
DB_TABELA = "painel_subor"

# Escala: os valores da tabela estão em REAIS; o motor trabalha em R$ bilhões.
# Ajuste se a sua base já estiver em milhares/milhões.
DB_ESCALA_PARA_BI = 1e-9   # reais -> R$ bi   (use 1e-6 se estiver em milhares)

# Métrica de execução usada como "realizado" nos índices.
# Opções: "Empenhado", "Liquidado", "Pago". Também exposta como controle na UI.
DB_METRICA_PADRAO = "Empenhado"

# Mapa lógico -> nome FÍSICO da coluna em painel_subor.
# Nomes com espaço/acento são citados com crase (`) no SQL (ver db.py).
# Se algum nome divergir, rode scripts/descobrir_dominios.py e ajuste aqui.
COLS = {
    "cod_gd": "Cod GD",
    "tit_gd": "Tit GD",
    "cod_uo": "Cod UO",
    "tit_uo": "Tit UO",
    "funcao": "Função",
    "tit_funcao": "Tit Função",
    "cod_poder": "Cod Poder",
    "tit_poder": "Tit Poder",
    "tipo_despesa": "tipo_despesa",
    "fr_resultado": "fr_resultado",
    "dot_inicial": "Dot. Inicial",
    "dot_atual": "Dot. Atual",
    "despesa_autorizada": "Despesa Autorizada",
    "empenhado": "Empenhado",
    "liquidado": "Liquidado",
    "pago": "Pago",
    "ano": "ano",
    "mes": "mes",
}

# Mapa Grupo de Despesa (GND) -> categoria do motor.
# A classificação usa o 1º dígito do "Cod GD" (padrão GND 1..6):
#   1 Pessoal e Encargos | 2 Juros e Encargos da Dívida | 3 Outras Desp. Correntes
#   4 Investimentos | 5 Inversões Financeiras | 6 Amortização da Dívida
# Se a sua base codificar diferente, ajuste MAPA_GD_POR_DIGITO.
MAPA_GD_POR_DIGITO = {
    "1": "pessoal",
    "2": "juros",
    "3": "custeio",
    "4": "investimento",
    "5": "inversoes",
    "6": "amortizacao",
}
# Correntes x capital (para poupança do CAPAG e serviço da dívida)
CATEGORIAS_CORRENTES = ["pessoal", "juros", "custeio"]
CATEGORIAS_CAPITAL = ["investimento", "inversoes", "amortizacao"]
# Serviço da dívida = juros (corrente) + amortização (capital)
CATEGORIAS_SERVICO_DIVIDA = ["juros", "amortizacao"]

DB_STATUS_VALIDACAO = (
    "[VALIDAR-SEFAZ] Confirmar métrica de execução (Empenhado/Liquidado/Pago), "
    "escala dos valores e o mapeamento de Grupo de Despesa (GND)."
)
