# Controle Financeiro 3.0

Sistema web do controle financeiro pessoal, no mesmo padrão do SICAD 3.0:
**FastAPI + Postgres (Neon) + interface estática em HTML/CSS/JS**, publicado no
**Render**, com **planilha do Google como espelho só de saída**.

O que ele resolve que a planilha sozinha não resolvia:

- lê a **fatura do Santander em PDF protegido por senha** (Apps Script não tem
  biblioteca de PDF e a conversão do Drive falha em arquivo criptografado);
- **importação incremental** — subir o mesmo arquivo duas vezes não duplica nada;
- **conciliação** que separa "diferença esperada" de "erro de importação".

> ⚠️ **Contas próprias.** Este projeto usa uma conta Google, um Neon, um Render e
> um GitHub **diferentes dos do SICAD**. Nenhuma credencial, ID de planilha ou
> conta de serviço do SICAD deve ser reaproveitada aqui. Tudo entra por variável
> de ambiente — não há ID nem segredo no código.

---

## 1. Estrutura

```
financas-web/
  main.py                    FastAPI: 25 rotas, sessão por cookie assinado
  core/
    config.py                ambiente e vocabulário (categorias, contas, sinais)
    bd.py                    engine do Neon, com retentativa do cold start
    repositorio.py           TODO o SQL, com allowlist de gravação
    parsers.py               CSV, XLSX, OFX e PDF (inclusive com senha)
    categorizacao.py         regras regex → categoria / item fixo / tipo
    importacao.py            deduplicação por multiplicidade
    conciliacao.py           gasto do mês × valor a pagar
    usuarios.py              login PBKDF2 e Primeiro Acesso
    espelho.py               escrita na planilha do Google (só saída)
  static/
    tema.css                 design system: tokens de cor, espaço, tipografia
    app.css                  componentes
    tema.js                  tema antes da primeira pintura
    login.html / login.js
    index.html / app.js      as sete telas
    graficos.js              gráficos em SVG, sem biblioteca
  scripts/
    criar_schema.py          DDL idempotente + contas + regras iniciais
    criar_usuario.py         cria o login (sem senha; você define na tela)
    migrar_da_planilha.py    carga do histórico de 2026 vindo do .xlsx
  tests/                     48 testes
  render.yaml                blueprint do Render
  run_dev.sh                 servidor local na porta 8800
```

---

## 2. Instalar

### 2.1 Banco (Neon)

1. Crie a conta no [neon.tech](https://neon.tech) e um projeto — sugestão de nome
   `financas`, região `aws-us-east-1` (a mais perto do Render free).
2. Copie a **connection string** (a do *pooler*, opção "psycopg").
3. Guarde no `.env` local e depois no Render:

```bash
cp .env.exemplo .env
```

### 2.2 Criar o schema e o usuário

```bash
python3 -m venv ~/.venvs/financas-web
~/.venvs/financas-web/bin/pip install -r requirements.txt
```

```bash
~/.venvs/financas-web/bin/python scripts/criar_schema.py
```

```bash
~/.venvs/financas-web/bin/python scripts/criar_usuario.py seu-email@exemplo.com "Vitor"
```

O usuário nasce **sem senha**: na tela de login, informe o e-mail e o sistema
oferece o Primeiro Acesso para você criar a sua. Nenhuma senha passa por script,
chat ou e-mail.

### 2.3 Carga do histórico

Leva os 1.874 lançamentos de jan–ago/2026 que já estão conferidos, mais os 7
resumos oficiais das faturas Santander:

```bash
~/.venvs/financas-web/bin/python scripts/migrar_da_planilha.py "$HOME/Library/CloudStorage/GoogleDrive-vr.alencar@gmail.com/Meu Drive/_Controle Financeiro/Controle Financeiro 2.0.xlsx"
```

É idempotente — usa a mesma chave de deduplicação da importação normal, então
rodar de novo não duplica.

### 2.4 Rodar local

```bash
bash run_dev.sh
```

Abre em <http://127.0.0.1:8800>. Deixe `COOKIE_SEGURO=0` no `.env` local: com `1`
o navegador exige https e descarta o cookie, e o login nunca "pega".

### 2.5 Planilha espelho (Google)

Na **conta Google nova**, não na do SICAD:

1. [console.cloud.google.com](https://console.cloud.google.com) → novo projeto
   (ex.: `financas-espelho`).
2. Ative a **Google Sheets API** e a **Google Drive API**.
3. *IAM e administrador → Contas de serviço* → criar → *Chaves* → **Adicionar
   chave → JSON**. Baixe o arquivo.
4. Cole o **conteúdo inteiro do JSON, em uma linha só**, em
   `GCP_SERVICE_ACCOUNT_JSON`.
5. Crie a planilha espelho no Drive dessa conta e ponha o id (o trecho entre
   `/d/` e `/edit`) em `PLANILHA_ESPELHO_ID`.
6. **Compartilhe a planilha como Editor com o `client_email` do JSON.** Sem isso
   o Google devolve 403 — a tela *Espelho e diagnóstico* mostra qual e-mail usar.

O sistema roda inteiro sem o espelho; só não escreve na planilha.

### 2.6 Publicar (GitHub + Render)

Na conta GitHub nova:

```bash
git init && git add -A && git commit -m "Controle Financeiro 3.0: primeira versão"
```

```bash
git remote add origin git@github.com:SEU-USUARIO/financas-web.git && git push -u origin main
```

No Render (conta nova): **New → Blueprint**, apontando para o repositório. O
`render.yaml` declara o serviço `financas` na branch `main` e lista as variáveis;
os valores você preenche no painel (`sync: false` = "pedir aqui, não versionar").

Depois do primeiro deploy, rode `criar_schema.py` e `criar_usuario.py` apontando
a `DATABASE_URL` para o Neon — o Render não roda script de migração sozinho.

> O repositório pode ficar público, como o do SICAD. O `.gitignore` já barra
> `.env`, JSON de conta de serviço e **todo arquivo de extrato ou fatura** —
> fatura de cartão não vai para o Git.

---

## 3. O ciclo do mês

1. **Importar arquivos** → arraste o que baixou do banco. Aceita:

   | Formato | Origem | Observação |
   |---|---|---|
   | `.csv` `date,title,amount` | fatura Nubank | competência vem do nome `Nubank_AAAA-MM-DD.csv` |
   | `.csv` / `.ofx` | extrato de conta | competência = mês da data |
   | `.pdf` | fatura Santander | **abre com a senha** de `SENHA_PDF_SANTANDER` |
   | `.pdf` | fatura/extrato Nubank | funciona, mas prefira o CSV: é exato |
   | `.xlsx` | exportações diversas | detecta as colunas pelo cabeçalho |

   O nome do arquivo precisa deixar claro a conta — conter "Nubank" ou
   "Santander". Se não der para deduzir, a importação para e diz isso.

2. **Conciliação** → olhe a coluna *Situação*.
3. **Espelhar na planilha** → botão no topo, quando quiser a planilha atualizada.

---

## 4. As três decisões que sustentam o sistema

### Deduplicação por multiplicidade, garantida pelo banco

A tabela `lancamentos` tem `UNIQUE (chave, ocorrencia)`, onde `chave` é
`conta + competência + dia + descrição + centavos` e `ocorrencia` é 1, 2, 3… para
repetições da mesma chave.

Não é preciosismo: na fatura de ago/2026 existem **duas** cobranças idênticas de
`Google Workspace_sicad 50,00` em 29/07, duas de `Anthropic 20,76` e duas de
`IOF 0,72` em 25/07 — todas legítimas. Medido nos dados reais:

- por multiplicidade: reimportar o CSV insere **0**;
- por presença ("já existe uma igual? pula"): insere **3**, R$ 71,48 de gasto que
  nunca existiu, a cada reimportação.

Como a garantia é uma *constraint*, nem importação simultânea nem bug futuro no
Python conseguem duplicar.

### O sistema mede gasto do mês; o app do banco mede valor a pagar

```
Total a pagar = Saldo anterior + Despesas + Encargos − Créditos − Pagamentos
```

Conferido ao centavo nas 7 faturas Santander de 2026. Em jul/2026 o app mostrava
R$ 13.731,69 e o gasto do mês foi R$ 9.216,26, porque R$ 13.015,43 vinham de trás
e R$ 8.500,00 foram pagos. Em mai/26 e ago/26 os dois números quase coincidem —
**por coincidência aritmética**, não por acerto. Sem a conciliação, "bateu" e
"não bateu" viram impressão.

A coluna que acusa erro de verdade é **Δ importação**: diferente de zero
significa lançamento faltando.

### Espelho só de saída

A planilha nunca alimenta o sistema de volta (mesma decisão do SICAD desde
04/08/2026). Dois lugares editáveis com a mesma informação divergem, e depois não
há como saber qual está certo. Descrição vinda do banco é escrita com um apóstrofo
à frente quando começa com `=`, `+`, `-` ou `@`, para não virar fórmula na
planilha — anti-injeção, igual à correção M-1 da auditoria do SICAD.

---

## 5. Bugs já corrigidos que vale não reintroduzir

- **R$ 726,52 de juros perdidos em jul/2026.** O parser antigo procurava só o
  rótulo `Juros Remuneratórios`; naquela fatura o Santander escreveu
  `Juros de Crédito Rotativo`. Hoje `ENCARGOS_SANTANDER` aceita todas as
  variantes, e existe teste de regressão.
- **Seção do PDF do Santander atravessa as colunas.** O layout é de duas colunas
  e o título da seção aparece só na primeira. Reiniciar o estado a cada metade
  descartava tudo depois dela — em jul/2026 sobravam R$ 4.254 de R$ 8.477.
- **Descrição truncada em 80 caracteres**, igual ao pipeline que gerou o
  histórico. Cortar em tamanho diferente muda a chave de deduplicação e as 106
  linhas já cortadas voltariam como "novas".
- **`python-multipart` é obrigatória.** Sem ela o FastAPI não sobe, e a falha só
  aparece ao importar o `main.py`.

---

## 6. Testes

```bash
SENHA_PDF_SANTANDER=... ~/.venvs/financas-web/bin/python -m pytest tests -q
```

48 testes. Dois deles leem as **faturas reais em PDF** e exigem que cada uma
reconstrua exatamente o total que o app do banco mostra; são pulados
automaticamente se a senha ou a pasta não estiverem disponíveis.
