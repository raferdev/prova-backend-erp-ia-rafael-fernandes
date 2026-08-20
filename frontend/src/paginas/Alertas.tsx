import { useEffect, useState } from "react";

import { type Alerta, ErroApi, listarAlertas } from "../api";

export function Alertas({ aoExpirar }: { aoExpirar: () => void }) {
  const [alertas, setAlertas] = useState<Alerta[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    listarAlertas()
      .then(setAlertas)
      .catch((falha) => {
        if (falha instanceof ErroApi && falha.status === 401) return aoExpirar();
        setErro(falha.message);
      });
  }, [aoExpirar]);

  return (
    <section>
      <p className="explicacao">
        Abertos pelo worker de fila, que roda por evento após cada movimentação e por
        varredura periódica. A quantidade mostrada é a <strong>do momento do alerta</strong>,
        não a de agora — sem isso, um alerta antigo contaria uma história falsa.
      </p>

      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}

      {alertas && alertas.length === 0 && (
        <p className="vazio" data-testid="sem-alertas">
          Nenhum alerta aberto.
        </p>
      )}

      {alertas && alertas.length > 0 && (
        <table data-testid="tabela-alertas">
          <thead>
            <tr>
              <th>Produto</th>
              <th>Quantidade no alerta</th>
              <th>Mínimo</th>
              <th>Aberto em</th>
            </tr>
          </thead>
          <tbody>
            {alertas.map((alerta) => (
              <tr key={alerta.id} data-testid="linha-alerta">
                <td className="id">{alerta.produto_id.slice(0, 8)}…</td>
                <td className="alerta">{alerta.quantidade_no_alerta}</td>
                <td>{alerta.estoque_minimo_no_alerta}</td>
                <td>{new Date(alerta.criado_em).toLocaleString("pt-BR")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
