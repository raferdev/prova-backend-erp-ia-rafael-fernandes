"""Execução das ferramentas expostas por MCP.

Separado do transporte (`servidor.py`) de propósito: assim dá para testar comportamento
chamando função, sem levantar processo nem falar stdio. Os schemas ficam lá, derivados das
assinaturas; aqui fica o que acontece quando a ferramenta é chamada.

Dois princípios da Q9 do README moram neste arquivo:

- Ferramenta de escrita nunca executa direto: devolve preview e exige confirmação.
- Falha nunca vira resultado vazio. Um modelo que recebe lista vazia conclui que não há
  nada; ele precisa saber que não conseguiu ver.
"""

import json
from typing import Any

from app.mcp.cliente_erp import ClienteERP, ErroERP
from app.mcp.confirmacao import VALIDADE_SEGUNDOS, RegistroConfirmacoes

LIMITE_PADRAO = 20


def texto_json(dados: Any) -> str:
    return json.dumps(dados, ensure_ascii=False, indent=2, default=str)


class Executor:
    """Executa a ferramenta pedida. Nunca levanta exceção: falha vira texto explicado.

    Falha que vira exceção no transporte perde a explicação pelo caminho, e o modelo fica
    com "erro" sem saber se deve tentar de novo, ajustar o argumento ou desistir.
    """

    def __init__(self, erp: ClienteERP | None = None) -> None:
        self.erp = erp or ClienteERP()
        self.confirmacoes = RegistroConfirmacoes()

    async def executar(self, nome: str, argumentos: dict[str, Any]) -> str:
        try:
            return await self._despachar(nome, argumentos)
        except ErroERP as erro:
            # Explicitamente uma falha, e não um resultado vazio. Um modelo que recebe
            # lista vazia conclui que não há nada; ele precisa saber que não conseguiu ver.
            return texto_json(
                {
                    "status": "indisponivel",
                    "erro": str(erro),
                    "observacao": (
                        "Nao foi possivel consultar o ERP. Isto NAO significa que nao ha "
                        "dados. Informe ao usuario que a consulta falhou."
                    ),
                }
            )

    async def _despachar(self, nome: str, argumentos: dict[str, Any]) -> str:
        if nome == "consultar_estoque":
            return await self._consultar_estoque(argumentos)
        if nome == "consultar_alertas":
            alertas = await self.erp.listar_alertas(argumentos.get("apenas_abertos", True))
            return texto_json({"total": len(alertas), "alertas": alertas})
        if nome == "perguntar_sobre_catalogo":
            return texto_json(await self.erp.perguntar(argumentos["pergunta"]))
        if nome == "preparar_ajuste_estoque":
            return await self._preparar_ajuste(argumentos)
        if nome == "confirmar_ajuste_estoque":
            return await self._confirmar_ajuste(argumentos)
        return texto_json({"status": "erro", "erro": f"ferramenta desconhecida: {nome}"})

    async def _consultar_estoque(self, argumentos: dict[str, Any]) -> str:
        pagina = await self.erp.listar_produtos(
            {
                "nome": argumentos.get("nome"),
                "preco_min": argumentos.get("preco_min"),
                "preco_max": argumentos.get("preco_max"),
                "estoque_max": argumentos.get("estoque_max"),
                "apenas_estoque_baixo": argumentos.get("apenas_estoque_baixo"),
                "tamanho": min(int(argumentos.get("limite", LIMITE_PADRAO)), 50),
            }
        )
        # `total` separado dos itens: "quantos produtos estao em falta" nao precisa
        # carregar o catalogo inteiro no contexto para responder um numero.
        return texto_json({"total": pagina["total"], "itens": pagina["itens"]})

    async def _preparar_ajuste(self, argumentos: dict[str, Any]) -> str:
        delta = int(argumentos["delta"])
        if delta == 0:
            return texto_json({"status": "erro", "erro": "delta zero nao movimenta estoque"})

        # Busca o produto antes de preparar: id inexistente vira erro explicito, e nunca
        # busca aproximada. "Encontrei algo parecido" e como se movimenta o produto errado.
        produto = await self.erp.buscar_produto(argumentos["produto_id"])
        saldo_previsto = produto["quantidade_estoque"] + delta

        if saldo_previsto < 0:
            return texto_json(
                {
                    "status": "recusado",
                    "erro": (
                        f"saldo insuficiente: {produto['nome']} tem "
                        f"{produto['quantidade_estoque']} unidades e a baixa e de {abs(delta)}"
                    ),
                }
            )

        verbo = "Baixar" if delta < 0 else "Repor"
        resumo = (
            f'{verbo} {abs(delta)} unidade(s) de "{produto["nome"]}". '
            f"Saldo atual {produto['quantidade_estoque']}, ficara {saldo_previsto}. "
            f"Motivo: {argumentos['motivo']}."
        )

        pendente = self.confirmacoes.registrar("ajustar_estoque", argumentos, resumo)
        return texto_json(
            {
                "status": "aguardando_confirmacao",
                "preview": resumo,
                "produto": produto["nome"],
                "saldo_atual": produto["quantidade_estoque"],
                "saldo_apos": saldo_previsto,
                "token_confirmacao": pendente.token,
                "validade_segundos": VALIDADE_SEGUNDOS,
                "instrucao": (
                    "Mostre o preview ao usuario e aguarde confirmacao explicita antes de "
                    "chamar confirmar_ajuste_estoque."
                ),
            }
        )

    async def _confirmar_ajuste(self, argumentos: dict[str, Any]) -> str:
        pendente = self.confirmacoes.resgatar(argumentos["token_confirmacao"])
        if pendente is None:
            return texto_json(
                {
                    "status": "erro",
                    "erro": (
                        "token invalido, ja usado ou expirado. Prepare a movimentacao de "
                        "novo com preparar_ajuste_estoque."
                    ),
                }
            )

        resultado = await self.erp.ajustar_estoque(
            pendente.argumentos["produto_id"],
            int(pendente.argumentos["delta"]),
            pendente.argumentos["motivo"],
        )
        return texto_json(
            {
                "status": "enfileirado",
                "executado": pendente.resumo,
                "job_id": resultado["job_id"],
                "observacao": (
                    "A movimentacao foi enfileirada e sera processada pelo worker. "
                    "Consulte o produto de novo para ver o saldo atualizado."
                ),
            }
        )
