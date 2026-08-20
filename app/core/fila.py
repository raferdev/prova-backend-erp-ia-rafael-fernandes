"""Conexao com a fila do arq.

O arq usa o mesmo Redis do cache e dos locks, em um banco logico separado. Bancos
distintos evitam que um `FLUSHDB` de manutencao no cache leve junto a fila de jobs.
"""

from arq.connections import RedisSettings

from app.core.config import get_settings

settings = get_settings()

# Banco 1 para a fila; o cache usa o configurado em REDIS_DB (0 por padrao).
FILA_REDIS_DB = 1

NOME_FILA = "erp:estoque"


def redis_settings() -> RedisSettings:
    return RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        database=FILA_REDIS_DB,
    )
