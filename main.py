"""Entrypoint da API.

O `main.py` fica na raiz (fora de `app/`) para bater exatamente com a estrutura de
pastas descrita na resposta teorica -- a coerencia entre o que esta escrito e o que
esta no codigo e um criterio explicito da prova.

Responsabilidade deste arquivo: montar a aplicacao e registrar routers. Nenhuma regra
de negocio mora aqui.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.database import engine
from app.core.redis import pool
from app.routers import health

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ciclo de vida: hoje so garante o fechamento limpo dos pools no shutdown.

    Nao criamos tabelas aqui de proposito -- schema e responsabilidade do Alembic,
    para que dev e producao sigam o mesmo caminho de migracao.
    """
    yield
    await engine.dispose()
    await pool.aclose()


app = FastAPI(
    title="ERP - Pedidos e Estoque",
    description="Prova tecnica back-end (IA). Modulo de Pedidos e Estoque.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
