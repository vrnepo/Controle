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
from typing import Any, Dict, List

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


def _palavras_da_anotacao(anotacao: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Achata a fullTextAnnotation em palavras com posição (x, topo, base)."""
    saida: List[Dict[str, Any]] = []
    for pagina in anotacao.get("pages", []):
        for bloco in pagina.get("blocks", []):
            for paragrafo in bloco.get("paragraphs", []):
                for palavra in paragrafo.get("words", []):
                    texto = "".join(s.get("text", "")
                                    for s in palavra.get("symbols", []))
                    vertices = (palavra.get("boundingBox") or {}).get("vertices") or []
                    if not texto.strip() or not vertices:
                        continue
                    xs = [v.get("x", 0) for v in vertices]
                    ys = [v.get("y", 0) for v in vertices]
                    saida.append({"texto": texto, "x": min(xs), "fim": max(xs),
                                  "topo": min(ys), "base": max(ys)})
    return saida


def _linhas_por_posicao(palavras: List[Dict[str, Any]]) -> str:
    """
    Reconstrói as linhas VISUAIS pela posição das palavras — a correção da
    quase-duplicata de 10/08/2026. O texto corrido da Vision (.text) veio com
    valores da coluna da direita DESLOCADOS: o "R$ 120,00" de um Pix caiu
    depois do cabeçalho de data seguinte, e a movimentação saiu com descrição
    e data de outra transação — furando a deduplicação. Aqui cada linha da
    tela vira uma linha de texto: palavras cujo centro vertical cai na faixa
    da linha corrente pertencem a ela, ordenadas da esquerda para a direita —
    contraparte e valor saem JUNTOS, na ordem em que aparecem na tela.
    """
    if not palavras:
        return ""
    palavras = sorted(palavras, key=lambda p: (p["topo"] + p["base"]) / 2)
    linhas: List[List[Dict[str, Any]]] = []
    for p in palavras:
        centro = (p["topo"] + p["base"]) / 2
        if linhas:
            atual = linhas[-1]
            topo = sum(q["topo"] for q in atual) / len(atual)
            base = sum(q["base"] for q in atual) / len(atual)
            if topo <= centro <= base:
                atual.append(p)
                continue
        linhas.append([p])
    return "\n".join(_texto_da_linha(linha) for linha in linhas)


def _texto_da_linha(linha: List[Dict[str, Any]]) -> str:
    """
    Junta as palavras de uma linha visual respeitando o ESPAÇAMENTO real
    entre as caixas: a Vision fatia tokens em pedaços ("6.580" "," "38";
    "-" "R$") e juntar tudo com espaço quebrava o padrão de valor do
    extrato_de_print — foi o "Não reconheci movimentações" de 10/08/2026 na
    reimportação. Pedaços praticamente colados (folga proporcional à altura
    da linha) se emendam sem espaço; o resto ganha espaço normal.
    """
    linha = sorted(linha, key=lambda q: q["x"])
    altura = sum(q["base"] - q["topo"] for q in linha) / len(linha)
    folga = max(3.0, altura * 0.2)
    partes = [linha[0]["texto"]]
    for anterior, seguinte in zip(linha, linha[1:]):
        sep = "" if (seguinte["x"] - anterior["fim"]) <= folga else " "
        partes.append(sep + seguinte["texto"])
    return "".join(partes)


def texto_de_imagem(dados: bytes) -> str:
    """
    Devolve o texto reconhecido na imagem (a Vision identifica o formato
    pelos próprios bytes — não precisa de nome nem content-type). Levanta
    OcrIndisponivel com o motivo em português se algo impedir.

    DOCUMENT_TEXT_DETECTION em vez de TEXT_DETECTION: o print do app é texto
    denso organizado em linhas. As linhas devolvidas NÃO são o .text corrido
    da API — são reconstruídas pela posição das palavras (_linhas_por_posicao),
    porque a ordem do .text embaralhou coluna esquerda e direita em produção.
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
    anotacao = corpo.get("fullTextAnnotation") or {}
    linhas = _linhas_por_posicao(_palavras_da_anotacao(anotacao))
    return linhas or anotacao.get("text", "")
