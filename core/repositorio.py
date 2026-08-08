"""
Acesso ao banco. TODA leitura e gravação passa por aqui.

Convenção herdada do SICAD: nenhum SQL de escrita fora deste módulo, e a
gravação só acontece em tabela da allowlist. Assim "onde isso foi gravado?"
tem uma resposta só, e uma tabela nova exige um passo consciente.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import text

from core import bd

# Tabela nova só entra aqui de propósito, junto do schema.
TABELAS_GRAVAVEIS = {
    "contas", "usuarios", "lancamentos", "resumo_faturas", "regras", "importacoes",
}


def _checar(tabela: str) -> None:
    if tabela not in TABELAS_GRAVAVEIS:
        raise ValueError("Gravação em tabela fora da allowlist: %s" % tabela)


def _linhas(resultado) -> List[Dict[str, Any]]:
    return [dict(r) for r in resultado.mappings().all()]


# ------------------------------------------------------------------- contas

def contas() -> List[Dict[str, Any]]:
    with bd.obter_conexao() as c:
        return _linhas(c.execute(text(
            "SELECT id, nome, banco, tipo, ativa FROM contas ORDER BY tipo DESC, nome")))


def mapa_contas() -> Dict[str, Dict[str, Any]]:
    return {c["nome"]: c for c in contas()}


# ----------------------------------------------------------------- usuários

def usuario_por_email(email: str) -> Optional[Dict[str, Any]]:
    with bd.obter_conexao() as c:
        r = _linhas(c.execute(text(
            "SELECT id, email, nome, senha_hash FROM usuarios WHERE lower(email) = lower(:e)"
        ), {"e": email}))
    return r[0] if r else None


def contar_usuarios() -> int:
    with bd.obter_conexao() as c:
        return int(c.execute(text("SELECT count(*) FROM usuarios")).scalar() or 0)


def criar_usuario(email: str, nome: str, senha_hash: Optional[str]) -> int:
    _checar("usuarios")
    with bd.obter_conexao() as c:
        novo = c.execute(text(
            "INSERT INTO usuarios (email, nome, senha_hash) VALUES (:e, :n, :h) "
            "ON CONFLICT (email) DO UPDATE SET nome = EXCLUDED.nome RETURNING id"
        ), {"e": email.strip(), "n": nome.strip(), "h": senha_hash}).scalar()
        c.commit()
    return int(novo)


def definir_senha(email: str, senha_hash: str) -> None:
    _checar("usuarios")
    with bd.obter_conexao() as c:
        c.execute(text("UPDATE usuarios SET senha_hash = :h WHERE lower(email) = lower(:e)"),
                  {"h": senha_hash, "e": email})
        c.commit()


def marcar_acesso(email: str) -> None:
    _checar("usuarios")
    with bd.obter_conexao() as c:
        c.execute(text("UPDATE usuarios SET ultimo_acesso = now() WHERE lower(email) = lower(:e)"),
                  {"e": email})
        c.commit()


# ------------------------------------------------------------------ regras

def regras(somente_ativas: bool = True) -> List[Dict[str, Any]]:
    sql = ("SELECT id, ordem, padrao, categoria, subcategoria, item_fixo, tipo, "
           "ativa, observacao FROM regras")
    if somente_ativas:
        sql += " WHERE ativa"
    sql += " ORDER BY ordem, id"
    with bd.obter_conexao() as c:
        return _linhas(c.execute(text(sql)))


def salvar_regra(dados: Dict[str, Any]) -> int:
    _checar("regras")
    with bd.obter_conexao() as c:
        if dados.get("id"):
            c.execute(text(
                "UPDATE regras SET ordem = :ordem, padrao = :padrao, categoria = :categoria, "
                "subcategoria = :subcategoria, item_fixo = :item_fixo, tipo = :tipo, "
                "ativa = :ativa, observacao = :observacao WHERE id = :id"), dados)
            c.commit()
            return int(dados["id"])
        novo = c.execute(text(
            "INSERT INTO regras (ordem, padrao, categoria, subcategoria, item_fixo, tipo, "
            "ativa, observacao) VALUES (:ordem, :padrao, :categoria, :subcategoria, "
            ":item_fixo, :tipo, :ativa, :observacao) RETURNING id"), dados).scalar()
        c.commit()
    return int(novo)


def apagar_regra(regra_id: int) -> None:
    _checar("regras")
    with bd.obter_conexao() as c:
        c.execute(text("DELETE FROM regras WHERE id = :i"), {"i": regra_id})
        c.commit()


# ------------------------------------------------------------- lançamentos

def contagem_por_chave(chaves: Sequence[str]) -> Dict[str, int]:
    """Quantas vezes cada chave já existe. Base da deduplicação."""
    if not chaves:
        return {}
    with bd.obter_conexao() as c:
        rs = c.execute(text(
            "SELECT chave, count(*) AS n FROM lancamentos "
            "WHERE chave = ANY(:chaves) GROUP BY chave"
        ), {"chaves": list(set(chaves))})
        return {r["chave"]: int(r["n"]) for r in rs.mappings().all()}


def chaves_das_competencias(pares: Iterable[Tuple[int, dt.date]]) -> List[str]:
    """
    Todas as chaves já gravadas nas competências afetadas pela importação.

    Serve para o aviso de "suspeito": mesma descrição e valor no mesmo mês, mas
    em outro dia. Essas linhas ENTRAM (podem ser cobranças legítimas repetidas)
    — só ficam sinalizadas, porque quem decide é o usuário.
    """
    pares = list(set(pares))
    if not pares:
        return []
    condicoes, params = [], {}
    for i, (conta_id, comp) in enumerate(pares):
        condicoes.append("(conta_id = :c%d AND competencia = :m%d)" % (i, i))
        params["c%d" % i] = conta_id
        params["m%d" % i] = comp
    with bd.obter_conexao() as c:
        rs = c.execute(text("SELECT chave FROM lancamentos WHERE " + " OR ".join(condicoes)),
                       params)
        return [r["chave"] for r in rs.mappings().all()]


def inserir_lancamentos(linhas: List[Dict[str, Any]]) -> int:
    """
    Insere já com a `ocorrencia` calculada por quem chamou.

    ON CONFLICT DO NOTHING é a rede de segurança: a UNIQUE (chave, ocorrencia)
    é que garante, no banco, que reimportar não duplica — nem se duas
    importações rodarem ao mesmo tempo, nem se algum bug futuro no Python
    errar a contagem.
    """
    _checar("lancamentos")
    if not linhas:
        return 0
    with bd.obter_conexao() as c:
        resultado = c.execute(text(
            "INSERT INTO lancamentos (conta_id, fonte, data, descricao, categoria, "
            "subcategoria, item_fixo, tipo, valor, competencia, status, arquivo, "
            "chave, ocorrencia) VALUES (:conta_id, :fonte, :data, :descricao, :categoria, "
            ":subcategoria, :item_fixo, :tipo, :valor, :competencia, :status, :arquivo, "
            ":chave, :ocorrencia) ON CONFLICT (chave, ocorrencia) DO NOTHING"
        ), linhas)
        c.commit()
    return int(resultado.rowcount or 0)


def listar_lancamentos(competencia: Optional[dt.date] = None,
                       conta_id: Optional[int] = None,
                       categoria: Optional[str] = None,
                       busca: str = "",
                       limite: int = 500) -> List[Dict[str, Any]]:
    sql = ["SELECT l.id, l.data, l.descricao, l.categoria, l.subcategoria, l.item_fixo,",
           "       l.tipo, l.valor, l.competencia, l.status, l.arquivo, l.fonte,",
           "       c.nome AS conta, c.banco",
           "  FROM lancamentos l JOIN contas c ON c.id = l.conta_id",
           " WHERE 1 = 1"]
    p: Dict[str, Any] = {"limite": max(1, min(int(limite), 5000))}
    if competencia:
        sql.append(" AND l.competencia = :comp")
        p["comp"] = competencia
    if conta_id:
        sql.append(" AND l.conta_id = :conta")
        p["conta"] = conta_id
    if categoria:
        sql.append(" AND l.categoria = :cat")
        p["cat"] = categoria
    if busca.strip():
        sql.append(" AND l.descricao ILIKE :busca")
        p["busca"] = "%" + busca.strip() + "%"
    sql.append(" ORDER BY l.data DESC, l.id DESC LIMIT :limite")
    with bd.obter_conexao() as c:
        return _linhas(c.execute(text("\n".join(sql)), p))


def atualizar_lancamento(lanc_id: int, campos: Dict[str, Any]) -> None:
    """Correção manual pela tela. Só os campos de classificação — data, valor e
    conta vêm do banco e não se editam à mão: mexer neles quebraria a chave de
    deduplicação e o arquivo voltaria a entrar na próxima importação."""
    _checar("lancamentos")
    permitidos = {"categoria", "subcategoria", "item_fixo", "tipo", "status"}
    sets, p = [], {"id": lanc_id}
    for k, v in campos.items():
        if k in permitidos:
            sets.append("%s = :%s" % (k, k))
            p[k] = v
    if not sets:
        return
    with bd.obter_conexao() as c:
        c.execute(text("UPDATE lancamentos SET " + ", ".join(sets) + " WHERE id = :id"), p)
        c.commit()


def apagar_competencia(conta_id: Optional[int], competencia: dt.date) -> int:
    """Limpa um mês para reimportar do zero (fatura corrigida pelo banco)."""
    _checar("lancamentos")
    sql = "DELETE FROM lancamentos WHERE competencia = :comp"
    p: Dict[str, Any] = {"comp": competencia}
    if conta_id:
        sql += " AND conta_id = :conta"
        p["conta"] = conta_id
    with bd.obter_conexao() as c:
        r = c.execute(text(sql), p)
        c.commit()
    return int(r.rowcount or 0)


# --------------------------------------------------------- resumo de fatura

def upsert_resumo(dados: Dict[str, Any]) -> None:
    _checar("resumo_faturas")
    with bd.obter_conexao() as c:
        c.execute(text(
            "INSERT INTO resumo_faturas (conta_id, competencia, saldo_anterior, despesas, "
            "encargos, creditos, pagamentos, total_informado, arquivo) "
            "VALUES (:conta_id, :competencia, :saldo_anterior, :despesas, :encargos, "
            ":creditos, :pagamentos, :total_informado, :arquivo) "
            "ON CONFLICT (conta_id, competencia) DO UPDATE SET "
            "saldo_anterior = EXCLUDED.saldo_anterior, despesas = EXCLUDED.despesas, "
            "encargos = EXCLUDED.encargos, creditos = EXCLUDED.creditos, "
            "pagamentos = EXCLUDED.pagamentos, total_informado = EXCLUDED.total_informado, "
            "arquivo = EXCLUDED.arquivo, atualizado_em = now()"), dados)
        c.commit()


def resumos(competencia: Optional[dt.date] = None) -> List[Dict[str, Any]]:
    sql = ["SELECT r.*, c.nome AS conta, c.banco",
           "  FROM resumo_faturas r JOIN contas c ON c.id = r.conta_id"]
    p: Dict[str, Any] = {}
    if competencia:
        sql.append(" WHERE r.competencia = :comp")
        p["comp"] = competencia
    sql.append(" ORDER BY r.competencia, c.nome")
    with bd.obter_conexao() as c:
        return _linhas(c.execute(text("\n".join(sql)), p))


# ------------------------------------------------------------- importações

def registrar_importacao(dados: Dict[str, Any]) -> None:
    _checar("importacoes")
    with bd.obter_conexao() as c:
        c.execute(text(
            "INSERT INTO importacoes (arquivo, formato, conta, lidos, inseridos, "
            "duplicados, suspeitos, status, observacao) VALUES (:arquivo, :formato, "
            ":conta, :lidos, :inseridos, :duplicados, :suspeitos, :status, :observacao)"),
            dados)
        c.commit()


def importacoes(limite: int = 100) -> List[Dict[str, Any]]:
    with bd.obter_conexao() as c:
        return _linhas(c.execute(text(
            "SELECT * FROM importacoes ORDER BY quando DESC LIMIT :l"),
            {"l": max(1, min(int(limite), 500))}))


# --------------------------------------------------------------- agregados

def competencias() -> List[dt.date]:
    with bd.obter_conexao() as c:
        rs = c.execute(text(
            "SELECT DISTINCT competencia FROM lancamentos ORDER BY competencia"))
        return [r[0] for r in rs.all()]


def resumo_do_mes(competencia: dt.date) -> Dict[str, Any]:
    """Receitas, despesas e resultado — transferências ficam de fora."""
    with bd.obter_conexao() as c:
        r = c.execute(text(
            "SELECT "
            " COALESCE(SUM(valor) FILTER (WHERE tipo = 'Receita'), 0) AS receitas,"
            " COALESCE(SUM(valor) FILTER (WHERE tipo = 'Despesa'), 0) AS despesas,"
            " COALESCE(SUM(valor) FILTER (WHERE tipo = 'Despesa' AND fonte = 'Extrato'), 0)"
            "   AS debito_pix,"
            " count(*) AS lancamentos"
            " FROM lancamentos WHERE competencia = :comp"), {"comp": competencia})
        d = dict(r.mappings().one())
    d["resultado"] = float(d["receitas"]) + float(d["despesas"])
    return d


def despesas_por_categoria(competencia: dt.date) -> List[Dict[str, Any]]:
    with bd.obter_conexao() as c:
        return _linhas(c.execute(text(
            "SELECT categoria, SUM(valor) AS total, count(*) AS n"
            " FROM lancamentos WHERE competencia = :comp AND tipo = 'Despesa'"
            " GROUP BY categoria ORDER BY SUM(valor)"), {"comp": competencia}))


def evolucao_mensal() -> List[Dict[str, Any]]:
    with bd.obter_conexao() as c:
        return _linhas(c.execute(text(
            "SELECT competencia,"
            " COALESCE(SUM(valor) FILTER (WHERE tipo = 'Receita'), 0) AS receitas,"
            " COALESCE(SUM(valor) FILTER (WHERE tipo = 'Despesa'), 0) AS despesas"
            " FROM lancamentos GROUP BY competencia ORDER BY competencia")))


def gasto_por_conta() -> List[Dict[str, Any]]:
    """Gasto do mês por conta — é o número que a fatura do cartão representa."""
    with bd.obter_conexao() as c:
        return _linhas(c.execute(text(
            "SELECT l.competencia, c.nome AS conta, c.tipo, SUM(l.valor) AS total"
            " FROM lancamentos l JOIN contas c ON c.id = l.conta_id"
            " GROUP BY l.competencia, c.nome, c.tipo"
            " ORDER BY l.competencia, c.nome")))


def itens_fixos(competencia: dt.date) -> List[Dict[str, Any]]:
    with bd.obter_conexao() as c:
        return _linhas(c.execute(text(
            "SELECT item_fixo, SUM(valor) AS total, count(*) AS n"
            " FROM lancamentos WHERE competencia = :comp"
            "   AND item_fixo IS NOT NULL AND item_fixo <> ''"
            " GROUP BY item_fixo ORDER BY SUM(valor)"), {"comp": competencia}))
