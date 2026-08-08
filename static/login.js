/* Tela de entrada.
   Nada de handler inline (onclick=) no HTML: a CSP do servidor manda
   script-src 'self', e o navegador bloquearia. Tudo é addEventListener. */

const el = (id) => document.getElementById(id);

function mostrarErro(caixa, mensagem) {
  caixa.textContent = mensagem;
  caixa.classList.remove("oculto");
}

function esconder(caixa) {
  caixa.classList.add("oculto");
}

/* Guarda o e-mail digitado na entrada para reusar no primeiro acesso — pedir de
   novo a mesma informação é atrito sem motivo. */
let emailPendente = "";

async function entrar(evento) {
  evento.preventDefault();
  const botao = el("botao-entrar");
  const erro = el("erro-entrar");
  esconder(erro);
  botao.disabled = true;
  botao.textContent = "Entrando…";

  try {
    const corpo = new FormData();
    corpo.append("email", el("email").value.trim());
    corpo.append("senha", el("senha").value);
    const resposta = await fetch("/api/login", { method: "POST", body: corpo });
    const dados = await resposta.json().catch(() => ({}));

    if (dados.primeiro_acesso) {
      emailPendente = el("email").value.trim();
      el("bloco-entrar").classList.add("oculto");
      el("bloco-primeiro").classList.remove("oculto");
      el("texto-primeiro").textContent =
        "A conta " + emailPendente + " ainda não tem senha. Defina a sua agora.";
      el("nova").focus();
      return;
    }
    if (!resposta.ok || !dados.ok) {
      mostrarErro(erro, dados.erro || "Não foi possível entrar.");
      return;
    }
    window.location.href = "/";
  } catch (e) {
    mostrarErro(erro, "Servidor não respondeu. Tente de novo.");
  } finally {
    botao.disabled = false;
    botao.textContent = "Entrar";
  }
}

async function criarSenha(evento) {
  evento.preventDefault();
  const erro = el("erro-primeiro");
  esconder(erro);

  const nova = el("nova").value;
  const repeticao = el("repeticao").value;
  if (nova !== repeticao) {
    mostrarErro(erro, "As duas senhas não são iguais.");
    return;
  }

  const corpo = new FormData();
  corpo.append("email", emailPendente);
  corpo.append("senha", nova);
  corpo.append("repeticao", repeticao);

  const resposta = await fetch("/api/primeiro-acesso", { method: "POST", body: corpo });
  const dados = await resposta.json().catch(() => ({}));
  if (!resposta.ok || !dados.ok) {
    mostrarErro(erro, dados.erro || "Não foi possível criar a senha.");
    return;
  }

  /* Senha criada: entra direto, sem obrigar a digitar tudo outra vez. */
  const login = new FormData();
  login.append("email", emailPendente);
  login.append("senha", nova);
  const entrada = await fetch("/api/login", { method: "POST", body: login });
  if (entrada.ok) {
    window.location.href = "/";
  } else {
    el("bloco-primeiro").classList.add("oculto");
    el("bloco-entrar").classList.remove("oculto");
  }
}

el("form-entrar").addEventListener("submit", entrar);
el("form-primeiro").addEventListener("submit", criarSenha);
el("botao-tema").addEventListener("click", alternarTema);
el("voltar-entrar").addEventListener("click", () => {
  el("bloco-primeiro").classList.add("oculto");
  el("bloco-entrar").classList.remove("oculto");
});
el("email").focus();
