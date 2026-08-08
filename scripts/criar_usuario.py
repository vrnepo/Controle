#!/usr/bin/env python3
"""
Cria o usuário de acesso ao sistema.

    DATABASE_URL='postgresql://...' python3 scripts/criar_usuario.py \
        vr.alencar@gmail.com "Vitor"

O usuário nasce SEM senha: ele mesmo a define na tela, no Primeiro Acesso.
Isso é de propósito — nenhuma senha passa por script, por chat ou por e-mail, e
nem eu nem o histórico do terminal chegam a ver a senha real.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Carrega o .env da raiz do projeto ANTES de importar core.* — sem isto, rodar
# o script "a seco" (como manda o DEPLOY.md) falhava com "DATABASE_URL não
# configurada", e a alternativa (source .env no shell) quebra no "&" dos
# parâmetros da URL do Neon. Descoberto na primeira carga real, 08/08/2026.
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from core import bd, repositorio  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("Uso: python3 scripts/criar_usuario.py <email> <nome>")
    if not bd.banco_configurado():
        sys.exit("DATABASE_URL não configurada.")

    email, nome = sys.argv[1].strip(), sys.argv[2].strip()
    existente = repositorio.usuario_por_email(email)
    if existente and existente.get("senha_hash"):
        print("O usuário %s já existe e já tem senha. Nada a fazer." % email)
        print("Para zerar a senha, apague o hash no banco:")
        print("  UPDATE usuarios SET senha_hash = NULL WHERE email = '%s';" % email)
        return

    repositorio.criar_usuario(email, nome, None)
    print("Usuário %s criado sem senha." % email)
    print("Abra /login, informe esse e-mail e qualquer senha: o sistema vai")
    print("oferecer o Primeiro Acesso para você criar a sua.")


if __name__ == "__main__":
    main()
