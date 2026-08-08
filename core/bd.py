"""
Conexão com o banco (Postgres no Neon) — a fonte da verdade dos dados.

Herdado do core/bd.py do SICAD, que já pagou o preço de aprender isto:

- A URL vem SÓ de DATABASE_URL e NUNCA aparece em log, erro ou tela. Toda
  exceção repassada adiante passa por sanitizar_erro().
- O Neon dorme quando ocioso e acorda em ~1 s na primeira conexão. Por isso
  pool_pre_ping revalida conexões mortas e obter_conexao() faz UMA retentativa
  curta — sem ela, o primeiro acesso do dia falha.
- Tolerância aos erros clássicos de colagem no painel do Render (aspas,
  espaços, quebra de linha, o prefixo "psql " do snippet do Neon), que
  produziam um "Could not parse URL" difícil de diagnosticar.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Tuple

_engine = None
_engine_lock = threading.Lock()


def banco_configurado() -> bool:
    return bool(os.environ.get("DATABASE_URL", "").strip())


def _url_sqlalchemy() -> str:
    url = os.environ["DATABASE_URL"]
    url = url.strip().strip("'\"").strip()
    if url.lower().startswith("psql "):
        url = url[5:].strip().strip("'\"").strip()
    # Dialeto explícito do psycopg 3: "postgresql://" puro faria o SQLAlchemy
    # procurar o psycopg2, que não está (nem estará) instalado.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def obter_engine():
    """Engine única do processo."""
    global _engine
    with _engine_lock:
        if _engine is None:
            from sqlalchemy import create_engine

            # Pool pequeno de propósito: um usuário só. O SICAD precisou de
            # 10+10 porque tinha 40 pessoas simultâneas; aqui isso só
            # consumiria conexão do Neon à toa.
            _engine = create_engine(
                _url_sqlalchemy(),
                pool_size=3,
                max_overflow=2,
                pool_timeout=10,
                pool_pre_ping=True,
                pool_recycle=300,
            )
        return _engine


def obter_conexao():
    """
    Conexão do pool com UMA retentativa após 1,5 s — cobre o cold start do
    Neon. Uso: `with bd.obter_conexao() as conexao: ...`.
    """
    try:
        return obter_engine().connect()
    except Exception:
        time.sleep(1.5)
        return obter_engine().connect()


def sanitizar_erro(erro: object) -> str:
    """Tira usuário:senha de qualquer URL embutida na mensagem e troca jargão
    de infraestrutura por frase que se entende na tela."""
    texto = re.sub(r"://[^@\s]+@", "://***@", str(erro))
    if "QueuePool limit" in texto or "connection timed out" in texto:
        return "O sistema está com muitos acessos ao mesmo tempo. Tente de novo em alguns segundos."
    return texto


def testar_conexao() -> Tuple[bool, str]:
    """(ok, mensagem) — a mensagem NUNCA contém a URL nem a senha."""
    if not banco_configurado():
        return False, "DATABASE_URL não configurada."
    try:
        from sqlalchemy import text

        with obter_conexao() as conexao:
            banco = conexao.execute(text("SELECT current_database()")).scalar()
        return True, "Conectado ao banco '%s'." % banco
    except Exception as erro:
        return False, sanitizar_erro(erro)
