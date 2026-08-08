"""
Controle Financeiro 3.0 — API e servidor.

Mesmo desenho do SICAD: FastAPI servindo uma interface estática em
HTML/CSS/JS puro, banco Postgres no Neon como fonte da verdade e planilha do
Google como espelho só de saída.

    uvicorn main:app --reload            (desenvolvimento)
    bash run_dev.sh                      (com o venv já pronto)
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()   # antes de importar core.*, que lê o ambiente na chamada

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner  # noqa: E402

from core import (bd, categorizacao, conciliacao, config, espelho,  # noqa: E402
                  importacao, repositorio, usuarios)

AQUI = os.path.dirname(os.path.abspath(__file__))
ESTATICO = os.path.join(AQUI, "static")

app = FastAPI(title=config.APP_NOME, version=config.APP_VERSAO, docs_url=None,
              redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=ESTATICO), name="static")

COOKIE = "financas_sessao"
VALIDADE_SESSAO = 60 * 60 * 12        # 12 h
TAMANHO_MAXIMO = 15 * 1024 * 1024     # 15 MB por arquivo

_signer = TimestampSigner(config.secret_key())


# ------------------------------------------------------------------ sessão

def _assinar(email: str) -> str:
    return _signer.sign(email.encode("utf-8")).decode("utf-8")


def _ler_sessao(request: Request) -> Optional[str]:
    bruto = request.cookies.get(COOKIE)
    if not bruto:
        return None
    try:
        return _signer.unsign(bruto, max_age=VALIDADE_SESSAO).decode("utf-8")
    except (BadSignature, SignatureExpired):
        return None


def exigir_login(request: Request) -> str:
    email = _ler_sessao(request)
    if not email:
        raise HTTPException(status_code=401, detail="Sessão expirada. Entre de novo.")
    return email


@app.middleware("http")
async def cabecalhos_de_seguranca(request: Request, call_next):
    """Cabeçalhos que o SICAD passou a mandar depois da auditoria de 04/08/2026
    (achado M-2). CSP sem 'unsafe-inline' para script: o JS todo está em
    arquivo, nunca no HTML."""
    resposta = await call_next(request)
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["X-Frame-Options"] = "DENY"
    resposta.headers["Referrer-Policy"] = "same-origin"
    resposta.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'")
    return resposta


# -------------------------------------------------------------- utilidades

def _competencia(texto: Optional[str]) -> Optional[dt.date]:
    """'2026-08' ou '2026-08-01' → 1º do mês."""
    if not texto:
        return None
    t = texto.strip()
    if len(t) == 7:
        t += "-01"
    try:
        d = dt.date.fromisoformat(t)
    except ValueError:
        raise HTTPException(status_code=400, detail="Competência inválida (use AAAA-MM).")
    return dt.date(d.year, d.month, 1)


def _serializar(valor: Any) -> Any:
    if isinstance(valor, (dt.date, dt.datetime)):
        return valor.isoformat()
    from decimal import Decimal
    if isinstance(valor, Decimal):
        return float(valor)
    return valor


def _limpar(dados: Any) -> Any:
    if isinstance(dados, list):
        return [_limpar(x) for x in dados]
    if isinstance(dados, dict):
        return {k: _limpar(v) for k, v in dados.items()}
    return _serializar(dados)


def json_ok(dados: Any) -> JSONResponse:
    return JSONResponse(_limpar(dados))


# --------------------------------------------------------------- páginas

@app.get("/health")
def health() -> Dict[str, Any]:
    """Endpoint do UptimeRobot e do health check do Render. Não exige login e
    NÃO revela nada de dado — só se o processo está de pé."""
    return {"ok": True, "app": config.APP_NOME, "versao": config.APP_VERSAO}


@app.get("/")
def raiz(request: Request):
    if not _ler_sessao(request):
        return RedirectResponse("/login")
    return FileResponse(os.path.join(ESTATICO, "index.html"))


@app.get("/login")
def pagina_login(request: Request):
    if _ler_sessao(request):
        return RedirectResponse("/")
    return FileResponse(os.path.join(ESTATICO, "login.html"))


# ------------------------------------------------------------------ login

@app.post("/api/login")
def api_login(email: str = Form(...), senha: str = Form(...)):
    if not bd.banco_configurado():
        return JSONResponse({"ok": False,
                             "erro": "Banco de dados não configurado no servidor."},
                            status_code=503)
    try:
        ok, mensagem, usuario = usuarios.autenticar(email, senha)
    except Exception as erro:
        return JSONResponse({"ok": False, "erro": bd.sanitizar_erro(erro)},
                            status_code=503)

    if not ok and mensagem == "primeiro_acesso":
        return json_ok({"ok": False, "primeiro_acesso": True,
                        "nome": usuario.get("nome") if usuario else ""})
    if not ok:
        return JSONResponse({"ok": False, "erro": mensagem}, status_code=401)

    resposta = json_ok({"ok": True, "nome": usuario["nome"]})
    resposta.set_cookie(COOKIE, _assinar(usuario["email"]), httponly=True,
                        samesite="lax", secure=config.cookie_seguro(),
                        max_age=VALIDADE_SESSAO, path="/")
    return resposta


@app.post("/api/primeiro-acesso")
def api_primeiro_acesso(email: str = Form(...), senha: str = Form(...),
                        repeticao: str = Form(...)):
    ok, mensagem = usuarios.definir_primeira_senha(email, senha, repeticao)
    return JSONResponse({"ok": ok, "mensagem" if ok else "erro": mensagem},
                        status_code=200 if ok else 400)


@app.post("/api/trocar-senha")
def api_trocar_senha(atual: str = Form(...), nova: str = Form(...),
                     repeticao: str = Form(...), email: str = Depends(exigir_login)):
    ok, mensagem = usuarios.trocar_senha(email, atual, nova, repeticao)
    return JSONResponse({"ok": ok, "mensagem" if ok else "erro": mensagem},
                        status_code=200 if ok else 400)


@app.post("/api/sair")
def api_sair():
    resposta = json_ok({"ok": True})
    resposta.delete_cookie(COOKIE, path="/")
    return resposta


@app.get("/api/sessao")
def api_sessao(email: str = Depends(exigir_login)):
    usuario = repositorio.usuario_por_email(email) or {}
    return json_ok({"email": email, "nome": usuario.get("nome", ""),
                    "app": config.APP_NOME, "versao": config.APP_VERSAO,
                    "espelho_ativo": espelho.ativo()})


# ------------------------------------------------------------------ painel

@app.get("/api/painel")
def api_painel(competencia: Optional[str] = None, email: str = Depends(exigir_login)):
    meses = repositorio.competencias()
    comp = _competencia(competencia) or (meses[-1] if meses else None)
    if not comp:
        return json_ok({"vazio": True, "competencias": []})

    gastos = [g for g in repositorio.gasto_por_conta() if g["competencia"] == comp]
    return json_ok({
        "vazio": False,
        "competencia": comp,
        "competencias": meses,
        "resumo": repositorio.resumo_do_mes(comp),
        "categorias": repositorio.despesas_por_categoria(comp),
        "evolucao": repositorio.evolucao_mensal(),
        "contas": gastos,
        "itens_fixos": repositorio.itens_fixos(comp),
        "conciliacao": conciliacao.linhas(comp),
        "situacoes": conciliacao.resumo_situacoes(),
    })


@app.get("/api/lancamentos")
def api_lancamentos(competencia: Optional[str] = None, conta_id: Optional[int] = None,
                    categoria: Optional[str] = None, busca: str = "",
                    limite: int = 500, email: str = Depends(exigir_login)):
    return json_ok(repositorio.listar_lancamentos(
        competencia=_competencia(competencia), conta_id=conta_id,
        categoria=categoria, busca=busca, limite=limite))


@app.post("/api/lancamentos/{lanc_id}")
async def api_editar_lancamento(lanc_id: int, request: Request,
                                email: str = Depends(exigir_login)):
    campos = await request.json()
    if not isinstance(campos, dict):
        raise HTTPException(status_code=400, detail="Corpo inválido.")
    repositorio.atualizar_lancamento(lanc_id, campos)
    return json_ok({"ok": True})


@app.get("/api/contas")
def api_contas(email: str = Depends(exigir_login)):
    return json_ok(repositorio.contas())


# -------------------------------------------------------------- importação

@app.post("/api/importar")
async def api_importar(arquivos: List[UploadFile] = File(...),
                       email: str = Depends(exigir_login)):
    """Recebe um ou vários arquivos e importa cada um. Um arquivo com erro não
    impede os outros — o relatório diz o que aconteceu com cada um."""
    if not arquivos:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")

    relatorio: List[Dict[str, Any]] = []
    for arquivo in arquivos:
        dados = await arquivo.read()
        if len(dados) > TAMANHO_MAXIMO:
            relatorio.append({"arquivo": arquivo.filename, "status": "ERRO",
                              "erro": "Arquivo maior que 15 MB.", "lidos": 0,
                              "inseridos": 0, "duplicados": 0, "suspeitos": 0,
                              "resumos": 0, "avisos": []})
            continue
        relatorio.append(importacao.importar(arquivo.filename or "arquivo", dados)
                         .como_dict())

    total = {
        "inseridos": sum(r["inseridos"] for r in relatorio),
        "duplicados": sum(r["duplicados"] for r in relatorio),
        "suspeitos": sum(r["suspeitos"] for r in relatorio),
        "resumos": sum(r.get("resumos", 0) for r in relatorio),
        "erros": sum(1 for r in relatorio if r["status"] == "ERRO"),
    }
    return json_ok({"ok": True, "total": total, "arquivos": relatorio})


@app.get("/api/importacoes")
def api_importacoes(limite: int = 100, email: str = Depends(exigir_login)):
    return json_ok(repositorio.importacoes(limite))


@app.post("/api/reprocessar")
def api_reprocessar(competencia: str = Form(...), conta_id: Optional[int] = Form(None),
                    email: str = Depends(exigir_login)):
    comp = _competencia(competencia)
    if not comp:
        raise HTTPException(status_code=400, detail="Informe a competência.")
    apagados = importacao.reprocessar(conta_id, comp)
    return json_ok({"ok": True, "apagados": apagados})


# ------------------------------------------------------------- conciliação

@app.get("/api/conciliacao")
def api_conciliacao(competencia: Optional[str] = None,
                    email: str = Depends(exigir_login)):
    return json_ok(conciliacao.linhas(_competencia(competencia)))


@app.post("/api/resumo")
def api_resumo(conta_id: int = Form(...), competencia: str = Form(...),
               saldo_anterior: float = Form(0), despesas: float = Form(0),
               encargos: float = Form(0), creditos: float = Form(0),
               pagamentos: float = Form(0), total_informado: float = Form(0),
               email: str = Depends(exigir_login)):
    """Resumo digitado à mão — é o caminho do Nubank, que não exporta esse
    quadro em arquivo nenhum."""
    comp = _competencia(competencia)
    repositorio.upsert_resumo({
        "conta_id": conta_id, "competencia": comp, "saldo_anterior": saldo_anterior,
        "despesas": despesas, "encargos": encargos, "creditos": creditos,
        "pagamentos": pagamentos, "total_informado": total_informado,
        "arquivo": "informado na tela"})
    return json_ok({"ok": True})


@app.get("/api/resumos")
def api_resumos(email: str = Depends(exigir_login)):
    return json_ok(repositorio.resumos())


# ------------------------------------------------------------------ regras

@app.get("/api/regras")
def api_regras(email: str = Depends(exigir_login)):
    lista = repositorio.regras(somente_ativas=False)
    for r in lista:
        r["regex_valida"] = categorizacao.regex_valida(r["padrao"] or "")
    return json_ok(lista)


@app.post("/api/regras")
async def api_salvar_regra(request: Request, email: str = Depends(exigir_login)):
    dados = await request.json()
    campos = {
        "id": dados.get("id"),
        "ordem": int(dados.get("ordem") or 999),
        "padrao": (dados.get("padrao") or "").strip(),
        "categoria": (dados.get("categoria") or "").strip(),
        "subcategoria": (dados.get("subcategoria") or "").strip(),
        "item_fixo": (dados.get("item_fixo") or "").strip(),
        "tipo": (dados.get("tipo") or "").strip(),
        "ativa": bool(dados.get("ativa", True)),
        "observacao": (dados.get("observacao") or "").strip(),
    }
    if not campos["padrao"]:
        raise HTTPException(status_code=400, detail="O padrão não pode ficar vazio.")
    if not categorizacao.regex_valida(campos["padrao"]):
        raise HTTPException(status_code=400,
                            detail="Expressão regular inválida — corrija o padrão.")
    return json_ok({"ok": True, "id": repositorio.salvar_regra(campos)})


@app.delete("/api/regras/{regra_id}")
def api_apagar_regra(regra_id: int, email: str = Depends(exigir_login)):
    repositorio.apagar_regra(regra_id)
    return json_ok({"ok": True})


# ----------------------------------------------------------------- espelho

@app.get("/api/espelho")
def api_espelho_status(email: str = Depends(exigir_login)):
    ok, mensagem = espelho.testar()
    return json_ok({"ativo": espelho.ativo(), "ok": ok, "mensagem": mensagem,
                    "conta_de_servico": espelho.email_da_conta_de_servico(),
                    "planilha_id": config.planilha_espelho_id()})


@app.post("/api/espelho/sincronizar")
def api_espelho_sincronizar(email: str = Depends(exigir_login)):
    try:
        return json_ok({"ok": True, "abas": espelho.sincronizar()})
    except espelho.EspelhoDesligado as erro:
        return JSONResponse({"ok": False, "erro": str(erro)}, status_code=400)
    except Exception as erro:
        return JSONResponse({"ok": False, "erro": bd.sanitizar_erro(erro)},
                            status_code=502)


# ------------------------------------------------------------ diagnóstico

@app.get("/api/diagnostico")
def api_diagnostico(email: str = Depends(exigir_login)):
    banco_ok, banco_msg = bd.testar_conexao()
    espelho_ok, espelho_msg = espelho.testar()
    return json_ok({
        "banco": {"ok": banco_ok, "mensagem": banco_msg},
        "espelho": {"ok": espelho_ok, "mensagem": espelho_msg,
                    "ativo": espelho.ativo()},
        "senha_pdf_configurada": bool(config.senha_pdf_santander()),
        "lancamentos": len(repositorio.competencias()),
    })
