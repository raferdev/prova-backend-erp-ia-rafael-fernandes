import { useState } from "react";

import { autenticar } from "../api";

export function Login({ aoEntrar }: { aoEntrar: () => void }) {
  const [email, setEmail] = useState("admin@erp.local");
  const [senha, setSenha] = useState("admin123");
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function enviar(evento: React.FormEvent) {
    evento.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      await autenticar(email, senha);
      aoEntrar();
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "Não foi possível entrar.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="login">
      <form onSubmit={enviar}>
        <h1>ERP — Pedidos e Estoque</h1>

        <label>
          E-mail
          <input
            type="email"
            value={email}
            data-testid="email"
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>

        <label>
          Senha
          <input
            type="password"
            value={senha}
            data-testid="senha"
            onChange={(e) => setSenha(e.target.value)}
            required
          />
        </label>

        <button type="submit" data-testid="entrar" disabled={enviando}>
          {enviando ? "Entrando…" : "Entrar"}
        </button>

        {erro && (
          <p className="erro" data-testid="erro-login" role="alert">
            {erro}
          </p>
        )}

        <p className="dica">
          O seed cria <code>admin@erp.local</code> / <code>admin123</code> para
          desenvolvimento.
        </p>
      </form>
    </div>
  );
}
