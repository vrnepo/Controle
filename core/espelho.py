"""
Espelho na planilha do Google — SOMENTE DE SAÍDA.

Mesma decisão vigente no SICAD desde 04/08/2026: o banco é a fonte da verdade e
a planilha é leitura. Ela não alimenta o sistema de volta. Sem isso, dois
lugares editáveis com a mesma informação divergem, e não há como saber qual
está certo.

Contas: as credenciais são de uma conta de serviço PRÓPRIA deste projeto, num
projeto próprio do Google Cloud, numa conta Google separada da do SICAD. Nada
aqui reaproveita ID ou chave do SICAD.

Para funcionar, a planilha precisa estar COMPARTILHADA COMO EDITOR com o e-mail
da conta de serviço (o `client_email` do JSON). Sem isso o gspread devolve 403 e
a mensagem de erro não é óbvia — por isso `testar()` explica o que fazer.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from typing import Any, Dict, List, Optional, Tuple

from core import bd, conciliacao, config, repositorio

_cliente = None
_lock = threading.Lock()

ABAS = {
    "lancamentos": "Lançamentos",
    "resumo": "Resumo de Faturas",
    "conciliacao": "Conciliação",
    "dashboard": "Dashboard",
    "importacoes": "Importações",
}

ESCOPOS = ["https://www.googleapis.com/auth/spreadsheets",
           "https://www.googleapis.com/auth/drive.file"]


class EspelhoDesligado(Exception):
    pass


def ativo() -> bool:
    return config.espelho_ativo()


def _obter_cliente():
    global _cliente
    if not ativo():
        raise EspelhoDesligado(
            "Espelho desligado: configure GCP_SERVICE_ACCOUNT_JSON e "
            "PLANILHA_ESPELHO_ID.")
    with _lock:
        if _cliente is None:
            import gspread
            from google.oauth2.service_account import Credentials

            bruto = config.env("GCP_SERVICE_ACCOUNT_JSON")
            try:
                info = json.loads(bruto)
            except json.JSONDecodeError:
                raise EspelhoDesligado(
                    "GCP_SERVICE_ACCOUNT_JSON não é um JSON válido. Cole o conteúdo "
                    "inteiro do arquivo da conta de serviço, em uma linha.")
            credenciais = Credentials.from_service_account_info(info, scopes=ESCOPOS)
            _cliente = gspread.authorize(credenciais)
        return _cliente


def _planilha():
    return _obter_cliente().open_by_key(config.planilha_espelho_id())


def email_da_conta_de_servico() -> str:
    """Para a tela poder dizer com quem compartilhar a planilha."""
    try:
        return json.loads(config.env("GCP_SERVICE_ACCOUNT_JSON")).get("client_email", "")
    except Exception:
        return ""


def testar() -> Tuple[bool, str]:
    if not ativo():
        return False, ("Espelho desligado. Faltam GCP_SERVICE_ACCOUNT_JSON e/ou "
                       "PLANILHA_ESPELHO_ID.")
    try:
        planilha = _planilha()
        return True, "Conectado à planilha '%s'." % planilha.title
    except EspelhoDesligado as erro:
        return False, str(erro)
    except Exception as erro:
        texto = str(erro)
        if "403" in texto or "PERMISSION_DENIED" in texto:
            email = email_da_conta_de_servico() or "(e-mail da conta de serviço)"
            return False, ("Sem permissão na planilha. Compartilhe-a como EDITOR "
                           "com %s." % email)
        if "404" in texto:
            return False, "Planilha não encontrada — confira o PLANILHA_ESPELHO_ID."
        return False, bd.sanitizar_erro(erro)


# ----------------------------------------------------------------- escrita

def _aba(planilha, nome: str, colunas: int):
    try:
        return planilha.worksheet(nome)
    except Exception:
        return planilha.add_worksheet(title=nome, rows=100, cols=max(colunas, 10))


def _escrever(aba, matriz: List[List[Any]]) -> None:
    """Limpa e reescreve a aba inteira.

    Reescrever tudo, em vez de tentar casar linha por linha, é de propósito: o
    espelho é derivado: qualquer estado dele que não venha do banco é lixo. E
    uma escrita só gasta uma chamada da cota da API, contra uma por linha.
    """
    # Filtro ativo herdado de antes da sincronização esconde as linhas novas —
    # na aba Lançamentos ficou um filtro da planilha original mostrando 55 de
    # 1.876 linhas (08/08/2026). O clear() não o remove; isto sim.
    try:
        aba.clear_basic_filter()
    except Exception:
        pass
    aba.clear()
    if not matriz:
        return
    aba.update(values=matriz, range_name="A1", value_input_option="USER_ENTERED")


FORMATO_DATA = {"numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}}
FORMATO_MES = {"numberFormat": {"type": "DATE", "pattern": "mmm/yy"}}
FORMATO_MOEDA = {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00;[Red](#,##0.00)"}}


def _formatar(aba, formatos: Dict[str, Dict[str, Any]]) -> None:
    """Aplica formato numérico por intervalo. Falha de formato não pode abortar
    a sincronização — o dado já está lá; formato é cosmético."""
    for intervalo, formato in formatos.items():
        try:
            aba.format(intervalo, formato)
        except Exception:
            pass


def _dia(valor: Optional[dt.date]) -> str:
    # ISO: o Sheets reconhece como DATA em qualquer localidade. "07/08/2026"
    # dependeria da localidade da planilha (em en-US viraria 8 de julho) e
    # "ago./26" viraria TEXTO — foi exatamente isso que deixou o Painel Mensal
    # em branco em 08/08/2026: as fórmulas comparam com DATE(), e data ≠ texto.
    # A exibição (dd/mm/aaaa, mmm/aa) vem do formato numérico aplicado depois.
    return valor.strftime("%Y-%m-%d") if valor else ""


def _mes(valor: Optional[dt.date]) -> str:
    if not valor:
        return ""
    return valor.strftime("%Y-%m-01")


def _numero(valor: Any) -> Any:
    """Número vai como número (para a planilha somar), nunca como texto."""
    return float(valor) if valor is not None else ""


def _texto_seguro(valor: Any) -> str:
    """
    Anti-injeção de fórmula: descrição vinda do extrato do banco não pode virar
    fórmula na planilha. Mesma correção aplicada no SICAD (achado M-1 da
    auditoria de 04/08/2026) — um estabelecimento chamado "=CMD" viraria
    fórmula, e há formas de isso virar exfiltração de dados via HYPERLINK.
    """
    texto = "" if valor is None else str(valor)
    return "'" + texto if texto[:1] in ("=", "+", "-", "@") else texto


def sincronizar() -> Dict[str, int]:
    """Reescreve todas as abas do espelho. Devolve as linhas por aba."""
    planilha = _planilha()
    contagem: Dict[str, int] = {}

    # --- Lançamentos
    #
    # LAYOUT ORIGINAL DA PLANILHA, de propósito: título na linha 1, nota na 2,
    # cabeçalho na 3 e dados a partir da linha 4 — porque as abas antigas que o
    # usuário preservou (Painel Mensal, Faturas) têm fórmulas apontando para
    # 'Lançamentos'!$X$4:$X$2177. Quando o espelho escrevia o cabeçalho na
    # linha 1, essas fórmulas liam as linhas erradas e o Painel Mensal ficava
    # em branco (visto em 08/08/2026). Escrever no mesmo lugar as ressuscita
    # sem tocar em fórmula nenhuma.
    TETO_FORMULAS_ANTIGAS = 2177
    lanc = repositorio.listar_lancamentos(limite=5000)
    lanc = list(reversed(lanc))          # ascendente por data, como o original
    nota = ("Aba escrita pelo sistema — NÃO editar (a sincronização reescreve). "
            "Uma linha por transação.")
    if len(lanc) + 3 > TETO_FORMULAS_ANTIGAS - 50:
        nota += (" ⚠ ATENÇÃO: %d linhas, chegando perto do teto %d das fórmulas "
                 "do Painel Mensal/Faturas — é preciso ampliar os intervalos delas."
                 % (len(lanc) + 3, TETO_FORMULAS_ANTIGAS))
    matriz: List[List[Any]] = [
        ["LANÇAMENTOS"],
        [nota],
        ["Banco", "Fonte", "Data", "Descrição", "Categoria", "Subcategoria",
         "Item fixo", "Conta", "Tipo", "Valor", "Competência", "Status", "Arquivo"]]
    for r in lanc:
        matriz.append([
            r["banco"], r["fonte"], _dia(r["data"]), _texto_seguro(r["descricao"]),
            r["categoria"] or "", r["subcategoria"] or "", r["item_fixo"] or "",
            r["conta"], r["tipo"], _numero(r["valor"]), _mes(r["competencia"]),
            r["status"], _texto_seguro(r["arquivo"])])
    aba_lanc = _aba(planilha, ABAS["lancamentos"], 13)
    _escrever(aba_lanc, matriz)
    _formatar(aba_lanc, {"C4:C": FORMATO_DATA, "K4:K": FORMATO_MES,
                         "J4:J": FORMATO_MOEDA})
    contagem["lancamentos"] = len(lanc)

    # --- Resumo de Faturas
    resumos = repositorio.resumos()
    matriz = [["Competência", "Cartão", "Saldo anterior", "Despesas", "Encargos",
               "Créditos", "Pagamentos", "Total informado", "Arquivo"]]
    for r in resumos:
        matriz.append([
            _mes(r["competencia"]), r["conta"], _numero(r["saldo_anterior"]),
            _numero(r["despesas"]), _numero(r["encargos"]), _numero(r["creditos"]),
            _numero(r["pagamentos"]), _numero(r["total_informado"]),
            _texto_seguro(r["arquivo"])])
    aba_res = _aba(planilha, ABAS["resumo"], 9)
    _escrever(aba_res, matriz)
    _formatar(aba_res, {"A2:A": FORMATO_MES, "C2:H": FORMATO_MOEDA})
    contagem["resumo"] = len(resumos)

    # --- Conciliação
    linhas_conc = conciliacao.linhas()
    matriz = [["Competência", "Cartão", "Gasto do mês", "Despesas+encargos",
               "Δ importação", "Saldo anterior", "Pagamentos", "Total calculado",
               "Total no app", "Δ vs app", "Situação", "Explicação"]]
    for r in linhas_conc:
        matriz.append([
            _mes(r["competencia"]), r["conta"], _numero(r["gasto_do_mes"]),
            _numero(r["despesas_encargos"]), _numero(r["delta_importacao"]),
            _numero(r["saldo_anterior"]), _numero(r["pagamentos"]),
            _numero(r["total_calculado"]), _numero(r["total_informado"]),
            _numero(r["delta_app"]), SITUACAO_ROTULO.get(r["situacao"], r["situacao"]),
            r["explicacao"]])
    aba_conc = _aba(planilha, ABAS["conciliacao"], 12)
    _escrever(aba_conc, matriz)
    _formatar(aba_conc, {"A2:A": FORMATO_MES, "C2:J": FORMATO_MOEDA})
    contagem["conciliacao"] = len(linhas_conc)

    # --- Dashboard (evolução mensal)
    evolucao = repositorio.evolucao_mensal()
    gastos = repositorio.gasto_por_conta()
    por_mes: Dict[Any, Dict[str, float]] = {}
    for g in gastos:
        por_mes.setdefault(g["competencia"], {})[g["conta"]] = float(g["total"] or 0)
    nomes_contas = [c["nome"] for c in repositorio.contas()]
    matriz = [["Competência", "Receitas", "Despesas", "Resultado"] + nomes_contas]
    for e in evolucao:
        receitas, despesas = float(e["receitas"] or 0), float(e["despesas"] or 0)
        linha = [_mes(e["competencia"]), receitas, despesas, receitas + despesas]
        for nome in nomes_contas:
            linha.append(por_mes.get(e["competencia"], {}).get(nome, 0.0))
        matriz.append(linha)
    aba_dash = _aba(planilha, ABAS["dashboard"], 4 + len(nomes_contas))
    _escrever(aba_dash, matriz)
    _formatar(aba_dash, {"A2:A": FORMATO_MES, "B2:H": FORMATO_MOEDA})
    contagem["dashboard"] = len(evolucao)

    # --- Importações
    imp = repositorio.importacoes(limite=200)
    matriz = [["Quando", "Arquivo", "Formato", "Conta", "Lidos", "Inseridos",
               "Duplicados", "Suspeitos", "Status", "Observação"]]
    for r in imp:
        quando = r["quando"]
        matriz.append([
            quando.strftime("%d/%m/%Y %H:%M") if quando else "",
            _texto_seguro(r["arquivo"]), r["formato"] or "", r["conta"] or "",
            r["lidos"], r["inseridos"], r["duplicados"], r["suspeitos"],
            r["status"], r["observacao"] or ""])
    _escrever(_aba(planilha, ABAS["importacoes"], 10), matriz)
    contagem["importacoes"] = len(imp)

    return contagem


SITUACAO_ROTULO = {
    "ok": "✔ confere",
    "importacao_incompleta": "⚠ importação incompleta",
    "conferir_resumo": "⚠ conferir resumo",
    "sem_resumo": "sem resumo",
    "sem_lancamentos": "sem lançamentos",
}
