/* Aplica o tema salvo ANTES da primeira pintura, para a tela não piscar escura
   ao abrir no claro.

   Isto é um arquivo, e não um <script> no HTML, porque a CSP do servidor manda
   script-src 'self' — sem 'unsafe-inline'. Um bloco inline aqui seria
   silenciosamente bloqueado e o tema só apareceria depois. Precisa ser
   carregado de forma síncrona no <head>. */
(function () {
  try {
    if (localStorage.getItem("financas-tema") === "claro") {
      document.documentElement.setAttribute("data-tema", "claro");
    }
  } catch (e) {
    /* armazenamento bloqueado (navegação privada): segue no escuro */
  }
})();

function alternarTema() {
  var raiz = document.documentElement;
  var claro = raiz.getAttribute("data-tema") === "claro";
  if (claro) {
    raiz.removeAttribute("data-tema");
  } else {
    raiz.setAttribute("data-tema", "claro");
  }
  try {
    localStorage.setItem("financas-tema", claro ? "escuro" : "claro");
  } catch (e) { /* idem */ }
}
