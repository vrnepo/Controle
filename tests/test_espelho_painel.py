# -*- coding: utf-8 -*-
"""
O ajustador do Painel Mensal — a parte pura (transformação de fórmula).
As fórmulas dos testes são as REAIS da planilha, na forma canônica da API.
"""

from __future__ import annotations

from core.espelho import _para_dialeto_pt, _sumifs_com_extrato, _trocar_coluna

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


# --------------------------------------------- réplica da coluna Previsão

def test_troca_o_subtotal_para_a_propria_coluna():
    """A réplica em B tem de somar a si mesma, não a coluna de origem."""
    assert _trocar_coluna("=SUM($C7:$C15)", "C", "B") == "=SUM($B7:$B15)"


def test_troca_referencias_relativas_e_mistas():
    assert _trocar_coluna("=C6-C7+$C$24", "C", "B") == "=B6-B7+$B$24"


def test_nao_troca_referencia_qualificada_de_outra_aba():
    f = "=SUMIFS(Faturas!$C$4:$C$27,Faturas!C4,$F$4)"
    assert _trocar_coluna(f, "C", "B") == f


def test_nao_troca_dentro_de_aspas_nem_nome_de_funcao():
    """O C de COUNTIFS não é referência (sem dígito depois) e "C7" entre
    aspas é texto — só o C7 solto no fim pode virar B7."""
    f = '=IF(COUNTIFS(Faturas!$A$4:$A$27,"<="&$F$4),"C7 no texto",C7)'
    assert _trocar_coluna(f, "C", "B") == (
        '=IF(COUNTIFS(Faturas!$A$4:$A$27,"<="&$F$4),"C7 no texto",B7)')


def test_formula_real_dos_grupos_fica_intacta():
    """As SUMIFS dos grupos só referenciam Lançamentos e $F$4 — a réplica
    delas é idêntica à origem."""
    f = ("=SUMIFS('Lançamentos'!$J$4:$J$2177,'Lançamentos'!$G$4:$G$2177,"
         "\"Cozinheira\",'Lançamentos'!$K$4:$K$2177,$F$4)")
    assert _trocar_coluna(f, "C", "B") == f


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
