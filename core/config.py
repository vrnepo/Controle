"""
Configuração central — tudo que vem do ambiente e tudo que é convenção.

Mesmo princípio do SICAD: nada de segredo no código, nada de índice de coluna
espalhado pelo sistema. Se um nome muda, muda aqui.
"""

from __future__ import annotations

import os

# ----------------------------------------------------------------- ambiente

APP_NOME = "Controle Financeiro"
APP_VERSAO = "3.0"

FUSO = "America/Sao_Paulo"


def env(chave: str, padrao: str = "") -> str:
    return (os.environ.get(chave) or padrao).strip()


def cookie_seguro() -> bool:
    """No Render (https) o cookie vai com Secure; no localhost, não — senão o
    navegador descarta e o login nunca "pega"."""
    return env("COOKIE_SEGURO") == "1"


def secret_key() -> str:
    # Em desenvolvimento uma chave fixa é aceitável e evita perder a sessão a
    # cada --reload. Em produção o Render gera a dela (generateValue: true).
    return env("SECRET_KEY", "financas-desenvolvimento-nao-use-em-producao")


def senha_pdf_santander() -> str:
    """Senha dos PDFs de fatura do Santander. Fica SÓ no ambiente — nunca no
    código e nunca em log, porque é o CPF do titular."""
    return env("SENHA_PDF_SANTANDER")


def planilha_espelho_id() -> str:
    return env("PLANILHA_ESPELHO_ID")


def espelho_ativo() -> bool:
    return bool(planilha_espelho_id() and env("GCP_SERVICE_ACCOUNT_JSON"))


# ------------------------------------------------------------- vocabulário

# Sinal: saída de dinheiro é NEGATIVA em toda parte do sistema. Estorno e
# crédito são positivos. Uma regra só, sem exceção por tela.
TIPO_RECEITA = "Receita"
TIPO_DESPESA = "Despesa"
TIPO_TRANSFERENCIA = "Transferência"

FONTE_FATURA = "Fatura"
FONTE_EXTRATO = "Extrato"

STATUS_PADRAO = "Confirmado"

CATEGORIA_TRANSFERENCIA = "Transferência entre contas"

CONTAS_PADRAO = [
    # (nome, banco, tipo)
    ("Cartão Nubank", "Nubank", "cartao"),
    ("Cartão Santander", "Santander", "cartao"),
    ("Conta Nubank", "Nubank", "conta"),
    ("Conta Santander", "Santander", "conta"),
]

CATEGORIAS = [
    "Moradia – APTO", "FLAT", "Carro", "Saúde", "Alimentação", "Assinaturas",
    "Estudos", "Lazer & Viagem", "Presentes", "Compras & Vestuário",
    "Transporte", "Tarifas & Impostos", "Imprevistos", "Outros",
    "Salário", "Aluguel FLAT", "Reembolsos & Estornos", "Outras Receitas",
    "Aplicação", CATEGORIA_TRANSFERENCIA,
]

# Categorias que NÃO entram no total de despesas do mês: movimento entre
# contas próprias e pagamento de fatura não são gasto novo — contá-los
# dobraria o mês, porque a despesa já entrou quando a compra foi feita.
CATEGORIAS_FORA_DO_RESULTADO = [CATEGORIA_TRANSFERENCIA]

# Cartões cuja fatura, por decisão do usuário (08/08/2026), carrega TAMBÉM o
# saldo anterior e os pagamentos como lançamentos (tipo Transferência): a soma
# dos lançamentos do mês passa a ser o "(=) Saldo Desta Fatura" do resumo.
# A conciliação usa esta lista para saber o que esperar da soma.
CONTAS_FATURA_TOTAL = ["Cartão Santander"]

MESES_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]

MES_ABREV = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
             "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12}


def mes_curto(mes: int) -> str:
    return MESES_PT[mes - 1][:3] + "./"
