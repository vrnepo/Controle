# -*- coding: utf-8 -*-
"""
A deduplicação e a categorização — as duas regras de negócio que, se errarem,
erram o dinheiro.
"""

from __future__ import annotations

import collections
import datetime as dt

from core import categorizacao, config, importacao


def regras():
    return categorizacao.compilar([
        {"padrao": p, "categoria": c, "subcategoria": s, "item_fixo": i, "tipo": t,
         "ativa": True}
        for p, c, s, i, t in categorizacao.REGRAS_PADRAO])


# ------------------------------------------------------------------- chave

def test_chave_ignora_acento_e_caixa():
    a = importacao.chave(1, dt.date(2026, 8, 1), dt.date(2026, 8, 7),
                         "Mercadolivre*Gamestick", -56.99)
    b = importacao.chave(1, dt.date(2026, 8, 1), dt.date(2026, 8, 7),
                         "MERCADOLIVRE*GAMESTICK", -56.99)
    assert a == b


def test_chave_separa_valor_diferente():
    a = importacao.chave(1, dt.date(2026, 8, 1), dt.date(2026, 8, 7), "Spotify", -23.90)
    b = importacao.chave(1, dt.date(2026, 8, 1), dt.date(2026, 8, 7), "Spotify", -23.91)
    assert a != b


def test_chave_usa_centavos_inteiros():
    """0,1 + 0,2 em float não dá 0,3. Comparar em centavos inteiros evita que
    um arredondamento faça a mesma linha parecer nova."""
    a = importacao.chave(1, dt.date(2026, 8, 1), dt.date(2026, 8, 7), "X", -0.3)
    b = importacao.chave(1, dt.date(2026, 8, 1), dt.date(2026, 8, 7), "X", -(0.1 + 0.2))
    assert a == b


def test_chave_corta_descricao_em_80():
    longa = "PIX " + "A" * 200
    k = importacao.chave(1, dt.date(2026, 8, 1), dt.date(2026, 8, 7), longa, -10)
    descricao = k.split("|")[3]
    assert len(descricao) == importacao.LIMITE_DESCRICAO


def test_chave_sem_dia_agrupa_o_mes():
    a = importacao.chave(1, dt.date(2026, 8, 1), dt.date(2026, 8, 7), "Uber", -20)
    b = importacao.chave(1, dt.date(2026, 8, 1), dt.date(2026, 8, 19), "Uber", -20)
    assert a != b
    assert importacao.chave_sem_dia(a) == importacao.chave_sem_dia(b)


# ----------------------------------------------- multiplicidade x presença

def simular(existente, arquivo, por_multiplicidade):
    """Reproduz a decisão de inserir/pular, dos dois jeitos, para comparar."""
    vistas: collections.Counter = collections.Counter()
    inseridos, duplicados = [], 0
    for k in arquivo:
        vistas[k] += 1
        limite = existente.get(k, 0) if por_multiplicidade else (1 if existente.get(k) else 0)
        if vistas[k] <= limite:
            duplicados += 1
        else:
            inseridos.append(k)
    return inseridos, duplicados


def test_reimportar_o_mesmo_arquivo_nao_insere_nada():
    """
    Caso real: no CSV de ago/2026 há duas cobranças idênticas de
    "Google Workspace_sicad 50,00" em 29/07 — as duas legítimas.

    Com multiplicidade, reimportar insere 0. Com o dedup ingênuo ("já existe uma
    igual? então pula"), a segunda de cada par escapa e entra de novo — R$ 71,48
    de gasto que nunca existiu, a cada reimportação.
    """
    arquivo = ["workspace", "workspace", "anthropic", "anthropic", "iof", "iof",
               "youtube"]
    existente = {"workspace": 2, "anthropic": 2, "iof": 2, "youtube": 1}

    inseridos, duplicados = simular(existente, arquivo, por_multiplicidade=True)
    assert inseridos == [] and duplicados == 7

    inseridos_ingenuo, _ = simular(existente, arquivo, por_multiplicidade=False)
    assert len(inseridos_ingenuo) == 3      # é o bug que estamos evitando


def test_primeira_importacao_preserva_repeticao_legitima():
    arquivo = ["workspace", "workspace"]
    inseridos, duplicados = simular({}, arquivo, por_multiplicidade=True)
    assert len(inseridos) == 2 and duplicados == 0


def test_arquivo_com_uma_linha_nova_entre_conhecidas():
    """O caso da fatura corrigida: só o que é novo entra."""
    arquivo = ["a", "b", "juros_rotativo", "c"]
    existente = {"a": 1, "b": 1, "c": 1}
    inseridos, duplicados = simular(existente, arquivo, por_multiplicidade=True)
    assert inseridos == ["juros_rotativo"] and duplicados == 3


# --------------------------------------------------------- categorização

def test_transferencia_vence_tudo():
    """Pagamento de fatura não é despesa: a compra já foi lançada quando
    aconteceu. Contar o pagamento também dobraria o mês."""
    r = categorizacao.classificar(
        "PAGAMENTO CARTAO CREDITO BCE 191858 11/07", -9000.0, "conta", regras())
    assert r["tipo"] == config.TIPO_TRANSFERENCIA
    assert r["categoria"] == config.CATEGORIA_TRANSFERENCIA
    assert r["item_fixo"] == ""      # transferência não é item fixo


def test_fechamento_da_fatura_e_transferencia():
    """Saldo anterior e pagamentos da fatura Santander (decisão de 08/08/2026):
    entram nos lançamentos para a soma bater com o Saldo Desta Fatura, mas como
    Transferência — senão o resultado do mês contaria o saldo de novo."""
    r1 = categorizacao.classificar("Saldo anterior da fatura", -13015.43,
                                   "cartao", regras())
    r2 = categorizacao.classificar("Pagamentos recebidos na fatura", 8500.00,
                                   "cartao", regras())
    for r in (r1, r2):
        assert r["tipo"] == config.TIPO_TRANSFERENCIA
        assert r["categoria"] == config.CATEGORIA_TRANSFERENCIA
        assert r["item_fixo"] == ""
    # e o estorno de cartão não é capturado por engano pela regra nova
    assert "(estorno)" not in r2["subcategoria"]


def test_pix_para_si_mesmo_e_transferencia():
    r = categorizacao.classificar(
        "PIX RECEBIDO Vitor Alencar Farias Nepo", 1771.72, "conta", regras())
    assert r["tipo"] == config.TIPO_TRANSFERENCIA


def test_pai_nao_e_confundido_com_o_usuario():
    """A regra de nome próprio tem de ser específica: 'NEPOMUCENO' solto
    capturava Vladimir (o pai) como transferência entre contas próprias."""
    r = categorizacao.classificar(
        "PIX ENVIADO VLADIMIR FARIAS NEPOMUCENO", -2100.0, "conta", regras())
    assert r["categoria"] == "FLAT"
    assert r["item_fixo"] == "Condomínio FLAT (pai)"
    assert r["tipo"] == config.TIPO_DESPESA


def test_salario_e_receita_com_item_fixo():
    r = categorizacao.classificar(
        "LIQUIDO DE VENCIMENTO Municipio 04249873300014", 12742.33, "conta", regras())
    assert r["tipo"] == config.TIPO_RECEITA
    assert r["categoria"] == "Salário" and r["item_fixo"] == "Salário"


def test_encargo_de_fatura_vai_para_tarifas():
    r = categorizacao.classificar("Juros de Crédito Rotativo (fatura)", -726.52,
                                  "cartao", regras())
    assert r["categoria"] == "Tarifas & Impostos"
    assert r["item_fixo"] == "Encargos de fatura"


def test_valor_positivo_no_cartao_e_estorno():
    r = categorizacao.classificar("Mercadolivre*Mercadol", 22.49, "cartao", regras())
    assert r["tipo"] == config.TIPO_DESPESA
    assert "(estorno)" in r["subcategoria"]


def test_descricao_sem_regra_cai_em_outros():
    r = categorizacao.classificar("XPTO COMERCIO LTDA", -42.0, "cartao", regras())
    assert r["categoria"] == "Outros"


def test_pix_recebido_desconhecido_e_outras_receitas():
    r = categorizacao.classificar("PIX RECEBIDO Fulano de Tal", 300.0, "conta", regras())
    assert r["tipo"] == config.TIPO_RECEITA
    assert r["categoria"] == "Outras Receitas"


def test_regex_invalida_nao_derruba_a_importacao():
    """Regra digitada errado na tela não pode impedir o mês de entrar."""
    compiladas = categorizacao.compilar([
        {"padrao": "[sem fechar", "categoria": "X", "subcategoria": "", "item_fixo": "",
         "tipo": "", "ativa": True},
        {"padrao": "SPOTIFY", "categoria": "Assinaturas", "subcategoria": "Streaming",
         "item_fixo": "", "tipo": "", "ativa": True},
    ])
    assert len(compiladas) == 1
    assert categorizacao.classificar("Dm *Spotify", -23.90, "cartao",
                                     compiladas)["categoria"] == "Assinaturas"


def test_regra_desativada_e_ignorada():
    compiladas = categorizacao.compilar([
        {"padrao": "SPOTIFY", "categoria": "Assinaturas", "subcategoria": "",
         "item_fixo": "", "tipo": "", "ativa": False}])
    assert compiladas == []


def test_ordem_decide_o_empate():
    """Duas regras casam com a mesma descrição: vale a primeira."""
    compiladas = categorizacao.compilar([
        {"padrao": "AMAZON", "categoria": "Primeira", "subcategoria": "", "item_fixo": "",
         "tipo": "", "ativa": True},
        {"padrao": "AMAZON", "categoria": "Segunda", "subcategoria": "", "item_fixo": "",
         "tipo": "", "ativa": True},
    ])
    assert categorizacao.classificar("AMAZON BR", -100.0, "cartao",
                                     compiladas)["categoria"] == "Primeira"
