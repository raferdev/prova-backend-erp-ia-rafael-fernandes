"""Conexao com o Postgres (SQLAlchemy 2.0 async).

Por que SQLAlchemy e nao SQLModel: a prova pede `schemas/` (contrato Pydantic da API)
separado de `models/` (tabelas). SQLModel funde as duas coisas na mesma classe, o que
e conveniente mas acopla o contrato publico ao schema do banco -- exatamente o que a
separacao de camadas quer evitar.
"""

from collections.abc import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

# Nomes de indices e constraints seguindo a convencao do Postgres, e nao a do
# SQLAlchemy. Isso precisa existir ANTES da primeira migration: o Alembic gera
# `DROP CONSTRAINT <nome>` a partir destes nomes, e uma constraint criada com nome
# auto-gerado (ou pior, anonimo) vira uma migration de rollback que nao roda.
POSTGRES_NAMING_CONVENTION = {
    "ix": "%(column_0_label)s_idx",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_debug,
    pool_pre_ping=True,  # descarta conexoes mortas (restart do Postgres, idle timeout)
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # permite ler o objeto depois do commit sem novo SELECT
)


class Base(DeclarativeBase):
    """Base declarativa de todos os models do ORM."""

    metadata = MetaData(naming_convention=POSTGRES_NAMING_CONVENTION)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependencia do FastAPI: uma sessao por request, sempre fechada no fim."""
    async with SessionLocal() as session:
        yield session
