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
