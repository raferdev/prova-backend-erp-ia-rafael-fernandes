"""Servidor MCP do ERP.

Sobe com:  python -m app.mcp.servidor

Transporte stdio, que é o que clientes como o Claude Desktop usam. Este arquivo cuida do
protocolo e da declaração das ferramentas; a execução mora em `ferramentas.py`, e essa
separação é o que permite testar comportamento sem levantar processo nem falar stdio.

Não há LLM nenhum aqui. Um servidor MCP expõe ferramentas; quem chama modelo é o cliente do
outro lado. Por isso implementar isto não viola a regra do enunciado.

## Por que existe a subclasse `ServidorERP`

Na resposta da Q9 (README) eu argumentei que todo schema deve ter
`additionalProperties: false`, para um argumento alucinado não passar em silêncio.
Implementando, descobri que a coisa é pior do que eu tinha escrito: o SDK **aceita e
descarta** o argumento desconhecido, e devolve sucesso.

Verificado na mão: `consultar(nome="cabo", desconto_maximo=30)` retorna `is_error=False` e
o `desconto_maximo` simplesmente evapora. O efeito é exatamente o que eu queria evitar --
uma consulta com escopo diferente do pedido, respondida com cara de correta.

A conclusão corrige o documento: schema é declaração de intenção para o modelo, mas quem
protege é o servidor. A validação abaixo é a garantia de verdade.
"""

import asyncio
import logging
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from app.mcp.ferramentas import Executor, texto_json

# Log em stderr, nunca em stdout: no transporte stdio o stdout carrega o protocolo, e um
# print perdido no meio corrompe a sessão inteira.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("erp.mcp")

executor = Executor()


class ServidorERP(MCPServer):
    """MCPServer que recusa argumento fora do schema em vez de descartá-lo em silêncio."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._permitidos: dict[str, set[str]] = {}

    async def _argumentos_permitidos(self, nome: str) -> set[str] | None:
        if not self._permitidos:
            for ferramenta in await self.list_tools():
                propriedades = ferramenta.input_schema.get("properties", {})
                self._permitidos[ferramenta.name] = set(propriedades)
        return self._permitidos.get(nome)

    async def call_tool(self, name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        permitidos = await self._argumentos_permitidos(name)
        desconhecidos = sorted(set(arguments or {}) - permitidos) if permitidos is not None else []

        if desconhecidos:
            logger.warning(
                "ferramenta %s recebeu argumentos desconhecidos: %s", name, desconhecidos
            )
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=texto_json(
                            {
                                "status": "erro",
                                "erro": f"argumentos nao suportados: {', '.join(desconhecidos)}",
                                "aceitos": sorted(permitidos or []),
                                "observacao": (
                                    "A consulta NAO foi executada. Chame de novo apenas com "
                                    "os argumentos aceitos."
                                ),
                            }
                        ),
                    )
                ],
                is_error=True,
            )

        return await super().call_tool(name, arguments, context)


mcp = ServidorERP("erp-pedidos-estoque", version="0.1.0")


@mcp.tool()
async def consultar_estoque(
    nome: Annotated[str | None, Field(description="Busca parcial no nome do produto")] = None,
    preco_min: Annotated[float | None, Field(ge=0)] = None,
    preco_max: Annotated[float | None, Field(ge=0)] = None,
    estoque_max: Annotated[int | None, Field(ge=0)] = None,
    apenas_estoque_baixo: Annotated[
        bool | None,
        Field(
            description=(
                "Produtos no ou abaixo do limiar de reposicao definido para cada produto. "
                "Nao e um numero fixo global."
            )
        ),
    ] = None,
    limite: Annotated[int, Field(ge=1, le=50)] = 20,
) -> str:
    """Consulta produtos do catalogo por nome, faixa de preco ou nivel de estoque.

    Somente leitura, nao altera nada.
    """
    return await executor.executar(
        "consultar_estoque",
        {
            "nome": nome,
            "preco_min": preco_min,
            "preco_max": preco_max,
            "estoque_max": estoque_max,
            "apenas_estoque_baixo": apenas_estoque_baixo,
            "limite": limite,
        },
    )


@mcp.tool()
async def consultar_alertas(apenas_abertos: bool = True) -> str:
    """Lista alertas de estoque baixo, com a quantidade registrada quando o alerta abriu.

    Somente leitura.
    """
    return await executor.executar("consultar_alertas", {"apenas_abertos": apenas_abertos})


@mcp.tool()
async def perguntar_sobre_catalogo(
    pergunta: Annotated[str, Field(min_length=3, description="Pergunta em portugues")],
) -> str:
    """Responde uma pergunta em portugues sobre o catalogo usando o parser deterministico do ERP.

    Devolve a interpretacao que o ERP fez da pergunta e os filtros aplicados. Quando a
    pergunta e ambigua, recusa em vez de adivinhar. Somente leitura.
    """
    return await executor.executar("perguntar_sobre_catalogo", {"pergunta": pergunta})


@mcp.tool()
async def preparar_ajuste_estoque(
    produto_id: Annotated[
        str,
        Field(
            description=(
                "UUID do produto. Obtenha com consultar_estoque; nao invente nem deduza a "
                "partir do nome."
            )
        ),
    ],
    delta: Annotated[int, Field(description="Negativo da baixa, positivo repoe. Zero e recusado.")],
    motivo: Annotated[str, Field(min_length=3, max_length=200)],
) -> str:
    """ACAO DESTRUTIVA, primeira etapa. Prepara uma movimentacao e devolve um preview.

    NAO altera o estoque. Mostre o preview ao usuario e so chame confirmar_ajuste_estoque
    depois que ele confirmar explicitamente.
    """
    return await executor.executar(
        "preparar_ajuste_estoque",
        {"produto_id": produto_id, "delta": delta, "motivo": motivo},
    )


@mcp.tool()
async def confirmar_ajuste_estoque(token_confirmacao: str) -> str:
    """ACAO DESTRUTIVA, segunda etapa. Executa a movimentacao preparada.

    Use apenas depois de o usuario ter confirmado o preview em palavras. O token vale uma
    unica execucao.
    """
    return await executor.executar(
        "confirmar_ajuste_estoque", {"token_confirmacao": token_confirmacao}
    )


if __name__ == "__main__":
    asyncio.run(mcp.run_stdio_async())
