# -*- coding: utf-8 -*-
"""
Leitor de print de tela do app Santander (extrato parcial via OCR).
O texto abaixo é o do print real de 09/08/2026, na forma que o OCR devolve.
"""

from __future__ import annotations

import datetime as dt

import pytest

from core import parsers

TEXTO_PRINT = """
16:21
R$ 15.319,99
Filtrar
Saldo disponível
R$ 15.319,99
Saldo + Limite: R$ 23.319,99
Entenda seu limite
Última atualização às 16:16:09
Atualizar
Sexta, 7 de agosto
Pix recebido
Vitor alencar farias nepo R$ 1.771,72
Pix recebido
Vitor a f nepomuceno R$ 120,00
Terça, 4 de agosto
Liquido de vencimento
Municipio 04249873300014 R$ 12.742,33
Segunda, 3 de agosto
Remuneracao aplicacao automatica
R$ 0,01
Pix enviado
Lucia helena moreira de s -R$ 180,00
"""


def test_print_santander_reconhece_as_cinco_movimentacoes():
    r = parsers.extrato_de_print("IMG_2026.png", TEXTO_PRINT)
    assert len(r.linhas) == 5
    assert all(l["conta"] == "Conta Santander" for l in r.linhas)

    por_valor = {round(l["valor"], 2): l for l in r.linhas}
    # entradas
    assert por_valor[1771.72]["data"] == dt.date(2026, 8, 7)
    assert "Pix recebido Vitor alencar farias nepo" == por_valor[1771.72]["descricao"]
    assert por_valor[120.00]["data"] == dt.date(2026, 8, 7)
    assert por_valor[12742.33]["data"] == dt.date(2026, 8, 4)
    assert por_valor[0.01]["descricao"] == "Remuneracao aplicacao automatica"
    # saída, com o sinal vindo do "-R$"
    assert por_valor[-180.00]["data"] == dt.date(2026, 8, 3)
    assert "Lucia helena" in por_valor[-180.00]["descricao"]


def test_print_extrai_o_saldo_como_aviso_nao_como_lancamento():
    """O saldo do topo (15.319,99) NÃO pode virar lançamento — é estoque, não
    movimentação. Ele vai como aviso, para a conferência de conciliação."""
    r = parsers.extrato_de_print("IMG_2026.png", TEXTO_PRINT)
    assert not any(abs(l["valor"]) > 13000 for l in r.linhas)
    assert any("15319.99" in a or "15.319,99" in a or "15319,99" in a
               for a in r.avisos), r.avisos


def test_print_dedup_casa_com_o_que_foi_transcrito_a_mao():
    """As descrições compostas ("Pix recebido Fulano") têm de normalizar
    igual às transcritas à mão ("PIX RECEBIDO Fulano") — senão a importação
    do print duplicaria o que já entrou."""
    from core.categorizacao import normalizar
    r = parsers.extrato_de_print("IMG_2026.png", TEXTO_PRINT)
    descricoes = {normalizar(l["descricao"]) for l in r.linhas}
    assert "PIX RECEBIDO VITOR ALENCAR FARIAS NEPO" in descricoes
    assert "LIQUIDO DE VENCIMENTO MUNICIPIO 04249873300014" in descricoes
    assert "REMUNERACAO APLICACAO AUTOMATICA" in descricoes


def test_print_sem_movimentacao_avisa():
    with pytest.raises(parsers.ErroDeLeitura):
        parsers.extrato_de_print("IMG.png", "Saldo disponível\nR$ 10,00\n")
