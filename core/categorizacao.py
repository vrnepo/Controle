"""
Categorização dos lançamentos.

As regras vivem na tabela `regras` e são editáveis pela tela — antes moravam
dentro de um script Python e a planilha só as documentava, então a documentação
envelhecia sozinha.

A PRIMEIRA regra que casa vence, na ordem da coluna `ordem`. As regras de
transferência têm de vir antes de tudo: se um "PAGAMENTO CARTAO CREDITO" cair
numa regra de despesa, o mês conta o gasto duas vezes — uma na compra, outra no
pagamento da fatura.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Tuple

from core import config

# (padrão, categoria, subcategoria, item fixo, tipo forçado)
REGRAS_PADRAO: List[Tuple[str, str, str, str, str]] = [
    # --- transferências primeiro, sempre
    (r"PAGAMENTO DE FATURA|PAGAMENTO CARTAO CREDITO|PIX ENVIADO \d+ BANCO SANTANDER"
     r"|PAGAMENTO DE BOLETO BANCO SANTANDER",
     config.CATEGORIA_TRANSFERENCIA, "Pagamento de fatura", "", ""),
    # Linhas de fechamento da fatura Santander (decisão do usuário, 08/08/2026):
    # entram como lançamento para o total da fatura bater com o "Saldo Desta
    # Fatura" do resumo, mas como TRANSFERÊNCIA — não são gasto novo do mês.
    (r"SALDO ANTERIOR DA FATURA|PAGAMENTOS RECEBIDOS NA FATURA"
     r"|AJUSTE DE ARREDONDAMENTO DA FATURA",
     config.CATEGORIA_TRANSFERENCIA, "Fechamento da fatura", "", "Transferência"),
    (r"\bVITOR\b", config.CATEGORIA_TRANSFERENCIA, "Entre contas próprias", "", ""),

    # --- receitas
    (r"LIQUIDO DE VENCIMENTO", "Salário", "", "Salário", ""),
    (r"CARLOS EDUARDO S SILVA", "Aluguel FLAT", "", "Aluguel FLAT (recebido)", ""),
    (r"REMUNERACAO APLICACAO", "Outras Receitas", "Rendimento conta", "", ""),
    (r"ESTORNO|REEMBOLSO", "Reembolsos & Estornos", "", "", ""),

    # --- encargos de fatura
    (r"\(FATURA\)|PARCELAMENTO DE FATURA|AJUSTE DE IMPORTACAO",
     "Tarifas & Impostos", "Encargos/Tarifas", "Encargos de fatura", ""),
    (r"IOF|JUROS|MULTA|ENCARGO",
     "Tarifas & Impostos", "Encargos/Tarifas", "Encargos de fatura", ""),
    (r"TARIFA MENSALIDADE|ANUIDADE|MENSALIDADE PACOTE|TARIFA",
     "Tarifas & Impostos", "Encargos/Tarifas", "Tarifa bancária/anuidade", ""),
    # A assinatura Nubank+ é a anuidade do cartão (decisão do usuário,
    # 08/08/2026, ao corrigir a fatura de jul/26 onde ela tinha ficado de fora).
    (r"NUBANK\+", "Tarifas & Impostos", "Encargos/Tarifas", "Tarifa bancária/anuidade", ""),

    # --- moradia
    (r"ALMEIDA FERNANDES ADVOGAD", "Moradia – APTO", "Aluguel", "Aluguel apartamento", ""),
    (r"VLADIMIR FARIAS NEPOMUCEN", "FLAT", "Condomínio/IPTU", "Condomínio FLAT (pai)", ""),
    (r"\bLIGHT\b|CEB\b|NEOENERGIA|ENEL", "Moradia – APTO", "Energia", "Luz (Light)", ""),
    (r"NATURG|NIT GAS|\bCEG\b|DISTRIBUIDORA DE GAS|\bGAS\b",
     "Moradia – APTO", "Gás", "Gás (Naturgy/CEG)", ""),
    (r"TELEFONICA|VIVO ", "Moradia – APTO", "Telefonia/Internet",
     "Telefone (Vivo/Telefônica)", ""),
    (r"CLARO", "Moradia – APTO", "Telefonia/Internet", "Internet (Claro)", ""),
    (r"\bIPTU\b", "Moradia – APTO", "Condomínio/IPTU", "IPTU", ""),
    (r"CONDOMINIO|COND\.|\bCOND\b", "Moradia – APTO", "Condomínio/IPTU",
     "Condomínio apartamento", ""),
    (r"ROSEANE MARIA", "Moradia – APTO", "Diarista", "Diarista", ""),
    (r"LUCIA HELENA MOREIRA", "Moradia – APTO", "Cozinheira", "Cozinheira", ""),
    (r"ELETRICA|CLIMATIZACAO|MANUTENCAO|REFORMA", "Moradia – APTO", "Manutenção", "", ""),

    # --- saúde e pessoas
    (r"ANA MARIA PEREIRA LIMA", "Saúde", "Psicóloga", "Psicóloga", ""),
    (r"DROGA|FARMA|PACHECO|RAIA|PAGUE MENOS|PLANO DE SAUDE|UNIMED|AMIL"
     r"|BRADESCO SAUDE|LABORATORIO|CLINICA|DENTISTA|HOSPITAL", "Saúde", "Saúde", "", ""),
    (r"GUILHERME ZENHA", "Outros", "Família", "Família (Guilherme)", ""),

    # --- assinaturas e estudos
    (r"TEC CONCURSOS|LS CONCURSOS|ESTRATEGIA|GRAN CURSOS|UDEMY|ALURA|CONCURSO",
     "Estudos", "Concursos/Cursos", "", ""),
    (r"SELFIT|UPPER SPORT|SMARTFIT|SMART FIT|BLUEFIT|ACADEMIA|GYMPASS|WELLHUB",
     "Assinaturas", "Academia", "Academia", ""),
    (r"SPOTIFY|YOUTUBE|NETFLIX|PRIME CANAIS|AMAZON PRIME|HBO|DISNEY|GLOBOPLAY|DEEZER",
     "Assinaturas", "Streaming", "", ""),
    (r"OPENAI|ANTHROPIC|CLAUDE|CURSOR|CHATGPT|GOOGLE WORKSPACE|REGISTROBR|ICLOUD"
     r"|APPLE\.COM|APPLE |WPS OFFICE|MICROSOFT|ADOBE|CANVA",
     "Assinaturas", "Apps/IA", "", ""),
    (r"\bTIM\b", "Assinaturas", "Telefonia/Internet", "Celular (TIM)", ""),

    # --- transporte
    (r"POSTO|COMBUSTIVEL|GASOLINA|IPVA|DETRAN|SEGURO AUTO|PORTO SEGURO|LAVA ?JATO"
     r"|ESTACIONAMENTO|SEM PARAR|LOCADORA", "Carro", "Carro", "", ""),
    (r"\bUBER|99\*|99APP|METRO RJ|METRO\b|BILHETE UNICO|ONIBUS|BRT\b",
     "Transporte", "Urbano", "", ""),

    # --- lazer
    (r"AIRBNB|HOTEL|POUSADA|LATAM|GOL\b|AZUL\b|VOO|BOOKING|DECOLAR|AEROPORTO|GALEAO",
     "Lazer & Viagem", "Viagem", "", ""),
    (r"ZOUK|FORRO|INGRESSO|CINEMA|TEATRO|SHOW|EVENTO|BAILE|GUAPIKART|KART"
     r"|BIKE RADICAL|DANCA|FUTEBOLCARD", "Lazer & Viagem", "Lazer", "", ""),

    # --- alimentação
    (r"IFD\*|IFOOD|ZONA SUL|SUPERM|MERCADO|PAO DE ACUCAR|HORTIFRUTI|VAREJAO|ACOUGUE"
     r"|PADARIA|RESTAURANTE|PIZZARIA|BURGER|LANCHES|\bBAR\b|CAFE|ROTISSERIA|CHURRASC"
     r"|SUSHI|CREPE|MANGAI|CASERATTO|DOG DO|GOURMET|BIO MUNDO|SPID\b|FARTURA|BARCELOS"
     r"|SHEKINAH|GLORIA MATE|QUALITY|SAIDA SUL|VILA RICA|CHIBA|ARCOS DOURADOS|PAPRICA"
     r"|BRAZOLIA|BRASOLIA|RESTAURAN|STEAK|EMPORIO|CUCINA|BACKER|COMBINADO|MEGAGLORIA"
     r"|SM MUNDIAL|FILET", "Alimentação", "Alimentação", "", ""),

    # --- compras
    (r"AMAZON|MERCADOLIVRE|MERCADOPAGO|MP \*|SHOPEE|ALIEXPRESS|MAGALU|MAGAZINE|SHEIN"
     r"|DECATHLON|CENTAURO|RENNER|RIACHUELO|C&A|HTM\*|DL ?\*",
     "Compras & Vestuário", "Compras", "", ""),
    (r"BARBEARIA|CABELO|SALAO|BELEZA", "Compras & Vestuário", "Cuidados pessoais", "", ""),
    (r"MOVEIS|DECORACO", "Compras & Vestuário", "Casa/Móveis", "", ""),
    (r"ADVOGAD", "Outros", "Serviços jurídicos", "", ""),
    (r"PETZ|PET SHOP|VETERINARI", "Outros", "Pets", "", ""),
]


def normalizar(texto: object) -> str:
    """Sem acento, maiúsculo, espaços colapsados. Base de toda comparação."""
    s = unicodedata.normalize("NFD", str(texto or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.upper().split())


class Regra:
    __slots__ = ("padrao", "rx", "categoria", "subcategoria", "item_fixo", "tipo")

    def __init__(self, padrao: str, categoria: str, subcategoria: str,
                 item_fixo: str, tipo: str):
        self.padrao = padrao
        self.rx = re.compile(padrao)
        self.categoria = categoria or ""
        self.subcategoria = subcategoria or ""
        self.item_fixo = item_fixo or ""
        self.tipo = tipo or ""


def compilar(brutas) -> List[Regra]:
    """Compila as regras vindas do banco, pulando regex inválida.

    Pular em silêncio é deliberado: uma regex quebrada que o usuário digitou na
    tela não pode derrubar a importação inteira do mês. Ela aparece marcada na
    tela de Regras.
    """
    out: List[Regra] = []
    for r in brutas:
        padrao = (r["padrao"] or "").strip()
        if not padrao or not r.get("ativa", True):
            continue
        try:
            out.append(Regra(padrao, r.get("categoria"), r.get("subcategoria"),
                             r.get("item_fixo"), r.get("tipo")))
        except re.error:
            continue
    return out


def regex_valida(padrao: str) -> bool:
    try:
        re.compile(padrao)
        return True
    except re.error:
        return False


def classificar(descricao: str, valor: float, conta_tipo: str,
                regras: List[Regra]) -> Dict[str, str]:
    """
    Devolve {categoria, subcategoria, item_fixo, tipo}.

    `conta_tipo` é 'cartao' ou 'conta': numa fatura tudo é despesa (e valor
    positivo é estorno); num extrato o sinal decide receita ou despesa.
    """
    d = normalizar(descricao)
    categoria = subcategoria = item_fixo = tipo_forcado = ""

    for r in regras:
        if r.rx.search(d):
            categoria, subcategoria = r.categoria, r.subcategoria
            item_fixo, tipo_forcado = r.item_fixo, r.tipo
            break

    # item fixo não se aplica a movimento entre contas próprias
    if categoria == config.CATEGORIA_TRANSFERENCIA:
        item_fixo = ""

    if tipo_forcado:
        tipo = tipo_forcado
    elif categoria == config.CATEGORIA_TRANSFERENCIA:
        tipo = config.TIPO_TRANSFERENCIA
    elif conta_tipo == "cartao":
        tipo = config.TIPO_DESPESA
        if not categoria:
            categoria, subcategoria = "Outros", ""
        if valor > 0 and categoria != "Reembolsos & Estornos":
            subcategoria = (subcategoria + " (estorno)").strip()
    elif valor > 0:
        tipo = config.TIPO_RECEITA
        if not categoria or categoria in ("Alimentação", "Compras & Vestuário"):
            categoria, subcategoria = "Outras Receitas", "PIX recebido"
    else:
        tipo = config.TIPO_DESPESA
        if not categoria:
            categoria, subcategoria = "Outros", "PIX/pagamento"

    return {"categoria": categoria, "subcategoria": subcategoria,
            "item_fixo": item_fixo, "tipo": tipo}
