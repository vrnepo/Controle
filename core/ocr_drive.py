"""
OCR de imagens via Google Drive — para os prints de tela do app do banco.

O Drive converte imagem em Documento Google fazendo OCR no caminho (o mesmo
truque que a Ponte do SICAD usava). Custa zero, não adiciona dependência
pesada e usa a MESMA conta de serviço do espelho — só exige a Google Drive
API ativa no projeto, que já está (Etapa 6 do DEPLOY.md).

Fluxo: sobe a imagem pedindo conversão para Doc com ocrLanguage=pt →
exporta o Doc como texto puro → apaga o arquivo temporário.
"""

from __future__ import annotations

import json

from core import config

ESCOPOS = ["https://www.googleapis.com/auth/drive.file"]


class OcrIndisponivel(Exception):
    """Sem credencial ou falha na conversão — a mensagem explica o que fazer."""


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


def texto_de_imagem(nome: str, dados: bytes, content_type: str = "image/png") -> str:
    """Devolve o texto reconhecido na imagem. Levanta OcrIndisponivel com o
    motivo em português se algo impedir."""
    sessao = _sessao()
    limite = "===fronteira-ocr==="
    metadados = json.dumps({"name": "[ocr temporário] " + nome,
                            "mimeType": "application/vnd.google-apps.document"})
    corpo = (
        ("--%s\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n%s\r\n"
         % (limite, metadados)).encode("utf-8")
        + ("--%s\r\nContent-Type: %s\r\n\r\n" % (limite, content_type)).encode("utf-8")
        + dados
        + ("\r\n--%s--\r\n" % limite).encode("utf-8"))

    resposta = sessao.post(
        "https://www.googleapis.com/upload/drive/v3/files"
        "?uploadType=multipart&ocrLanguage=pt",
        data=corpo,
        headers={"Content-Type": "multipart/related; boundary=" + limite},
        timeout=120)
    if resposta.status_code >= 300:
        raise OcrIndisponivel("O Drive recusou a conversão da imagem (%d): %s"
                              % (resposta.status_code, resposta.text[:200]))
    arquivo_id = resposta.json().get("id", "")

    try:
        exportado = sessao.get(
            "https://www.googleapis.com/drive/v3/files/%s/export?mimeType=text/plain"
            % arquivo_id, timeout=120)
        if exportado.status_code >= 300:
            raise OcrIndisponivel("Falha ao ler o texto reconhecido (%d)."
                                  % exportado.status_code)
        return exportado.content.decode("utf-8", errors="replace")
    finally:
        # o temporário nunca fica no Drive, nem em caso de erro
        try:
            sessao.delete("https://www.googleapis.com/drive/v3/files/" + arquivo_id,
                          timeout=30)
        except Exception:
            pass
