"""Orquestra a consulta em linguagem natural.

Fino de propósito: o parser traduz, o repository consulta. Este service só liga os dois e
decide o que responder quando o parser recusa.

Repare no que ele *não* faz: não monta SQL. O `FiltrosProduto` que sai do parser é o mesmo
que a API REST recebe por query string, e vai para o mesmo `ProdutoRepository`. Uma
implementação de consulta, dois jeitos de chegar nela.
"""

from typing import Any

from app.repositories.produto import ProdutoRepository
from app.schemas.consulta import RespostaConsultaNatural
from app.schemas.filtros import FiltrosProduto, Paginacao
from app.schemas.produto import ProdutoResponse
from app.services.parser_consulta import interpretar

# Consulta em linguagem natural é exploratória: quem pergunta quer ver o suficiente para
# decidir, não paginar. Um teto fixo evita devolver o catálogo inteiro sem querer.
LIMITE_ITENS = 20


class ConsultaNaturalService:
    def __init__(self, produtos: ProdutoRepository) -> None:
        self.produtos = produtos

    async def responder(self, pergunta: str) -> RespostaConsultaNatural:
        leitura = interpretar(pergunta)

        if not leitura.entendida or leitura.filtros is None:
            return RespostaConsultaNatural(
                pergunta=pergunta,
                entendida=False,
                ambiguidade=leitura.ambiguidade,
                motivo=leitura.explicacao,
                sugestoes=leitura.sugestoes,
            )

        itens, total = await self.produtos.listar(
            leitura.filtros, Paginacao(pagina=1, tamanho=LIMITE_ITENS)
        )

        return RespostaConsultaNatural(
            pergunta=pergunta,
            entendida=True,
            interpretacao=leitura.explicacao,
            filtros_aplicados=self._so_o_que_foi_pedido(leitura.filtros),
            total=total,
            # Numa contagem, devolver a lista seria ruído: a pergunta foi "quantos".
            itens=None
            if leitura.intencao == "contar"
            else [ProdutoResponse.model_validate(i) for i in itens],
        )

    @staticmethod
    def _so_o_que_foi_pedido(filtros: FiltrosProduto) -> dict[str, Any]:
        """Devolve apenas os filtros que o parser realmente definiu.

        `model_fields_set` e nao `exclude_defaults`, por dois motivos.

        O semantico: quero mostrar o que a pergunta pediu, e `fields_set` e exatamente
        isso. `apenas_estoque_baixo: false` num filtro de preco nao foi pedido -- e ruido
        que atrapalha justamente quem esta conferindo se a interpretacao bateu.

        E o pratico: `exclude_defaults` nao funciona nos nossos schemas. O
        `@field_serializer("*")` do `CustomModel` faz o Pydantic devolver todos os campos,
        inclusive os que valem o default. Verificado lado a lado com um BaseModel puro, que
        exclui corretamente. Nao e bug do Pydantic e sim efeito do serializer curinga, e
        `fields_set` e imune a ele.
        """
        despejo = filtros.model_dump(mode="json")
        return {campo: despejo[campo] for campo in filtros.model_fields_set}
