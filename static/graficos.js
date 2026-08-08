/* ==========================================================================
   Gráficos em SVG, escritos à mão.

   Sem biblioteca: a CSP é default-src 'self', então nada de CDN, e vendorizar
   um Chart.js inteiro para desenhar quatro gráficos custa mais do que estes
   ~200 linhas. As cores saem dos tokens do tema, então trocar de tema troca os
   gráficos junto.

   Todos recebem (dados) e devolvem uma string de SVG.
   ========================================================================== */

const G = (() => {

  const PALETA = ["--c1","--c2","--c3","--c4","--c5","--c6","--c7","--c8","--c9","--c10"];
  const cor = (i) => "var(" + PALETA[i % PALETA.length] + ")";

  function esc(texto) {
    return String(texto == null ? "" : texto)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* Escala "bonita": o topo do eixo cai num número redondo, senão o rótulo
     fica 18.437 e ninguém lê gráfico assim. */
  function topoRedondo(maximo) {
    if (maximo <= 0) return 1;
    const magnitude = Math.pow(10, Math.floor(Math.log10(maximo)));
    const passos = [1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10];
    for (const p of passos) {
      if (magnitude * p >= maximo) return magnitude * p;
    }
    return magnitude * 10;
  }

  const compacto = (valor) => {
    const v = Math.abs(valor);
    if (v >= 1000000) return (valor / 1000000).toFixed(1).replace(".", ",") + "M";
    if (v >= 1000) return Math.round(valor / 1000) + "k";
    return String(Math.round(valor));
  };

  /* ---------------------------------------------------- barras agrupadas */
  /* Receitas x Despesas por mês. Duas séries lado a lado, não empilhadas:
     empilhar somaria coisas que a gente quer comparar. */
  function barrasDuplas(itens, opcoes) {
    opcoes = opcoes || {};
    const L = 640, A = 260;
    const mE = 46, mD = 8, mT = 12, mB = 32;
    const larguraUtil = L - mE - mD, alturaUtil = A - mT - mB;
    if (!itens.length) return vazio("Sem dados no período");

    const maximo = topoRedondo(Math.max(
      ...itens.map(d => Math.max(Math.abs(d.a), Math.abs(d.b))), 1));
    const passoX = larguraUtil / itens.length;
    const largBarra = Math.max(4, Math.min(16, passoX / 2.8));
    const y = (v) => mT + alturaUtil - (Math.abs(v) / maximo) * alturaUtil;

    let svg = `<svg class="grafico" viewBox="0 0 ${L} ${A}" role="img"
      aria-label="${esc(opcoes.titulo || "Receitas e despesas por mês")}">`;

    for (let i = 0; i <= 4; i++) {
      const valor = (maximo / 4) * i;
      const py = mT + alturaUtil - (alturaUtil / 4) * i;
      svg += `<line class="eixo" x1="${mE}" y1="${py}" x2="${L - mD}" y2="${py}"/>`;
      svg += `<text x="${mE - 6}" y="${py + 3}" text-anchor="end">${compacto(valor)}</text>`;
    }

    itens.forEach((d, i) => {
      const base = mE + passoX * i + passoX / 2;
      const xa = base - largBarra - 1, xb = base + 1;
      svg += `<rect x="${xa}" y="${y(d.a)}" width="${largBarra}"
        height="${Math.max(1, mT + alturaUtil - y(d.a))}" rx="2"
        fill="var(--receita)"><title>${esc(d.rotulo)} · receitas ${esc(d.aTexto)}</title></rect>`;
      svg += `<rect x="${xb}" y="${y(d.b)}" width="${largBarra}"
        height="${Math.max(1, mT + alturaUtil - y(d.b))}" rx="2"
        fill="var(--despesa)"><title>${esc(d.rotulo)} · despesas ${esc(d.bTexto)}</title></rect>`;
      /* Com muitos meses, rotular todos vira borrão: mostra 1 em cada 2. */
      if (itens.length <= 14 || i % 2 === 0) {
        svg += `<text x="${base}" y="${A - 10}" text-anchor="middle">${esc(d.rotulo)}</text>`;
      }
    });

    return svg + "</svg>";
  }

  /* -------------------------------------------------------------- linha */
  /* Duas séries: gasto do mês e total a pagar. É o gráfico que mostra a
     dívida rolando — quando as linhas se separam, é saldo anterior. */
  function linhas(series, rotulos, opcoes) {
    opcoes = opcoes || {};
    const L = 640, A = 250;
    const mE = 46, mD = 10, mT = 14, mB = 30;
    const larguraUtil = L - mE - mD, alturaUtil = A - mT - mB;
    if (!rotulos.length) return vazio("Sem dados");

    const todos = series.flatMap(s => s.valores.filter(v => v != null).map(Math.abs));
    const maximo = topoRedondo(Math.max(...(todos.length ? todos : [1])));
    const px = (i) => mE + (rotulos.length === 1 ? larguraUtil / 2
      : (larguraUtil / (rotulos.length - 1)) * i);
    const py = (v) => mT + alturaUtil - (Math.abs(v) / maximo) * alturaUtil;

    let svg = `<svg class="grafico" viewBox="0 0 ${L} ${A}" role="img"
      aria-label="${esc(opcoes.titulo || "Evolução")}">`;

    for (let i = 0; i <= 4; i++) {
      const valor = (maximo / 4) * i;
      const y = mT + alturaUtil - (alturaUtil / 4) * i;
      svg += `<line class="eixo" x1="${mE}" y1="${y}" x2="${L - mD}" y2="${y}"/>`;
      svg += `<text x="${mE - 6}" y="${y + 3}" text-anchor="end">${compacto(valor)}</text>`;
    }

    series.forEach((s) => {
      /* Ponto faltando quebra a linha em vez de virar zero: fingir zero num
         mês sem dado desenharia um despencamento que nunca existiu. */
      let caminho = "", abrindo = true;
      s.valores.forEach((v, i) => {
        if (v == null) { abrindo = true; return; }
        caminho += (abrindo ? "M" : "L") + px(i) + " " + py(v) + " ";
        abrindo = false;
      });
      svg += `<path d="${caminho.trim()}" fill="none" stroke="${s.cor}"
        stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
      s.valores.forEach((v, i) => {
        if (v == null) return;
        svg += `<circle cx="${px(i)}" cy="${py(v)}" r="3" fill="${s.cor}">
          <title>${esc(rotulos[i])} · ${esc(s.nome)} ${esc(s.textos ? s.textos[i] : v)}</title>
        </circle>`;
      });
    });

    rotulos.forEach((r, i) => {
      if (rotulos.length <= 14 || i % 2 === 0) {
        svg += `<text x="${px(i)}" y="${A - 10}" text-anchor="middle">${esc(r)}</text>`;
      }
    });

    return svg + "</svg>";
  }

  /* ------------------------------------------------- barras horizontais */
  /* Categorias. Horizontal porque os nomes são longos ("Compras &
     Vestuário") e girar texto para caber é pior do que virar o gráfico. */
  function barrasHorizontais(itens) {
    if (!itens.length) return vazio("Sem despesas no mês");
    const L = 640, alturaLinha = 26, mT = 8;
    const A = mT + itens.length * alturaLinha + 8;
    const rotuloL = 168, valorL = 92;
    const util = L - rotuloL - valorL - 12;
    const maximo = Math.max(...itens.map(i => Math.abs(i.valor)), 1);

    let svg = `<svg class="grafico" viewBox="0 0 ${L} ${A}" role="img"
      aria-label="Despesas por categoria">`;
    itens.forEach((item, i) => {
      const y = mT + i * alturaLinha;
      const largura = Math.max(2, (Math.abs(item.valor) / maximo) * util);
      svg += `<text x="0" y="${y + 15}" fill="var(--texto-medio)"
        font-size="12">${esc(corta(item.rotulo, 26))}</text>`;
      svg += `<rect x="${rotuloL}" y="${y + 5}" width="${largura}" height="13" rx="3"
        fill="${cor(i)}"><title>${esc(item.rotulo)} · ${esc(item.texto)}</title></rect>`;
      svg += `<text class="rotulo-valor" x="${L}" y="${y + 15}"
        text-anchor="end">${esc(item.texto)}</text>`;
    });
    return svg + "</svg>";
  }

  /* ---------------------------------------------------------- rosquinha */
  function rosquinha(itens, opcoes) {
    opcoes = opcoes || {};
    const total = itens.reduce((s, i) => s + Math.abs(i.valor), 0);
    if (!total) return vazio("Sem dados");
    const T = 200, r = 78, espessura = 22, centro = T / 2;

    let angulo = -Math.PI / 2;
    let svg = `<svg class="grafico" viewBox="0 0 ${T} ${T}"
      style="max-width:200px" role="img"
      aria-label="${esc(opcoes.titulo || "Distribuição")}">`;
    itens.forEach((item, i) => {
      const fatia = (Math.abs(item.valor) / total) * Math.PI * 2;
      const fim = angulo + fatia;
      const x1 = centro + r * Math.cos(angulo), y1 = centro + r * Math.sin(angulo);
      const x2 = centro + r * Math.cos(fim), y2 = centro + r * Math.sin(fim);
      const maior = fatia > Math.PI ? 1 : 0;
      svg += `<path d="M ${x1} ${y1} A ${r} ${r} 0 ${maior} 1 ${x2} ${y2}"
        fill="none" stroke="${cor(i)}" stroke-width="${espessura}">
        <title>${esc(item.rotulo)} · ${esc(item.texto)}</title></path>`;
      angulo = fim;
    });
    if (opcoes.centro) {
      svg += `<text x="${centro}" y="${centro - 2}" text-anchor="middle"
        fill="var(--texto)" font-size="15" font-weight="650">${esc(opcoes.centro)}</text>`;
      svg += `<text x="${centro}" y="${centro + 14}" text-anchor="middle"
        font-size="10">${esc(opcoes.centroNota || "")}</text>`;
    }
    return svg + "</svg>";
  }

  function legenda(itens) {
    return '<div class="legenda">' + itens.map((item, i) =>
      `<span><i style="background:${item.cor || cor(i)}"></i>${esc(item.rotulo)}</span>`
    ).join("") + "</div>";
  }

  function vazio(texto) {
    return `<div class="vazio" style="padding:32px 16px">${esc(texto)}</div>`;
  }

  function corta(texto, limite) {
    const t = String(texto || "");
    return t.length > limite ? t.slice(0, limite - 1) + "…" : t;
  }

  return { barrasDuplas, linhas, barrasHorizontais, rosquinha, legenda, cor, esc, corta };
})();
