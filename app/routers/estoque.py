"""Endpoints de movimentacao de estoque e consulta de alertas.

O ajuste responde 202 e enfileira: e movimentacao que tolera consistencia eventual
(reposicao, ajuste de inventario, devolucao). O caminho de reserva de pedido, que precisa
de resposta sincrona sob lock, nao passa por aqui -- registrado no ADR 0008.
"""

import uuid
from typing import Annotated

from arq import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import usuario_autenticado
from app.repositories.alerta import AlertaRepository
from app.repositories.movimento import MovimentoRepository
from app.schemas.estoque import AjusteAceito, AjusteEstoque, AlertaResponse, MovimentoResponse

router = APIRouter(tags=["estoque"], dependencies=[Depends(usuario_autenticado)])


def get_fila(request: Request) -> ArqRedis:
    """Pool do arq criado no lifespan da aplicacao.

    Se a fila nao subiu, respondo 503 em vez de estourar 500: a API continua servindo
    leitura normalmente, so nao aceita enfileirar. Nos testes esta dependencia e
    sobrescrita, ja que o ASGITransport nao executa o lifespan.
    """
    fila = getattr(request.app.state, "fila", None)
    if fila is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="fila indisponivel",
        )
    return fila


@router.post(
    "/produtos/{produto_id}/estoque",
    response_model=AjusteAceito,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enfileira uma movimentacao de estoque",
)
async def ajustar_estoque(
    produto_id: uuid.UUID,
    ajuste: AjusteEstoque,
    fila: Annotated[ArqRedis, Depends(get_fila)],
) -> AjusteAceito:
    job = await fila.enqueue_job(
        "ajustar_estoque",
        str(produto_id),
        ajuste.delta,
        ajuste.motivo,
    )
    return AjusteAceito(job_id=job.job_id, produto_id=produto_id)


@router.get(
    "/alertas",
    response_model=list[AlertaResponse],
    summary="Lista alertas de estoque",
)
async def listar_alertas(
    session: Annotated[AsyncSession, Depends(get_session)],
    apenas_abertos: bool = True,
) -> list[AlertaResponse]:
    alertas = await AlertaRepository(session).listar(apenas_abertos=apenas_abertos)
    return [AlertaResponse.model_validate(a) for a in alertas]


@router.get(
    "/produtos/{produto_id}/movimentos",
    response_model=list[MovimentoResponse],
    summary="Historico de movimentacao de um produto",
)
async def historico_movimentos(
    produto_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[MovimentoResponse]:
    movimentos = await MovimentoRepository(session).historico(produto_id)
    return [MovimentoResponse.model_validate(m) for m in movimentos]
