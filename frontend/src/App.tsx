import { useState } from "react";

import { sessao } from "./api";
import { Alertas } from "./paginas/Alertas";
import { Consulta } from "./paginas/Consulta";
import { Login } from "./paginas/Login";
import { Produtos } from "./paginas/Produtos";

type Aba = "produtos" | "consulta" | "alertas";

const ABAS: { id: Aba; rotulo: string }[] = [
  { id: "produtos", rotulo: "Produtos" },
  { id: "consulta", rotulo: "Perguntar" },
  { id: "alertas", rotulo: "Alertas" },
];

export function App() {
  // Sem react-router: são três telas e nenhuma URL profunda para compartilhar. Uma
  // dependência a menos, e o roteador entraria no dia em que houvesse rota para rotear.
  const [autenticado, setAutenticado] = useState(() => sessao.token() !== null);
  const [aba, setAba] = useState<Aba>("produtos");

  if (!autenticado) {
    return <Login aoEntrar={() => setAutenticado(true)} />;
  }

  return (
    <div className="app">
      <header>
        <h1>ERP — Pedidos e Estoque</h1>
        <nav>
          {ABAS.map(({ id, rotulo }) => (
            <button
              key={id}
              data-testid={`aba-${id}`}
              className={aba === id ? "ativa" : ""}
              onClick={() => setAba(id)}
            >
              {rotulo}
            </button>
          ))}
          <button
            className="sair"
            data-testid="sair"
            onClick={() => {
              sessao.encerrar();
              setAutenticado(false);
            }}
          >
            Sair
          </button>
        </nav>
      </header>

      <main>
        {aba === "produtos" && <Produtos aoExpirar={() => setAutenticado(false)} />}
        {aba === "consulta" && <Consulta aoExpirar={() => setAutenticado(false)} />}
        {aba === "alertas" && <Alertas aoExpirar={() => setAutenticado(false)} />}
      </main>
    </div>
  );
}
