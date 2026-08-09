# -*- coding: utf-8 -*-
"""
O ajustador do Painel Mensal — a parte pura (transformação de fórmula).
As fórmulas dos testes são as REAIS da planilha, na forma canônica da API.
"""

from __future__ import annotations

from core.espelho import (_formula_pagamento, _para_dialeto_pt,
                          _sumifs_com_extrato, _valor_congelado)

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


# ---------------------------------------- congelamento da coluna Previsão

def test_congela_formula_no_valor_calculado_arredondado():
    """A fórmula vira o número calculado, sem poeira binária de float."""
    c = {"userEnteredValue": {"formulaValue": "=SUM($B7:$B15)"},
         "effectiveValue": {"numberValue": -180.00000000000003}}
    assert _valor_congelado(c) == -180.0


def test_congela_formula_vazia_em_celula_vazia():
    """Linha de pagamento sem pagamento: IFERROR devolvia "" — congela
    como célula vazia, pronta para o preenchimento manual."""
    c = {"userEnteredValue": {"formulaValue": '=IFERROR(INDEX(...),"")'}}
    assert _valor_congelado(c) == ""


def test_nao_toca_celula_sem_formula():
    """None = pular a célula: o que o usuário digitou fica como está."""
    assert _valor_congelado({"userEnteredValue": {"numberValue": 100.0}}) is None
    assert _valor_congelado({"userEnteredValue": {"stringValue": "meta"}}) is None
    assert _valor_congelado({}) is None


def test_congela_texto_com_protecao_anti_formula():
    c = {"userEnteredValue": {"formulaValue": "=A1"},
         "effectiveValue": {"stringValue": "=CMD"}}
    assert _valor_congelado(c) == "'=CMD"


# ------------------------------------------- pagamentos individualizados

def test_formula_do_pagamento_n_no_dialeto():
    """Linha do n-º pagamento (Cozinheira/Diarista): FILTER pega os
    pagamentos do mês, INDEX o n-º, IFERROR deixa em branco quando o mês
    teve menos pagamentos — tudo no dialeto pt-BR ao descer."""
    f = _para_dialeto_pt(_formula_pagamento("Cozinheira", 3))
    assert f.startswith("=IFERROR(INDEX(FILTER('Lançamentos'!$J$4:$J$2177;")
    assert "'Lançamentos'!$G$4:$G$2177=\"Cozinheira\"" in f
    assert "'Lançamentos'!$K$4:$K$2177=$F$4" in f
    assert "'Lançamentos'!$B$4:$B$2177=\"Extrato\"" in f
    assert f.endswith(";3);\"\")")
    assert "," not in f


def test_formula_do_pagamento_sem_sumifs_escapa_do_auto_reparo():
    """A fase 1 do ajustador só regrava fórmulas com SUMIFS — as linhas de
    pagamento não podem ser capturadas por ela."""
    assert "SUMIFS(" not in _formula_pagamento("Diarista", 1)


# ------------------------------------------------- transporte de saldo

def _lanc(conta, comp, valor, banco="Santander"):
    import datetime as dt
    return {"banco": banco, "fonte": "Extrato", "data": comp,
            "descricao": "x", "categoria": "", "subcategoria": "",
            "item_fixo": "", "conta": conta, "tipo": "Despesa",
            "valor": valor, "competencia": comp, "status": "Confirmado",
            "arquivo": "t"}


def test_transporte_acumula_o_saldo_dos_meses_anteriores():
    import datetime as dt
    from core.espelho import _transportes_de_saldo
    jan, fev, mar = dt.date(2026, 1, 1), dt.date(2026, 2, 1), dt.date(2026, 3, 1)
    lanc = [_lanc("Conta Santander", jan, -246.32),
            _lanc("Conta Santander", fev, 784.33),
            _lanc("Conta Santander", mar, 100.00)]
    t = _transportes_de_saldo(lanc, ["Conta Santander"])
    # 1º mês não tem transporte; fev carrega jan; mar carrega jan+fev
    assert [(x["competencia"], x["valor"]) for x in t] == [
        (fev, -246.32), (mar, 538.01)]
    # e as linhas são inertes para as análises: tipo próprio, sem item fixo
    assert all(x["tipo"] == "Saldo" and x["item_fixo"] == "" for x in t)


def test_transporte_ignora_cartoes_e_zero():
    import datetime as dt
    from core.espelho import _transportes_de_saldo
    jan, fev = dt.date(2026, 1, 1), dt.date(2026, 2, 1)
    lanc = [_lanc("Cartão Santander", jan, -100.0),      # cartão: fora
            _lanc("Conta Nubank", jan, 50.0, "Nubank"),
            _lanc("Conta Nubank", fev, -50.0, "Nubank"),
            _lanc("Conta Santander", jan, 0.0),          # saldo zero: sem linha
            _lanc("Conta Santander", fev, 10.0)]
    t = _transportes_de_saldo(lanc, ["Conta Santander", "Conta Nubank"])
    contas = {(x["conta"], x["competencia"]): x["valor"] for x in t}
    assert ("Conta Nubank", fev) in contas and contas[("Conta Nubank", fev)] == 50.0
    # Conta Santander: acumulado até jan é 0 → nenhum transporte
    assert not any(c == "Conta Santander" for c, _ in contas)
    assert not any(x["conta"].startswith("Cartão") for x in t)


# ------------------------------------------------------- dialeto pt-BR

def test_dialeto_troca_virgula_por_ponto_e_virgula():
    """A API lê fórmulas em forma canônica (vírgulas) mas TODA escrita é
    interpretada na localidade da planilha — gravar vírgula no pt-BR foi o
    que encheu o Painel Mensal de #ERROR! em 09/08/2026."""
    f = "=SUMIFS('Lançamentos'!$J$4:$J$2177,'Lançamentos'!$K$4:$K$2177,$E$4)"
    assert _para_dialeto_pt(f) == (
        "=SUMIFS('Lançamentos'!$J$4:$J$2177;'Lançamentos'!$K$4:$K$2177;$E$4)")


def test_dialeto_preserva_virgula_dentro_de_aspas():
    f = '=IF(A1=0,"sem valor, confira",SUMIFS(B:B,C:C,"x"))'
    assert _para_dialeto_pt(f) == (
        '=IF(A1=0;"sem valor, confira";SUMIFS(B:B;C:C;"x"))')


def test_pipeline_completo_criterio_mais_dialeto():
    """O caminho real da sincronização: canônica → critério → pt-BR."""
    f = ("=SUMIFS('Lançamentos'!$J$4:$J$2177,'Lançamentos'!$G$4:$G$2177,"
         "\"Telefone (Vivo/Telefônica)\",'Lançamentos'!$K$4:$K$2177,$E$4)")
    final = _para_dialeto_pt(_sumifs_com_extrato(f))
    assert final.endswith(";'Lançamentos'!$B$4:$B$2177;\"Extrato\")")
    assert "," not in final.replace('"Telefone (Vivo/Telefônica)"', "")
