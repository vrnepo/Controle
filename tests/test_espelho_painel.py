# -*- coding: utf-8 -*-
"""
O ajustador do Painel Mensal — a parte pura (transformação de fórmula).
As fórmulas dos testes são as REAIS da planilha, na forma canônica da API.
"""

from __future__ import annotations

from core.espelho import _sumifs_com_extrato

CRITERIO = ",'Lançamentos'!$B$4:$B$2177,\"Extrato\""


def test_adiciona_o_criterio_no_fim_do_sumifs():
    f = ("=SUMIFS('Lançamentos'!$J$4:$J$2177,'Lançamentos'!$G$4:$G$2177,"
         "\"Cozinheira\",'Lançamentos'!$K$4:$K$2177,$E$4)")
    nova = _sumifs_com_extrato(f)
    assert nova.endswith(CRITERIO + ")")
    assert nova.count("SUMIFS(") == 1


def test_parenteses_dentro_das_aspas_nao_enganam():
    """O critério "Telefone (Vivo/Telefônica)" tem parênteses DENTRO da
    string — um casador ingênuo fecharia o SUMIFS no lugar errado."""
    f = ("=SUMIFS('Lançamentos'!$J$4:$J$2177,'Lançamentos'!$G$4:$G$2177,"
         "\"Telefone (Vivo/Telefônica)\",'Lançamentos'!$K$4:$K$2177,$E$4)")
    nova = _sumifs_com_extrato(f)
    # o critério novo entra DEPOIS do critério com parênteses, não no meio
    assert nova.endswith("$E$4" + CRITERIO + ")")
    assert "\"Telefone (Vivo/Telefônica)\"" in nova


def test_so_o_sumifs_recebe_o_criterio_nao_o_countifs():
    """Coluna Média: IFERROR(SUMIFS(...)/COUNTIFS(Faturas!...)) — só o
    numerador olha os Lançamentos; o COUNTIFS conta meses e fica intacto."""
    f = ("=IFERROR(SUMIFS('Lançamentos'!$J$4:$J$2177,'Lançamentos'!$G$4:$G$2177,"
         "\"Salário\")/COUNTIFS(Faturas!$A$4:$A$27,\"<=\"&$E$4),\"\")")
    nova = _sumifs_com_extrato(f)
    assert "\"Salário\"" + CRITERIO + ")" in nova
    assert "COUNTIFS(Faturas!$A$4:$A$27,\"<=\"&$E$4)" in nova   # intocado


def test_idempotente():
    f = ("=SUMIFS('Lançamentos'!$J$4:$J$2177,'Lançamentos'!$G$4:$G$2177,"
         "\"Diarista\",'Lançamentos'!$K$4:$K$2177,$E$4)")
    uma_vez = _sumifs_com_extrato(f)
    assert _sumifs_com_extrato(uma_vez) == uma_vez


def test_sumifs_sem_lancamentos_fica_como_esta():
    f = "=SUMIFS(Faturas!$D$4:$D$27,Faturas!$A$4:$A$27,$E$4)"
    assert _sumifs_com_extrato(f) == f
