# Subir o Controle Financeiro 3.0 online

Passo a passo completo, do zero ao sistema no ar, no mesmo arranjo do SICAD 3.0:
**Neon** (banco) + **Render** (servidor) + **GitHub** (código) + **Google Cloud**
(planilha espelho).

Tempo: cerca de 1 h na primeira vez. Custo: R$ 0 — tudo em plano gratuito.

---

## Antes de começar

### A ordem importa

```
1. Neon          →  precisa existir antes de tudo (gera a DATABASE_URL)
2. Carga         →  schema + usuário + histórico, rodando DO SEU MAC
3. GitHub        →  o Render só publica a partir de um repositório
4. Render        →  aponta para o repo e recebe a DATABASE_URL
5. Primeiro acesso e conferência
6. Google Cloud  →  planilha espelho (pode ficar para depois)
7. Anti-hibernação
```

Fazer a carga (passo 2) **antes** do Render é de propósito: o plano free do Render
**não dá acesso a shell**, então não há como rodar `criar_schema.py` lá dentro. O
banco tem de chegar pronto.

### Duas decisões suas, agora

**1. O repositório tem de ser PRIVADO.**

O do SICAD é público, mas este não pode ser. O arquivo `core/categorizacao.py`
tem, embutidos nas regras, **nomes reais de sete pessoas**: o inquilino do FLAT,
o escritório de advocacia, seu pai, a diarista, a cozinheira, a psicóloga e um
familiar. Publicar isso expõe dados de terceiros que nunca consentiram — e o caso
da psicóloga permite inferir informação de saúde.

O Render free publica de repositório privado sem custo. É um clique na criação.

> Se algum dia quiser tornar público, antes tire esses nomes do código: as regras
> já vivem na tabela `regras` do banco, então basta deixar em `REGRAS_PADRAO` só
> as genéricas (mercados, apps, transporte) e cadastrar as pessoais pela tela.

**2. Onde vai rodar a carga.** No seu Mac, com o venv que já existe em
`~/.venvs/financas-web`. Todos os comandos abaixo assumem isso.

### O que você vai precisar criar

Quatro contas **novas**, separadas das do SICAD, como você decidiu:

| Serviço | Para quê |
|---|---|
| [neon.tech](https://neon.tech) | banco Postgres |
| [github.com](https://github.com) | repositório privado |
| [render.com](https://render.com) | servidor web |
| [console.cloud.google.com](https://console.cloud.google.com) | conta de serviço da planilha |

---

## Etapa 1 — Banco no Neon

1. Entre em <https://neon.tech> e crie a conta (dá para entrar com Google —
   **use a conta Google nova**, não a do SICAD).
2. **Create project**:
   - *Project name*: `financas`
   - *Postgres version*: 16 ou mais nova
   - *Region*: **AWS US East (Ohio)** ou **N. Virginia** — as mais próximas dos
     servidores free do Render. Região distante soma latência em toda requisição.
3. Na tela que aparece depois de criar, procure **Connection string** e escolha o
   dropdown **Connection pooling → habilitado** e o modo **psycopg**.
   A string tem esta cara:

   ```
   postgresql://financas_owner:AbC123xyz@ep-nome-12345-pooler.us-east-2.aws.neon.tech/financas?sslmode=require
   ```

   > Use a do **pooler** (tem `-pooler` no host). Ela existe justamente para
   > absorver muitas conexões, e é o que o Render precisa.

4. Copie e guarde. Ela é a senha do seu banco — não cole em chat, issue ou
   commit.

### Guardar no `.env` local

```bash
cd "$HOME/Library/CloudStorage/GoogleDrive-vr.alencar@gmail.com/Meu Drive/_Claude-VR/Sistema Financeiro/financas-web" && cp -n .env.exemplo .env && open -e .env
```

Preencha:

```
DATABASE_URL=postgresql://...   (a string do Neon, colada inteira)
SECRET_KEY=qualquer-frase-longa-para-uso-local
COOKIE_SEGURO=0
SENHA_PDF_SANTANDER=   (o CPF do titular do cartão — a senha dos PDFs; não fica neste guia)
```

> `COOKIE_SEGURO=0` **só no local**. Com `1`, o navegador exige https e descarta o
> cookie em `127.0.0.1` — o login parece funcionar e nunca entra.

---

## Etapa 2 — Carregar o banco (do seu Mac)

### 2.1 Criar as tabelas

```bash
cd "$HOME/Library/CloudStorage/GoogleDrive-vr.alencar@gmail.com/Meu Drive/_Claude-VR/Sistema Financeiro/financas-web" && ~/.venvs/financas-web/bin/python scripts/criar_schema.py
```

Esperado:

```
Schema criado/atualizado.
Contas: 4
Regras: 38 inseridas.
OK — Conectado ao banco 'financas'.
```

É idempotente: rodar de novo não estraga nada.

### 2.2 Criar o seu usuário

```bash
~/.venvs/financas-web/bin/python scripts/criar_usuario.py vr.alencar@gmail.com "Vitor"
```

Nasce **sem senha** — você define na tela, no Primeiro Acesso. Nenhuma senha
passa por script nem por terminal.

> Aqui use um e-mail de verdade, não `admin`. O `admin`/`admin` existe só na
> maquete local e não deve chegar a um servidor exposto na internet.

### 2.3 Levar o histórico de 2026

```bash
~/.venvs/financas-web/bin/python scripts/migrar_da_planilha.py "$HOME/Library/CloudStorage/GoogleDrive-vr.alencar@gmail.com/Meu Drive/_Controle Financeiro/Controle Financeiro 2.0.xlsx"
```

Esperado: `Inseridos: 1874` e `Resumos de fatura gravados: 7`.

### 2.4 Conferir localmente antes de publicar

```bash
COOKIE_SEGURO=0 PORT=8800 bash run_dev.sh
```

Abra <http://127.0.0.1:8800>, faça o Primeiro Acesso e confira o Painel. **Não
siga adiante se isto não funcionar** — depurar no Render é muito pior.

---

## Etapa 3 — GitHub (repositório privado)

1. Em <https://github.com>, crie a conta nova.
2. **New repository**:
   - *Name*: `financas-web`
   - **Private** ← obrigatório, pelo motivo explicado no começo
   - Não marque "Add a README" (já existe um)

3. No seu Mac:

```bash
cd "$HOME/Library/CloudStorage/GoogleDrive-vr.alencar@gmail.com/Meu Drive/_Claude-VR/Sistema Financeiro/financas-web" && git init -b main
```

**Confira o que vai subir antes do primeiro commit:**

```bash
git add -A && git status --short
```

Na lista **não pode** aparecer: `.env`, nenhum `.pdf`, nenhum `.csv` de extrato,
nenhum JSON de conta de serviço. Se aparecer, pare e me chame.

```bash
git commit -m "Controle Financeiro 3.0: primeira versão"
```

```bash
git remote add origin https://github.com/SEU-USUARIO/financas-web.git && git push -u origin main
```

---

## Etapa 4 — Render

1. Em <https://render.com>, crie a conta e conecte o GitHub novo. Autorize o
   acesso ao repositório `financas-web`.
2. **New → Blueprint** → escolha o repositório. O Render lê o `render.yaml` e
   propõe um serviço chamado `financas`.
3. Ele vai pedir os valores das variáveis marcadas com `sync: false`. Preencha:

| Variável | Valor | Obrigatória |
|---|---|---|
| `DATABASE_URL` | a string do Neon (a mesma do `.env`) | **sim** |
| `SENHA_PDF_SANTANDER` | o CPF do titular (o mesmo do `.env` local) | para ler fatura Santander em PDF |
| `GCP_SERVICE_ACCOUNT_JSON` | deixe vazio por ora (Etapa 6) | não |
| `PLANILHA_ESPELHO_ID` | deixe vazio por ora (Etapa 6) | não |

`SECRET_KEY` o Render gera sozinho (`generateValue: true`) e `COOKIE_SEGURO` já
vem como `1` no blueprint — é o certo em produção, porque lá é https.

4. **Apply** / **Create**. O primeiro build leva 2–4 min. Acompanhe em *Logs*.

### Conferir que subiu

A URL fica parecida com `https://financas-XXXX.onrender.com`. Teste:

```bash
curl -s https://SUA-URL.onrender.com/health
```

Esperado: `{"ok":true,"app":"Controle Financeiro","versao":"3.0"}`

---

## Etapa 5 — Primeiro acesso em produção

1. Abra `https://SUA-URL.onrender.com`.
2. Informe o e-mail que você cadastrou no passo 2.2 e **qualquer senha**.
3. O sistema reconhece que a conta não tem senha e troca para *Criar sua senha*.
   Mínimo de 8 caracteres. Escolha uma senha forte e única — este endereço é
   público na internet, e é o seu histórico financeiro que está atrás dele.
4. Confira: Painel com os números de ago/26, e a Conciliação acusando
   `importação incompleta` em jul/26 (os R$ 726,52 de juros).

> **A primeira visita do dia demora.** O plano free do Render hiberna o serviço
> após ~15 min sem acesso, e acordar leva 30–60 s. O Neon também dorme, mas
> acorda em ~1 s (o `core/bd.py` já faz a retentativa que cobre isso).

---

## Etapa 6 — Planilha espelho no Google

Pode ser feita depois; o sistema funciona inteiro sem ela, só não escreve na
planilha.

### 6.1 Projeto e APIs

1. Entre em <https://console.cloud.google.com> **com a conta Google nova**.
2. Crie um projeto: `financas-espelho`.
3. *APIs e serviços → Biblioteca* → ative as duas:
   - **Google Sheets API**
   - **Google Drive API**

### 6.2 Conta de serviço

1. *IAM e administrador → Contas de serviço → Criar conta de serviço*
   - Nome: `espelho-financas`
   - Não precisa conceder papel nenhum no projeto (o acesso vem do
     compartilhamento da planilha, não do IAM).
2. Na conta criada: aba **Chaves → Adicionar chave → Criar nova chave → JSON**.
   Baixa um arquivo.
3. Abra o JSON e localize o campo `client_email` — algo como
   `espelho-financas@financas-espelho.iam.gserviceaccount.com`. **Guarde esse
   endereço.**

### 6.3 A planilha

1. No Drive **da conta nova**, crie uma planilha vazia: `Controle Financeiro — Espelho`.
2. Copie o id da URL — o trecho entre `/d/` e `/edit`.
3. **Compartilhe a planilha como Editor com o `client_email`** do passo anterior.
   Sem isso o Google devolve 403, e a mensagem não é óbvia.

### 6.4 Configurar no Render

Em *Environment*, preencha:

- `PLANILHA_ESPELHO_ID` → o id da planilha
- `GCP_SERVICE_ACCOUNT_JSON` → **o conteúdo inteiro do JSON, em uma linha só**

Para transformar o arquivo em uma linha:

```bash
python3 -c "import json,sys;print(json.dumps(json.load(open(sys.argv[1]))))" ~/Downloads/financas-espelho-*.json | pbcopy
```

Isso põe o JSON compactado na área de transferência — cole no campo do Render.
Salvar as variáveis reinicia o serviço sozinho.

### 6.5 Testar

No sistema: **Espelho e diagnóstico**. Deve dizer
`Conectado à planilha 'Controle Financeiro — Espelho'`. Clique em
**Reescrever a planilha agora** e confira que apareceram as 5 abas: Lançamentos,
Resumo de Faturas, Conciliação, Dashboard e Importações.

> O espelho é **só de saída**: a planilha nunca alimenta o sistema de volta.
> Editar algo lá é inútil — a próxima sincronização reescreve.

---

## Etapa 7 — Anti-hibernação (opcional)

Para não esperar 30–60 s na primeira visita do dia:

1. Crie conta em <https://uptimerobot.com> (free, 50 monitores).
2. **Add New Monitor**:
   - *Type*: HTTP(s)
   - *URL*: `https://SUA-URL.onrender.com/health`
   - *Interval*: 5 minutos

O `/health` não exige login e não devolve dado nenhum — só diz que o processo
está de pé.

> Atenção ao limite: o free do Render dá **750 h/mês somadas em todos os
> serviços**. Um serviço só, pingado 24/7, consome ~720 h — cabe. Dois serviços
> acordados o tempo todo, não (lição já aprendida no SICAD).

---

## O ciclo do mês, depois de tudo no ar

1. Baixe do banco: CSV da fatura do Nubank, PDF da fatura do Santander, extratos.
2. Abra o sistema → **Importar arquivos** → arraste tudo de uma vez.
3. Confira o resultado da importação e a aba **Conciliação**.
4. **Espelhar na planilha**, se quiser a planilha atualizada.

Reimportar o mesmo arquivo é inofensivo: linha repetida é reconhecida e ignorada.

---

## Manutenção

### Publicar uma alteração no código

```bash
git add -A && git commit -m "descrição em português, do ponto de vista de quem usa" && git push
```

O Render detecta o push e republica sozinho. Diferente do SICAD, aqui há **uma
branch só** (`main`) — não existe o par Produção/Admin, então não há o risco de
esquecer a segunda branch.

### Mudança de schema

O Render **não** roda migração. Sempre nesta ordem:

1. Rode o script de schema do seu Mac, apontando para o Neon;
2. só depois faça o push do código que depende da mudança.

Inverter a ordem deixa o sistema no ar consultando coluna que não existe.

### Backup

O Neon free mantém histórico de 24 h (point-in-time restore). Para um backup seu,
rodando **de dentro da pasta do projeto** (ele lê a `DATABASE_URL` do `.env`):

```bash
~/.venvs/financas-web/bin/python -c "
import os, csv, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from core import repositorio
linhas = repositorio.listar_lancamentos(limite=100000)
destino = os.path.expanduser('~/Desktop/backup-lancamentos.csv')
with open(destino, 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(linhas[0].keys()))
    w.writeheader(); w.writerows(linhas)
print(len(linhas), 'linhas salvas em', destino)"
```

Testado na maquete: exportou as 1.874 linhas.

---

## Quando algo der errado

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Login diz "Banco de dados não configurado" | `DATABASE_URL` ausente ou vazia no Render | confira em *Environment*; salvar reinicia o serviço |
| `Could not parse URL` nos logs | string do Neon colada com aspas, espaço ou o prefixo `psql ` | o `core/bd.py` tolera os casos comuns; se persistir, cole de novo limpa |
| Login "funciona" mas volta para a tela de entrada | `COOKIE_SEGURO=1` em ambiente http, ou `0` em https | produção = `1`; local = `0` |
| Primeira visita demora ~40 s | hibernação do plano free | normal; Etapa 7 resolve |
| Espelho: "Sem permissão na planilha" | planilha não compartilhada com a conta de serviço | compartilhe como **Editor** com o `client_email` |
| Espelho: "não é um JSON válido" | JSON colado com quebras de linha | recole usando o comando do passo 6.4 |
| Fatura Santander em PDF não abre | `SENHA_PDF_SANTANDER` ausente | preencha no Render |
| Conciliação diz "importação incompleta" | é o sistema funcionando: falta lançamento | veja a coluna *Δ importação* — ela diz quanto |
| Importei e nada apareceu | mês selecionado é outro | troque o mês no seletor do topo |

Para ver o que o servidor está dizendo: no Render, aba **Logs**. Mensagem de erro
nunca contém a senha do banco — o `sanitizar_erro` remove.

---

## O que nunca pode ir para o Git

Já está tudo no `.gitignore`, mas vale saber o motivo:

- `.env` — tem a `DATABASE_URL` e a senha dos PDFs;
- qualquer `*service_account*.json` — é chave privada;
- `Nubank_*.csv`, `NU_*.pdf`, `*Santander*.pdf` — extratos e faturas;
- `.pytest_cache/`, `__pycache__/` — lixo de execução.

Confira sempre com `git status --short` antes do commit.

---

## Uma ressalva honesta

Nunca publiquei este sistema. O código foi verificado por 48 testes e rodou
inteiro numa maquete local com PostgreSQL de verdade e os seus 1.874 lançamentos
— mas Neon, Render e a conta de serviço do Google são ambientes que este projeto
ainda não conheceu. Espere um ou dois ajustes na primeira subida, principalmente
em caminho de variável de ambiente e permissão da planilha.

Se travar em algum passo, me diga **em qual** e o que apareceu na tela ou no log —
com isso eu chego direto na causa.
