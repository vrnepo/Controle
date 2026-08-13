#!/usr/bin/env python3
"""
Cria (ou atualiza) o schema no Neon. Idempotente: pode rodar quantas vezes
quiser — só cria o que falta.

    DATABASE_URL='postgresql://...' python3 scripts/criar_schema.py

A decisão central está na tabela `lancamentos`: a deduplicação é do BANCO, não
do código de importação.

    UNIQUE (chave, ocorrencia)

`chave` = conta + competência + dia + descrição normalizada + centavos.
`ocorrencia` = 1, 2, 3… para repetições legítimas da MESMA chave.

Por que assim: existem cobranças idênticas de verdade no mesmo dia — na fatura
de ago/2026 há duas de "Google Workspace_sicad 50,00" em 29/07, duas de
"Anthropic 20,76" e duas de "IOF de compra internacional 0,72" em 25/07. Um
dedup que pergunta "já existe uma linha igual?" apagaria a segunda de cada par.
Contando ocorrências, reimportar o mesmo arquivo insere zero (as chaves 1 e 2 já
existem) e um arquivo com repetição legítima preserva as duas. E como a garantia
é uma constraint, nem uma importação simultânea ou um bug futuro no Python
conseguem duplicar.
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

from core import bd, config  # noqa: E402

DDL = [
    """
    CREATE TABLE IF NOT EXISTS contas (
        id          serial PRIMARY KEY,
        nome        text NOT NULL UNIQUE,
        banco       text NOT NULL,
        tipo        text NOT NULL CHECK (tipo IN ('cartao', 'conta')),
        ativa       boolean NOT NULL DEFAULT true
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS usuarios (
        id             serial PRIMARY KEY,
        email          text NOT NULL UNIQUE,
        nome           text NOT NULL,
        senha_hash     text,
        criado_em      timestamptz NOT NULL DEFAULT now(),
        ultimo_acesso  timestamptz
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS lancamentos (
        id            bigserial PRIMARY KEY,
        conta_id      integer NOT NULL REFERENCES contas(id),
        fonte         text NOT NULL,
        data          date NOT NULL,
        descricao     text NOT NULL,
        categoria     text,
        subcategoria  text,
        item_fixo     text,
        tipo          text NOT NULL,
        valor         numeric(14, 2) NOT NULL,
        competencia   date NOT NULL,
        status        text NOT NULL DEFAULT 'Confirmado',
        arquivo       text,
        chave         text NOT NULL,
        ocorrencia    integer NOT NULL DEFAULT 1,
        criado_em     timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT lancamentos_dedup UNIQUE (chave, ocorrencia)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_lanc_competencia ON lancamentos (competencia)",
    "CREATE INDEX IF NOT EXISTS ix_lanc_conta_comp ON lancamentos (conta_id, competencia)",
    "CREATE INDEX IF NOT EXISTS ix_lanc_categoria ON lancamentos (categoria)",
    """
    CREATE TABLE IF NOT EXISTS resumo_faturas (
        id               serial PRIMARY KEY,
        conta_id         integer NOT NULL REFERENCES contas(id),
        competencia      date NOT NULL,
        saldo_anterior   numeric(14, 2) NOT NULL DEFAULT 0,
        despesas         numeric(14, 2) NOT NULL DEFAULT 0,
        encargos         numeric(14, 2) NOT NULL DEFAULT 0,
        creditos         numeric(14, 2) NOT NULL DEFAULT 0,
        pagamentos       numeric(14, 2) NOT NULL DEFAULT 0,
        total_informado  numeric(14, 2) NOT NULL DEFAULT 0,
        arquivo          text,
        atualizado_em    timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT resumo_unico UNIQUE (conta_id, competencia)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS regras (
        id            serial PRIMARY KEY,
        ordem         integer NOT NULL,
        padrao        text NOT NULL,
        categoria     text,
        subcategoria  text,
        item_fixo     text,
        tipo          text,
        ativa         boolean NOT NULL DEFAULT true,
        observacao    text
    )
    """,
    # Exceções deliberadas da conciliação (13/08/2026): o caso de origem é o
    # estorno Airbnb que consta na fatura de ago/26 mas fica em jul/26 por
    # decisão do usuário. Guarda o Δ aceito para o alarme VOLTAR se o mês
    # mudar de novo por outro motivo.
    """
    CREATE TABLE IF NOT EXISTS justificativas (
        id           serial PRIMARY KEY,
        conta_id     integer NOT NULL REFERENCES contas(id),
        competencia  date NOT NULL,
        delta        numeric(14, 2) NOT NULL,
        motivo       text NOT NULL,
        criado_em    timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT justificativa_unica UNIQUE (conta_id, competencia)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS importacoes (
        id           bigserial PRIMARY KEY,
        quando       timestamptz NOT NULL DEFAULT now(),
        arquivo      text NOT NULL,
        formato      text,
        conta        text,
        lidos        integer NOT NULL DEFAULT 0,
        inseridos    integer NOT NULL DEFAULT 0,
        duplicados   integer NOT NULL DEFAULT 0,
        suspeitos    integer NOT NULL DEFAULT 0,
        status       text NOT NULL,
        observacao   text
    )
    """,
]


def main() -> None:
    if not bd.banco_configurado():
        sys.exit("DATABASE_URL não configurada. "
                 "Ex.: DATABASE_URL='postgresql://...' python3 scripts/criar_schema.py")

    from sqlalchemy import text

    with bd.obter_conexao() as conexao:
        for comando in DDL:
            conexao.execute(text(comando))
        conexao.commit()
        print("Schema criado/atualizado.")

        # contas
        for nome, banco, tipo in config.CONTAS_PADRAO:
            conexao.execute(text(
                "INSERT INTO contas (nome, banco, tipo) VALUES (:n, :b, :t) "
                "ON CONFLICT (nome) DO NOTHING"
            ), {"n": nome, "b": banco, "t": tipo})
        conexao.commit()
        n = conexao.execute(text("SELECT count(*) FROM contas")).scalar()
        print("Contas: %s" % n)

        # regras (só se a tabela estiver vazia — não sobrescreve ajuste seu)
        ja = conexao.execute(text("SELECT count(*) FROM regras")).scalar()
        if ja:
            print("Regras: %s já cadastradas, nada a fazer." % ja)
        else:
            from core.categorizacao import REGRAS_PADRAO

            for i, r in enumerate(REGRAS_PADRAO, start=1):
                conexao.execute(text(
                    "INSERT INTO regras (ordem, padrao, categoria, subcategoria, "
                    "item_fixo, tipo) VALUES (:o, :p, :c, :s, :i, :t)"
                ), {"o": i, "p": r[0], "c": r[1], "s": r[2], "i": r[3], "t": r[4]})
            conexao.commit()
            print("Regras: %s inseridas." % len(REGRAS_PADRAO))

    ok, msg = bd.testar_conexao()
    print(("OK — " if ok else "FALHA — ") + msg)


if __name__ == "__main__":
    main()
