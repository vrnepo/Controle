"""
Importação incremental: pega o que os parsers leram, categoriza, deduplica e
grava.

A deduplicação é por MULTIPLICIDADE, não por presença. Conta-se quantas vezes
cada chave já existe no banco e quantas vezes ela vem no arquivo; entra só a
diferença.

Por que não o simples "já existe uma linha igual? então pula": existem cobranças
idênticas de verdade no mesmo dia. Na fatura de ago/2026 há duas de
"Google Workspace_sicad 50,00" em 29/07, duas de "Anthropic 20,76" e duas de
"IOF de compra internacional 0,72" em 25/07. Medido nos dados reais: reimportar
o CSV do Nubank com multiplicidade insere 0 linhas; com o dedup ingênuo insere 3,
somando R$ 71,48 de gasto que nunca existiu.

A garantia final é do banco — UNIQUE (chave, ocorrencia) em `lancamentos`.
"""

from __future__ import annotations

import collections
import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

from core import categorizacao, config, parsers, repositorio

# Mesmo corte do pipeline que gerou o histórico de 2026. Truncar em tamanho
# diferente mudaria a chave e as 106 linhas já cortadas em 80 voltariam como
# "novas" na primeira importação.
LIMITE_DESCRICAO = 80

# Formatos onde a MESMA transação chega com grafia diferente e a chave exata
# não protege. Print: o OCR reescreve a descrição (caso de 10/08/2026).
# Faturas: medido em 13/08/2026 na Nubank ago/26 — CSV parcial, CSV fechado e
# PDF grafam o mesmo item de três jeitos ("IOF de compra internacional" ×
# 'IOF de "Anthropic"' × "IOF de Anthropic* Claude Sub"; "Cursor Ai" ×
# "Cursor, Ai"), e 19 duplicatas entraram somando R$ 883,21. Extratos ficam
# FORA: lá a grafia é estável e a barreira só arriscaria bloquear PIX
# legítimos de mesmo valor no mesmo dia.
FORMATOS_QUASE_DUPLICATA = frozenset([
    "Print do app (OCR)",
    "CSV fatura Nubank", "PDF fatura Nubank", "PDF fatura Santander",
])


def chave(conta_id: int, competencia: dt.date, data: dt.date,
          descricao: str, valor: float) -> str:
    return "|".join([
        str(conta_id),
        competencia.strftime("%Y-%m"),
        data.strftime("%Y-%m-%d"),
        categorizacao.normalizar(descricao[:LIMITE_DESCRICAO]),
        str(int(round(float(valor) * 100))),
    ])


def chave_sem_dia(k: str) -> str:
    """A mesma chave sem o dia — só para o aviso de duplicata deslocada."""
    partes = k.split("|")
    return "|".join([partes[0], partes[1]] + partes[3:])


def decidir_linhas(linhas: List[Tuple[str, Tuple[int, str, int]]],
                   ja_no_banco: Dict[str, int],
                   quase_gemeas: Dict[Tuple[int, str, int], int]
                   ) -> List[Tuple[str, int]]:
    """
    O veredicto de cada linha, na ordem do arquivo: ("insere" | "duplicada" |
    "quase", ocorrencia). Pura de propósito — é a regra que, se errar, erra
    o dinheiro.

    Degraus: 1) chave exata já no banco, por MULTIPLICIDADE (comportamento de
    sempre); 2) QUASE-DUPLICATA (10/08/2026 p/ print; 13/08/2026 também p/
    faturas — `quase_gemeas` vem vazio nos demais formatos): mesma (conta,
    dia, valor) já no banco com outra grafia NÃO entra. Foi o furo real: o OCR trocou a descrição/data e
    "Liquido de vencimento 12.742,33" entrou de novo ao lado da transcrição à
    mão. Cada linha do banco só "absorve" UMA linha do arquivo (consumidas):
    dois PIX legítimos de mesmo valor no mesmo dia continuam entrando quando
    o banco só tem um.
    """
    vistas: collections.Counter = collections.Counter()
    consumidas: collections.Counter = collections.Counter()
    saida: List[Tuple[str, int]] = []
    for k, tripla in linhas:
        vistas[k] += 1
        if vistas[k] <= ja_no_banco.get(k, 0):
            consumidas[tripla] += 1              # a gêmea exata também conta
            saida.append(("duplicada", vistas[k]))
        elif consumidas[tripla] < quase_gemeas.get(tripla, 0):
            consumidas[tripla] += 1
            saida.append(("quase", vistas[k]))
        else:
            saida.append(("insere", vistas[k]))
    return saida


class Resultado:
    def __init__(self, arquivo: str, formato: str = "", conta: str = ""):
        self.arquivo = arquivo
        self.formato = formato
        self.conta = conta
        self.lidos = 0
        self.inseridos = 0
        self.duplicados = 0
        self.suspeitos = 0
        self.resumos = 0
        self.avisos: List[str] = []
        self.erro = ""

    def como_dict(self) -> Dict[str, Any]:
        return {
            "arquivo": self.arquivo, "formato": self.formato, "conta": self.conta,
            "lidos": self.lidos, "inseridos": self.inseridos,
            "duplicados": self.duplicados, "suspeitos": self.suspeitos,
            "resumos": self.resumos, "avisos": self.avisos,
            "status": "ERRO" if self.erro else "OK", "erro": self.erro,
        }


def importar(nome: str, dados: bytes) -> Resultado:
    """Lê um arquivo e grava. Nunca levanta exceção para fora: erro previsto
    volta no Resultado, para a tela mostrar o motivo e o log guardar."""
    resultado = Resultado(nome)
    try:
        leitura = parsers.ler(nome, dados, config.senha_pdf_santander())
        resultado.formato = leitura.formato
        resultado.conta = leitura.conta
        resultado.avisos.extend(leitura.avisos)
        _gravar(leitura, resultado)
    except parsers.ErroDeLeitura as erro:
        resultado.erro = str(erro)
    except Exception as erro:                     # imprevisto: não expõe stack
        resultado.erro = "Falha ao ler o arquivo: %s" % erro

    repositorio.registrar_importacao({
        "arquivo": resultado.arquivo, "formato": resultado.formato,
        "conta": resultado.conta, "lidos": resultado.lidos,
        "inseridos": resultado.inseridos, "duplicados": resultado.duplicados,
        "suspeitos": resultado.suspeitos,
        "status": "ERRO" if resultado.erro else "OK",
        "observacao": resultado.erro or "; ".join(resultado.avisos),
    })
    return resultado


def _gravar(leitura: parsers.Leitura, resultado: Resultado) -> None:
    contas = repositorio.mapa_contas()

    # --- resumos oficiais de fatura
    for r in leitura.resumos:
        conta = contas.get(r["conta"])
        if not conta:
            resultado.avisos.append("Conta desconhecida no resumo: %s" % r["conta"])
            continue
        repositorio.upsert_resumo({
            "conta_id": conta["id"], "competencia": r["competencia"],
            "saldo_anterior": r["saldo_anterior"], "despesas": r["despesas"],
            "encargos": r["encargos"], "creditos": r["creditos"],
            "pagamentos": r["pagamentos"], "total_informado": r["total_informado"],
            "arquivo": r["arquivo"]})
        resultado.resumos += 1

    if not leitura.linhas:
        return

    resultado.lidos = len(leitura.linhas)
    regras = categorizacao.compilar(repositorio.regras(somente_ativas=True))

    # --- monta as chaves
    preparadas: List[Tuple[str, Dict[str, Any]]] = []
    pares_competencia = set()
    for linha in leitura.linhas:
        conta = contas.get(linha["conta"])
        if not conta:
            resultado.avisos.append("Conta desconhecida: %s" % linha["conta"])
            continue
        k = chave(conta["id"], linha["competencia"], linha["data"],
                  linha["descricao"], linha["valor"])
        classe = categorizacao.classificar(linha["descricao"], linha["valor"],
                                           conta["tipo"], regras)
        preparadas.append((k, {
            "conta_id": conta["id"],
            "fonte": config.FONTE_FATURA if conta["tipo"] == "cartao" else config.FONTE_EXTRATO,
            "data": linha["data"],
            "descricao": linha["descricao"][:LIMITE_DESCRICAO],
            "categoria": classe["categoria"], "subcategoria": classe["subcategoria"],
            "item_fixo": classe["item_fixo"], "tipo": classe["tipo"],
            "valor": round(float(linha["valor"]), 2),
            "competencia": linha["competencia"], "status": config.STATUS_PADRAO,
            "arquivo": linha["arquivo"],
        }))
        pares_competencia.add((conta["id"], linha["competencia"]))

    if not preparadas:
        return

    # --- quantas vezes cada chave já existe
    ja_no_banco = repositorio.contagem_por_chave([k for k, _ in preparadas])
    no_mes = collections.Counter(
        chave_sem_dia(k) for k in repositorio.chaves_das_competencias(pares_competencia))

    # Quase-gêmeas para print E faturas (FORMATOS_QUASE_DUPLICATA — extensão
    # de 13/08/2026): nos extratos a descrição é estável e a chave exata
    # basta — o dicionário fica vazio e o degrau 2 nunca dispara.
    quase_gemeas: Dict[Tuple[int, str, int], int] = {}
    if leitura.formato in FORMATOS_QUASE_DUPLICATA:
        quase_gemeas = repositorio.contagem_por_dia_valor(
            {(d["conta_id"], d["data"]) for _, d in preparadas})

    def tripla(d: Dict[str, Any]) -> Tuple[int, str, int]:
        return (d["conta_id"], d["data"].isoformat(),
                int(round(float(d["valor"]) * 100)))

    decisoes = decidir_linhas([(k, tripla(d)) for k, d in preparadas],
                              ja_no_banco, quase_gemeas)
    quase = 0
    novas: List[Dict[str, Any]] = []
    for (k, dados), (veredicto, ocorrencia) in zip(preparadas, decisoes):
        if veredicto == "duplicada":
            resultado.duplicados += 1
            continue
        if veredicto == "quase":
            resultado.duplicados += 1
            quase += 1
            continue
        if ja_no_banco.get(k, 0) == 0 and no_mes.get(chave_sem_dia(k), 0) > 0:
            resultado.suspeitos += 1
        dados["chave"] = k
        dados["ocorrencia"] = ocorrencia
        novas.append(dados)

    if quase:
        resultado.avisos.append(
            "%d linha(s) do arquivo não entraram: o banco já tem lançamento "
            "com a mesma conta, mesmo dia e mesmo valor vindo de outra "
            "importação (grafia diferente — quase-duplicata). Se for de fato "
            "OUTRA transação de igual valor no mesmo dia, lance à mão pela "
            "tela Lançamentos." % quase)

    resultado.inseridos = repositorio.inserir_lancamentos(novas)
    # A diferença entre o que tentamos inserir e o que o banco aceitou só pode
    # vir do ON CONFLICT — ou seja, corrida com outra importação.
    if resultado.inseridos < len(novas):
        resultado.duplicados += len(novas) - resultado.inseridos

    if resultado.suspeitos:
        resultado.avisos.append(
            "%d lançamento(s) com mesma descrição e valor no mês, em outro dia. "
            "Entraram — confira se não é repetição." % resultado.suspeitos)


def reprocessar(conta_id: Optional[int], competencia: dt.date) -> int:
    """Limpa um mês para reimportar do zero (fatura corrigida pelo banco)."""
    return repositorio.apagar_competencia(conta_id, competencia)
