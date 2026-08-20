import { useState } from "react";

import { ErroApi, perguntar, type RespostaConsulta } from "../api";

const EXEMPLOS = [
  "produtos com estoque abaixo de 10",
  "quantos produtos estão em falta",
  "produtos com preço acima de 200",
  "produtos abaixo de 10",
];

export function Consulta({ aoExpirar }: { aoExpirar: () => void }) {
  const [pergunta, setPergunta] = useState("");
  const [resposta, setResposta] = useState<RespostaConsulta | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);

  async function enviar(texto: string) {
    if (!texto.trim()) return;
    setPergunta(texto);
    setCarregando(true);
    setErro(null);
    try {
      setResposta(await perguntar(texto));
    } catch (falha) {
      if (falha instanceof ErroApi && falha.status === 401) return aoExpirar();
      setErro(falha instanceof Error ? falha.message : "Falha na consulta.");
    } finally {
      setCarregando(false);
    }
  }

  return (
    <section className="consulta">
      <p className="explicacao">
        Pergunta em português, respondida por um parser determinístico — sem LLM. A resposta
        sempre mostra <strong>como a pergunta foi interpretada</strong>, para o número ser
        conferível.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void enviar(pergunta);
        }}
      >
        <input
          placeholder="ex.: produtos com estoque abaixo de 10"
          value={pergunta}
          data-testid="pergunta"
          onChange={(e) => setPergunta(e.target.value)}
        />
        <button type="submit" data-testid="perguntar" disabled={carregando}>
          {carregando ? "Consultando…" : "Perguntar"}
        </button>
      </form>

      <div className="exemplos">
        {EXEMPLOS.map((exemplo) => (
          <button key={exemplo} className="exemplo" onClick={() => void enviar(exemplo)}>
            {exemplo}
          </button>
        ))}
      </div>

      {erro && (
        <p className="erro" role="alert">
          {erro}
        </p>
      )}

      {resposta?.entendida && (
        <div className="resultado" data-testid="resultado">
          <p className="interpretacao" data-testid="interpretacao">
            Entendi: {resposta.interpretacao}
          </p>
          <pre className="filtros-aplicados" data-testid="filtros-aplicados">
            {JSON.stringify(resposta.filtros_aplicados, null, 2)}
          </pre>
          <p className="total" data-testid="total-consulta">
            {resposta.total} produto(s)
          </p>

          {resposta.itens && resposta.itens.length > 0 && (
            <ul data-testid="itens-consulta">
              {resposta.itens.map((produto) => (
                <li key={produto.id}>
                  {produto.nome} — {produto.quantidade_estoque} un — R$ {produto.preco}
                </li>
              ))}
            </ul>
          )}

          {resposta.itens === null && (
            <p className="nota">
              A pergunta foi de contagem, então a lista não é devolvida — é o que evita
              carregar o catálogo inteiro para responder um número.
            </p>
          )}
        </div>
      )}

      {resposta && !resposta.entendida && (
        <div className="recusa" data-testid="recusa">
          <p data-testid="motivo-recusa">
            {resposta.ambiguidade ?? resposta.motivo}
          </p>
          <p className="nota">
            O parser recusa em vez de adivinhar. Chutar aqui devolveria um número errado com
            aparência de certo.
          </p>
          {resposta.sugestoes.length > 0 && (
            <ul className="sugestoes" data-testid="sugestoes">
              {resposta.sugestoes.map((sugestao) => (
                <li key={sugestao}>
                  <button onClick={() => void enviar(sugestao)}>{sugestao}</button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
