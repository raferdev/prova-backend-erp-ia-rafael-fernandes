"""Fixtures compartilhadas dos testes.

As variaveis de ambiente sao definidas *antes* de qualquer import da aplicacao porque
`Settings` valida a config no momento do import -- sem elas o proprio import falharia.
Isso e efeito colateral desejado do fail-fast em `app/core/config.py`.

O client e **async desde o dia zero**, de proposito. O `TestClient` sincrono do Starlette
roda o app em um event loop proprio, criado por baixo dos panos; quando entrarem testes
de integracao que compartilham engine/sessao async do SQLAlchemy, isso produz o classico
`attached to a different loop`. Trocar depois significa reescrever todos os testes, entao
a escolha e feita agora, enquanto custa duas linhas.
"""

import os

os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("REDIS_HOST", "localhost")
# 48 bytes: a aplicacao recusa segredo abaixo de 32 (ver app/core/config.py).
os.environ.setdefault("JWT_SECRET", "segredo-de-teste-com-tamanho-suficiente-para-hs256")
os.environ.setdefault("APP_DEBUG", "false")

from collections.abc import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from main import app  # noqa: E402


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Client HTTP async falando direto com o app ASGI, sem abrir porta de rede.

    Nota: o `ASGITransport` nao executa o `lifespan` da aplicacao. Para estes testes
    isso e desejavel -- nao queremos abrir e fechar pools de conexao a cada teste.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
