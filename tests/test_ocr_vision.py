# -*- coding: utf-8 -*-
"""
Tradução das recusas da Vision API em instrução acionável (parte pura).
As mensagens de erro reais do Google que motivaram cada caso estão nos
próprios testes — billing ausente e API desativada são os dois tropeços
esperados na primeira execução em produção.
"""

from __future__ import annotations

from core.ocr_vision import explicar_recusa


def test_faturamento_ausente_vira_instrucao_de_billing():
    m = explicar_recusa(403, '{"error": {"code": 403, "message": "This API '
                        'method requires billing to be enabled."}}')
    assert "Faturamento" in m
    assert "1.000" in m


def test_api_desativada_vira_instrucao_de_ativacao():
    m = explicar_recusa(403, '{"error": {"message": "Cloud Vision API has '
                        'not been used in project 123 before or it is '
                        'disabled."}}')
    assert "Cloud Vision API" in m
    assert "Biblioteca" in m


def test_recusa_desconhecida_mostra_codigo_e_texto():
    m = explicar_recusa(429, '{"error": {"message": "Quota exceeded."}}')
    assert "429" in m
    assert "Quota exceeded" in m


# ------------------------------------ reconstrução das linhas pela posição

def _palavra(texto, x, topo, base, fim=None):
    # fim padrão: caixa proporcional ao texto (~15 px por caractere), como
    # numa fonte de ~30 px — o suficiente para os espaçamentos dos cenários
    return {"texto": texto, "x": x, "topo": topo, "base": base,
            "fim": fim if fim is not None else x + 15 * len(texto)}


def _cenario_do_drift():
    """
    A geometria do print real de 09/08 à noite, no trecho que quebrou em
    produção (10/08): o .text corrido da Vision soltou o "R$ 120,00" DEPOIS
    do cabeçalho "Terça, 4 de agosto", e o Pix recebido virou "Liquido de
    vencimento 120,00 em 04/08" — duplicando contra a transcrição à mão.
    A ordem da lista abaixo reproduz esse embaralhamento; as POSIÇÕES são a
    verdade da tela.
    """
    return [
        # Sexta, 7 de agosto (linha y 100-130); folga entre palavras = 10 px
        _palavra("Sexta,", 60, 100, 130), _palavra("7", 160, 100, 130),
        _palavra("de", 185, 100, 130), _palavra("agosto", 225, 100, 130),
        # título (y 140-170) e contraparte (y 180-210) do 2º Pix
        _palavra("Pix", 60, 140, 170), _palavra("recebido", 115, 140, 170),
        _palavra("Vitor", 60, 180, 210), _palavra("a", 145, 180, 210),
        _palavra("f", 170, 180, 210), _palavra("nepomuceno", 195, 180, 210),
        # Terça, 4 de agosto (y 220-250) — no .text corrido vinha ANTES do valor
        _palavra("Terça,", 60, 220, 250), _palavra("4", 160, 220, 250),
        _palavra("de", 185, 220, 250), _palavra("agosto", 225, 220, 250),
        # o valor do Pix, geometricamente na linha da contraparte (y 180-210)
        _palavra("R$", 700, 180, 210), _palavra("120,00", 740, 180, 210),
        # Liquido de vencimento (y 260-290) + contraparte com valor (y 300-330)
        _palavra("Liquido", 60, 260, 290), _palavra("de", 175, 260, 290),
        _palavra("vencimento", 215, 260, 290),
        _palavra("Municipio", 60, 300, 330),
        _palavra("04249873300014", 205, 300, 330),
        _palavra("R$", 680, 300, 330), _palavra("12.742,33", 720, 300, 330),
    ]


def test_pedacos_colados_se_emendam_e_espacos_reais_ficam():
    """A Vision fatia "-R$" e "6.580,38" em pedaços; juntar tudo com espaço
    quebrava o padrão de valor ("6.580 , 38") — foi o "Não reconheci
    movimentações" da reimportação de 10/08/2026. Pedaço colado emenda;
    espaço de verdade (folga maior que ~20% da altura) permanece."""
    from core.ocr_vision import _linhas_por_posicao
    linha = [
        _palavra("-", 88, 0, 30, fim=96),
        _palavra("R$", 100, 0, 30, fim=130),
        _palavra("6.580", 140, 0, 30, fim=215),
        _palavra(",", 216, 0, 30, fim=222),
        _palavra("38", 223, 0, 30, fim=253),
    ]
    assert _linhas_por_posicao(linha) == "-R$ 6.580,38"


def test_linhas_saem_na_ordem_da_tela_mesmo_com_texto_embaralhado():
    from core.ocr_vision import _linhas_por_posicao
    linhas = _linhas_por_posicao(_cenario_do_drift()).split("\n")
    assert linhas == [
        "Sexta, 7 de agosto",
        "Pix recebido",
        "Vitor a f nepomuceno R$ 120,00",
        "Terça, 4 de agosto",
        "Liquido de vencimento",
        "Municipio 04249873300014 R$ 12.742,33",
    ]


def test_drift_corrigido_de_ponta_a_ponta_no_extrato():
    """O caso de produção inteiro: posição → linhas → extrato_de_print.
    O 120,00 tem de sair como Pix recebido de 07/08 — não como Liquido de
    vencimento de 04/08 (o que duplicou o lançamento no banco)."""
    import datetime as dt

    from core import parsers
    from core.ocr_vision import _linhas_por_posicao

    r = parsers.extrato_de_print(
        "IMG.png", _linhas_por_posicao(_cenario_do_drift()))
    por_valor = {round(l["valor"], 2): l for l in r.linhas}
    assert por_valor[120.00]["descricao"] == "Pix recebido Vitor a f nepomuceno"
    assert por_valor[120.00]["data"] == dt.date(2026, 8, 7)
    assert por_valor[12742.33]["descricao"] == (
        "Liquido de vencimento Municipio 04249873300014")
    assert por_valor[12742.33]["data"] == dt.date(2026, 8, 4)


def test_palavras_da_anotacao_extrai_texto_e_caixa():
    from core.ocr_vision import _palavras_da_anotacao
    anotacao = {"pages": [{"blocks": [{"paragraphs": [{"words": [
        {"symbols": [{"text": "R$"}],
         "boundingBox": {"vertices": [{"x": 700, "y": 180}, {"x": 730, "y": 180},
                                      {"x": 730, "y": 210}, {"x": 700, "y": 210}]}},
        # vértice sem "x" (a API omite coordenada zero) não pode quebrar
        {"symbols": [{"text": "Oi"}],
         "boundingBox": {"vertices": [{"y": 5}, {"x": 20, "y": 5},
                                      {"x": 20, "y": 30}, {"y": 30}]}},
    ]}]}]}]}
    palavras = _palavras_da_anotacao(anotacao)
    assert palavras[0] == {"texto": "R$", "x": 700, "fim": 730,
                           "topo": 180, "base": 210}
    assert palavras[1]["x"] == 0 and palavras[1]["texto"] == "Oi"
