"""Hash de senha, emissao e validacao de JWT.

Escolhi `bcrypt` direto em vez de `passlib`: passlib esta praticamente sem manutencao e
quebrou com bcrypt 4.x. Uma dependencia a menos e uma fonte de surpresa a menos.
"""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.models.usuario import Usuario

settings = get_settings()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

# bcrypt trunca a entrada em 72 bytes. Em vez de deixar o truncamento silencioso (duas
# senhas longas diferentes virando o mesmo hash), recuso a senha explicitamente.
LIMITE_BCRYPT_BYTES = 72


def gerar_hash_senha(senha: str) -> str:
    if len(senha.encode()) > LIMITE_BCRYPT_BYTES:
        raise ValueError("senha excede o limite de 72 bytes suportado pelo bcrypt")
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()


def conferir_senha(senha: str, hash_armazenado: str) -> bool:
    if len(senha.encode()) > LIMITE_BCRYPT_BYTES:
        return False
    return bcrypt.checkpw(senha.encode(), hash_armazenado.encode())


def criar_token(usuario_id: uuid.UUID) -> str:
    expira_em = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(usuario_id),
        "exp": expira_em,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def usuario_autenticado(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> Usuario:
    """Dependencia de autenticacao.

    O FastAPI cacheia o resultado de uma dependencia dentro do escopo do request, entao
    usar isto em varias rotas ou dependencias encadeadas nao decodifica o token varias
    vezes nem consulta o banco de novo.
    """
    nao_autorizado = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="credenciais invalidas",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        usuario_id = uuid.UUID(payload["sub"])
    except (InvalidTokenError, KeyError, ValueError):
        raise nao_autorizado from None

    usuario = await session.get(Usuario, usuario_id)
    # Checo `ativo` a cada request de proposito: um token valido de usuario desativado
    # continuaria funcionando ate expirar se eu confiasse so na assinatura.
    if usuario is None or not usuario.ativo:
        raise nao_autorizado

    return usuario
