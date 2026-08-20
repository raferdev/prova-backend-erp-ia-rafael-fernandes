"""Endpoint de contexto de venda: tres fontes consultadas em paralelo.

Responde 200 mesmo com fonte fora do ar. Isso e deliberado e e o ponto do exercicio:
degradacao graciosa significa entregar o que deu para obter, dizendo com clareza o que
faltou. Um 502 aqui jogaria fora as duas fontes que responderam.

Quem precisa recusar a venda por falta de dado e o modulo de Pedidos, com a politica dele.
Este endpoint entrega contexto, nao veredito.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.security import usuario_autenticado
from app.integracoes.mocks import ClientesAPI, Comportamento, FinanceiroAPI, LogisticaAPI
from app.schemas.contexto import ContextoDeVenda
from app.services.contexto import ContextoService

router = APIRouter(
    prefix="/integracoes",
    tags=["integracoes"],
    dependencies=[Depends(usuario_autenticado)],
)


@router.get(
    "/contexto-de-venda/{cliente_id}",
    response_model=ContextoDeVenda,
    summary="Consulta Clientes, Financeiro e Logistica em paralelo",
    description=(
        "Sempre 200. Cada fonte traz o proprio status, e `dados` vem null quando a fonte "
        "falhou -- nunca um objeto vazio, que seria lido como resposta legitima. "
        "Os parametros `simular_*` existem para demonstrar a degradacao sem derrubar nada."
    ),
)
async def contexto_de_venda(
    cliente_id: str,
    simular_clientes: Annotated[Comportamento, Query()] = Comportamento.NORMAL,
    simular_financeiro: Annotated[Comportamento, Query()] = Comportamento.NORMAL,
    simular_logistica: Annotated[Comportamento, Query()] = Comportamento.NORMAL,
) -> ContextoDeVenda:
    servico = ContextoService(
        clientes=ClientesAPI(nome="clientes", comportamento=simular_clientes),
        financeiro=FinanceiroAPI(nome="financeiro", comportamento=simular_financeiro),
        logistica=LogisticaAPI(nome="logistica", comportamento=simular_logistica),
    )
    return await servico.montar(cliente_id)
