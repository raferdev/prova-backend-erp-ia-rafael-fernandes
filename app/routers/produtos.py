"""Endpoints de produto.

O router e fino de proposito: recebe o request, chama o service, devolve a response. Ele
nao conhece cache, nao monta SQL e nao decide regra. Se algum dia eu precisar expor o mesmo
CRUD por outro transporte (mensageria, CLI), o service ja esta pronto e so este arquivo
seria descartado.

`response_model` e `status_code` explicitos em toda rota para o /docs sair util em vez de
generico.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.redis import get_redis
from app.core.security import usuario_autenticado
from app.repositories.produto import ProdutoRepository
from app.schemas.filtros import ConsultaProdutos
from app.schemas.produto import PaginaProdutos, ProdutoCreate, ProdutoResponse, ProdutoUpdate
from app.services.produto import ProdutoService

# Autenticacao aplicada no router inteiro, e nao rota a rota: assim uma rota nova nasce
# protegida por padrao. Esquecer de proteger e mais provavel que esquecer de liberar.
router = APIRouter(
    prefix="/produtos",
    tags=["produtos"],
    dependencies=[Depends(usuario_autenticado)],
)


def get_produto_service(
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> ProdutoService:
    return ProdutoService(ProdutoRepository(session), redis)


ServicoProduto = Annotated[ProdutoService, Depends(get_produto_service)]


@router.get(
    "",
    response_model=PaginaProdutos,
    summary="Lista produtos com filtros e paginacao",
    description=(
        "Consultas de catalogo sao servidas de cache. Consultas com "
        "`apenas_estoque_baixo=true` vao sempre ao banco, porque estoque e o dado volatil."
    ),
)
async def listar_produtos(
    servico: ServicoProduto,
    consulta: Annotated[ConsultaProdutos, Query()],
) -> PaginaProdutos:
    return await servico.listar(consulta.filtros(), consulta.paginacao())


@router.get("/{produto_id}", response_model=ProdutoResponse, summary="Busca um produto")
async def buscar_produto(produto_id: uuid.UUID, servico: ServicoProduto) -> ProdutoResponse:
    return await servico.buscar(produto_id)


@router.post(
    "",
    response_model=ProdutoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cria um produto",
)
async def criar_produto(dados: ProdutoCreate, servico: ServicoProduto) -> ProdutoResponse:
    return await servico.criar(dados)


@router.patch(
    "/{produto_id}",
    response_model=ProdutoResponse,
    summary="Atualiza parcialmente um produto",
)
async def atualizar_produto(
    produto_id: uuid.UUID, dados: ProdutoUpdate, servico: ServicoProduto
) -> ProdutoResponse:
    return await servico.atualizar(produto_id, dados)


@router.delete(
    "/{produto_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove um produto",
)
async def remover_produto(produto_id: uuid.UUID, servico: ServicoProduto) -> Response:
    await servico.remover(produto_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
