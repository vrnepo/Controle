"""
Conciliação: por que o app do banco mostra outro número.

O sistema mede GASTO DO MÊS. O app do banco mostra VALOR A PAGAR — outra
grandeza:

    Total a pagar = Saldo anterior + Despesas + Encargos − Créditos − Pagamentos

Quando a fatura é paga parcialmente, o saldo rola para o mês seguinte e os dois
números se separam. Verificado ao centavo nas 7 faturas Santander de 2026:

    jul/2026   app 13.731,69   gasto do mês 9.216,26
               13.015,43 vinham de trás e 8.500,00 foram pagos

Em mai/2026 e ago/2026 os dois números quase coincidem — por coincidência
aritmética, não por acerto. É justamente por isso que a conciliação precisa
existir: sem ela, "bateu" e "não bateu" viram impressão.

A coluna `situacao` separa o que é diferença esperada do que é erro:

    ok                      gasto e resumo batem, e o total calculado bate com o app
    importacao_incompleta   falta lançamento — `delta_importacao` diz quanto
    conferir_resumo         os lançamentos fecham, mas o resumo digitado não
    sem_resumo              falta preencher o resumo oficial daquele mês
    sem_lancamentos         nada importado nesse mês
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from core import config, repositorio

TOLERANCIA = 0.05        # centavos de arredondamento não são divergência


def linhas(competencia: Optional[dt.date] = None) -> List[Dict[str, Any]]:
    """Uma linha por cartão × competência."""
    gastos = {}
    for g in repositorio.gasto_por_conta():
        if g["tipo"] != "cartao":
            continue
        gastos[(g["conta"], g["competencia"])] = float(g["total"] or 0)

    resumos = {}
    for r in repositorio.resumos():
        resumos[(r["conta"], r["competencia"])] = r

    chaves = set(gastos) | set(resumos)
    if competencia:
        chaves = {k for k in chaves if k[1] == competencia}

    saida: List[Dict[str, Any]] = []
    for conta, comp in sorted(chaves, key=lambda k: (k[1], k[0])):
        # gasto do mês em positivo: fatura se lê como valor a pagar, não como
        # saldo negativo
        gasto = -gastos.get((conta, comp), 0.0)
        r = resumos.get((conta, comp))

        linha: Dict[str, Any] = {
            "conta": conta, "competencia": comp, "gasto_do_mes": round(gasto, 2),
            "despesas_encargos": None, "delta_importacao": None,
            "saldo_anterior": None, "pagamentos": None,
            "total_calculado": None, "total_informado": None, "delta_app": None,
            "situacao": "sem_resumo", "explicacao": "",
        }

        if not gasto and not r:
            linha["situacao"] = "sem_lancamentos"
            saida.append(linha)
            continue

        if r:
            despesas = float(r["despesas"] or 0)
            encargos = float(r["encargos"] or 0)
            creditos = float(r["creditos"] or 0)
            saldo = float(r["saldo_anterior"] or 0)
            pagamentos = float(r["pagamentos"] or 0)
            informado = float(r["total_informado"] or 0)

            novo = despesas + encargos - creditos
            calculado = saldo + novo - pagamentos

            # O que a soma dos lançamentos DEVE dar depende do desenho da
            # conta: no Cartão Santander os lançamentos incluem saldo anterior
            # e pagamentos (config.CONTAS_FATURA_TOTAL), então a soma esperada
            # é o próprio Saldo Desta Fatura; nas demais, só o gasto novo.
            esperado = calculado if conta in config.CONTAS_FATURA_TOTAL else novo

            linha["despesas_encargos"] = round(novo, 2)
            linha["delta_importacao"] = round(gasto - esperado, 2)
            linha["saldo_anterior"] = round(saldo, 2)
            linha["pagamentos"] = round(pagamentos, 2)
            linha["total_calculado"] = round(calculado, 2)
            linha["total_informado"] = round(informado, 2)
            linha["delta_app"] = round(calculado - informado, 2) if informado else None

            if abs(linha["delta_importacao"]) > TOLERANCIA:
                linha["situacao"] = "importacao_incompleta"
                linha["explicacao"] = (
                    "Faltam %s em lançamentos: pelo resumo da fatura a soma deveria "
                    "ser %s, e os lançamentos somam %s."
                    % (_moeda(abs(linha["delta_importacao"])), _moeda(esperado),
                       _moeda(gasto)))
            elif linha["delta_app"] is not None and abs(linha["delta_app"]) > TOLERANCIA:
                linha["situacao"] = "conferir_resumo"
                linha["explicacao"] = (
                    "Os lançamentos fecham com o resumo, mas o resumo não fecha com o "
                    "total do app: calculado %s contra %s informado."
                    % (_moeda(calculado), _moeda(informado)))
            else:
                linha["situacao"] = "ok"
                if conta in config.CONTAS_FATURA_TOTAL:
                    linha["explicacao"] = (
                        "Os lançamentos incluem saldo anterior e pagamentos: a soma "
                        "%s é o próprio Saldo Desta Fatura." % _moeda(gasto))
                elif informado and abs(gasto - informado) > TOLERANCIA:
                    linha["explicacao"] = (
                        "Gasto do mês %s; o app mostra %s porque %s vieram de saldo "
                        "anterior e %s foram pagos. Diferença esperada."
                        % (_moeda(gasto), _moeda(informado), _moeda(saldo),
                           _moeda(pagamentos)))
        else:
            linha["explicacao"] = (
                "Importe o resumo oficial dessa fatura (ou preencha à mão) para poder "
                "comparar com o app.")

        saida.append(linha)
    return saida


def _moeda(valor: float) -> str:
    """1234.5 → 'R$ 1.234,50'. O \\x00 é só um pivô para trocar . e , de uma vez."""
    texto = "{:,.2f}".format(float(valor or 0))
    return "R$ " + texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def resumo_situacoes(competencia: Optional[dt.date] = None) -> Dict[str, int]:
    contagem: Dict[str, int] = {}
    for linha in linhas(competencia):
        contagem[linha["situacao"]] = contagem.get(linha["situacao"], 0) + 1
    return contagem
