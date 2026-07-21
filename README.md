# Simulador Orçamentário — Estado do Rio de Janeiro (PLDO 2027)

Protótipo funcional **com motor de cálculo real** para simulação de alocação
orçamentária do ERJ, ancorado nos números e metodologias declarados no **PLDO 2027**.

## O que ele faz

- Projeta **receita por rubrica** (ICMS, FECP, IPVA, ITD, IRRF, Royalties & PE,
  FPE/IPI-Exp, RPPS, outras) a partir de drivers macro, com os drivers declarados
  no PLDO (ICMS~IBC-Br/câmbio, R&PE~Brent×câmbio×produção, FPE~PIB+IPCA, IRRF
  vegetativo 3,44%…), separando **receita recorrente × não recorrente**.
- Calcula **CAPAG simulado** (3 indicadores: endividamento, poupança corrente,
  liquidez; nota pelo pior). *O CAPAG não é publicado no PLDO* — é calculado aqui
  e deve ser reconciliado contra a nota oficial da STN.
- Calcula o **Índice de adesão sustentável ao Propag** (composto, 0–100, 5
  subindicadores) — LC nº 212/2025, com semáforo do ativo FNDR.
- Verifica **limites da LRF e vinculações** (pessoal/RCL, DCL/RCL, saúde 12%,
  educação 25%).
- **Cenários lado a lado**: base, otimista, pessimista e o **adverso de fábrica
  ACO nº 3.678** (+R$ 11,7 bi no serviço da dívida em 2027).
- Sliders de drivers com **âncora, fonte e SLA de frescor** visíveis.

## Calibração

O PLDO fornece **razões** (pessoal 68,57% da RCL; DC 263%; DCL 277%; R&PE ~R$ 30,7 bi)
mas não todos os **absolutos**. O motor calibra a base 2026 para que o
**cenário-base reproduza exatamente** essas razões (ver `engine/receita.py::calibrar`).
Os valores absolutos do baseline estão marcados `[CALIBRACAO-PROTOTIPO]` e devem
ser substituídos pelos oficiais do **RREO/RGF**.

## Estrutura

```
engine/
  config.py       # Fonte única de premissas: âncoras macro, fichas de fonte,
                  # faixas CAPAG [VALIDAR-STN], pesos Propag [VALIDAR-COMITE], LRF.
  receita.py      # Projeção por rubrica + calibração às razões do PLDO.
  indicadores.py  # CAPAG, Índice Propag, LRF, qualidade da receita.
  cenarios.py     # Orquestra cenários (base/otimista/pessimista/ACO 3.678).
app.py            # Painel Streamlit (6 abas).
smoke_test.py     # Valida a calibração contra o PLDO.
```

## Como rodar

```bash
pip install -r requirements.txt
streamlit run app.py
```

Validar o motor sem UI:

```bash
python smoke_test.py
```

## Ressalvas (governança de modelos)

Ferramenta de **apoio à decisão** — implementa premissas, não as decide.
Pendências marcadas no código e na aba *Fontes & Governança*:

- `[VALIDAR-STN]` faixas do CAPAG — ler portaria vigente e reconciliar.
- `[VALIDAR-COMITE]` pesos do índice Propag.
- `[VALIDAR-JURIDICO]` aplicabilidade dos limites LRF sob RRF/Propag.
- `[VALIDAR-SEFAZ]` elasticidades de receita por tributo.
- Confirmar se este PLDO é a **versão vigente** (metas podem mudar na PLOA 2027
  se a adesão ao Propag se concretizar).
