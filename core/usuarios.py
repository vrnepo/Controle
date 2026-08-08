"""
Autenticação. Mesmo desenho do SICAD: e-mail + senha com PBKDF2-HMAC-SHA256,
hash guardado no banco, nunca a senha.

Primeiro Acesso: o usuário é criado SEM senha (`senha_hash` nulo) e a define
ele mesmo na tela. Assim nenhuma senha passa por e-mail, por chat ou por mim.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Optional, Tuple

from core import repositorio

ITERACOES = 240_000        # PBKDF2; custo alto o suficiente para 2026
MINIMO_SENHA = 8


def gerar_hash(senha: str) -> str:
    """Formato: pbkdf2_sha256$<iteracoes>$<salt_hex>$<hash_hex>."""
    if len(senha) < MINIMO_SENHA:
        raise ValueError("A senha precisa ter pelo menos %d caracteres." % MINIMO_SENHA)
    salt = secrets.token_bytes(16)
    derivado = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, ITERACOES)
    return "pbkdf2_sha256$%d$%s$%s" % (ITERACOES, salt.hex(), derivado.hex())


def conferir(senha: str, guardado: Optional[str]) -> bool:
    """compare_digest para não vazar informação pelo tempo de resposta."""
    if not guardado:
        return False
    try:
        algoritmo, iteracoes, salt_hex, esperado = guardado.split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        derivado = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"),
                                       bytes.fromhex(salt_hex), int(iteracoes))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derivado.hex(), esperado)


def autenticar(email: str, senha: str) -> Tuple[bool, str, Optional[dict]]:
    """(ok, mensagem, usuario). A mensagem nunca diz se o e-mail existe."""
    email = (email or "").strip()
    if not email or not senha:
        return False, "Informe e-mail e senha.", None

    usuario = repositorio.usuario_por_email(email)
    if not usuario:
        # Mesma resposta de senha errada: dizer "e-mail não cadastrado" entrega
        # a quem tentar adivinhar quais contas existem.
        _consumir_tempo(senha)
        return False, "E-mail ou senha incorretos.", None

    if not usuario.get("senha_hash"):
        return False, "primeiro_acesso", usuario

    if not conferir(senha, usuario["senha_hash"]):
        return False, "E-mail ou senha incorretos.", None

    repositorio.marcar_acesso(email)
    return True, "", usuario


def _consumir_tempo(senha: str) -> None:
    """Gasta o mesmo tempo de um PBKDF2 real quando o e-mail não existe, para o
    tempo de resposta não revelar a diferença."""
    hashlib.pbkdf2_hmac("sha256", (senha or "").encode("utf-8"), b"tempo-constante",
                        ITERACOES)


def definir_primeira_senha(email: str, senha: str, repeticao: str) -> Tuple[bool, str]:
    if senha != repeticao:
        return False, "As duas senhas não são iguais."
    usuario = repositorio.usuario_por_email(email)
    if not usuario:
        return False, "E-mail não encontrado."
    if usuario.get("senha_hash"):
        return False, "Essa conta já tem senha. Use a tela de entrada."
    try:
        repositorio.definir_senha(email, gerar_hash(senha))
    except ValueError as erro:
        return False, str(erro)
    return True, "Senha criada. Já pode entrar."


def trocar_senha(email: str, atual: str, nova: str, repeticao: str) -> Tuple[bool, str]:
    if nova != repeticao:
        return False, "As duas senhas novas não são iguais."
    usuario = repositorio.usuario_por_email(email)
    if not usuario or not conferir(atual, usuario.get("senha_hash")):
        return False, "Senha atual incorreta."
    try:
        repositorio.definir_senha(email, gerar_hash(nova))
    except ValueError as erro:
        return False, str(erro)
    return True, "Senha alterada."
