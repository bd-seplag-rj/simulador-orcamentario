# Integração com o banco (execução de despesa — `painel_subor`)

Este guia conecta o dashboard à sua base MySQL/MariaDB (phpMyAdmin) para
substituir as premissas de despesa `[CALIBRACAO-PROTOTIPO]` pela **execução real**
da tabela `painel_subor` e **atualizar os índices** (Pessoal/RCL, poupança do
CAPAG, serviço da dívida, saldo primário do Propag, Bloco 5 de execução).

O lado da **receita** continua projetado a partir do PLDO 2027 (o `painel_subor`
é de despesa). Se você tiver uma tabela de receita realizada, dá para integrá-la
depois no mesmo padrão.

---

## 1. Instalar dependências

```bash
pip install -r requirements.txt
```

Inclui `SQLAlchemy` e `PyMySQL` (driver Python puro, sem compilação no Windows).

## 2. Configurar as credenciais (somente leitura)

Use um usuário do banco com **apenas `SELECT`**. Há dois caminhos:

**a) `.streamlit/secrets.toml`** (recomendado). Copie o exemplo e preencha:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

```toml
[mysql]
host = "localhost"      # host/IP do servidor MySQL (o mesmo que o phpMyAdmin acessa)
port = 3306
database = "nome_do_banco"
user = "consulta"
password = "SUA_SENHA"
table = "painel_subor"
```

> O arquivo `secrets.toml` está no `.gitignore` — não é versionado.

**b) Variáveis de ambiente** (alternativa, útil em servidor):

```bash
export SIMULADOR_DB_HOST=...   SIMULADOR_DB_PORT=3306
export SIMULADOR_DB_NAME=...   SIMULADOR_DB_USER=consulta
export SIMULADOR_DB_PASSWORD=...
```

> **Host:** se o MySQL só aceita conexão local, rode o dashboard na mesma máquina
> do banco. Para acesso remoto, o usuário precisa ter permissão de conexão a
> partir do seu IP e a porta 3306 precisa estar liberada.

## 3. Testar a conexão

```bash
python scripts/testar_conexao.py
```

Deve imprimir o total de linhas e os anos disponíveis.

## 4. Conferir os mapeamentos

```bash
python scripts/descobrir_dominios.py
```

Isso lista as **colunas reais**, os **Grupos de Despesa** (com a categoria que o
motor inferiu) e os **anos**. Verifique dois pontos em `engine/config.py`:

- **`COLS`** — se algum nome de coluna divergir do físico (espaços/acentos),
  ajuste o valor correspondente.
- **`MAPA_GD_POR_DIGITO`** — o motor classifica pelo 1º dígito do `Cod GD`
  (padrão GND: 1 Pessoal · 2 Juros · 3 Custeio · 4 Investimento · 5 Inversões ·
  6 Amortização). Se a coluna `categoria_mapeada` sair como `outros` para algum
  GND, ajuste o mapa.

Confira também, no `config.py`:

- **`DB_ESCALA_PARA_BI`** — o motor trabalha em **R$ bilhões**. Se os valores da
  tabela estão em reais, mantenha `1e-9`; se em milhares, use `1e-6`.
- **`DB_METRICA_PADRAO`** — `Empenhado` (padrão), `Liquidado` ou `Pago`.

## 5. Usar no dashboard

```bash
streamlit run app.py
```

Na barra lateral, ligue **“Usar execução real do banco”**, escolha o **ano-base**
e a **métrica**. O cabeçalho passa a mostrar `🟢 despesa: execução real`, a aba
**Execução (SIAFE)** exibe a despesa por GND/função/UO, e os índices das demais
abas passam a refletir os dados reais.

---

## Como cada campo alimenta os índices

| Campo `painel_subor` | Vira | Impacta |
|---|---|---|
| `Cod GD` = 1 (Pessoal) | despesa de pessoal | **Pessoal/RCL** (LRF), poupança (CAPAG) |
| `Cod GD` = 2 (Juros) | juros da dívida | despesa corrente, **serviço da dívida** |
| `Cod GD` = 3 (Custeio) | outras desp. correntes | poupança, **saldo primário** (Propag) |
| `Cod GD` = 4 (Investimento) | investimento | Bloco 5, aba Execução |
| `Cod GD` = 6 (Amortização) | amortização | **serviço da dívida** |
| `Empenhado`/`Liquidado`/`Pago` vs `Dot. Atual` | % execução | aba Execução |
| `Função` / `Cod UO` | agregações | execução por função/órgão |
| `ano` / `mes` | recorte temporal | ano-base da projeção |

A base do ano escolhido é projetada para 2027-2029 (pessoal pelo vegetativo
3,44%; custeio/investimento/amortização por IPCA; juros pela Selic) e o choque
do cenário ACO 3.678 soma ao serviço da dívida.

## Segurança

- Credenciais **nunca** ficam no código — só em `secrets.toml`/env, fora do git.
- Use usuário **somente leitura** (`SELECT`).
- Todas as consultas são parametrizadas e cacheadas por 10 min.

## Validação pendente

`[VALIDAR-SEFAZ]` confirmar métrica de execução, escala dos valores e o
mapeamento de Grupo de Despesa antes de usar em decisão.
