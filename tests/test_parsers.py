# -*- coding: utf-8 -*-
"""
Testes dos leitores de arquivo.

Os que dependem de arquivo real do banco (fatura em PDF com senha) são pulados
quando a pasta ou a senha não estão disponíveis, para o conjunto continuar
rodando em qualquer máquina e no CI.
"""

from __future__ import annotations

import datetime as dt
import glob
import os

import pytest

from core import parsers

PASTAS = [
    os.path.expanduser("~/Library/CloudStorage/GoogleDrive-vr.alencar@gmail.com/"
                       "Meu Drive/_Controle Financeiro"),
    os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/"
                       "_Controle Financeiro"),
]
SENHA = os.environ.get("SENHA_PDF_SANTANDER", "")


def pasta():
    for p in PASTAS:
        if os.path.isdir(p):
            return p
    return None


# ------------------------------------------------------------------ números

@pytest.mark.parametrize("entrada,esperado", [
    ("1.234,56", 1234.56),
    ("26,90", 26.90),
    ("-R$ 89,90", -89.90),
    ("− 568,74", -568.74),          # menos unicode, como o Nubank exporta
    ("(45,00)", -45.00),            # parênteses = negativo, como na planilha
    ("R$ 1.234,56", 1234.56),
    ("- 2.692,24", -2692.24),       # com espaço depois do sinal
    ("1234.56", 1234.56),           # já em formato inglês
    ("", None),
    ("abacaxi", None),
])
def test_num_br(entrada, esperado):
    assert parsers.num_br(entrada) == esperado


@pytest.mark.parametrize("entrada,esperado", [
    ("2026-08-07", dt.date(2026, 8, 7)),
    ("07/08/2026", dt.date(2026, 8, 7)),
    ("07/08/26", dt.date(2026, 8, 7)),
])
def test_data_br(entrada, esperado):
    assert parsers.data_br(entrada) == esperado


def test_data_br_precisa_de_ano_quando_o_arquivo_nao_traz():
    assert parsers.data_br("07/08") is None
    assert parsers.data_br("07/08", 2026) == dt.date(2026, 8, 7)


# ------------------------------------------------------------- competência

@pytest.mark.parametrize("nome,esperado", [
    ("Nubank_2026-08-17.csv", dt.date(2026, 8, 1)),
    ("Santander Fatura_082026_VITOR_9662.PDF", dt.date(2026, 8, 1)),
    ("NU_74646779_01AGO2026_06AGO2026.pdf", dt.date(2026, 8, 1)),
])
def test_competencia_do_nome(nome, esperado):
    assert parsers.competencia_do_nome(nome) == esperado


@pytest.mark.parametrize("nome,esperado", [
    ("Nubank_2026-08-17.csv", "Cartão Nubank"),
    ("NU_74646779_01AGO2026_06AGO2026.pdf", "Conta Nubank"),
    ("Santander Fatura_082026_VITOR_9662.PDF", "Cartão Santander"),
    ("Santander Extrato - ABC.pdf", "Conta Santander"),
])
def test_conta_do_nome(nome, esperado):
    assert parsers.conta_do_nome(nome) == esperado


# ---------------------------------------------------------- linha contábil

def test_pagamento_recebido_nao_e_gasto():
    """A fatura lista o pagamento da fatura anterior como crédito. Se isso
    entrasse como lançamento, o mês contaria o gasto duas vezes."""
    assert parsers.linha_contabil("Pagamento recebido")
    assert parsers.linha_contabil("Saldo em atraso")


def test_estorno_e_encargo_entram():
    """Estorno e juros são dinheiro de verdade — não são linha de fechamento."""
    assert not parsers.linha_contabil("Estorno de compra (Airbnb)")
    assert not parsers.linha_contabil("Juros de rotativo")
    assert not parsers.linha_contabil("IOF de compra internacional")


# ----------------------------------------------------- CSV fatura Nubank

CSV_NUBANK = (
    "date,title,amount\n"
    "2026-08-07,Google Youtubepremium,\"26,90\"\n"
    "2026-07-29,Google Workspace_sicad,\"50,00\"\n"
    "2026-07-29,Google Workspace_sicad,\"50,00\"\n"
    "2026-07-16,Pagamento recebido,\"- 2.692,24\"\n"
    "2026-07-13,Estorno de compra (Airbnb),\"- 568,74\"\n"
).encode("utf-8")


def test_csv_nubank_fatura():
    r = parsers.ler("Nubank_2026-08-17.csv", CSV_NUBANK)

    # o pagamento sai; as outras 4 ficam
    assert len(r.linhas) == 4
    assert all(l["conta"] == "Cartão Nubank" for l in r.linhas)
    assert all(l["competencia"] == dt.date(2026, 8, 1) for l in r.linhas)

    # compra vira saída (negativo)
    compra = [l for l in r.linhas if l["descricao"] == "Google Youtubepremium"][0]
    assert compra["valor"] == -26.90

    # estorno é entrada (positivo) — dinheiro que voltou
    estorno = [l for l in r.linhas if "Estorno" in l["descricao"]][0]
    assert estorno["valor"] == 568.74

    # as DUAS cobranças iguais de 29/07 são preservadas na leitura;
    # quem decide sobre repetição é a deduplicação, não o parser
    iguais = [l for l in r.linhas if l["descricao"] == "Google Workspace_sicad"]
    assert len(iguais) == 2


def test_csv_nubank_exige_competencia_no_nome():
    """Compra de 31/07 entra na fatura de agosto: a competência tem de vir do
    nome do arquivo, nunca da data da compra."""
    with pytest.raises(parsers.ErroDeLeitura):
        parsers.ler("fatura.csv", CSV_NUBANK)


def test_csv_resumo():
    dados = (
        "conta,competencia,saldo_anterior,despesas,encargos,creditos,pagamentos,"
        "total_informado\n"
        "Cartão Santander,2026-07,13015.43,8477.08,739.20,0.02,8500.00,13731.69\n"
    ).encode("utf-8")
    r = parsers.ler("resumo_santander_072026.csv", dados)
    assert not r.linhas and len(r.resumos) == 1
    resumo = r.resumos[0]
    calculado = (resumo["saldo_anterior"] + resumo["despesas"] + resumo["encargos"]
                 - resumo["creditos"] - resumo["pagamentos"])
    assert round(calculado, 2) == resumo["total_informado"]


def test_ofx():
    dados = (
        "<OFX><BANKMSGSRSV1><STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260803120000"
        "<TRNAMT>-180.00<MEMO>PIX ENVIADO Lucia Helena</STMTTRN>"
        "<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260804<TRNAMT>12742.33"
        "<MEMO>LIQUIDO DE VENCIMENTO</STMTTRN></BANKMSGSRSV1></OFX>"
    ).encode("latin-1")
    r = parsers.ler("Santander Extrato ago.ofx", dados)
    assert len(r.linhas) == 2
    assert r.linhas[0]["valor"] == -180.0
    assert r.linhas[1]["valor"] == 12742.33
    assert r.linhas[0]["conta"] == "Conta Santander"


# -------------------------------------------- fatura Santander de verdade

@pytest.mark.skipif(not SENHA, reason="SENHA_PDF_SANTANDER não configurada")
def test_fatura_santander_fecha_com_o_total_do_app():
    """
    O teste que importa: para cada fatura de 2026, o resumo extraído tem de
    reconstruir exatamente o total que o app do banco mostra, e a soma dos itens
    tem de fechar com as despesas declaradas.
    """
    base = pasta()
    if not base:
        pytest.skip("pasta _Controle Financeiro não encontrada nesta máquina")
    faturas = sorted(glob.glob(os.path.join(base, "Santander Fatura_*.PDF")))
    if not faturas:
        pytest.skip("nenhuma fatura do Santander na pasta")

    for caminho in faturas:
        nome = os.path.basename(caminho)
        with open(caminho, "rb") as fh:
            r = parsers.ler(nome, fh.read(), SENHA)

        assert len(r.resumos) == 1, nome
        s = r.resumos[0]
        calculado = (s["saldo_anterior"] + s["despesas"] + s["encargos"]
                     - s["creditos"] - s["pagamentos"])
        assert abs(calculado - s["total_informado"]) < 0.02, (
            "%s: reconstruí %.2f e a fatura declara %.2f"
            % (nome, calculado, s["total_informado"]))

        # a soma dos lançamentos precisa igualar despesas + encargos − créditos
        soma = sum(l["valor"] for l in r.linhas)
        esperado = -(s["despesas"] + s["encargos"] - s["creditos"])
        assert abs(soma - esperado) < 0.02, (
            "%s: itens somam %.2f e o resumo pede %.2f" % (nome, soma, esperado))


@pytest.mark.skipif(not SENHA, reason="SENHA_PDF_SANTANDER não configurada")
def test_juros_de_credito_rotativo_de_julho():
    """
    Regressão do bug que custou R$ 726,52.

    O parser antigo procurava só o rótulo "Juros Remuneratórios". Na fatura de
    jul/2026 o Santander escreveu "Juros de Crédito Rotativo" e o valor
    simplesmente não entrou — sem erro, sem aviso.
    """
    base = pasta()
    if not base:
        pytest.skip("pasta não encontrada")
    achados = glob.glob(os.path.join(base, "Santander Fatura_072026*.PDF"))
    if not achados:
        pytest.skip("fatura de jul/2026 não está na pasta")

    with open(achados[0], "rb") as fh:
        r = parsers.ler(os.path.basename(achados[0]), fh.read(), SENHA)

    assert abs(r.resumos[0]["encargos"] - 739.20) < 0.01
    juros = [l for l in r.linhas if "Rotativo" in l["descricao"]]
    assert juros and abs(juros[0]["valor"] + 726.52) < 0.01
    assert abs(sum(l["valor"] for l in r.linhas) + 9216.26) < 0.02
