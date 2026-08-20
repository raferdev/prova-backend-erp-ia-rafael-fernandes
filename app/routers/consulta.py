"""Consulta do catálogo em linguagem natural (Parte 5, Q8).

Determinístico, por regras. Nenhuma chamada a LLM de terceiro em runtime, que é exigência
do enunciado.

Responde 200 mesmo quando não entende a pergunta. Não entender é um resultado legítimo
deste endpoint, e não um erro do cliente: o corpo traz `entendida: false`, o motivo e
exemplos do que o parser sabe responder.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import usuario_autenticado
from app.repositories.produto import ProdutoRepository
from app.schemas.consulta import PerguntaNatural, RespostaConsultaNatural
from app.services.consulta_natural import ConsultaNaturalService

router = APIRouter(
    prefix="/consultas",
    tags=["consultas"],
    dependencies=[Depends(usuario_autenticado)],
)


@router.post(
    "/produtos",
    response_model=RespostaConsultaNatural,
    summary="Responde uma pergunta em linguagem natural sobre o catálogo",
    description=(
        "Parser determinístico, sem LLM. A resposta sempre inclui a interpretação em "
        "português e os filtros que de fato rodaram, para a resposta ser conferível. "
        "Quando a pergunta é ambígua, o parser recusa em vez de adivinhar."
    ),
)
async def consultar_em_linguagem_natural(
    entrada: PerguntaNatural,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RespostaConsultaNatural:
    servico = ConsultaNaturalService(ProdutoRepository(session))
    return await servico.responder(entrada.pergunta)
