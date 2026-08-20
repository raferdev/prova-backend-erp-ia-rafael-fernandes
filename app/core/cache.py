"""Cache do catalogo e invalidacao. Implementa o ADR 0007.

Mora em `core/` e nao no router porque existem dois escritores no sistema: a API e o
worker de estoque. O worker nao passa por router nenhum, entao invalidacao implementada na
camada HTTP deixaria o cache velho por um caminho que ninguem esta olhando.

Regra que atravessa o arquivo inteiro: falha de Redis nunca derruba o request. Cache fora
do ar significa aplicacao mais lenta, nao aplicacao quebrada.
"""

import hashlib
import json
import logging
import random
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

CHAVE_VERSAO = "produtos:version"


def chave_detalhe(produto_id: UUID | str) -> str:
    return f"produto:{produto_id}"


def _ttl_com_jitter() -> int:
    """TTL com variacao de +-20%.

    Sem jitter, chaves criadas na mesma rajada expiram no mesmo segundo e todas as
    requisicoes caem no Postgres ao mesmo tempo (cache stampede). O jitter espalha isso.
    """
    base = settings.cache_ttl_seconds
    return max(1, int(base * random.uniform(0.8, 1.2)))


async def versao_listagem(redis: Redis) -> int:
    """Versao corrente do namespace de listagens.

    Chave ausente vale 0, e nao 1. O motivo e sutil e ja me custou um bug: `INCR` numa
    chave inexistente cria a chave valendo 1. Se "ausente" tambem valesse 1, a primeira
    invalidacao nao mudaria o namespace e as listagens gravadas antes dela continuariam
    sendo servidas.
    """
    try:
        bruto = await redis.get(CHAVE_VERSAO)
    except RedisError:
        logger.warning("redis indisponivel ao ler a versao do cache", exc_info=True)
        return 0
    return int(bruto) if bruto else 0


async def chave_listagem(redis: Redis, criterios: dict[str, Any]) -> str:
    """Monta `produtos:v{N}:list:{fingerprint}`.

    `sort_keys=True` e o detalhe que evita duplicar cache: sem ele, `?nome=cabo&pagina=1`
    e `?pagina=1&nome=cabo` gerariam fingerprints diferentes para o mesmo resultado.
    """
    versao = await versao_listagem(redis)
    payload = json.dumps(criterios, sort_keys=True, default=str)
    fingerprint = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"produtos:v{versao}:list:{fingerprint}"


async def invalidar_listagens(redis: Redis) -> None:
    """Invalida TODAS as listagens em O(1).

    O `INCR` muda o namespace, entao as chaves antigas viram inalcancaveis de uma vez, sem
    varrer o keyspace. Elas somem sozinhas quando o TTL vence.

    A alternativa seria `SCAN`/`KEYS` com pattern: `KEYS` bloqueia o Redis, que e
    single-threaded, e travaria junto os locks de estoque; `SCAN` e O(n) sobre o keyspace
    inteiro numa operacao que roda em toda escrita.
    """
    try:
        await redis.incr(CHAVE_VERSAO)
    except RedisError:
        # Nao propago: a escrita no Postgres ja foi commitada e reverter uma venda porque
        # o cache piscou seria trocar um problema pequeno por um grande. O TTL e a rede
        # de seguranca para exatamente este caso.
        logger.warning("falha ao invalidar listagens no cache", exc_info=True)


async def invalidar_produto(redis: Redis, produto_id: UUID | str) -> None:
    """Invalida o detalhe (chave conhecida) e as listagens (namespace)."""
    try:
        await redis.delete(chave_detalhe(produto_id))
    except RedisError:
        logger.warning("falha ao invalidar o produto %s no cache", produto_id, exc_info=True)
    await invalidar_listagens(redis)


async def ler_json(redis: Redis, chave: str) -> Any | None:
    try:
        bruto = await redis.get(chave)
    except RedisError:
        logger.warning("redis indisponivel na leitura de %s", chave, exc_info=True)
        return None
    if not bruto:
        return None
    try:
        return json.loads(bruto)
    except json.JSONDecodeError:
        # Valor corrompido ou de um formato antigo: trato como miss em vez de estourar.
        logger.warning("valor invalido em cache na chave %s", chave)
        return None


async def gravar_json(redis: Redis, chave: str, valor: Any) -> None:
    try:
        await redis.set(chave, json.dumps(valor, default=str), ex=_ttl_com_jitter())
    except RedisError:
        logger.warning("redis indisponivel na escrita de %s", chave, exc_info=True)
