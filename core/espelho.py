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


def _escrever(aba, matriz: List[List[Any]],
              intervalos_limpeza: Optional[List[str]] = None) -> None:
    """Limpa e reescreve a aba inteira.

    Reescrever tudo, em vez de tentar casar linha por linha, é de propósito: o
    espelho é derivado: qualquer estado dele que não venha do banco é lixo. E
    uma escrita só gasta uma chamada da cota da API, contra uma por linha.

    `intervalos_limpeza`: quando presente, limpa SÓ esses intervalos em vez da
    aba inteira — é como a célula J2 dos Lançamentos fica de fora (ela é do
    usuário; ver o comentário na montagem da matriz). Na matriz, célula None
    é PULADA pela API (não sobrescreve), diferente de "" que apaga.
    """
    # Filtro ativo herdado de antes da sincronização esconde as linhas novas —
    # na aba Lançamentos ficou um filtro da planilha original mostrando 55 de
    # 1.876 linhas (08/08/2026). O clear() não o remove; isto sim.
    try:
        aba.clear_basic_filter()
    except Exception:
        pass
    # Mesclas herdadas engolem o cabeçalho: a linha 1 da planilha original era
    # um título mesclado de A a M, o clear() preserva a mescla, e o que se via
    # era só "Banco" na linha inteira (08/08/2026). Desfaz todas antes de
    # escrever — o espelho escreve célula a célula e não usa mescla nenhuma.
    try:
        aba.spreadsheet.batch_update({
            "requests": [{"unmergeCells": {"range": {"sheetId": aba.id}}}]})
    except Exception:
        pass
    if intervalos_limpeza:
        aba.batch_clear(intervalos_limpeza)
    else:
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


def _transportes_de_saldo(lanc: List[Dict[str, Any]],
                          contas_corrente: List[str]) -> List[Dict[str, Any]]:
    """
    Linhas de "Saldo inicial" por mês, SÓ PARA A PLANILHA ESPELHO (decisão do
    usuário, 09/08/2026): filtrando um mês de competência nos Lançamentos, o
    SUBTOTAL da J2 soma saldo inicial + movimentos = o saldo disponível do app.

    Elas NUNCA entram no banco — todas as análises do sistema (Painel,
    Conciliação, evolução) continuam vendo só movimentos reais. Na planilha,
    saem com Tipo = "Saldo", que nenhuma fórmula do Painel Mensal soma; e a
    célula de saldo total (L2) as exclui explicitamente.

    Uma linha por conta-corrente × mês, a partir do 1º mês com transporte
    diferente de zero: valor = acumulado de TODOS os meses anteriores.
    """
    por_conta: Dict[str, Dict[Any, float]] = {}
    bancos: Dict[str, str] = {}
    for r in lanc:
        if r["conta"] not in contas_corrente:
            continue
        meses = por_conta.setdefault(r["conta"], {})
        meses[r["competencia"]] = meses.get(r["competencia"], 0.0) + float(r["valor"])
        bancos[r["conta"]] = r["banco"]

    saida: List[Dict[str, Any]] = []
    for conta, meses in por_conta.items():
        acumulado = 0.0
        anterior = None
        for comp in sorted(meses):
            if abs(acumulado) > 0.005 and anterior is not None:
                saida.append({
                    "banco": bancos[conta], "fonte": "Extrato",
                    "data": comp,
                    "descricao": "Saldo inicial da conta (acumulado até %s%s)"
                                 % (config.mes_curto(anterior.month),
                                    anterior.strftime("%y")),
                    "categoria": "Saldo do mês anterior", "subcategoria": "",
                    "item_fixo": "", "conta": conta, "tipo": "Saldo",
                    "valor": round(acumulado, 2), "competencia": comp,
                    "status": "Calculado", "arquivo": "espelho (transporte de saldo)"})
            acumulado += meses[comp]
            anterior = comp
    return saida


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
    correntes = [c["nome"] for c in repositorio.contas() if c["tipo"] == "conta"]
    transportes = _transportes_de_saldo(lanc, correntes)
    nota = ("Aba escrita pelo sistema — NÃO editar (a sincronização reescreve). "
            "Exceção: a célula J2 é SUA — o sistema nunca a toca. Linhas com "
            "Tipo=Saldo são transporte de saldo, só para leitura filtrada.")
    total_linhas = len(lanc) + len(transportes) + 3
    if total_linhas > TETO_FORMULAS_ANTIGAS - 50:
        nota += (" ⚠ ATENÇÃO: %d linhas, chegando perto do teto %d das fórmulas "
                 "do Painel Mensal/Faturas — é preciso ampliar os intervalos delas."
                 % (total_linhas, TETO_FORMULAS_ANTIGAS))
    # J2 é DO USUÁRIO (decisão dele, 08/08/2026): ele mantém ali o
    # =SUBTOTAL(9;J4:J2177) que soma o que o filtro mostra. A primeira versão
    # era escrita pelo sistema em sintaxe de vírgula e quebrou: USER_ENTERED
    # interpreta na LOCALIDADE da planilha, e o pt-BR exige ponto e vírgula.
    # Agora a sincronização nem limpa nem escreve J2: os intervalos de limpeza
    # excluem a célula, e None na matriz faz a API pular a posição.
    #
    # K2/L2: saldo total da Conta Santander (exclui as linhas Tipo=Saldo, que
    # são transporte) — é o número comparável com o "Saldo disponível" do app.
    linha_nota: List[Any] = [nota] + [None] * 12
    linha_nota[10] = "Saldo em conta (Santander) →"
    linha_nota[11] = ('=SUMIFS($J$4:$J$100000;$H$4:$H$100000;"Conta Santander";'
                      '$I$4:$I$100000;"<>Saldo")')
    matriz: List[List[Any]] = [
        ["LANÇAMENTOS"],
        linha_nota,
        ["Banco", "Fonte", "Data", "Descrição", "Categoria", "Subcategoria",
         "Item fixo", "Conta", "Tipo", "Valor", "Competência", "Status", "Arquivo"]]
    # transporte de saldo entra ANTES dos movimentos do dia 1 de cada mês —
    # ordenação por (data, 0=transporte/1=real, ordem original)
    combinadas = ([(r["data"], 1, i, r) for i, r in enumerate(lanc)] +
                  [(t["data"], 0, i, t) for i, t in enumerate(transportes)])
    combinadas.sort(key=lambda x: (x[0], x[1], x[2]))
    for _, _, _, r in combinadas:
        matriz.append([
            r["banco"], r["fonte"], _dia(r["data"]), _texto_seguro(r["descricao"]),
            r["categoria"] or "", r["subcategoria"] or "", r["item_fixo"] or "",
            r["conta"], r["tipo"], _numero(r["valor"]), _mes(r["competencia"]),
            r["status"], _texto_seguro(r["arquivo"])])
    aba_lanc = _aba(planilha, ABAS["lancamentos"], 13)
    # Limpa tudo MENOS J2: linhas 1-2 nas colunas A-I e K-M, o J1 sozinho, e
    # da linha 3 para baixo tudo — a única célula fora das faixas é a J2.
    _escrever(aba_lanc, matriz,
              intervalos_limpeza=["A1:I2", "J1", "K1:M2", "A3:M100000"])
    _formatar(aba_lanc, {"C4:C": FORMATO_DATA, "K4:K": FORMATO_MES,
                         "J4:J": FORMATO_MOEDA, "J2": FORMATO_MOEDA,
                         "L2": FORMATO_MOEDA})
    # Nota em cada título de coluna (aparece ao passar o mouse): o cabeçalho
    # diz O QUE é; a nota diz o que significa e de onde vem. Pedido do usuário
    # em 08/08/2026. Falha aqui não pode abortar a sincronização.
    try:
        aba_lanc.insert_notes(NOTAS_COLUNAS_LANCAMENTOS)
    except Exception:
        pass
    # Filtro nos títulos da linha 3 (pedido do usuário): o _escrever removeu o
    # filtro herdado; este é recriado limpo a cada sincronização, cobrindo só
    # os dados reais — e é o que o SUBTOTAL de J2 respeita.
    try:
        aba_lanc.set_basic_filter("A3:M%d" % (len(combinadas) + 3))
    except Exception:
        pass
    contagem["lancamentos"] = len(lanc)
    contagem["transportes de saldo"] = len(transportes)

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

    # --- Dashboard: NÃO existe mais no espelho (decisão do usuário, 08/08/2026).
    # O painel mensal é o Painel Mensal da própria planilha; a tela Painel do
    # sistema cobre o resto. A aba é removida ativamente porque só parar de
    # escrevê-la deixaria uma aba órfã com dados velhos — pior que não ter.
    try:
        planilha.del_worksheet(planilha.worksheet(ABAS["dashboard"]))
        contagem["dashboard removida"] = 1
    except Exception:
        pass  # já não existe — o estado desejado

    # Painel Mensal como primeira aba (decisão do usuário, 08/08/2026): é a
    # visão que ele abre primeiro. Se a aba for renomeada um dia, o reorder
    # simplesmente não acontece — nunca é motivo para abortar a sincronização.
    try:
        painel = planilha.worksheet("Painel Mensal")
        painel.update_index(0)
        _validacoes_painel_mensal(planilha, painel)
        _ajustar_painel_mensal(planilha, painel)
    except Exception:
        pass

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


def _sumifs_com_extrato(formula: str) -> str:
    """
    Acrescenta o critério Fonte="Extrato" a cada SUMIFS sobre Lançamentos.

    Decisão do usuário (09/08/2026): no Painel Mensal, os grupos de despesa
    (Apartamento, FLAT, Pessoais Fixas, Despesas Variáveis) mostram só o que
    saiu da CONTA no mês — o que foi no cartão já está dentro da linha da
    fatura, que é paga no mês selecionado; sem o filtro, o mesmo gasto
    aparecia duas vezes na leitura.

    O parser respeita aspas ao casar parênteses porque os critérios contêm
    parênteses ("Telefone (Vivo/Telefônica)") — um replace ingênuo fecharia a
    fórmula no lugar errado. Opera na forma CANÔNICA da API (vírgulas).
    """
    CRITERIO = ",'Lançamentos'!$B$4:$B$2177,\"Extrato\""
    saida = []
    i = 0
    while True:
        pos = formula.find("SUMIFS(", i)
        if pos < 0:
            saida.append(formula[i:])
            break
        fim = pos + len("SUMIFS(")
        profundidade = 1
        em_aspas = False
        while fim < len(formula) and profundidade:
            ch = formula[fim]
            if ch == '"':
                em_aspas = not em_aspas
            elif not em_aspas:
                if ch == "(":
                    profundidade += 1
                elif ch == ")":
                    profundidade -= 1
            fim += 1
        chamada = formula[pos:fim]                      # SUMIFS(...) completo
        if "Lançamentos" in chamada and "Extrato" not in chamada:
            chamada = chamada[:-1] + CRITERIO + ")"
        saida.append(formula[i:pos])
        saida.append(chamada)
        i = fim
    return "".join(saida)


def _para_dialeto_pt(formula: str) -> str:
    """
    Converte os separadores de argumento de vírgula (forma canônica) para
    ponto e vírgula (dialeto pt-BR), preservando o que está entre aspas.

    Por que existe: a API LÊ fórmulas em forma canônica (nomes em inglês,
    vírgulas), mas TODA escrita — updateCells/formulaValue inclusive — é
    interpretada na LOCALIDADE da planilha. Descoberto em 09/08/2026 do
    jeito caro: o ajustador gravou vírgulas e todos os grupos do Painel
    Mensal viraram #ERROR!. Se a localidade da planilha um dia mudar para
    en-US, isto precisa mudar junto.
    """
    saida = []
    em_aspas = False
    for ch in formula:
        if ch == '"':
            em_aspas = not em_aspas
        if ch == "," and not em_aspas:
            saida.append(";")
        else:
            saida.append(ch)
    return "".join(saida)


def _ajustar_painel_mensal(planilha, painel) -> None:
    """
    Ajustes estruturais do Painel Mensal (decisões do usuário, 09/08/2026):
    1. grupos de despesa passam a filtrar Fonte = "Extrato" (ver
       _sumifs_com_extrato);
    2. o bloco RESULTADO DO MÊS sobe para logo abaixo dos seletores (linha 5),
       acima do cabeçalho da tabela — via moveDimension, que reescreve as
       referências como um arrasto manual faria.

    Leitura por gridData (canônica) e escrita por USER_ENTERED no dialeto
    pt-BR (_para_dialeto_pt) — ver o comentário daquela função. O passo 1 é
    AUTO-REPARADOR: reescreve as fórmulas dos grupos em toda sincronização,
    então uma fórmula quebrada ali se conserta na rodada seguinte.
    """
    def ler_grade():
        meta = planilha.fetch_sheet_metadata({
            "ranges": "'Painel Mensal'!A1:F80",
            "includeGridData": True,
            "fields": "sheets(properties(sheetId,title),"
                      "data(rowData(values(userEnteredValue,formattedValue))))"})
        folha = next(s for s in meta["sheets"]
                     if s["properties"]["title"] == "Painel Mensal")
        return folha["properties"]["sheetId"], folha["data"][0].get("rowData", [])

    sid, grade = ler_grade()

    def celula(r: int, c: int) -> Dict[str, Any]:
        try:
            return grade[r]["values"][c] or {}
        except (IndexError, KeyError):
            return {}

    def texto_a(r: int) -> str:
        return (celula(r, 0).get("formattedValue") or "").strip()

    def formula(r: int, c: int) -> str:
        return (celula(r, c).get("userEnteredValue") or {}).get("formulaValue") or ""

    def achar(prefixo: str) -> Optional[int]:
        alvo = prefixo.upper()
        for r in range(len(grade)):
            if texto_a(r).upper().startswith(alvo):
                return r
        return None

    # --- 0. RESULTADO DO MÊS sobe para a linha 5 (uma vez só)
    if not texto_a(4).upper().startswith("RESULTADO"):
        inicio = achar("RESULTADO DO M")
        fim = None
        if inicio is not None:
            for r in range(inicio, len(grade)):
                if texto_a(r).lower().startswith("resultado (sobra"):
                    fim = r
                    break
        if inicio is not None and fim is not None and inicio > 4:
            planilha.batch_update({"requests": [{"moveDimension": {
                "source": {"sheetId": sid, "dimension": "ROWS",
                           "startIndex": inicio, "endIndex": fim + 1},
                "destinationIndex": 4}}]})
            sid, grade = ler_grade()

    # --- 0b. linha-memo "Saldo em conta corrente" ACIMA do grupo RECEITAS
    # (decisão do usuário, 09/08/2026): mostra o saldo acumulado da Conta
    # Santander até o mês selecionado — o número comparável com o app. É memo:
    # não entra em subtotal nenhum, e exclui as linhas de transporte
    # (Tipo="Saldo") para não contar o carregado duas vezes.
    if achar("SALDO EM CONTA CORRENTE") is None:
        r_receitas = achar("RECEITAS")
        if r_receitas is not None and r_receitas > 0:
            planilha.batch_update({"requests": [{"insertDimension": {
                "range": {"sheetId": sid, "dimension": "ROWS",
                          "startIndex": r_receitas, "endIndex": r_receitas + 1},
                "inheritFromBefore": False}}]})
            linha = r_receitas + 1                      # 1-based na planilha
            painel.batch_update([
                {"range": "A%d" % linha,
                 "values": [["Saldo em conta corrente (Santander) — até o mês selecionado"]]},
                {"range": "B%d" % linha,
                 "values": [["=SUMIFS('Lançamentos'!$J$4:$J$100000;"
                             "'Lançamentos'!$H$4:$H$100000;\"Conta Santander\";"
                             "'Lançamentos'!$K$4:$K$100000;\"<=\"&$E$4;"
                             "'Lançamentos'!$I$4:$I$100000;\"<>Saldo\")"]]},
                {"range": "F%d" % linha,
                 "values": [["memo — compare com o Saldo disponível do app"]]},
            ], value_input_option="USER_ENTERED")
            _formatar(painel, {"B%d" % linha: FORMATO_MOEDA})
            sid, grade = ler_grade()

    # --- 0c. linha "Transferências recebidas" DENTRO do grupo RECEITAS,
    # somando no Subtotal (decisão do usuário, 09/08/2026): as entradas por
    # transferência (PIX entre contas etc.) contam como receita do mês no
    # Painel. Só as POSITIVAS (">0") e só do extrato; Tipo="Transferência"
    # já deixa os transportes de saldo de fora. O Subtotal é reescrito com o
    # intervalo estendido, porque inserir linha na borda do SUM não o expande.
    if achar("TRANSFERÊNCIAS RECEBIDAS") is None:
        r_rec = achar("RECEITAS")
        r_sub = None
        for r in range(len(grade)):
            rotulo = texto_a(r).upper()
            if rotulo.startswith("SUBTOTAL") and "RECEITAS" in rotulo:
                r_sub = r
                break
        if r_rec is not None and r_sub is not None and r_sub > r_rec:
            planilha.batch_update({"requests": [{"insertDimension": {
                "range": {"sheetId": sid, "dimension": "ROWS",
                          "startIndex": r_sub, "endIndex": r_sub + 1},
                "inheritFromBefore": True}}]})
            nova_linha = r_sub + 1                     # 1-based
            primeira = r_rec + 2                       # 1ª linha de dados do grupo
            subtotal = r_sub + 2                       # subtotal, já deslocado
            painel.batch_update([
                {"range": "A%d" % nova_linha,
                 "values": [["    Transferências recebidas (entre contas)"]]},
                {"range": "B%d" % nova_linha,
                 "values": [["=SUMIFS('Lançamentos'!$J$4:$J$100000;"
                             "'Lançamentos'!$I$4:$I$100000;\"Transferência\";"
                             "'Lançamentos'!$B$4:$B$100000;\"Extrato\";"
                             "'Lançamentos'!$K$4:$K$100000;$E$4;"
                             "'Lançamentos'!$J$4:$J$100000;\">0\")"]]},
                {"range": "B%d" % subtotal,
                 "values": [["=SUM($B%d:$B%d)" % (primeira, nova_linha)]]},
                {"range": "C%d" % subtotal,
                 "values": [["=SUM($C%d:$C%d)" % (primeira, nova_linha)]]},
            ], value_input_option="USER_ENTERED")
            _formatar(painel, {"B%d" % nova_linha: FORMATO_MOEDA})
            sid, grade = ler_grade()

    # --- 1. critério Extrato nas RECEITAS e nos grupos de despesa (B e C).
    # RECEITAS também (decisão do usuário, 09/08/2026): só entradas que
    # passaram pelo extrato — estorno de cartão, por exemplo, já está dentro
    # da fatura. SEMPRE reescreve (auto-reparo): a leitura vem canônica, o
    # critério é garantido e a fórmula desce no dialeto pt-BR.
    GRUPOS = ("RECEITAS", "APARTAMENTO", "FLAT", "PESSOAIS FIXAS", "DESPESAS VARI")
    celulas_valores: List[Dict[str, Any]] = []
    dentro = False
    for r in range(len(grade)):
        rotulo = texto_a(r).upper()
        if not rotulo:
            continue
        if any(rotulo.startswith(g) for g in GRUPOS):
            dentro = True
            continue
        if (rotulo.startswith("SUBTOTAL") or rotulo.startswith("RESULTADO")
                or rotulo.startswith("FATURAS")):
            dentro = False
            continue
        if not dentro:
            continue
        for c in (1, 2):                                # B (mês) e C (média)
            f = formula(r, c)
            if not f or "SUMIFS(" not in f:
                continue
            nova = _para_dialeto_pt(_sumifs_com_extrato(f))
            celulas_valores.append({
                "range": "%s%d" % ("B" if c == 1 else "C", r + 1),
                "values": [[nova]]})

    # --- 2. faturas de cartão entram no "Total de despesas" (decisão do
    # usuário, 09/08/2026). Os grupos de despesa estão filtrados a Extrato,
    # então somar as faturas por cima NÃO conta nada duas vezes: compra de
    # cartão só existe dentro da fatura.
    r_total = achar("TOTAL DE DESPESAS")
    r_faturas = achar("SUBTOTAL — FATURAS")
    if r_total is not None and r_faturas is not None:
        for c, letra in ((1, "B"), (2, "C")):
            f = formula(r_total, c)
            ref = "$%s$%d" % (letra, r_faturas + 1)
            if f and ref not in f:
                celulas_valores.append({
                    "range": "%s%d" % (letra, r_total + 1),
                    "values": [[_para_dialeto_pt(f) + "+" + ref]]})

    if celulas_valores:
        painel.batch_update(celulas_valores, value_input_option="USER_ENTERED")


def _validacoes_painel_mensal(planilha, painel) -> None:
    """
    Menus suspensos do Painel Mensal (pedido do usuário, 08/08/2026):
    B4 = mês (Janeiro..Dezembro) e D4 = ano (2025..2030).

    A grafia dos meses tem de ser EXATAMENTE a da aba Categorias (R5:R16,
    capitalizada), porque a competência calculada em E4 usa
    CORRESP($B$4; Categorias!$R$5:$R$16; 0) — um "janeiro" minúsculo casaria
    (CORRESP ignora caixa), mas manter a mesma grafia evita depender disso.

    Reaplicar a cada sincronização é de propósito: se a validação for
    removida por acidente, a próxima rodada a devolve.
    """
    meses = [m.capitalize() for m in config.MESES_PT]
    anos = [str(a) for a in range(2025, 2031)]

    def regra(valores):
        return {"condition": {"type": "ONE_OF_LIST",
                              "values": [{"userEnteredValue": v} for v in valores]},
                "showCustomUi": True, "strict": True}

    def intervalo(linha, coluna):        # 0-based, célula única
        return {"sheetId": painel.id,
                "startRowIndex": linha, "endRowIndex": linha + 1,
                "startColumnIndex": coluna, "endColumnIndex": coluna + 1}

    planilha.batch_update({"requests": [
        {"setDataValidation": {"range": intervalo(3, 1), "rule": regra(meses)}},   # B4
        {"setDataValidation": {"range": intervalo(3, 3), "rule": regra(anos)}},    # D4
    ]})


# Notas dos títulos da aba Lançamentos (cabeçalho na linha 3).
NOTAS_COLUNAS_LANCAMENTOS = {
    "A3": "Banco do lançamento: Nubank ou Santander.",
    "B3": "De onde veio: Fatura (cartão de crédito) ou Extrato (conta corrente).",
    "C3": "Data da transação. No cartão, é o dia da compra — não o da fatura.",
    "D3": "Descrição como veio do banco (estabelecimento, PIX, tarifa...).",
    "E3": "Categoria dada pelas Regras do sistema (editável na tela Lançamentos).",
    "F3": "Detalhe da categoria (ex.: Streaming, Urbano, Encargos/Tarifas).",
    "G3": "Rótulo dos gastos recorrentes (aluguel, luz, academia...). "
          "É o que alimenta o Painel Mensal.",
    "H3": "Conta: Cartão Nubank, Cartão Santander, Conta Nubank ou Conta Santander.",
    "I3": "Receita, Despesa ou Transferência. Transferência = movimento entre "
          "contas próprias e pagamento de fatura — não soma no resultado do mês.",
    "J3": "Valor em R$. Negativo = saída; positivo = entrada ou estorno.",
    "K3": "Mês em que o valor pesa no caixa: mês da fatura (cartões) "
          "ou mês da data (extratos).",
    "L3": "Situação do lançamento (Confirmado / Previsto).",
    "M3": "Arquivo importado que originou a linha.",
}

SITUACAO_ROTULO = {
    "ok": "✔ confere",
    "importacao_incompleta": "⚠ importação incompleta",
    "conferir_resumo": "⚠ conferir resumo",
    "sem_resumo": "sem resumo",
    "sem_lancamentos": "sem lançamentos",
}
