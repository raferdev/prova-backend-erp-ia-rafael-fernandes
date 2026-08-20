"""Emissao de token.

Uso `OAuth2PasswordRequestForm` (form-urlencoded) em vez de um corpo JSON proprio porque e
o formato que o botao "Authorize" do /docs entende. Isso torna a API testavel pelo Swagger
sem copiar token na mao.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import conferir_senha, criar_token
from app.models.usuario import Usuario
from app.schemas.auth import TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Autentica e devolve um JWT",
)
async def emitir_token(
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    resultado = await session.execute(select(Usuario).where(Usuario.email == form.username))
    usuario = resultado.scalar_one_or_none()

    # Mensagem unica para usuario inexistente e senha errada, de proposito: responder
    # "usuario nao existe" entrega ao atacante uma lista de e-mails validos.
    if (
        usuario is None
        or not usuario.ativo
        or not conferir_senha(form.password, usuario.senha_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="email ou senha invalidos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(access_token=criar_token(usuario.id))
