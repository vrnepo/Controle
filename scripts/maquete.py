#!/usr/bin/env python3
"""
SERVIDOR MAQUETE — banco Postgres local, descartável, com usuário de teste.

Serve para navegar o sistema inteiro antes de existir Neon, Render ou qualquer
conta criada. Sobe um PostgreSQL de verdade (pacote `pgserver`, que traz o
binário dentro do venv — não instala nada no sistema), cria o schema, semeia o
login de teste e carrega o histórico real de 2026 se a planilha estiver à mão.

    ~/.venvs/financas-web/bin/python scripts/maquete.py
    # imprime a DATABASE_URL; use-a para subir o servidor:
    DATABASE_URL="$(...)" PORT=8800 bash run_dev.sh

Login de teste: admin / admin

⚠️  A senha "admin" tem 5 caracteres e é MAIS CURTA que o mínimo de 8 que o
    sistema exige de verdade (core/usuarios.gerar_hash levanta erro abaixo
    disso). Aqui o hash é montado direto, de propósito, porque é fixture de
    maquete. Por isso o script se RECUSA a rodar contra banco remoto: uma senha
    dessas não pode encostar em produção. O caminho de produção continua sendo o
    Primeiro Acesso, em que você escolhe a senha na tela.

Para apagar tudo: rm -rf ~/.financas-maquete
"""

from __future__ import annotations

import datetime as dt
import glob
import hashlib
import os
import pathlib
import secrets
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Fora da pasta do projeto: ela mora no Google Drive, e um diretório de dados do
# Postgres ali sincronizaria milhares de arquivos e corromperia o banco.
DADOS = pathlib.Path(os.path.expanduser("~/.financas-maquete/pgdata"))

EMAIL_TESTE = "admin"
SENHA_TESTE = "admin"
NOME_TESTE = "Admin da maquete"

PLANILHAS = [
    os.path.expanduser("~/Library/CloudStorage/GoogleDrive-vr.alencar@gmail.com/"
                       "Meu Drive/_Controle Financeiro/Controle Financeiro 2.0.xlsx"),
    os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/"
                       "_Controle Financeiro/Controle Financeiro 2.0.xlsx"),
]


def hash_de_fixture(senha: str) -> str:
    """PBKDF2 no mesmo formato de core/usuarios, sem o mínimo de 8 caracteres."""
    from core.usuarios import ITERACOES

    salt = secrets.token_bytes(16)
    derivado = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, ITERACOES)
    return "pbkdf2_sha256$%d$%s$%s" % (ITERACOES, salt.hex(), derivado.hex())


def subir_postgres() -> str:
    try:
        import pgserver
    except ImportError:
        sys.exit("Falta o pacote da maquete:\n"
                 "  ~/.venvs/financas-web/bin/pip install pgserver")
    DADOS.mkdir(parents=True, exist_ok=True)
    # cleanup_mode=None: o padrão ('stop') derruba o Postgres quando o último
    # handle fecha — ou seja, quando ESTE script termina, e o servidor web
    # encontraria o socket já sumido. A maquete precisa continuar de pé depois.
    servidor = pgserver.get_server(DADOS, cleanup_mode=None)
    return servidor.get_uri()


def main() -> None:
    uri = subir_postgres()

    # Trava de segurança: fixture com senha "admin" só em socket local.
    if "host=/" not in uri and "localhost" not in uri and "127.0.0.1" not in uri:
        sys.exit("A maquete só roda em banco local. URI inesperada: %s" % uri)

    os.environ["DATABASE_URL"] = uri

    from core import bd, importacao, repositorio  # depois de definir a env
    from scripts import criar_schema  # noqa: F401  (só para reusar o DDL)
    from sqlalchemy import text

    with bd.obter_conexao() as conexao:
        for comando in criar_schema.DDL:
            conexao.execute(text(comando))
        conexao.commit()
    print("Schema criado.")

    from core import config
    with bd.obter_conexao() as conexao:
        for nome, banco, tipo in config.CONTAS_PADRAO:
            conexao.execute(text(
                "INSERT INTO contas (nome, banco, tipo) VALUES (:n, :b, :t) "
                "ON CONFLICT (nome) DO NOTHING"), {"n": nome, "b": banco, "t": tipo})
        ja = conexao.execute(text("SELECT count(*) FROM regras")).scalar()
        if not ja:
            from core.categorizacao import REGRAS_PADRAO
            for i, r in enumerate(REGRAS_PADRAO, start=1):
                conexao.execute(text(
                    "INSERT INTO regras (ordem, padrao, categoria, subcategoria, "
                    "item_fixo, tipo) VALUES (:o, :p, :c, :s, :i, :t)"),
                    {"o": i, "p": r[0], "c": r[1], "s": r[2], "i": r[3], "t": r[4]})
        conexao.commit()
    print("Contas e regras semeadas.")

    repositorio.criar_usuario(EMAIL_TESTE, NOME_TESTE, None)
    repositorio.definir_senha(EMAIL_TESTE, hash_de_fixture(SENHA_TESTE))
    print("Usuário de teste: %s / %s" % (EMAIL_TESTE, SENHA_TESTE))

    # --- histórico real, se a planilha estiver por aqui
    planilha = next((p for p in PLANILHAS if os.path.isfile(p)), None)
    if planilha:
        from scripts.migrar_da_planilha import RESUMOS_2026, ler_planilha
        import collections

        contas = repositorio.mapa_contas()
        linhas = ler_planilha(planilha)
        vistas: collections.Counter = collections.Counter()
        preparadas = []
        for linha in linhas:
            conta = contas.get(linha["conta"])
            if not conta:
                continue
            k = importacao.chave(conta["id"], linha["competencia"], linha["data"],
                                 linha["descricao"], linha["valor"])
            vistas[k] += 1
            preparadas.append({
                "conta_id": conta["id"], "fonte": linha["fonte"], "data": linha["data"],
                "descricao": linha["descricao"], "categoria": linha["categoria"],
                "subcategoria": linha["subcategoria"], "item_fixo": linha["item_fixo"],
                "tipo": linha["tipo"], "valor": linha["valor"],
                "competencia": linha["competencia"], "status": linha["status"],
                "arquivo": str(linha["arquivo"]), "chave": k, "ocorrencia": vistas[k]})
        inseridos = repositorio.inserir_lancamentos(preparadas)
        print("Lançamentos carregados: %d (de %d lidos)" % (inseridos, len(linhas)))

        for ano, mes, conta_nome, saldo, desp, enc, cred, pag, total in RESUMOS_2026:
            conta = contas.get(conta_nome)
            if conta:
                repositorio.upsert_resumo({
                    "conta_id": conta["id"], "competencia": dt.date(ano, mes, 1),
                    "saldo_anterior": saldo, "despesas": desp, "encargos": enc,
                    "creditos": cred, "pagamentos": pag, "total_informado": total,
                    "arquivo": "Fatura_%02d%04d (PDF)" % (mes, ano)})
        print("Resumos de fatura: %d" % len(RESUMOS_2026))
    else:
        print("Planilha do histórico não encontrada — a maquete sobe vazia.")

    print("\n" + "=" * 74)
    print("MAQUETE PRONTA")
    print("=" * 74)
    print("Login: %s     Senha: %s" % (EMAIL_TESTE, SENHA_TESTE))
    print("\nSuba o servidor apontando para este banco:\n")
    print('  DATABASE_URL="%s" \\' % uri)
    print("  COOKIE_SEGURO=0 PORT=8800 bash run_dev.sh")
    print("\nPara apagar a maquete: rm -rf ~/.financas-maquete")


if __name__ == "__main__":
    main()
