/* ==========================================================================
   Controle Financeiro 3.0 — interface.

   Sem framework: sete telas trocando HTML no mesmo container. Regras da casa:
   - nenhum handler inline no HTML (a CSP manda script-src 'self');
   - todo texto vindo do banco passa por G.esc() antes de virar HTML —
     descrição de extrato é dado de fora, não é confiável;
   - o mês selecionado é um estado só, em ESTADO.competencia.
   ========================================================================== */

const ESTADO = {
  competencia: null,
  competencias: [],
  contas: [],
  painel: null,
  tela: "painel",
};

const $ = (id) => document.getElementById(id);
const tela = () => $("tela");

/* --------------------------------------------------------------- formato */

const moeda = (valor) => {
  const n = Number(valor || 0);
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
};

/* Em coluna de dinheiro, despesa em vermelho e receita em verde poupa a leitura
   do sinal. Zero fica neutro — pintar zero de vermelho é ruído. */
const celulaValor = (valor) => {
  const n = Number(valor || 0);
  const classe = n > 0 ? "positivo" : (n < 0 ? "negativo" : "");
  return `<td class="num ${classe}">${moeda(n)}</td>`;
};

const dataBR = (iso) => {
  if (!iso) return "";
  const [a, m, d] = String(iso).slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
};

const MESES = ["jan", "fev", "mar", "abr", "mai", "jun",
               "jul", "ago", "set", "out", "nov", "dez"];

const mesCurto = (iso) => {
  if (!iso) return "";
  const [a, m] = String(iso).slice(0, 10).split("-");
  return `${MESES[Number(m) - 1]}/${a.slice(2)}`;
};

const mesLongo = (iso) => {
  if (!iso) return "";
  const [a, m] = String(iso).slice(0, 10).split("-");
  const nomes = ["janeiro","fevereiro","março","abril","maio","junho",
                 "julho","agosto","setembro","outubro","novembro","dezembro"];
  return `${nomes[Number(m) - 1]} de ${a}`;
};

/* ------------------------------------------------------------------ rede */

async function api(caminho, opcoes) {
  const resposta = await fetch(caminho, opcoes);
  if (resposta.status === 401) {
    window.location.href = "/login";
    throw new Error("sessao");
  }
  const dados = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    throw new Error((dados && (dados.erro || dados.detail)) || "Falha na requisição.");
  }
  return dados;
}

function avisar(texto, tipo) {
  $("mensagem-global").innerHTML =
    `<div class="aviso aviso-${tipo || "info"}" style="margin-bottom:16px">
       <div>${G.esc(texto)}</div></div>`;
  if (tipo === "ok") {
    setTimeout(() => { $("mensagem-global").innerHTML = ""; }, 6000);
  }
}

const limparAviso = () => { $("mensagem-global").innerHTML = ""; };

/* ---------------------------------------------------------------- telas */

const TELAS = {
  painel:      { titulo: "Painel", sub: "Receitas, despesas e o resultado do mês." },
  lancamentos: { titulo: "Lançamentos", sub: "Uma linha por transação." },
  conciliacao: { titulo: "Conciliação", sub: "A fatura do sistema contra a do app do banco." },
  importar:    { titulo: "Importar arquivos", sub: "CSV, XLSX, OFX e PDF — inclusive o PDF com senha do Santander." },
  faturas:     { titulo: "Resumo de faturas", sub: "Os números do quadro-resumo da fatura." },
  regras:      { titulo: "Regras", sub: "Como cada descrição virou categoria. A primeira que casa vence." },
  ajustes:     { titulo: "Espelho e diagnóstico", sub: "Planilha do Google, banco e senha do PDF." },
};

function irPara(nome) {
  ESTADO.tela = nome;
  document.querySelectorAll("#nav button").forEach((b) => {
    if (b.dataset.tela === nome) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  $("titulo-tela").textContent = TELAS[nome].titulo;
  $("subtitulo-tela").textContent = TELAS[nome].sub;
  limparAviso();
  tela().innerHTML = `<div class="vazio">Carregando…</div>`;
  const dependeDoMes = ["painel", "lancamentos"].includes(nome);
  $("seletor-mes").classList.toggle("oculto", !dependeDoMes);
  ({
    painel: desenharPainel, lancamentos: desenharLancamentos,
    conciliacao: desenharConciliacao, importar: desenharImportar,
    faturas: desenharFaturas, regras: desenharRegras, ajustes: desenharAjustes,
  })[nome]();
}

/* ---------------------------------------------------------------- painel */

async function desenharPainel() {
  const dados = await api("/api/painel?competencia=" +
    encodeURIComponent(ESTADO.competencia || ""));
  ESTADO.painel = dados;

  if (dados.vazio) {
    tela().innerHTML = `<div class="cartao"><div class="vazio">
      <strong>Nenhum lançamento ainda</strong>
      Comece em <em>Importar arquivos</em>: jogue lá o CSV da fatura do Nubank
      ou o PDF da fatura do Santander.</div></div>`;
    return;
  }

  ESTADO.competencia = dados.competencia;
  ESTADO.competencias = dados.competencias;
  preencherSeletor();

  const r = dados.resumo;
  const receitas = Number(r.receitas || 0);
  const despesas = Number(r.despesas || 0);
  const resultado = Number(r.resultado || 0);

  const cartoes = dados.contas.filter((c) => c.tipo === "cartao");
  const alertas = (dados.conciliacao || []).filter(
    (c) => c.situacao === "importacao_incompleta" || c.situacao === "conferir_resumo");

  const categorias = (dados.categorias || [])
    .filter((c) => Number(c.total) !== 0)
    .map((c) => ({ rotulo: c.categoria || "(sem categoria)",
                   valor: Math.abs(Number(c.total)),
                   texto: moeda(Math.abs(Number(c.total))) }));

  const evolucao = (dados.evolucao || []).map((e) => ({
    rotulo: mesCurto(e.competencia),
    a: Math.abs(Number(e.receitas || 0)), aTexto: moeda(Number(e.receitas || 0)),
    b: Math.abs(Number(e.despesas || 0)), bTexto: moeda(Number(e.despesas || 0)),
  }));

  tela().innerHTML = `
    ${alertas.length ? `<div class="aviso aviso-alerta" style="margin-bottom:16px">
      <div><strong>${alertas.length} fatura(s) pedindo atenção.</strong>
      ${G.esc(alertas[0].conta)} em ${mesCurto(alertas[0].competencia)}:
      ${G.esc(alertas[0].explicacao)}
      <button class="botao botao-p" type="button" id="ir-conciliacao"
        style="margin-left:8px">Ver conciliação</button></div></div>` : ""}

    <div class="grade grade-kpi" style="margin-bottom:16px">
      <div class="cartao kpi">
        <div class="kpi-rotulo">Receitas</div>
        <div class="kpi-valor positivo">${moeda(receitas)}</div>
        <div class="kpi-nota">${mesLongo(dados.competencia)}</div>
      </div>
      <div class="cartao kpi">
        <div class="kpi-rotulo">Despesas</div>
        <div class="kpi-valor negativo">${moeda(despesas)}</div>
        <div class="kpi-nota">${r.lancamentos} lançamentos</div>
      </div>
      <div class="cartao kpi">
        <div class="kpi-rotulo">Resultado</div>
        <div class="kpi-valor ${resultado >= 0 ? "positivo" : "negativo"}">${moeda(resultado)}</div>
        <div class="kpi-nota">${resultado >= 0 ? "sobrou" : "faltou"} no mês</div>
      </div>
      <div class="cartao kpi">
        <div class="kpi-rotulo">Débito e PIX</div>
        <div class="kpi-valor">${moeda(r.debito_pix)}</div>
        <div class="kpi-nota">fora das faturas</div>
      </div>
    </div>

    <div class="grade grade-2" style="margin-bottom:16px">
      <div class="cartao">
        <div class="cartao-cabeca"><div>
          <h2>Receitas e despesas</h2>
          <p>Mês a mês, para comparar — não empilhado.</p>
        </div></div>
        <div class="cartao-corpo">
          ${G.barrasDuplas(evolucao)}
          ${G.legenda([{ rotulo: "Receitas", cor: "var(--receita)" },
                       { rotulo: "Despesas", cor: "var(--despesa)" }])}
        </div>
      </div>

      <div class="cartao">
        <div class="cartao-cabeca"><div>
          <h2>Gasto por cartão</h2>
          <p>É o que a fatura do mês representa.</p>
        </div></div>
        <div class="cartao-corpo">
          ${cartoes.length ? `<div style="display:flex;gap:24px;align-items:center;
            flex-wrap:wrap">
            ${G.rosquinha(cartoes.map((c) => ({
                rotulo: c.conta, valor: Math.abs(Number(c.total)),
                texto: moeda(Math.abs(Number(c.total))) })),
              { centro: moeda(cartoes.reduce((s, c) => s + Math.abs(Number(c.total)), 0)),
                centroNota: "nos cartões" })}
            <div style="flex:1;min-width:180px">
              ${G.legenda(cartoes.map((c) => ({ rotulo: c.conta })))}
              <table class="tabela" style="margin-top:8px">
                ${cartoes.map((c) => `<tr><td>${G.esc(c.conta)}</td>
                  ${celulaValor(c.total)}</tr>`).join("")}
              </table>
            </div></div>` : `<div class="vazio">Sem fatura neste mês</div>`}
        </div>
      </div>
    </div>

    <div class="grade grade-2">
      <div class="cartao">
        <div class="cartao-cabeca"><div>
          <h2>Despesas por categoria</h2>
          <p>${mesLongo(dados.competencia)}</p>
        </div></div>
        <div class="cartao-corpo">${G.barrasHorizontais(categorias)}</div>
      </div>

      <div class="cartao">
        <div class="cartao-cabeca"><div>
          <h2>Itens fixos</h2>
          <p>O que se repete todo mês.</p>
        </div></div>
        <div class="cartao-corpo sem-espaco">
          ${(dados.itens_fixos || []).length ? `<div class="tabela-caixa">
            <table class="tabela"><thead><tr><th>Item</th><th class="num">Valor</th>
            <th class="num">Lanç.</th></tr></thead><tbody>
            ${dados.itens_fixos.map((i) => `<tr><td>${G.esc(i.item_fixo)}</td>
              ${celulaValor(i.total)}<td class="num">${i.n}</td></tr>`).join("")}
            </tbody></table></div>`
            : `<div class="vazio">Nenhum item fixo identificado neste mês</div>`}
        </div>
      </div>
    </div>`;

  const botao = $("ir-conciliacao");
  if (botao) botao.addEventListener("click", () => irPara("conciliacao"));
}

/* ----------------------------------------------------------- lançamentos */

async function desenharLancamentos() {
  const lista = await api("/api/lancamentos?limite=1000&competencia=" +
    encodeURIComponent(ESTADO.competencia || ""));

  tela().innerHTML = `
    <div class="cartao">
      <div class="cartao-cabeca">
        <div><h2>${lista.length} lançamento(s)</h2>
          <p>${mesLongo(ESTADO.competencia)} · edite a categoria clicando nela</p></div>
        <input class="campo campo-auto" id="busca" placeholder="Buscar descrição…"
          style="min-width:220px">
      </div>
      <div class="cartao-corpo sem-espaco">
        <div class="tabela-caixa" style="max-height:68vh;overflow-y:auto">
          <table class="tabela"><thead><tr>
            <th>Data</th><th>Descrição</th><th>Conta</th><th>Categoria</th>
            <th>Item fixo</th><th>Tipo</th><th class="num">Valor</th>
          </tr></thead><tbody id="corpo-lancamentos"></tbody></table>
        </div>
      </div>
    </div>`;

  const desenhar = (itens) => {
    if (!itens.length) {
      $("corpo-lancamentos").innerHTML =
        `<tr><td colspan="7"><div class="vazio">Nada encontrado</div></td></tr>`;
      return;
    }
    $("corpo-lancamentos").innerHTML = itens.map((l) => `
      <tr>
        <td style="white-space:nowrap">${dataBR(l.data)}</td>
        <td class="truncar" title="${G.esc(l.descricao)}">${G.esc(l.descricao)}</td>
        <td><span class="selo selo-neutro">${G.esc(l.conta)}</span></td>
        <td>${G.esc(l.categoria || "—")}
          ${l.subcategoria ? `<br><span style="color:var(--texto-fraco);
            font-size:var(--t-p)">${G.esc(l.subcategoria)}</span>` : ""}</td>
        <td>${l.item_fixo ? `<span class="selo selo-marca">${G.esc(l.item_fixo)}</span>` : ""}</td>
        <td>${G.esc(l.tipo)}</td>
        ${celulaValor(l.valor)}
      </tr>`).join("");
  };

  desenhar(lista);

  /* Busca no que já está na mão: filtrar 1.000 linhas no navegador é
     instantâneo e não gasta ida ao servidor a cada tecla. */
  $("busca").addEventListener("input", (ev) => {
    const termo = ev.target.value.trim().toLowerCase();
    desenhar(termo ? lista.filter((l) =>
      (l.descricao || "").toLowerCase().includes(termo) ||
      (l.categoria || "").toLowerCase().includes(termo)) : lista);
  });
}

/* ----------------------------------------------------------- conciliação */

const SITUACOES = {
  ok: { selo: "selo-ok", texto: "confere" },
  importacao_incompleta: { selo: "selo-erro", texto: "importação incompleta" },
  justificada: { selo: "selo-neutro", texto: "justificada" },
  conferir_resumo: { selo: "selo-alerta", texto: "conferir resumo" },
  sem_resumo: { selo: "selo-neutro", texto: "sem resumo" },
  sem_lancamentos: { selo: "selo-neutro", texto: "sem lançamentos" },
};

async function desenharConciliacao() {
  const linhas = await api("/api/conciliacao");

  const porCartao = {};
  linhas.forEach((l) => {
    porCartao[l.conta] = porCartao[l.conta] || { rotulos: [], gasto: [], total: [] };
    porCartao[l.conta].rotulos.push(mesCurto(l.competencia));
    porCartao[l.conta].gasto.push(l.gasto_do_mes || null);
    porCartao[l.conta].total.push(l.total_informado || null);
  });

  const graficos = Object.keys(porCartao).map((conta) => {
    const d = porCartao[conta];
    return `<div class="cartao"><div class="cartao-cabeca"><div>
        <h2>${G.esc(conta)}</h2>
        <p>Quando as linhas se separam, a diferença é dívida rolando.</p></div></div>
      <div class="cartao-corpo">
        ${G.linhas([
          { nome: "Gasto do mês", cor: "var(--marca)", valores: d.gasto,
            textos: d.gasto.map(moeda) },
          { nome: "Total no app", cor: "var(--despesa)", valores: d.total,
            textos: d.total.map(moeda) }], d.rotulos)}
        ${G.legenda([{ rotulo: "Gasto do mês", cor: "var(--marca)" },
                     { rotulo: "Total a pagar no app", cor: "var(--despesa)" }])}
      </div></div>`;
  }).join("");

  tela().innerHTML = `
    <div class="aviso aviso-info" style="margin-bottom:16px"><div>
      O sistema mede <strong>gasto do mês</strong>; o app do banco mostra
      <strong>valor a pagar</strong>, que inclui o saldo que não foi pago e desconta
      os pagamentos. Os dois só coincidem quando a fatura anterior foi paga
      integralmente. A coluna <em>Δ importação</em> é a que acusa erro de verdade:
      diferente de zero significa lançamento faltando. Uma diferença examinada e
      explicada (ex.: estorno mantido em outro mês) pode ser registrada como
      <strong>justificada</strong> — sai do alarme, mas volta se o valor mudar.
    </div></div>

    <div class="grade grade-2" style="margin-bottom:16px">${graficos}</div>

    <div class="cartao"><div class="cartao-cabeca"><div>
        <h2>Mês a mês</h2><p>Passe o olho na coluna Situação.</p></div></div>
      <div class="cartao-corpo sem-espaco"><div class="tabela-caixa">
        <table class="tabela"><thead><tr>
          <th>Mês</th><th>Cartão</th><th class="num">Gasto do mês</th>
          <th class="num">Fatura: desp.+enc.</th><th class="num">Δ importação</th>
          <th class="num">Saldo anterior</th><th class="num">Pagamentos</th>
          <th class="num">Total calculado</th><th class="num">Total no app</th>
          <th>Situação</th>
        </tr></thead><tbody>
        ${linhas.map((l, i) => {
          const s = SITUACOES[l.situacao] || SITUACOES.sem_resumo;
          const delta = l.delta_importacao;
          const acao = l.situacao === "importacao_incompleta"
            ? `<button class="botao botao-p" type="button" data-justificar="${i}"
                 style="margin-left:6px">Justificar</button>`
            : l.situacao === "justificada"
              ? `<button class="botao botao-p botao-fantasma" type="button"
                   data-desjustificar="${i}" style="margin-left:6px">Remover</button>`
              : "";
          return `<tr>
            <td style="white-space:nowrap">${mesCurto(l.competencia)}</td>
            <td>${G.esc(l.conta)}</td>
            <td class="num">${moeda(l.gasto_do_mes)}</td>
            <td class="num">${l.despesas_encargos == null ? "—" : moeda(l.despesas_encargos)}</td>
            <td class="num ${delta && Math.abs(delta) > 0.05 && l.situacao !== "justificada" ? "negativo" : ""}">
              ${delta == null ? "—" : moeda(delta)}</td>
            <td class="num">${l.saldo_anterior == null ? "—" : moeda(l.saldo_anterior)}</td>
            <td class="num">${l.pagamentos == null ? "—" : moeda(l.pagamentos)}</td>
            <td class="num">${l.total_calculado == null ? "—" : moeda(l.total_calculado)}</td>
            <td class="num">${l.total_informado ? moeda(l.total_informado) : "—"}</td>
            <td style="white-space:nowrap"><span class="selo ${s.selo}"
              title="${G.esc(l.explicacao)}">${s.texto}</span>${acao}</td>
          </tr>`;
        }).join("")}
        </tbody></table></div></div></div>`;

  /* Justificar exige o motivo — é ele que aparece na Situação e no espelho.
     O valor aceito quem grava é o servidor, lendo o Δ atual do banco. */
  document.querySelectorAll("[data-justificar]").forEach((b) => {
    b.addEventListener("click", async () => {
      const l = linhas[Number(b.dataset.justificar)];
      const motivo = window.prompt(
        "Motivo da justificativa (fica registrado na conciliação e no espelho):");
      if (!motivo || !motivo.trim()) return;
      try {
        await api("/api/conciliacao/justificar", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ conta: l.conta, competencia: l.competencia,
                                 motivo: motivo.trim() }),
        });
        avisar("Diferença registrada como justificada.", "ok");
        desenharConciliacao();
      } catch (erro) { avisar(erro.message, "erro"); }
    });
  });
  document.querySelectorAll("[data-desjustificar]").forEach((b) => {
    b.addEventListener("click", async () => {
      const l = linhas[Number(b.dataset.desjustificar)];
      if (!window.confirm("Remover a justificativa? O alarme desse mês volta.")) return;
      try {
        await api("/api/conciliacao/justificar?conta=" + encodeURIComponent(l.conta) +
                  "&competencia=" + encodeURIComponent(l.competencia),
                  { method: "DELETE" });
        avisar("Justificativa removida.", "ok");
        desenharConciliacao();
      } catch (erro) { avisar(erro.message, "erro"); }
    });
  });
}

/* ------------------------------------------------------------- importar */

async function desenharImportar() {
  const historico = await api("/api/importacoes?limite=40");

  tela().innerHTML = `
    <div class="cartao" style="margin-bottom:16px">
      <div class="cartao-corpo">
        <div class="solta" id="solta">
          <input type="file" id="arquivos" multiple
            accept=".csv,.xlsx,.xlsm,.ofx,.qfx,.pdf,.txt,.png,.jpg,.jpeg,.webp">
          <h3>Arraste os arquivos aqui</h3>
          <p>ou clique para escolher · CSV, XLSX, OFX, PDF (inclusive a fatura do
             Santander com senha) e <strong>print de tela do app</strong> (png/jpg)
             para extrato parcial</p>
        </div>
        <ul class="lista-arquivos" id="escolhidos"></ul>
        <div style="display:flex;gap:8px;margin-top:16px;align-items:center">
          <button class="botao botao-primario" type="button" id="enviar" disabled>
            Importar</button>
          <button class="botao botao-fantasma" type="button" id="limpar">Limpar</button>
          <span style="color:var(--texto-fraco);font-size:var(--t-p)">
            Reimportar o mesmo arquivo é inofensivo: linha repetida é reconhecida
            e ignorada.</span>
        </div>
      </div>
    </div>

    <div id="resultado-importacao"></div>

    <div class="cartao"><div class="cartao-cabeca"><div>
        <h2>Importações anteriores</h2>
        <p>"Suspeitos" entraram — são iguais a outra linha do mês, em outro dia.</p>
      </div></div>
      <div class="cartao-corpo sem-espaco"><div class="tabela-caixa">
        <table class="tabela"><thead><tr>
          <th>Quando</th><th>Arquivo</th><th>Formato</th><th class="num">Lidos</th>
          <th class="num">Inseridos</th><th class="num">Duplicados</th>
          <th class="num">Suspeitos</th><th>Status</th><th>Observação</th>
        </tr></thead><tbody>
        ${historico.length ? historico.map((h) => `<tr>
          <td style="white-space:nowrap">${dataBR(h.quando)}
            ${String(h.quando || "").slice(11, 16)}</td>
          <td class="truncar" title="${G.esc(h.arquivo)}">${G.esc(h.arquivo)}</td>
          <td>${G.esc(h.formato || "—")}</td>
          <td class="num">${h.lidos}</td><td class="num">${h.inseridos}</td>
          <td class="num">${h.duplicados}</td><td class="num">${h.suspeitos}</td>
          <td><span class="selo ${h.status === "OK" ? "selo-ok" : "selo-erro"}">
            ${G.esc(h.status)}</span></td>
          <td class="truncar" title="${G.esc(h.observacao)}">${G.esc(h.observacao || "")}</td>
        </tr>`).join("")
        : `<tr><td colspan="9"><div class="vazio">Nenhuma importação ainda</div></td></tr>`}
        </tbody></table></div></div></div>`;

  const entrada = $("arquivos");
  const solta = $("solta");
  let escolhidos = [];

  const listar = () => {
    $("escolhidos").innerHTML = escolhidos.map((a, i) => `
      <li><span class="nome">${G.esc(a.name)}</span>
        <span style="color:var(--texto-fraco);font-size:var(--t-p)">
          ${(a.size / 1024).toFixed(0)} KB</span>
        <button class="botao botao-fantasma botao-p" type="button"
          data-remover="${i}">remover</button></li>`).join("");
    $("enviar").disabled = escolhidos.length === 0;
    $("escolhidos").querySelectorAll("[data-remover]").forEach((b) => {
      b.addEventListener("click", () => {
        escolhidos.splice(Number(b.dataset.remover), 1);
        listar();
      });
    });
  };

  const adicionar = (arquivos) => {
    escolhidos = escolhidos.concat(Array.from(arquivos));
    listar();
  };

  solta.addEventListener("click", () => entrada.click());
  entrada.addEventListener("change", () => adicionar(entrada.files));
  ["dragenter", "dragover"].forEach((evt) =>
    solta.addEventListener(evt, (ev) => {
      ev.preventDefault();
      solta.classList.add("ativa");
    }));
  ["dragleave", "drop"].forEach((evt) =>
    solta.addEventListener(evt, (ev) => {
      ev.preventDefault();
      solta.classList.remove("ativa");
    }));
  solta.addEventListener("drop", (ev) => adicionar(ev.dataTransfer.files));
  $("limpar").addEventListener("click", () => { escolhidos = []; listar(); });

  $("enviar").addEventListener("click", async () => {
    const botao = $("enviar");
    botao.disabled = true;
    botao.textContent = "Importando…";
    try {
      const corpo = new FormData();
      escolhidos.forEach((a) => corpo.append("arquivos", a));
      const r = await api("/api/importar", { method: "POST", body: corpo });
      mostrarResultado(r);
      escolhidos = [];
      listar();
      /* O mês pode ter mudado de cara: recarrega a lista de competências. */
      const painel = await api("/api/painel");
      ESTADO.competencias = painel.competencias || [];
      preencherSeletor();
    } catch (erro) {
      avisar(erro.message, "erro");
    } finally {
      botao.disabled = escolhidos.length === 0;
      botao.textContent = "Importar";
    }
  });
}

function mostrarResultado(r) {
  const t = r.total;
  const tipo = t.erros ? "alerta" : "ok";
  $("resultado-importacao").innerHTML = `
    <div class="cartao" style="margin-bottom:16px">
      <div class="cartao-cabeca"><div><h2>Resultado</h2>
        <p>${t.inseridos} inserido(s) · ${t.duplicados} duplicado(s) ignorado(s) ·
           ${t.resumos} resumo(s) de fatura · ${t.erros} com erro</p></div></div>
      <div class="cartao-corpo">
        <div class="aviso aviso-${tipo}" style="margin-bottom:12px"><div>
          ${t.erros ? "Alguns arquivos não entraram — veja abaixo."
                    : "Importação concluída."}</div></div>
        <div class="tabela-caixa"><table class="tabela"><thead><tr>
          <th>Arquivo</th><th>Formato</th><th class="num">Lidos</th>
          <th class="num">Inseridos</th><th class="num">Duplicados</th>
          <th class="num">Suspeitos</th><th>Situação</th>
        </tr></thead><tbody>
        ${r.arquivos.map((a) => `<tr>
          <td class="truncar" title="${G.esc(a.arquivo)}">${G.esc(a.arquivo)}</td>
          <td>${G.esc(a.formato || "—")}</td>
          <td class="num">${a.lidos}</td><td class="num">${a.inseridos}</td>
          <td class="num">${a.duplicados}</td><td class="num">${a.suspeitos}</td>
          <td>${a.status === "OK"
            ? `<span class="selo selo-ok">OK</span>
               ${(a.avisos || []).length ? `<br><span style="color:var(--texto-fraco);
                 font-size:var(--t-p)">${G.esc(a.avisos.join(" "))}</span>` : ""}`
            : `<span class="selo selo-erro">erro</span><br>
               <span style="color:var(--texto-fraco);font-size:var(--t-p)">
                 ${G.esc(a.erro)}</span>`}</td>
        </tr>`).join("")}
        </tbody></table></div></div></div>`;
}

/* -------------------------------------------------------------- faturas */

async function desenharFaturas() {
  const [resumos, contas] = await Promise.all([
    api("/api/resumos"), api("/api/contas")]);
  const cartoes = contas.filter((c) => c.tipo === "cartao");

  tela().innerHTML = `
    <div class="cartao" style="margin-bottom:16px">
      <div class="cartao-cabeca"><div><h2>Informar um resumo</h2>
        <p>O Nubank não exporta esse quadro em arquivo nenhum — para ele, digite
           daqui. O Santander vem preenchido pelo PDF da fatura.</p></div></div>
      <div class="cartao-corpo">
        <form id="form-resumo" class="grade"
              style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
          <div><label class="rotulo" for="r-conta">Cartão</label>
            <select class="campo" id="r-conta" required>
              ${cartoes.map((c) => `<option value="${c.id}">${G.esc(c.nome)}</option>`).join("")}
            </select></div>
          <div><label class="rotulo" for="r-comp">Competência</label>
            <input class="campo" id="r-comp" type="month" required></div>
          <div><label class="rotulo" for="r-saldo">Saldo anterior</label>
            <input class="campo" id="r-saldo" type="number" step="0.01" value="0"></div>
          <div><label class="rotulo" for="r-desp">Despesas</label>
            <input class="campo" id="r-desp" type="number" step="0.01" value="0"></div>
          <div><label class="rotulo" for="r-enc">Encargos</label>
            <input class="campo" id="r-enc" type="number" step="0.01" value="0"></div>
          <div><label class="rotulo" for="r-cred">Créditos</label>
            <input class="campo" id="r-cred" type="number" step="0.01" value="0"></div>
          <div><label class="rotulo" for="r-pag">Pagamentos</label>
            <input class="campo" id="r-pag" type="number" step="0.01" value="0"></div>
          <div><label class="rotulo" for="r-total">Total no app</label>
            <input class="campo" id="r-total" type="number" step="0.01" value="0"></div>
          <div style="display:flex;align-items:flex-end">
            <button class="botao botao-primario" type="submit">Salvar</button></div>
        </form>
      </div>
    </div>

    <div class="cartao"><div class="cartao-cabeca"><div><h2>Resumos gravados</h2>
      <p>Valores positivos, como aparecem na fatura.</p></div></div>
      <div class="cartao-corpo sem-espaco"><div class="tabela-caixa">
        <table class="tabela"><thead><tr>
          <th>Mês</th><th>Cartão</th><th class="num">Saldo anterior</th>
          <th class="num">Despesas</th><th class="num">Encargos</th>
          <th class="num">Créditos</th><th class="num">Pagamentos</th>
          <th class="num">Total no app</th><th>Origem</th>
        </tr></thead><tbody>
        ${resumos.length ? resumos.map((r) => `<tr>
          <td>${mesCurto(r.competencia)}</td><td>${G.esc(r.conta)}</td>
          <td class="num">${moeda(r.saldo_anterior)}</td>
          <td class="num">${moeda(r.despesas)}</td>
          <td class="num">${moeda(r.encargos)}</td>
          <td class="num">${moeda(r.creditos)}</td>
          <td class="num">${moeda(r.pagamentos)}</td>
          <td class="num">${moeda(r.total_informado)}</td>
          <td class="truncar">${G.esc(r.arquivo || "")}</td>
        </tr>`).join("")
        : `<tr><td colspan="9"><div class="vazio">Nenhum resumo ainda</div></td></tr>`}
        </tbody></table></div></div></div>`;

  $("form-resumo").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const corpo = new FormData();
    corpo.append("conta_id", $("r-conta").value);
    corpo.append("competencia", $("r-comp").value);
    corpo.append("saldo_anterior", $("r-saldo").value || 0);
    corpo.append("despesas", $("r-desp").value || 0);
    corpo.append("encargos", $("r-enc").value || 0);
    corpo.append("creditos", $("r-cred").value || 0);
    corpo.append("pagamentos", $("r-pag").value || 0);
    corpo.append("total_informado", $("r-total").value || 0);
    try {
      await api("/api/resumo", { method: "POST", body: corpo });
      avisar("Resumo salvo.", "ok");
      desenharFaturas();
    } catch (erro) {
      avisar(erro.message, "erro");
    }
  });
}

/* --------------------------------------------------------------- regras */

async function desenharRegras() {
  const regras = await api("/api/regras");

  tela().innerHTML = `
    <div class="aviso aviso-info" style="margin-bottom:16px"><div>
      A <strong>primeira</strong> regra que casa vence — por isso a ordem importa, e as
      de transferência precisam ficar no topo: se um pagamento de fatura cair numa
      regra de despesa, o mês conta o gasto duas vezes. O padrão é uma expressão
      regular aplicada à descrição <strong>sem acento e em maiúsculas</strong>.
    </div></div>

    <div class="cartao"><div class="cartao-cabeca">
      <div><h2>${regras.length} regra(s)</h2>
        <p>Mudança vale da próxima importação em diante.</p></div>
      <button class="botao botao-primario botao-p" type="button" id="nova-regra">
        Nova regra</button></div>
      <div class="cartao-corpo sem-espaco"><div class="tabela-caixa">
        <table class="tabela"><thead><tr>
          <th class="num">#</th><th>Padrão</th><th>Categoria</th><th>Subcategoria</th>
          <th>Item fixo</th><th>Tipo</th><th>Ativa</th><th></th>
        </tr></thead><tbody id="corpo-regras">
        ${regras.map((r) => `<tr data-id="${r.id}">
          <td class="num">${r.ordem}</td>
          <td class="truncar" title="${G.esc(r.padrao)}">
            <code style="font-family:var(--fonte-num);font-size:var(--t-p)">
              ${G.esc(G.corta(r.padrao, 58))}</code>
            ${r.regex_valida ? "" : `<span class="selo selo-erro"
              title="Regex inválida: esta regra é ignorada na importação">inválida</span>`}</td>
          <td>${G.esc(r.categoria || "")}</td>
          <td>${G.esc(r.subcategoria || "")}</td>
          <td>${r.item_fixo ? `<span class="selo selo-marca">${G.esc(r.item_fixo)}</span>` : ""}</td>
          <td>${G.esc(r.tipo || "")}</td>
          <td><span class="selo ${r.ativa ? "selo-ok" : "selo-neutro"}">
            ${r.ativa ? "sim" : "não"}</span></td>
          <td><button class="botao botao-fantasma botao-p" type="button"
            data-alternar="${r.id}">${r.ativa ? "desativar" : "ativar"}</button></td>
        </tr>`).join("")}
        </tbody></table></div></div></div>`;

  document.querySelectorAll("[data-alternar]").forEach((b) => {
    b.addEventListener("click", async () => {
      const id = Number(b.dataset.alternar);
      const regra = regras.find((r) => r.id === id);
      try {
        await api("/api/regras", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(Object.assign({}, regra, { ativa: !regra.ativa })),
        });
        desenharRegras();
      } catch (erro) {
        avisar(erro.message, "erro");
      }
    });
  });

  $("nova-regra").addEventListener("click", () => {
    avisar("Para criar regra nova, use a tela de Regras do próximo lote — " +
           "por ora dá para ativar e desativar as existentes.", "info");
  });
}

/* -------------------------------------------------------------- ajustes */

async function desenharAjustes() {
  const [diag, esp] = await Promise.all([api("/api/diagnostico"), api("/api/espelho")]);

  const linha = (rotulo, ok, mensagem) => `
    <tr><td>${G.esc(rotulo)}</td>
      <td><span class="selo ${ok ? "selo-ok" : "selo-erro"}">
        ${ok ? "ok" : "atenção"}</span></td>
      <td>${G.esc(mensagem)}</td></tr>`;

  tela().innerHTML = `
    <div class="grade grade-2">
      <div class="cartao"><div class="cartao-cabeca"><div><h2>Diagnóstico</h2>
        <p>O que está configurado neste servidor.</p></div></div>
        <div class="cartao-corpo sem-espaco"><div class="tabela-caixa">
          <table class="tabela"><tbody>
            ${linha("Banco de dados (Neon)", diag.banco.ok, diag.banco.mensagem)}
            ${linha("Espelho na planilha", diag.espelho.ok, diag.espelho.mensagem)}
            ${linha("Senha do PDF do Santander", diag.senha_pdf_configurada,
              diag.senha_pdf_configurada
                ? "Configurada — a fatura em PDF é lida direto."
                : "Falta SENHA_PDF_SANTANDER: a fatura em PDF do Santander não abre.")}
            <tr><td>Meses com lançamento</td><td></td>
              <td>${diag.lancamentos}</td></tr>
          </tbody></table></div></div></div>

      <div class="cartao"><div class="cartao-cabeca"><div><h2>Espelho</h2>
        <p>Só de saída: a planilha nunca alimenta o sistema de volta.</p></div></div>
        <div class="cartao-corpo">
          ${esp.ativo ? `
            <p style="font-size:var(--t-m);color:var(--texto-medio)">
              Planilha <code style="font-family:var(--fonte-num)">${G.esc(esp.planilha_id)}</code>.
              Ela precisa estar compartilhada como <strong>editor</strong> com
              <code style="font-family:var(--fonte-num)">${G.esc(esp.conta_de_servico)}</code>.
            </p>
            <div class="aviso aviso-${esp.ok ? "ok" : "erro"}" style="margin:12px 0">
              <div>${G.esc(esp.mensagem)}</div></div>
            <button class="botao botao-primario" type="button" id="sincronizar">
              Reescrever a planilha agora</button>`
          : `<div class="aviso aviso-alerta"><div>
              Espelho desligado. Configure <code>GCP_SERVICE_ACCOUNT_JSON</code> e
              <code>PLANILHA_ESPELHO_ID</code> no ambiente do servidor. O sistema
              funciona inteiro sem isso — só não escreve na planilha.
            </div></div>`}
        </div></div>
    </div>`;

  const botao = $("sincronizar");
  if (botao) botao.addEventListener("click", () => sincronizarEspelho(botao));
}

async function sincronizarEspelho(botao) {
  const original = botao ? botao.textContent : "";
  if (botao) { botao.disabled = true; botao.textContent = "Escrevendo…"; }
  try {
    const r = await api("/api/espelho/sincronizar", { method: "POST" });
    const abas = Object.keys(r.abas).map((k) => `${k}: ${r.abas[k]}`).join(" · ");
    avisar("Planilha atualizada — " + abas, "ok");
  } catch (erro) {
    avisar(erro.message, "erro");
  } finally {
    if (botao) { botao.disabled = false; botao.textContent = original; }
  }
}

/* ------------------------------------------------------------- seletor */

function preencherSeletor() {
  const seletor = $("seletor-mes");
  seletor.innerHTML = ESTADO.competencias.map((c) =>
    `<option value="${String(c).slice(0, 7)}"
      ${String(c).slice(0, 7) === String(ESTADO.competencia).slice(0, 7) ? "selected" : ""}>
      ${mesLongo(c)}</option>`).join("");
}

/* --------------------------------------------------------------- início */

async function iniciar() {
  document.querySelectorAll("#nav button").forEach((b) =>
    b.addEventListener("click", () => irPara(b.dataset.tela)));
  $("botao-tema").addEventListener("click", alternarTema);
  $("botao-espelhar").addEventListener("click", (ev) => sincronizarEspelho(ev.currentTarget));
  $("botao-sair").addEventListener("click", async () => {
    await fetch("/api/sair", { method: "POST" });
    window.location.href = "/login";
  });
  $("seletor-mes").addEventListener("change", (ev) => {
    ESTADO.competencia = ev.target.value + "-01";
    if (ESTADO.tela === "painel") desenharPainel();
    else if (ESTADO.tela === "lancamentos") desenharLancamentos();
  });

  try {
    const sessao = await api("/api/sessao");
    $("nome-usuario").textContent = sessao.nome || sessao.email;
    $("versao").textContent = "versão " + sessao.versao;
    $("botao-espelhar").classList.toggle("oculto", !sessao.espelho_ativo);
    ESTADO.contas = await api("/api/contas");
  } catch (erro) {
    return;   /* api() já redirecionou para /login se a sessão caiu */
  }

  irPara("painel");
}

iniciar();
