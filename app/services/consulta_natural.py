"""Orquestra a consulta em linguagem natural.

Fino de propósito: o parser traduz, o repository consulta. Este service só liga os dois e
decide o que responder quando o parser recusa.

Repare no que ele *não* faz: não monta SQL. O `FiltrosProduto` que sai do parser é o mesmo
que a API REST recebe por query string, e vai para o mesmo `ProdutoRepository`. Uma
implementação de consulta, dois jeitos de chegar nela.
"""

from app.repositories.produto import ProdutoRepository
from app.schemas.consulta import RespostaConsultaNatural
from app.schemas.filtros import Paginacao
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
            # `exclude_defaults` e não `exclude_none`: o segundo deixaria passar
            # `apenas_estoque_baixo: false`, que não foi pedido e polui a auditoria com um
            # filtro que não existe. A resposta mostra só o que a pergunta de fato pediu.
            filtros_aplicados=leitura.filtros.model_dump(mode="json", exclude_defaults=True),
            total=total,
            # Numa contagem, devolver a lista seria ruído: a pergunta foi "quantos".
            itens=None
            if leitura.intencao == "contar"
            else [ProdutoResponse.model_validate(i) for i in itens],
        )
