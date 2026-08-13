# -*- coding: utf-8 -*-
"""
Diferença justificada na conciliação — o caso de origem é o estorno Airbnb
(+568,74) que consta na fatura de ago/26 mas fica em jul/26 por decisão do
usuário (13/08/2026). Os números dos testes são os REAIS desse mês.
"""

from __future__ import annotations

import datetime as dt

from core import conciliacao, repositorio

JUL = dt.date(2026, 7, 1)


def _cenario(monkeypatch, gasto_total=-2692.24, justificativas=None):
    """Nubank jul/26 real: resumo fecha em 3.260,97 e os lançamentos somam
    2.692,24 porque o estorno de 568,74 foi mantido em julho."""
    monkeypatch.setattr(repositorio, "gasto_por_conta", lambda: [
        {"competencia": JUL, "conta": "Cartão Nubank", "tipo": "cartao",
         "total": gasto_total}])
    monkeypatch.setattr(repositorio, "resumos", lambda: [
        {"conta": "Cartão Nubank", "competencia": JUL, "saldo_anterior": -258.01,
         "despesas": 3511.23, "encargos": 7.75, "creditos": 0, "pagamentos": 0,
         "total_informado": 3260.98}])
    monkeypatch.setattr(repositorio, "justificativas",
                        lambda: justificativas or [])
    return conciliacao.linhas(JUL)[0]


def test_sem_justificativa_o_alarme_continua(monkeypatch):
    linha = _cenario(monkeypatch)
    assert linha["situacao"] == "importacao_incompleta"
    assert linha["delta_importacao"] == -568.73
    assert linha["explicacao"].startswith("Faltam R$ 568,73")


def test_justificativa_com_o_mesmo_delta_silencia_o_alarme(monkeypatch):
    linha = _cenario(monkeypatch, justificativas=[
        {"conta": "Cartão Nubank", "competencia": JUL, "delta": -568.73,
         "motivo": "Estorno Airbnb mantido em julho por decisão de 13/08."}])
    assert linha["situacao"] == "justificada"
    assert "Estorno Airbnb" in linha["explicacao"]
    assert "R$ 568,73" in linha["explicacao"]


def test_delta_diferente_do_justificado_traz_o_alarme_de_volta(monkeypatch):
    """A exceção é do VALOR aceito, não do mês: se o mês divergir por outro
    motivo, a justificativa velha não pode esconder o problema novo."""
    linha = _cenario(monkeypatch, gasto_total=-2500.00, justificativas=[
        {"conta": "Cartão Nubank", "competencia": JUL, "delta": -568.73,
         "motivo": "Estorno Airbnb mantido em julho por decisão de 13/08."}])
    assert linha["situacao"] == "importacao_incompleta"
    assert "mas o Δ atual é outro" in linha["explicacao"]


def test_delta_positivo_diz_sobram_nao_faltam(monkeypatch):
    """Quando o resumo de ago/26 entrar, o mesmo estorno aparecerá na direção
    oposta: lançamentos somando MAIS que o resumo."""
    linha = _cenario(monkeypatch, gasto_total=-3829.70)
    assert linha["situacao"] == "importacao_incompleta"
    assert linha["explicacao"].startswith("Sobram R$ 568,73")
