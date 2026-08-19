"""Conexao com o Redis.

O Redis tem tres papeis distintos neste projeto (detalhado no README):
  1. cache de leituras quentes (catalogo de produtos);
  2. broker do worker de background (arq);
  3. lock distribuido, para evitar oversell na ultima unidade em estoque.

Um unico pool de conexoes atende os tres -- eles usam bancos/prefixos diferentes.
"""

from redis.asyncio import ConnectionPool, Redis

from app.core.config import get_settings

settings = get_settings()

pool = ConnectionPool.from_url(settings.redis_url, decode_responses=True)


def get_redis() -> Redis:
    """Dependencia do FastAPI: cliente Redis sobre o pool compartilhado."""
    return Redis(connection_pool=pool)
