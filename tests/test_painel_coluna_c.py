# -*- coding: utf-8 -*-
"""
Gerador da coluna C do Painel Mensal (13/08/2026): a C inteira é do sistema
e é regravada a cada sincronização a partir dos rótulos da coluna A — mesmo
que o usuário tenha apagado a fórmula. Os rótulos do teste são os REAIS do
Painel na data.
"""

from __future__ import annotations

from core.espelho import _formulas_c_do_painel

# Coluna A real do Painel Mensal (0-based; linha 1 da planilha = índice 0).
ROTULOS = [
    "PAINEL MENSAL — ITENS FIXOS E PADRÕES",
    "Escolha mês e ano nas células amarelas.",
    "",
    "Mês de referência:",
    "RESULTADO DO MÊS",
    "Total de receitas",
    "Total de despesas",
    "Resultado (sobra do mês)",
    "",
    "Grupo / Item",
    "Saldo em conta corrente (Santander) — até o mês selecionado",
    "RECEITAS",
    "    Saldo do mês anterior (SANTANDER)",
    "    Salário",
    "    Aluguel FLAT (recebido)",
    "    Reembolsos & estornos",
    "    Outras receitas",
    "    Transferências recebidas (entre contas)",
    "Subtotal — RECEITAS",
    "FATURAS DE CARTÃO (memo — não soma no total)",
    "    Fatura Nubank",
    "    Fatura Santander",
    "Subtotal — FATURAS DE CARTÃO",
    "APARTAMENTO",
    "    Aluguel",
    "    Condomínio",
    "    IPTU",
    "    Telefone (Vivo/Telefônica)",
    "    Internet (Claro)",
    "    Conta de luz (Light)",
    "    Conta de gás (Naturgy/CEG)",
    "    Cozinheira — pagamento 1",
    "    Cozinheira — pagamento 2",
    "    Cozinheira — pagamento 3",
    "    Cozinheira — pagamento 4",
    "    Cozinheira — pagamento 5",
    "    Diarista — pagamento 1",
    "    Diarista — pagamento 2",
    "    Diarista — pagamento 3",
    "Subtotal — APARTAMENTO",
    "FLAT",
    "    Condomínio FLAT (pai)",
    "Subtotal — FLAT",
    "PESSOAIS FIXAS",
    "    Psicóloga",
    "    Academia",
    "    Celular (TIM)",
    "    Família (Guilherme)",
    "Subtotal — PESSOAIS FIXAS",
    "DESPESAS VARIÁVEIS (padrões dos extratos e faturas)",
    "    Alimentação",
    "    Transporte",
    "    Compras & vestuário",
    "    Assinaturas & serviços digitais",
    "    Saúde",
    "    Lazer & viagem",
    "    Estudos",
    "    Carro",
    "    Tarifas, juros & impostos",
    "    Presentes",
    "    Imprevistos",
    "    Outros",
    "Subtotal — DESPESAS VARIÁVEIS",
]

F = _formulas_c_do_painel(ROTULOS)
POR_ROTULO = {ROTULOS[i].strip(): f for i, f in F.items()}


def test_fatura_soma_por_conta_sem_filtro_extrato():
    f = POR_ROTULO["Fatura Nubank"]
    assert '"Cartão Nubank"' in f and "$H$4" in f and "$F$4" in f
    assert "Extrato" not in f
    assert '"Cartão Santander"' in POR_ROTULO["Fatura Santander"]


def test_item_com_rotulo_diferente_do_banco_usa_o_mapa():
    f = POR_ROTULO["Conta de gás (Naturgy/CEG)"]
    assert '"Gás (Naturgy/CEG)"' in f and "$G$4" in f and '"Extrato"' in f
    assert '"Luz (Light)"' in POR_ROTULO["Conta de luz (Light)"]
    assert '"Aluguel apartamento"' in POR_ROTULO["Aluguel"]


def test_item_igual_ao_banco_entra_pelo_fallback():
    f = POR_ROTULO["Celular (TIM)"]
    assert '"Celular (TIM)"' in f and "$G$4" in f
    assert '"Psicóloga"' in POR_ROTULO["Psicóloga"]


def test_categoria_e_outras_receitas():
    f = POR_ROTULO["Outras receitas"]
    assert '"Outras Receitas"' in f and "$E$4" in f
    assert '"Receita"' in f and "$I$4" in f          # só tipo Receita
    assert '"Assinaturas"' in POR_ROTULO["Assinaturas & serviços digitais"]
    assert '"Tarifas & Impostos"' in POR_ROTULO["Tarifas, juros & impostos"]


def test_linhas_com_passo_proprio_ficam_fora():
    assert "Saldo do mês anterior (SANTANDER)" not in POR_ROTULO
    assert "Cozinheira — pagamento 1" not in POR_ROTULO
    assert "Mês de referência:" not in POR_ROTULO


def test_linha_amarela_e_transferencias_tem_padrao():
    memo = POR_ROTULO["Saldo em conta corrente (Santander) — até o mês selecionado"]
    assert '"<="&$F$4' in memo and '"<>Saldo"' in memo
    transf = POR_ROTULO["Transferências recebidas (entre contas)"]
    assert '">0"' in transf and '"Transferência"' in transf


def test_subtotais_somam_o_bloco_do_grupo():
    # RECEITAS: dados nos índices 12..17 → SUM($C$13:$C$18), subtotal no 18
    assert F[18] == "=SUM($C$13:$C$18)"
    # APARTAMENTO: dados 24..38 (inclui as linhas de pagamento) → subtotal 39
    assert F[39] == "=SUM($C$25:$C$39)"


def test_totais_referenciam_os_subtotais():
    assert F[5] == "=$C$19"                            # Total de receitas
    # Total de despesas = APARTAMENTO + FLAT + PESSOAIS + VARIÁVEIS + FATURAS
    assert F[6] == "=$C$40+$C$43+$C$49+$C$63+$C$23"
    assert F[7] == "=$C$6+$C$7"                        # Resultado


def test_toda_formula_e_canonica_com_virgulas():
    for f in F.values():
        assert ";" not in f
