"""
OCR de imagens via Google Cloud Vision — para os prints de tela do app do banco.

Substitui o OCR por conversão no Drive (removido em 10/08/2026): contas de
serviço deixaram de ter QUALQUER cota de armazenamento no Drive (política do
Google desde 2025), e a conversão imagem→Documento cria um arquivo — por isso
o 403 "storage quota has been exceeded" veio logo na primeira imagem, com o
Drive do robô vazio. Não há plano pago que resolva: Google One não existe
para conta de serviço. A Vision API não guarda nada — manda os bytes,
recebe o texto — e usa a MESMA conta de serviço do espelho.

Requisitos no projeto GCP (uma vez, no console): Cloud Vision API ativada E
faturamento vinculado ao projeto (exigência do Google para esta API). As
primeiras 1.000 imagens/mês são gratuitas — o uso real daqui (alguns prints
por mês) fica em R$ 0. Quando faltar um dos dois, a recusa da API é
traduzida em instrução de onde ativar (explicar_recusa).
"""

from __future__ import annotations

import base64
import json

from core import config

ESCOPOS = ["https://www.googleapis.com/auth/cloud-platform"]
_URL = "https://vision.googleapis.com/v1/images:annotate"


class OcrIndisponivel(Exception):
    """Sem credencial ou falha no reconhecimento — a mensagem explica o que fazer."""


def _sessao():
    bruto = config.env("GCP_SERVICE_ACCOUNT_JSON")
    if not bruto:
        raise OcrIndisponivel(
            "Importação de print exige a conta de serviço do Google "
            "(GCP_SERVICE_ACCOUNT_JSON) — a mesma do espelho.")
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.service_account import Credentials

    info = json.loads(bruto)
    credenciais = Credentials.from_service_account_info(info, scopes=ESCOPOS)
    return AuthorizedSession(credenciais)


def explicar_recusa(codigo: int, texto: str) -> str:
    """
    Traduz a recusa da Vision API em instrução acionável, em português.
    Pura de propósito (testável sem rede). Os dois tropeços esperados na
    primeira execução são faturamento ausente e API não ativada — ambos se
    resolvem no console do Google Cloud, e a mensagem diz exatamente onde.
    """
    t = texto.lower()
    if "billing" in t:
        return ("O projeto do Google Cloud está sem faturamento — a Vision "
                "API exige um cartão vinculado (as 1.000 primeiras "
                "imagens/mês são gratuitas). Ative em "
                "console.cloud.google.com → Faturamento, no projeto da "
                "conta de serviço do espelho.")
    if "has not been used" in t or "is disabled" in t or "not enabled" in t:
        return ("A Cloud Vision API não está ativada no projeto da conta de "
                "serviço. Ative em console.cloud.google.com → APIs e "
                "serviços → Biblioteca → Cloud Vision API e tente de novo "
                "(a ativação leva ~1 minuto para valer).")
    return "A Vision API recusou a imagem (%d): %s" % (codigo, texto[:300])


def texto_de_imagem(dados: bytes) -> str:
    """
    Devolve o texto reconhecido na imagem (a Vision identifica o formato
    pelos próprios bytes — não precisa de nome nem content-type). Levanta
    OcrIndisponivel com o motivo em português se algo impedir.

    DOCUMENT_TEXT_DETECTION em vez de TEXT_DETECTION: o print do app é texto
    denso organizado em linhas, e o modo documento preserva melhor a ordem —
    é com essa ordem que o extrato_de_print monta título + contraparte.
    """
    sessao = _sessao()
    pedido = {"requests": [{
        "image": {"content": base64.b64encode(dados).decode("ascii")},
        "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
        "imageContext": {"languageHints": ["pt"]},
    }]}
    resposta = sessao.post(_URL, json=pedido, timeout=120)
    if resposta.status_code >= 300:
        raise OcrIndisponivel(explicar_recusa(resposta.status_code, resposta.text))
    corpo = (resposta.json().get("responses") or [{}])[0]
    if corpo.get("error"):
        erro = corpo["error"]
        raise OcrIndisponivel(explicar_recusa(int(erro.get("code", 0)),
                                              json.dumps(erro)))
    return (corpo.get("fullTextAnnotation") or {}).get("text", "")
