#!/bin/bash
# ============================================================================
# SERVIDOR LOCAL — http://127.0.0.1:8800
# ============================================================================
# O venv fica FORA da pasta do projeto (em ~/.venvs/financas-web) de propósito:
# este projeto mora no Google Drive, e um .venv aqui dentro sincronizaria
# milhares de arquivos à toa. Mesma decisão do SICAD.
#
# Porta 8800 para não colidir com os servidores do SICAD (8600/8601 dev,
# 8700/8710/8720 maquetes).
#
# ATENÇÃO: o main.py carrega o .env, então uma DATABASE_URL guardada ali faz
# este servidor local ler e GRAVAR no banco de PRODUÇÃO (Neon). É o mesmo banco
# — não existe "banco de teste" configurado. Para um branch separado, crie um
# branch no Neon e aponte a DATABASE_URL para ele.
set -euo pipefail
cd "$(dirname "$0")"

VENV="${FINANCAS_VENV:-$HOME/.venvs/financas-web}"
if [ ! -x "$VENV/bin/uvicorn" ]; then
  echo "Criando o venv em $VENV (só na primeira vez)…"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r requirements.txt
fi

if [ -z "${DATABASE_URL:-}" ] && ! grep -qs "^DATABASE_URL=." .env; then
  echo "⚠️  Sem DATABASE_URL (nem no ambiente, nem no .env)."
  echo "   O login vai falhar com 'Banco de dados não configurado'."
  echo "   Crie o .env a partir do .env.exemplo."
fi

echo "SERVIDOR LOCAL em http://127.0.0.1:${PORT:-8800}  (Ctrl+C para parar)"
exec "$VENV/bin/uvicorn" main:app --host 127.0.0.1 --port "${PORT:-8800}" --reload
