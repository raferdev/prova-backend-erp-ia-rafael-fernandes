import { useEffect, useState } from "react";

import { ErroApi, listarProdutos, type Pagina } from "../api";

export function Produtos({ aoExpirar }: { aoExpirar: () => void }) {
  const [nome, setNome] = useState("");
  const [precoMax, setPrecoMax] = useState("");
  const [estoqueBaixo, setEstoqueBaixo] = useState(false);
  const [pagina, setPagina] = useState(1);

  const [dados, setDados] = useState<Pagina | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    let cancelado = false;
    setCarregando(true);

    listarProdutos({
      nome,
      preco_max: precoMax,
      apenas_estoque_baixo: estoqueBaixo,
      pagina,
      tamanho: 5,
    })
      .then((resposta) => {
        // Sem esta guarda, uma resposta lenta de um filtro antigo sobrescreveria a de um
        // filtro novo. É a corrida clássica de busca enquanto se digita.
        if (!cancelado) {
          setDados(resposta);
          setErro(null);
        }
      })
      .catch((falha) => {
        if (cancelado) return;
        if (falha instanceof ErroApi && falha.status === 401) return aoExpirar();
        setErro(falha.message);
      })
      .finally(() => !cancelado && setCarregando(false));

    return () => {
      cancelado = true;
    };
  }, [nome, precoMax, estoqueBaixo, pagina, aoExpirar]);

  function aplicar(mudanca: () => void) {
    mudanca();
    setPagina(1);
  }

  return (
    <section>
      <div className="filtros">
        <input
          placeholder="Buscar por nome"
          value={nome}
          data-testid="filtro-nome"
          onChange={(e) => aplicar(() => setNome(e.target.value))}
        />
        <input
          type="number"
          placeholder="Preço máximo"
          value={precoMax}
          data-testid="filtro-preco"
          onChange={(e) => aplicar(() => setPrecoMax(e.target.value))}
        />
        <label className="checkbox">
          <input
            type="checkbox"
            checked={estoqueBaixo}
            data-testid="filtro-estoque-baixo"
            onChange={(e) => aplicar(() => setEstoqueBaixo(e.target.checked))}
          />
          Só estoque baixo
        </label>
      </div>

      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}

      {dados && (
        <>
          <p className="total" data-testid="total">
            {dados.total} produto(s)
          </p>

          <table data-testid="tabela-produtos">
            <thead>
              <tr>
                <th>Produto</th>
                <th>Preço</th>
                <th>Estoque</th>
                <th>Mínimo</th>
              </tr>
            </thead>
            <tbody>
              {dados.itens.map((produto) => {
                const emFalta = produto.quantidade_estoque <= produto.estoque_minimo;
                return (
                  <tr key={produto.id} data-testid="linha-produto">
                    <td>{produto.nome}</td>
                    <td>R$ {produto.preco}</td>
                    <td className={emFalta ? "alerta" : ""}>
                      {produto.quantidade_estoque}
                      {emFalta && <span className="tag">repor</span>}
                    </td>
                    <td>{produto.estoque_minimo}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {dados.itens.length === 0 && !carregando && (
            <p className="vazio" data-testid="sem-resultado">
              Nenhum produto para esses filtros.
            </p>
          )}

          {dados.paginas > 1 && (
            <div className="paginacao">
              <button
                data-testid="pagina-anterior"
                disabled={pagina <= 1}
                onClick={() => setPagina((p) => p - 1)}
              >
                Anterior
              </button>
              <span data-testid="pagina-atual">
                {dados.pagina} de {dados.paginas}
              </span>
              <button
                data-testid="pagina-proxima"
                disabled={pagina >= dados.paginas}
                onClick={() => setPagina((p) => p + 1)}
              >
                Próxima
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
